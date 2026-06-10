"""The gh adapter — GitHub access via the ``gh`` subprocess (§1, §3, §7.6).

``GhCli`` shells out to ``gh`` (REST via ``gh api``, GraphQL via
``gh api graphql``, head-OID via ``gh pr view``) through the injected
:class:`~prgroom.proc.CommandRunner` boundary, and maps failures onto the
existing :class:`~prgroom.errors.ErrorCode` registry:

* 5xx, or rate-limit (429 always; 403 only when stderr names a rate limit)
  -> ``RUNTIME_GH_TRANSIENT``
* other 4xx (not 404, not rate-limit)            -> ``RUNTIME_GH_TERMINAL``
* 404                                            -> :class:`GhNotFoundError`
  (a typed signal; the caller's startup precondition owns
  ``PRECONDITION_REPO_UNREACHABLE`` per §3.7 — the adapter does not guess)
* GraphQL request returns 200 but carries ``errors[]`` -> ``RUNTIME_GRAPHQL_FAILED``

It **structurally satisfies** :class:`GhClient` (no inheritance); ``mypy
--strict`` checks the fit, mirroring ``FileStore`` vs ``Store``.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol, runtime_checkable

from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.proc import CommandRunner
from prgroom.prsession.pr_ref import PRRef

JsonObj = dict[str, Any]

# gh prints `gh: <message> (HTTP NNN)` to stderr on an API error; the exit code is
# always 1, so the status token in stderr is the only classification signal.
_HTTP_STATUS = re.compile(r"\(HTTP (\d{3})\)")


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

    def rest(
        self, method: str, path: str, *, fields: JsonObj | None = None
    ) -> JsonObj: ...  # pragma: no cover

    def graphql(self, query: str, variables: JsonObj) -> JsonObj: ...  # pragma: no cover


def _classify_gh_failure(stdout: str, stderr: str) -> PrgroomError | GhNotFoundError:
    """Map a failed ``gh`` invocation to its registry error (§3.6/§3.7)."""
    match = _HTTP_STATUS.search(stderr)
    if match is None:
        # No parseable status: cannot prove transient, so treat as terminal
        # rather than invite an unbounded scheduler retry loop.
        return PrgroomError(
            tier=Tier.RUNTIME_TERMINAL_USER,
            code=ErrorCode.RUNTIME_GH_TERMINAL,
            detail=stderr.strip() or stdout.strip(),
        )
    status = int(match.group(1))
    detail = stderr.strip()
    if status == 404:  # HTTP status literal is self-documenting
        return GhNotFoundError(detail)
    # 429 is definitionally rate-limited; 403 is ambiguous (permissions vs
    # secondary rate limit) so it only counts as transient when the message
    # names a rate limit. 5xx is always a degraded-service transient.
    is_rate_limit = status == 429 or (  # Too Many Requests
        status == 403 and "rate limit" in stderr.lower()  # Forbidden
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

    def rest(self, method: str, path: str, *, fields: JsonObj | None = None) -> JsonObj:
        argv = ["gh", "api", "--method", method, path]
        for key, value in (fields or {}).items():
            argv += ["-f", f"{key}={value}"]
        out = self._run(argv)
        parsed: JsonObj = json.loads(out) if out.strip() else {}
        return parsed

    def graphql(self, query: str, variables: JsonObj) -> JsonObj:
        argv = ["gh", "api", "graphql", "-f", f"query={query}"]
        for key, value in variables.items():
            argv += ["-F", f"{key}={value}"]
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

    def _run(self, argv: list[str]) -> str:
        result = self._runner.run(argv)
        if result.returncode != 0:
            raise _classify_gh_failure(result.stdout, result.stderr)
        return result.stdout
