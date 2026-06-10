"""Fit-test for the gh adapter (§7.6).

Exercises the full public surface of ``GhCli`` against a ``RecordedRunner`` —
the subprocess boundary is the only mock point. Each failure-classification arm
(transient / terminal / not-found / graphql) is driven by a recorded
``CommandResult`` that reproduces what real ``gh`` writes, so the mapping to the
existing ``ErrorCode`` registry is exercised, not asserted at the definition
site.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.gh import GhCli, GhClient, GhNotFoundError
from prgroom.proc import CommandResult
from prgroom.prsession.pr_ref import PRRef
from tests.fakes import RecordedRunner

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "gh"


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text()


@pytest.fixture
def ref() -> PRRef:
    return PRRef(owner="octo", repo="demo", number=7)


def _ok(stdout: str) -> CommandResult:
    return CommandResult(returncode=0, stdout=stdout, stderr="")


def _gh_http_error(status: int, message: str) -> CommandResult:
    # Reproduces gh's real shape: JSON body on stdout, `gh: <msg> (HTTP NNN)` on stderr.
    body = json.dumps({"message": message, "status": str(status)})
    return CommandResult(returncode=1, stdout=body, stderr=f"gh: {message} (HTTP {status})")


# ── structural fit ──


def test_gh_cli_structurally_satisfies_protocol() -> None:
    assert isinstance(GhCli(RecordedRunner([])), GhClient)


# ── happy paths ──


def test_head_ref_oid_parses_json(ref: PRRef) -> None:
    runner = RecordedRunner([_ok(_fixture("pr_view_head_oid.json"))])
    client = GhCli(runner)
    assert client.head_ref_oid(ref) == "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4"
    # The adapter issued a `gh pr view <n> --json headRefOid` against the repo.
    argv = runner.calls[0]
    assert argv[:3] == ["gh", "pr", "view"]
    assert "headRefOid" in argv
    assert "octo/demo" in argv


def test_rest_returns_parsed_json() -> None:
    runner = RecordedRunner([_ok('{"login": "octocat"}')])
    client = GhCli(runner)
    assert client.rest("GET", "user") == {"login": "octocat"}
    assert runner.calls[0][:3] == ["gh", "api", "--method"]


def test_rest_with_fields_passes_each_as_field_flag() -> None:
    runner = RecordedRunner([_ok("{}")])
    client = GhCli(runner)
    client.rest("PATCH", "repos/octo/demo/pulls/7", fields={"body": "new body"})
    argv = runner.calls[0]
    assert "-f" in argv
    assert "body=new body" in argv


def test_graphql_returns_data() -> None:
    runner = RecordedRunner([_ok(_fixture("graphql_resolve_ok.json"))])
    client = GhCli(runner)
    data = client.graphql("mutation {...}", {"threadId": "PRRT_kwDOABC123"})
    assert data["resolveReviewThread"]["thread"]["isResolved"] is True
    argv = runner.calls[0]
    assert argv[:3] == ["gh", "api", "graphql"]


# ── failure classification ──


def test_graphql_errors_raise_graphql_failed() -> None:
    runner = RecordedRunner([_ok(_fixture("graphql_errors.json"))])
    client = GhCli(runner)
    with pytest.raises(PrgroomError) as exc:
        client.graphql("mutation {...}", {"threadId": "PRRT_bad"})
    assert exc.value.code is ErrorCode.RUNTIME_GRAPHQL_FAILED
    assert exc.value.tier is Tier.RUNTIME_TRANSIENT


def test_500_classifies_as_gh_transient() -> None:
    runner = RecordedRunner([_gh_http_error(500, "Internal Server Error")])
    client = GhCli(runner)
    with pytest.raises(PrgroomError) as exc:
        client.rest("GET", "user")
    assert exc.value.code is ErrorCode.RUNTIME_GH_TRANSIENT
    assert exc.value.tier is Tier.RUNTIME_TRANSIENT


def test_503_classifies_as_gh_transient() -> None:
    runner = RecordedRunner([_gh_http_error(503, "Service Unavailable")])
    client = GhCli(runner)
    with pytest.raises(PrgroomError) as exc:
        client.rest("GET", "user")
    assert exc.value.code is ErrorCode.RUNTIME_GH_TRANSIENT


def test_rate_limit_403_classifies_as_gh_transient() -> None:
    # gh's rate-limit message names "rate limit"; status is 403.
    runner = RecordedRunner(
        [
            CommandResult(
                returncode=1,
                stdout='{"message": "API rate limit exceeded", "status": "403"}',
                stderr="gh: API rate limit exceeded for user ID 1. (HTTP 403)",
            )
        ]
    )
    client = GhCli(runner)
    with pytest.raises(PrgroomError) as exc:
        client.rest("GET", "user")
    assert exc.value.code is ErrorCode.RUNTIME_GH_TRANSIENT


def test_429_classifies_as_gh_transient() -> None:
    runner = RecordedRunner([_gh_http_error(429, "Too Many Requests")])
    client = GhCli(runner)
    with pytest.raises(PrgroomError) as exc:
        client.rest("GET", "user")
    assert exc.value.code is ErrorCode.RUNTIME_GH_TRANSIENT


def test_422_classifies_as_gh_terminal() -> None:
    runner = RecordedRunner([_gh_http_error(422, "Validation Failed")])
    client = GhCli(runner)
    with pytest.raises(PrgroomError) as exc:
        client.rest("POST", "repos/octo/demo/issues")
    assert exc.value.code is ErrorCode.RUNTIME_GH_TERMINAL
    assert exc.value.tier is Tier.RUNTIME_TERMINAL_USER


def test_401_classifies_as_gh_terminal() -> None:
    runner = RecordedRunner([_gh_http_error(401, "Bad credentials")])
    client = GhCli(runner)
    with pytest.raises(PrgroomError) as exc:
        client.rest("GET", "user")
    assert exc.value.code is ErrorCode.RUNTIME_GH_TERMINAL


def test_403_without_rate_limit_classifies_as_gh_terminal() -> None:
    # A plain permissions 403 (no rate-limit wording) is terminal, not transient.
    runner = RecordedRunner(
        [
            CommandResult(
                returncode=1,
                stdout='{"message": "Resource not accessible by integration", "status": "403"}',
                stderr="gh: Resource not accessible by integration (HTTP 403)",
            )
        ]
    )
    client = GhCli(runner)
    with pytest.raises(PrgroomError) as exc:
        client.rest("POST", "repos/octo/demo/issues/1/labels")
    assert exc.value.code is ErrorCode.RUNTIME_GH_TERMINAL


def test_404_raises_typed_not_found_not_a_prgroom_error(ref: PRRef) -> None:
    # 404 is the caller's precondition (PRECONDITION_REPO_UNREACHABLE), so the
    # adapter surfaces a distinct typed signal and does NOT pre-classify it.
    runner = RecordedRunner([_gh_http_error(404, "Not Found")])
    client = GhCli(runner)
    with pytest.raises(GhNotFoundError):
        client.head_ref_oid(ref)


def test_unparseable_error_falls_back_to_gh_terminal() -> None:
    # A failure with no parseable `(HTTP NNN)` token is treated as terminal —
    # we cannot prove it transient, so we do not invite an infinite retry loop.
    runner = RecordedRunner(
        [CommandResult(returncode=1, stdout="", stderr="gh: command failed unexpectedly")]
    )
    client = GhCli(runner)
    with pytest.raises(PrgroomError) as exc:
        client.rest("GET", "user")
    assert exc.value.code is ErrorCode.RUNTIME_GH_TERMINAL
