"""CLI-boundary behaviour for the ``approve`` verb.

Both production boundaries — the App transport and the subprocess runner — are
monkeypatched at their build seams, so no test here reaches the network, a key,
or ``openssl``. Exit codes are the contract a caller keys on, so each failure
asserts the code the tier maps to and that no traceback escaped.
"""

from __future__ import annotations

import os
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from prgroom import cli
from prgroom.errors import ErrorCode, PreconditionError
from prgroom.gh.app import REVIEWS_PER_PAGE
from prgroom.lifecycle.run import Verbs
from prgroom.proc import CommandResult
from tests.fakes import RecordedRunner, RouteTableHttp

runner = CliRunner()

APP_ID = 4275336
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


def transport(routes: dict[tuple[str, str], tuple[int, Any]]) -> RouteTableHttp:
    """The App-HTTP fake with its credential rule armed for this App.

    Every construction in this module goes through here, so a call site that
    drops or swaps a credential is refused wherever one is added.
    """
    return RouteTableHttp(routes, app_id=APP_ID)


@pytest.fixture
def approver_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A readable key, an env var naming it, and a project config on disk."""
    key = tmp_path / "app.pem"
    key.write_text("-----BEGIN PRIVATE KEY-----\n")
    config = tmp_path / "project-config.toml"
    config.write_text(CONFIG)
    monkeypatch.setenv("APPROVER_KEY_PATH", str(key))
    return config, key


def wire(monkeypatch: pytest.MonkeyPatch, http: RouteTableHttp) -> None:
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


# Rich styles option tokens and wraps to the terminal width, so `--head-sha`
# arrives split by escape codes wherever colour is on (CI is). Asking for a wide,
# colourless render keeps an option name a contiguous token to assert on.
PLAIN_HELP_ENV = {"NO_COLOR": "1", "FORCE_COLOR": None, "TERM": "dumb", "COLUMNS": "200"}


def help_output(*args: str) -> str:
    return runner.invoke(cli.app, [*args, "--help"], env=PLAIN_HELP_ENV).output


def test_help_lists_the_four_inputs() -> None:
    result = runner.invoke(cli.app, ["approve", "--help"], env=PLAIN_HELP_ENV)
    assert result.exit_code == 0
    for token in ("PR", "--head-sha", "--facts", "--project-config"):
        assert token in result.output


def test_approve_is_a_registered_verb() -> None:
    assert "approve" in runner.invoke(cli.app, ["--help"]).output


def test_the_happy_path_posts_and_reports_the_review_on_stdout(
    approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = approver_env
    http = transport(BASE_ROUTES)
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
    http = transport(routes)
    wire(monkeypatch, http)
    result = invoke(config)
    assert result.exit_code == 0
    assert http.posted_reviews() == []
    assert "already approved" in result.output


def test_facts_default_to_an_empty_object(
    approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = approver_env
    http = transport(BASE_ROUTES)
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
        http = transport(routes)
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
        http = transport({})
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
        http = transport({})
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
        http = transport({})
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
        http = transport({})
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
        wire(monkeypatch, transport(routes))
        result = invoke(config)
        assert result.exit_code == 77
        assert ErrorCode.RUNTIME_APPROVER_NOT_INSTALLED.value in result.output

    def test_a_failed_mint_exits_with_the_terminal_environment_code(
        self, approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, _ = approver_env
        routes = dict(BASE_ROUTES)
        routes[("POST", "/app/installations/42/access_tokens")] = (401, {"message": "bad creds"})
        wire(monkeypatch, transport(routes))
        result = invoke(config)
        assert result.exit_code == 77
        assert ErrorCode.RUNTIME_APPROVER_API_FAILED.value in result.output

    def test_a_rejected_review_post_exits_with_the_terminal_environment_code(
        self, approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, _ = approver_env
        routes = dict(BASE_ROUTES)
        routes[("POST", f"{PULL}/reviews")] = (422, {"message": "unprocessable"})
        wire(monkeypatch, transport(routes))
        result = invoke(config)
        assert result.exit_code == 77
        assert ErrorCode.RUNTIME_APPROVER_API_FAILED.value in result.output

    def test_a_failed_signature_exits_with_the_terminal_environment_code(
        self, approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, _ = approver_env
        http = transport(BASE_ROUTES)
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
        wire(monkeypatch, transport(moved_routes))
        moved = invoke(config)
        failed_routes = dict(BASE_ROUTES)
        failed_routes[("POST", "/app/installations/42/access_tokens")] = (500, {"message": "boom"})
        wire(monkeypatch, transport(failed_routes))
        failed = invoke(config)
        assert moved.exit_code != failed.exit_code


class TestArgumentValidation:
    @pytest.mark.parametrize("bad", ["not-a-sha", "a" * 39, "a" * 41, "z" * 40, ""])
    def test_a_head_sha_that_is_not_40_hex_is_rejected_at_parse(
        self, bad: str, approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, _ = approver_env
        http = transport({})
        wire(monkeypatch, http)
        result = invoke(config, head=bad)
        assert result.exit_code == 2
        assert http.calls == []

    def test_an_uppercase_head_sha_is_normalized_rather_than_refused(
        self, approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, _ = approver_env
        http = transport(BASE_ROUTES)
        wire(monkeypatch, http)
        result = invoke(config, head=HEAD.upper())
        assert result.exit_code == 0
        (posted,) = http.posted_reviews()
        assert posted["commit_id"] == HEAD

    def test_a_malformed_pr_ref_is_refused_before_any_api_call(
        self, approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, _ = approver_env
        http = transport({})
        wire(monkeypatch, http)
        result = runner.invoke(
            cli.app,
            ["approve", "not a ref", "--head-sha", HEAD, "--project-config", str(config)],
        )
        assert result.exit_code == 2
        assert ErrorCode.PRECONDITION_BAD_PR_REF.value in result.output
        assert http.calls == []


class TestOutsideTheGroomingLoop:
    def test_a_store_that_cannot_be_built_does_not_prevent_an_approval(
        self, approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # approve reads and writes no grooming state and takes no PR lock, so an
        # unrelated --store / PRGROOM_STORE setting must not stand between a
        # human-instructed merge and the review that unblocks it.
        config, _ = approver_env

        def unusable_store(_name: str | None) -> object:
            raise PreconditionError(ErrorCode.PRECONDITION_STORE_UNAVAILABLE)

        monkeypatch.setattr(cli, "_build_store", unusable_store)
        http = transport(BASE_ROUTES)
        wire(monkeypatch, http)
        result = invoke(config)
        assert result.exit_code == 0
        assert len(http.posted_reviews()) == 1

    def test_approve_is_not_a_verb_the_run_aggregate_can_thread(self) -> None:
        # run drives exactly the callables Verbs carries, and builds its pipeline
        # from those fields alone; no slot for approve means no path to it.
        assert "approve" not in {field.name for field in fields(Verbs)}


class TestNoRetryAndNoOverride:
    def test_a_failing_route_is_called_exactly_once(
        self, approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, _ = approver_env
        routes = dict(BASE_ROUTES)
        routes[("POST", "/app/installations/42/access_tokens")] = (500, {"message": "boom"})
        http = transport(routes)
        wire(monkeypatch, http)
        assert invoke(config).exit_code == 77
        mints = [url for _, url, _, _ in http.calls if url.endswith("/access_tokens")]
        assert len(mints) == 1

    def test_no_admin_override_option_is_offered(self) -> None:
        assert "--admin" not in help_output("approve")
        assert invoke(Path("project-config.toml"), "--admin").exit_code != 0


class TestDefaultProjectConfigPath:
    def test_the_default_config_is_the_one_in_the_current_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        key = tmp_path / "app.pem"
        key.write_text("-----BEGIN PRIVATE KEY-----\n")
        (tmp_path / "project-config.toml").write_text(CONFIG)
        monkeypatch.setenv("APPROVER_KEY_PATH", str(key))
        monkeypatch.chdir(tmp_path)
        http = transport(BASE_ROUTES)
        wire(monkeypatch, http)
        result = runner.invoke(cli.app, ["approve", PR_ARG, "--head-sha", HEAD])
        assert result.exit_code == 0
        assert len(http.posted_reviews()) == 1


class TestUnreadableProjectConfig:
    def test_a_config_that_exists_but_cannot_be_opened_is_the_approver_config_error(
        self, approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        if os.geteuid() == 0:
            pytest.skip("root reads a mode-000 file, so the failure cannot be provoked")
        config, _ = approver_env
        config.chmod(0o000)
        http = transport({})
        wire(monkeypatch, http)
        try:
            result = invoke(config)
        finally:
            config.chmod(0o600)
        assert result.exit_code == 2
        assert ErrorCode.PRECONDITION_APPROVER_CONFIG.value in result.output
        assert http.calls == []


def test_head_sha_is_required_and_its_absence_costs_no_network_call(
    approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = approver_env
    http = transport({})
    wire(monkeypatch, http)
    result = runner.invoke(cli.app, ["approve", PR_ARG, "--project-config", str(config)])
    assert result.exit_code == 2
    assert http.calls == []


def test_facts_reach_the_review_body_byte_for_byte(
    approver_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Deliberately non-canonical: odd spacing and a key order json.dumps would
    # not reproduce, so a body built by re-serializing the input fails here.
    facts = '{ "rule":"instructed",   "b":1,\t"a":[2,3] }'
    config, _ = approver_env
    http = transport(BASE_ROUTES)
    wire(monkeypatch, http)
    assert invoke(config, "--facts", facts).exit_code == 0
    (posted,) = http.posted_reviews()
    assert facts in posted["body"]


def test_an_unreadable_key_file_is_refused_before_any_api_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root reads a mode-000 file, so the failure cannot be provoked")
    key = tmp_path / "app.pem"
    key.write_text("-----BEGIN PRIVATE KEY-----\n")
    key.chmod(0o000)
    config = tmp_path / "project-config.toml"
    config.write_text(CONFIG)
    monkeypatch.setenv("APPROVER_KEY_PATH", str(key))
    http = transport({})
    wire(monkeypatch, http)
    try:
        result = invoke(config)
    finally:
        key.chmod(0o600)
    assert result.exit_code == 2
    assert ErrorCode.PRECONDITION_APPROVER_KEY_UNREADABLE.value in result.output
    assert http.calls == []
