"""Test fakes for the subprocess, gh-protocol, and App-HTTP boundaries.

The gh/git adapters reach the outside world through a single seam — the
:class:`~prgroom.proc.CommandRunner` Protocol. These fakes structurally satisfy
that Protocol so adapter tests inject recorded responses instead of mocking code
we own. This is the spec's "mock only at the system boundary" discipline: the
boundary is the subprocess call, and a runner is the smallest honest stand-in
for it. :class:`RecordingGh` is the protocol-seam sibling for lifecycle verbs
that take a :class:`~prgroom.gh.client.GhClient` directly, and
:class:`RouteTableHttp` is the same for the App's own HTTP boundary.
"""

from __future__ import annotations

import base64
import json
import subprocess
from collections.abc import Sequence
from typing import Any

from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.gh.app import GITHUB_API
from prgroom.proc import CommandResult


class RecordedRunner:
    """A :class:`CommandRunner` fake that replays queued results in FIFO order.

    Each :meth:`run` pops the next recorded :class:`CommandResult` and records
    the argv it was called with, so a test can both feed a recorded
    gh/git response and assert the adapter built the right command line. Running
    dry (more calls than recorded results) raises — a silent empty result would
    mask an adapter issuing an unexpected extra call.
    """

    def __init__(self, results: Sequence[CommandResult]) -> None:
        self._results = list(results)
        self.calls: list[list[str]] = []
        self.inputs: list[str | None] = []
        self.timeouts: list[float | None] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # matches the Protocol's keyword name
        timeout: float | None = None,
    ) -> CommandResult:
        self.calls.append(list(argv))
        self.inputs.append(input)
        self.timeouts.append(timeout)
        if not self._results:
            msg = f"RecordedRunner exhausted: unexpected call {list(argv)!r}"
            raise AssertionError(msg)
        return self._results.pop(0)


class RecordingGh:
    """A :class:`~prgroom.gh.client.GhClient`-protocol fake for reply/verb tests.

    Records ``rest_calls`` / ``graphql_calls``. Constructor knobs:

    - ``post_reply_id`` — the ``id`` every POST response carries (``None`` → ``{}``,
      the malformed-response shape).
    - ``pr_body`` — the ``GET pulls/{n}`` body (the Decisions-block read).
    - ``listed`` — GET path → canned comment listing; unlisted list-paths (any
      path ending ``/comments``) return ``[]``.
    - ``fail_at`` — ``(surface, n)``: raise a transient gh error on the n-th call
      of the named surface (``"post"`` | ``"graphql"``), modelling a mid-loop
      partial failure.
    """

    def __init__(
        self,
        post_reply_id: int | None = None,
        pr_body: str = "",
        listed: dict[str, list[dict[str, Any]]] | None = None,
        fail_at: tuple[str, int] | None = None,
    ) -> None:
        self.rest_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.graphql_calls: list[tuple[str, dict[str, Any]]] = []
        self._post_reply_id = post_reply_id
        self._pr_body = pr_body
        self._listed = dict(listed or {})
        self._fail_at = fail_at
        self._surface_counts = {"post": 0, "graphql": 0}

    def _maybe_fail(self, surface: str) -> None:
        self._surface_counts[surface] += 1
        if self._fail_at is not None and (surface, self._surface_counts[surface]) == self._fail_at:
            raise PrgroomError(tier=Tier.RUNTIME_TRANSIENT, code=ErrorCode.RUNTIME_GH_TRANSIENT)

    def rest(
        self,
        method: str,
        path: str,
        *,
        fields: dict[str, Any] | None = None,
        paginate: bool = False,  # noqa: ARG002  # part of the Protocol signature; recorded calls suffice
    ) -> Any:
        self.rest_calls.append((method, path, dict(fields or {})))
        if method == "POST":
            self._maybe_fail("post")
            return {"id": self._post_reply_id} if self._post_reply_id is not None else {}
        if method == "GET":
            if path in self._listed:
                return self._listed[path]
            if path.endswith("/comments"):
                return []
            return {"body": self._pr_body}
        return {}

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.graphql_calls.append((query, dict(variables)))
        self._maybe_fail("graphql")
        return {}


def _padded(segment: str) -> str:
    """Restore the padding a JOSE segment drops, so base64 will decode it."""
    return segment + "=" * (-len(segment) % 4)


