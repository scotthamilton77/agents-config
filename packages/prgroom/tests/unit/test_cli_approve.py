"""CLI-boundary behaviour for the ``approve`` verb.

Both production boundaries — the App transport and the subprocess runner — are
monkeypatched at their build seams, so no test here reaches the network, a key,
or ``openssl``. Exit codes are the contract a caller keys on, so each failure
asserts the code the tier maps to and that no traceback escaped.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from prgroom import cli
from prgroom.errors import ErrorCode
from prgroom.gh.app import GITHUB_API, REVIEWS_PER_PAGE
from prgroom.proc import CommandResult
from tests.fakes import RecordedRunner

runner = CliRunner()

HEAD = "a" * 40
MOVED = "b" * 40
PULL = "/repos/octo/demo/pulls/5"
PR_ARG = "octo/demo#5"

Routes = dict[tuple[str, str], tuple[int, Any]]

BASE_ROUTES: Routes = {
    ("GET", "/app"): (200, {"slug": "pr-hater"}),
    ("GET", "/repos/octo/demo/installation"): (200, {"id": 42}),
    ("POST", "/app/installations/42/access_tokens"): (201, {"token": "tok"}),
    ("GET", PULL): (200, {"head": {"sha": HEAD}}),
    ("GET", f"{PULL}/reviews?per_page={REVIEWS_PER_PAGE}&page=1"): (200, []),
    ("POST", f"{PULL}/reviews"): (200, {"id": 99}),
}

CONFIG = """
[merge-policy]
merge-authorization = "explicit"

[merge-policy.approver]
type         = "github-app"
app-id       = 4275336
key-path-env = "APPROVER_KEY_PATH"
"""


class CliHttp:
    """An ``HttpTransport`` fake; an unrouted call raises rather than defaulting."""

    def __init__(self, routes: Routes) -> None:
        self.routes = dict(routes)
        self.calls: list[tuple[str, str, bytes | None]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Any,  # noqa: ARG002  # part of the transport signature; not asserted here
        body: bytes | None = None,
    ) -> tuple[int, Any]:
        self.calls.append((method, url, body))
        for (route_method, suffix), response in self.routes.items():
            if route_method == method and url == GITHUB_API + suffix:
                return response
        msg = f"unexpected call: {method} {url}"
        raise AssertionError(msg)

    def posted_reviews(self) -> list[Any]:
        return [
            json.loads(body)
            for method, url, body in self.calls
            if method == "POST" and url.endswith("/reviews") and body is not None
        ]


@pytest.fixture
def approver_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A readable key, an env var naming it, and a project config on disk."""
    key = tmp_path / "app.pem"
    key.write_text("-----BEGIN PRIVATE KEY-----\n")
    config = tmp_path / "project-config.toml"
    config.write_text(CONFIG)
    monkeypatch.setenv("APPROVER_KEY_PATH", str(key))
    return config, key


def wire(monkeypatch: pytest.MonkeyPatch, http: CliHttp) -> None:
    monkeypatch.setattr(cli, "_build_http", lambda: http)
    monkeypatch.setattr(
        cli,
        "_build_runner",
        lambda: RecordedRunner([CommandResult(0, "SHA2-256(stdin)= 0a0b\n", "")]),
    )


def invoke(config: Path, *extra: str, head: str = HEAD) -> Any:
    return runner.invoke(
        cli.app,
        ["approve", PR_ARG, "--head-sha", head, "--project-config", str(config), *extra],
    )


def test_help_lists_the_four_inputs() -> None:
    result = runner.invoke(cli.app, ["approve", "--help"])
    assert result.exit_code == 0
    for token in ("PR", "--head-sha", "--facts", "--project-config"):
        assert token in result.output


def test_approve_is_a_registered_verb() -> None:
    assert "approve" in runner.invoke(cli.app, ["--help"]).output


