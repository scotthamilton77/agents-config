"""The gh adapter — GitHub access via the ``gh`` subprocess (§1, §3, §7.6).

``GhCli`` shells out to ``gh`` (REST via ``gh api``, GraphQL via
``gh api graphql``, head-OID via ``gh pr view``) through the injected
:class:`~prgroom.proc.CommandRunner` boundary, and maps failures onto the
existing :class:`~prgroom.errors.ErrorCode` registry:

* 5xx, or rate-limit (429 always; 403 only when stderr names a rate limit)
  -> ``RUNTIME_GH_TRANSIENT``
* a hung call (``subprocess.TimeoutExpired``)     -> ``RUNTIME_GH_TRANSIENT``
  (symmetric with the git adapter; retry on the next cadence)
* other 4xx (not 404, not rate-limit)            -> ``RUNTIME_GH_TERMINAL``
* a missing ``gh`` binary (``OSError``)           -> ``RUNTIME_GH_TERMINAL``
  (a local config gap a retry won't fix)
* 404                                            -> :class:`GhNotFoundError`
  (a typed signal; the caller's startup precondition owns
  ``PRECONDITION_REPO_UNREACHABLE`` per §3.7 — the adapter does not guess)
* GraphQL request returns 200 but carries ``errors[]`` -> ``RUNTIME_GRAPHQL_FAILED``

Every call passes a bounded ``DEFAULT_SUBPROCESS_TIMEOUT`` so a hung ``gh``
cannot block forever while holding the PR lock. Callers only ever see a
registry-tagged :class:`~prgroom.errors.PrgroomError` or
:class:`GhNotFoundError` — no raw subprocess exception escapes ``_run``.

It **structurally satisfies** :class:`GhClient` (no inheritance); ``mypy
--strict`` checks the fit, mirroring ``FileStore`` vs ``Store``.
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Protocol, runtime_checkable

from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.proc import DEFAULT_SUBPROCESS_TIMEOUT, CommandRunner
from prgroom.prsession.pr_ref import PRRef

JsonObj = dict[str, Any]

# gh prints `gh: <message> (HTTP NNN)` to stderr on an API error; the exit code is
# always 1, so the status token in stderr is the only classification signal. gh's
# own status token is trailing, so we anchor on the LAST match — an upstream
# status echoed earlier in the message must not win.
_HTTP_STATUS = re.compile(r"\(HTTP (\d{3})\)")

# gh's actual secondary-rate-limit phrasing. Scoped tightly so a permissions 403
# whose human message merely contains the words "rate limit" is not mistaken for
# a throttle.
_RATE_LIMIT_PHRASE = "rate limit exceeded"


class GhNotFoundError(Exception):
    """A gh API 404. A typed signal, NOT a :class:`PrgroomError` (§3.7).

    404 is ambiguous at the boundary — repo-unreachable (a startup precondition,
    ``PRECONDITION_REPO_UNREACHABLE``) versus a PR/thread that vanished mid-run.
    The adapter reports the HTTP fact and lets the (out-of-scope) verb decide
    which precondition/runtime code applies.
    """


@runtime_checkable
class GhClient(Protocol):
    """The GitHub access surface the lifecycle verbs depend on (§3)."""

    def head_ref_oid(self, ref: PRRef) -> str: ...  # pragma: no cover

    def head_ref_name(self, ref: PRRef) -> str: ...  # pragma: no cover

    def rest(
        self,
        method: str,
        path: str,
        *,
        fields: dict[str, str] | None = None,
        paginate: bool = False,
    ) -> Any: ...  # pragma: no cover  # gh api returns object|array|primitive; caller narrows

    def graphql(self, query: str, variables: JsonObj) -> JsonObj: ...  # pragma: no cover

    def add_label(self, ref: PRRef, label: str) -> None: ...  # pragma: no cover


def _classify_gh_failure(stdout: str, stderr: str) -> PrgroomError | GhNotFoundError:
    """Map a failed ``gh`` invocation to its registry error (§3.6/§3.7)."""
    matches = _HTTP_STATUS.findall(stderr)
    if not matches:
        # No parseable status: cannot prove transient, so treat as terminal
        # rather than invite an unbounded scheduler retry loop.
        return PrgroomError(
            tier=Tier.RUNTIME_TERMINAL_USER,
            code=ErrorCode.RUNTIME_GH_TERMINAL,
            detail=stderr.strip() or stdout.strip(),
        )
    status = int(matches[-1])  # gh's own status token is trailing
    detail = stderr.strip()
    if status == 404:  # HTTP status literal is self-documenting
        return GhNotFoundError(detail)
    # 429 is definitionally rate-limited; 403 is ambiguous (permissions vs
    # secondary rate limit) so it only counts as transient when gh's actual
    # rate-limit phrasing is present. 5xx is always a degraded-service transient.
    is_rate_limit = status == 429 or (  # Too Many Requests
        status == 403 and _RATE_LIMIT_PHRASE in stderr.lower()  # Forbidden
    )
    if status >= 500 or is_rate_limit:  # 5xx server-error band
        return PrgroomError(
            tier=Tier.RUNTIME_TRANSIENT, code=ErrorCode.RUNTIME_GH_TRANSIENT, detail=detail
        )
    return PrgroomError(
        tier=Tier.RUNTIME_TERMINAL_USER, code=ErrorCode.RUNTIME_GH_TERMINAL, detail=detail
    )


class GhCli:
    """gh adapter. Structurally satisfies :class:`GhClient`."""

    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    def head_ref_oid(self, ref: PRRef) -> str:
        out = self._run(
            [
                "gh",
                "pr",
                "view",
                str(ref.number),
                "--repo",
                f"{ref.owner}/{ref.repo}",
                "--json",
                "headRefOid",
            ]
        )
        parsed: JsonObj = json.loads(out)
        return str(parsed["headRefOid"])

    def head_ref_name(self, ref: PRRef) -> str:
        out = self._run(
            [
                "gh",
                "pr",
                "view",
                str(ref.number),
                "--repo",
                f"{ref.owner}/{ref.repo}",
                "--json",
                "headRefName",
            ]
        )
        parsed: JsonObj = json.loads(out)
        return str(parsed["headRefName"])

    def rest(
        self,
        method: str,
        path: str,
        *,
        fields: dict[str, str] | None = None,
        paginate: bool = False,
    ) -> Any:
        argv = ["gh", "api", "--method", method, path]
        if paginate:
            # gh walks every page and concatenates the JSON arrays into one, so a list
            # read returns ALL items — not just GitHub's first 30. Only valid on GET
            # collection endpoints (the callers that opt in); object endpoints must not
            # set it (gh would emit one object per page, breaking json.loads).
            argv.append("--paginate")
        for key, value in (fields or {}).items():
            argv += ["-f", f"{key}={value}"]
        out = self._run(argv)
        # gh api returns a JSON object, array, or primitive depending on the
        # endpoint — the caller (which knows the endpoint) narrows. An empty body
        # (e.g. a 204) normalizes to {}.
        return json.loads(out) if out.strip() else {}

    def graphql(self, query: str, variables: JsonObj) -> JsonObj:
        argv = ["gh", "api", "graphql", "-f", f"query={query}"]
        for key, value in variables.items():
            # -F coerces typed scalars (int->Int, bool->Boolean); -f keeps the value a
            # literal string. Route by Python type so a String!-typed variable whose
            # value looks numeric (e.g. a purely-numeric owner/repo name) is never
            # coerced to Int and rejected against String!. (bool is an int subclass → -F.)
            flag = "-F" if isinstance(value, int) else "-f"
            argv += [flag, f"{key}={value}"]
        out = self._run(argv)
        envelope: JsonObj = json.loads(out)
        if envelope.get("errors"):
            raise PrgroomError(
                tier=Tier.RUNTIME_TRANSIENT,
                code=ErrorCode.RUNTIME_GRAPHQL_FAILED,
                detail=json.dumps(envelope["errors"]),
            )
        data: JsonObj = envelope.get("data") or {}
        return data

    def add_label(self, ref: PRRef, label: str) -> None:
        # POST to the issue's labels collection with gh's array placeholder syntax
        # (`labels[]=<name>`). The server treats a label already present as a no-op,
        # so this is idempotent — §4.7's auto-add re-issues it safely every gating
        # event. Routed through `rest` so a failure arrives as the registry-tagged
        # PrgroomError the §4.7 hook swallows (best-effort label add).
        self.rest(
            "POST",
            f"repos/{ref.owner}/{ref.repo}/issues/{ref.number}/labels",
            fields={"labels[]": label},
        )

    def _run(self, argv: list[str]) -> str:
        try:
            result = self._runner.run(argv, timeout=DEFAULT_SUBPROCESS_TIMEOUT)
        except subprocess.TimeoutExpired as exc:
            # A hung gh call is transient — symmetric with the git adapter; retry
            # on the next scheduler cadence.
            raise PrgroomError(
                tier=Tier.RUNTIME_TRANSIENT,
                code=ErrorCode.RUNTIME_GH_TRANSIENT,
                detail=f"gh timed out: {' '.join(argv)}",
            ) from exc
        except OSError as exc:
            # A missing `gh` binary (or other PATH/exec failure) raises OSError
            # before any command runs. A retry won't fix a local config gap, so
            # it is terminal.
            raise PrgroomError(
                tier=Tier.RUNTIME_TERMINAL_USER,
                code=ErrorCode.RUNTIME_GH_TERMINAL,
                detail=f"gh not runnable: {exc}",
            ) from exc
        if result.returncode != 0:
            raise _classify_gh_failure(result.stdout, result.stderr)
        return result.stdout