class RouteTableHttp:
    """An :class:`~prgroom.gh.app.HttpTransport` fake answering from a route table.

    Keyed by ``(method, url-suffix-after the API root)``. A call no route matches
    raises rather than returning a permissive default, so a request the code was
    never meant to make fails the test that provoked it — which is also what lets
    the refusal and no-op paths be asserted as the *absence* of a POST.

    Every call is recorded as ``(method, url, headers, body)``; the routes and
    their payloads stay in each test module, since what a route should answer is
    exactly what those tests are pinning.

    It also refuses a request that does not carry the credential that request
    should have been authorized by — an App-level call must carry a JWT, and a
    PR-scoped call must carry the very token this fake minted. That rule lives
    here rather than in a per-call assertion because it has to cover call sites
    nobody has written yet: an App flow that drops or swaps a credential is a
    real defect, and one that reaches GitHub unauthorized would be found in
    production rather than in a test. Pass ``app_id`` to have the JWT's issuer
    checked too; a caller driving one client function with a hand-made token
    omits it and only the shape is enforced.
    """

    def __init__(
        self, routes: dict[tuple[str, str], tuple[int, Any]], *, app_id: int | None = None
    ) -> None:
        self.routes = dict(routes)
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []
        self._app_id = app_id
        self._minted: str | None = None

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Any,
        body: bytes | None = None,
    ) -> tuple[int, Any]:

        self.calls.append((method, url, dict(headers), body))
        self._check_credential(method, url, dict(headers))
        for (route_method, suffix), response in self.routes.items():
            if route_method == method and url == GITHUB_API + suffix:
                self._remember_minted_token(url, response)
                return response
        msg = f"unexpected call: {method} {url}"
        raise AssertionError(msg)

    def _check_credential(self, method: str, url: str, headers: dict[str, str]) -> None:
        """Refuse a call whose bearer is not the one that call should carry."""
        authorization = headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            msg = f"{method} {url} carried no bearer credential: {authorization!r}"
            raise AssertionError(msg)
        credential = authorization.removeprefix("Bearer ")
        if "/pulls/" in url:
            # Everything under the PR rides the installation token, and only the
            # one this fake handed out. A mint that never produced a readable
            # token leaves nothing to compare against.
            if self._minted is not None and credential != self._minted:
                msg = f"{method} {url} carried {credential!r}, not the minted {self._minted!r}"
                raise AssertionError(msg)
            return
        if self._app_id is None:
            return  # a caller driving one client function brought its own token
        segments = credential.split(".")
        if len(segments) != 3 or not all(segments):  # a JWT's three segments
            msg = f"{method} {url} carried {credential!r}, which is not a signed JWT"
            raise AssertionError(msg)
        claims = json.loads(base64.urlsafe_b64decode(_padded(segments[1])))
        if claims.get("iss") != str(self._app_id):
            msg = f"{method} {url} carried a JWT issued by {claims.get('iss')!r}"
            raise AssertionError(msg)

    def _remember_minted_token(self, url: str, response: tuple[int, Any]) -> None:
        """Record the token this fake just handed out, so later calls must use it."""
        if not url.endswith("/access_tokens"):
            return
        payload = response[1]
        if isinstance(payload, dict) and isinstance(payload.get("token"), str):
            self._minted = payload["token"]

    def bodies_posted_to(self, tail: str) -> list[Any]:
        """The decoded JSON bodies of every POST whose URL ends with ``tail``."""
        return [
            json.loads(body)
            for method, url, _, body in self.calls
            if method == "POST" and url.endswith(tail) and body is not None
        ]

    def posted_reviews(self) -> list[Any]:
        """The reviews submitted — the assertion most of these tests turn on."""
        return self.bodies_posted_to("/reviews")


class TimeoutRunner:
    """A :class:`CommandRunner` fake that always raises ``TimeoutExpired``.

    Models the hung-call boundary failure both adapters must classify as their
    transient code (``RUNTIME_GIT_TRANSIENT`` / ``RUNTIME_GH_TRANSIENT``).
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # noqa: ARG002  # part of the Protocol signature; unused here
        timeout: float | None = None,
    ) -> CommandResult:  # pragma: no cover - never returns; raises below
        self.calls.append(list(argv))
        raise subprocess.TimeoutExpired(cmd=list(argv), timeout=timeout or 0.0)


class MissingBinaryRunner:
    """A :class:`CommandRunner` fake that always raises ``FileNotFoundError``.

    Models a missing ``gh`` / ``git`` binary on ``PATH`` — the OSError the real
    boundary raises before any command runs. Each adapter must map this to a
    registry error rather than leak the raw traceback.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # noqa: ARG002  # part of the Protocol signature; unused here
        timeout: float | None = None,  # noqa: ARG002  # part of the Protocol signature; unused here
    ) -> CommandResult:  # pragma: no cover - never returns; raises below
        self.calls.append(list(argv))
        raise FileNotFoundError(2, "No such file or directory", argv[0])