def test_the_happy_path_posts_and_reports_the_review_on_stdout(
    approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = approver_env
    http = CliHttp(BASE_ROUTES)
    wire(monkeypatch, http)
    result = invoke(config, "--facts", '{"why": "instructed"}')
    assert result.exit_code == 0
    (posted,) = http.posted_reviews()
    assert posted["event"] == "APPROVE"
    assert posted["commit_id"] == HEAD
    assert '{"why": "instructed"}' in posted["body"]
    assert "approved: review 99" in result.output


def test_an_existing_approval_at_the_head_exits_zero_without_posting(
    approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = approver_env
    routes = dict(BASE_ROUTES)
    routes[("GET", f"{PULL}/reviews?per_page={REVIEWS_PER_PAGE}&page=1")] = (
        200,
        [{"id": 7, "state": "APPROVED", "commit_id": HEAD, "user": {"login": "pr-hater[bot]"}}],
    )
    http = CliHttp(routes)
    wire(monkeypatch, http)
    result = invoke(config)
    assert result.exit_code == 0
    assert http.posted_reviews() == []
    assert "already approved" in result.output


def test_facts_default_to_an_empty_object(
    approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = approver_env
    http = CliHttp(BASE_ROUTES)
    wire(monkeypatch, http)
    assert invoke(config).exit_code == 0
    (posted,) = http.posted_reviews()
    assert "`{}`" in posted["body"]


class TestFailuresAreCodedNotTracebacks:
    def test_a_moved_head_refuses_at_the_precondition_exit_code(
        self, approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, _ = approver_env
        routes = dict(BASE_ROUTES)
        routes[("GET", PULL)] = (200, {"head": {"sha": MOVED}})
        http = CliHttp(routes)
        wire(monkeypatch, http)
        result = invoke(config)
        assert result.exit_code == 2
        assert ErrorCode.PRECONDITION_APPROVER_HEAD_MOVED.value in result.output
        assert http.posted_reviews() == []

    def test_a_missing_approver_block_is_refused_before_any_api_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = tmp_path / "project-config.toml"
        config.write_text('[merge-policy]\nmerge-authorization = "explicit"\n')
        http = CliHttp({})
        wire(monkeypatch, http)
        result = invoke(config)
        assert result.exit_code == 2
        assert ErrorCode.PRECONDITION_APPROVER_CONFIG.value in result.output
        assert http.calls == []

    def test_a_malformed_approver_block_is_refused_before_any_api_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = tmp_path / "project-config.toml"
        config.write_text('[merge-policy.approver]\ntype = "github-app"\napp-id = -1\n')
        http = CliHttp({})
        wire(monkeypatch, http)
        result = invoke(config)
        assert result.exit_code == 2
        assert ErrorCode.PRECONDITION_APPROVER_CONFIG.value in result.output
        assert http.calls == []

    def test_an_unset_key_env_var_is_refused_before_any_api_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = tmp_path / "project-config.toml"
        config.write_text(CONFIG)
        monkeypatch.delenv("APPROVER_KEY_PATH", raising=False)
        http = CliHttp({})
        wire(monkeypatch, http)
        result = invoke(config)
        assert result.exit_code == 2
        assert ErrorCode.PRECONDITION_APPROVER_KEY_ENV_UNSET.value in result.output
        assert http.calls == []

    def test_an_unreadable_key_is_refused_before_any_api_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = tmp_path / "project-config.toml"
        config.write_text(CONFIG)
        monkeypatch.setenv("APPROVER_KEY_PATH", str(tmp_path / "nowhere" / "app.pem"))
        http = CliHttp({})
        wire(monkeypatch, http)
        result = invoke(config)
        assert result.exit_code == 2
        assert ErrorCode.PRECONDITION_APPROVER_KEY_UNREADABLE.value in result.output
        assert http.calls == []

    def test_an_uninstalled_app_exits_with_the_terminal_environment_code(
        self, approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, _ = approver_env
        routes = dict(BASE_ROUTES)
        routes[("GET", "/repos/octo/demo/installation")] = (404, {"message": "Not Found"})
        wire(monkeypatch, CliHttp(routes))
        result = invoke(config)
        assert result.exit_code == 77
        assert ErrorCode.RUNTIME_APPROVER_NOT_INSTALLED.value in result.output

    def test_a_failed_mint_exits_with_the_terminal_environment_code(
        self, approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, _ = approver_env
        routes = dict(BASE_ROUTES)
        routes[("POST", "/app/installations/42/access_tokens")] = (401, {"message": "bad creds"})
        wire(monkeypatch, CliHttp(routes))
        result = invoke(config)
        assert result.exit_code == 77
        assert ErrorCode.RUNTIME_APPROVER_API_FAILED.value in result.output

    def test_a_rejected_review_post_exits_with_the_terminal_environment_code(
        self, approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, _ = approver_env
        routes = dict(BASE_ROUTES)
        routes[("POST", f"{PULL}/reviews")] = (422, {"message": "unprocessable"})
        wire(monkeypatch, CliHttp(routes))
        result = invoke(config)
        assert result.exit_code == 77
        assert ErrorCode.RUNTIME_APPROVER_API_FAILED.value in result.output

    def test_a_failed_signature_exits_with_the_terminal_environment_code(
        self, approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, _ = approver_env
        http = CliHttp(BASE_ROUTES)
        monkeypatch.setattr(cli, "_build_http", lambda: http)
        monkeypatch.setattr(
            cli,
            "_build_runner",
            lambda: RecordedRunner([CommandResult(1, "", "bad decrypt")]),
        )
        result = invoke(config)
        assert result.exit_code == 77
        assert ErrorCode.RUNTIME_APPROVER_SIGN_FAILED.value in result.output
        assert http.calls == []

    def test_the_head_moved_exit_code_differs_from_the_environment_one(
        self, approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A caller must be able to tell "re-decide against the new head" from
        # "this box cannot talk to GitHub" by exit status alone.
        config, _ = approver_env
        moved_routes = dict(BASE_ROUTES)
        moved_routes[("GET", PULL)] = (200, {"head": {"sha": MOVED}})
        wire(monkeypatch, CliHttp(moved_routes))
        moved = invoke(config)
        failed_routes = dict(BASE_ROUTES)
        failed_routes[("POST", "/app/installations/42/access_tokens")] = (500, {"message": "boom"})
        wire(monkeypatch, CliHttp(failed_routes))
        failed = invoke(config)
        assert moved.exit_code != failed.exit_code


class TestArgumentValidation:
    @pytest.mark.parametrize("bad", ["not-a-sha", "a" * 39, "a" * 41, "z" * 40, ""])
    def test_a_head_sha_that_is_not_40_hex_is_rejected_at_parse(
        self, bad: str, approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, _ = approver_env
        http = CliHttp({})
        wire(monkeypatch, http)
        result = invoke(config, head=bad)
        assert result.exit_code == 2
        assert http.calls == []

    def test_an_uppercase_head_sha_is_normalized_rather_than_refused(
        self, approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, _ = approver_env
        http = CliHttp(BASE_ROUTES)
        wire(monkeypatch, http)
        result = invoke(config, head=HEAD.upper())
        assert result.exit_code == 0
        (posted,) = http.posted_reviews()
        assert posted["commit_id"] == HEAD

    def test_a_malformed_pr_ref_is_refused_before_any_api_call(
        self, approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, _ = approver_env
        http = CliHttp({})
        wire(monkeypatch, http)
        result = runner.invoke(
            cli.app,
            ["approve", "not a ref", "--head-sha", HEAD, "--project-config", str(config)],
        )
        assert result.exit_code == 2
        assert ErrorCode.PRECONDITION_BAD_PR_REF.value in result.output
        assert http.calls == []
