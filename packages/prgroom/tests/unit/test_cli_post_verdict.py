"""CLI-boundary behaviour for the ``post-verdict`` verb.

Both production boundaries — the App transport and the subprocess runner — are
monkeypatched at their build seams, so no test here reaches the network, a key,
or ``openssl``. A verdict the verb cannot use is refused before any of them is
touched, and the assertion for that is the absence of a call, not just the code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from prgroom import cli
from prgroom.errors import ErrorCode, PreconditionError
from prgroom.gh.app import FILES_PER_PAGE, REVIEWS_PER_PAGE
from prgroom.lifecycle.post_verdict import MAX_BODY_CHARS
from prgroom.lifecycle.run import Verbs
from prgroom.proc import CommandResult
from tests.fakes import RecordedRunner, RouteTableHttp

runner = CliRunner()

APP_ID = 4275336
HEAD = "a" * 40
MOVED = "b" * 40
PULL = "/repos/octo/demo/pulls/5"
PR_ARG = "octo/demo#5"
APP_PY = "packages/prgroom/src/prgroom/gh/app.py"

Routes = dict[tuple[str, str], tuple[int, Any]]

FILES: list[dict[str, Any]] = [
    {"filename": APP_PY, "patch": "@@ -1,4 +1,6 @@\n import json\n+import re\n"}
]

BASE_ROUTES: Routes = {
    ("GET", "/app"): (200, {"slug": "pr-hater"}),
    ("GET", "/repos/octo/demo/installation"): (200, {"id": 42}),
    ("POST", "/app/installations/42/access_tokens"): (201, {"token": "tok"}),
    ("GET", PULL): (200, {"head": {"sha": HEAD}}),
    ("GET", f"{PULL}/reviews?per_page={REVIEWS_PER_PAGE}&page=1"): (200, []),
    ("GET", f"{PULL}/files?per_page={FILES_PER_PAGE}&page=1"): (200, FILES),
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

ENVELOPE: dict[str, Any] = {
    "schema_version": "3",
    "head_sha": HEAD,
    "verdict": "findings",
    "findings": [
        {
            "id": "correctness.r1.f1",
            "lens": "correctness",
            "type": "mechanical",
            "ac": "AC-2",
            "claim": "the field is read without a guard",
            "evidence": f"{APP_PY}:3 indexes it directly",
        }
    ],
}


def transport(routes: dict[tuple[str, str], tuple[int, Any]]) -> RouteTableHttp:
    """The App-HTTP fake with its credential rule armed for this App.

    Every construction in this module goes through here, so a call site that
    drops or swaps a credential is refused wherever one is added.
    """
    return RouteTableHttp(routes, app_id=APP_ID)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A readable key, an env var naming it, a project config, and a verdict file."""
    key = tmp_path / "app.pem"
    key.write_text("-----BEGIN PRIVATE KEY-----\n")
    config = tmp_path / "project-config.toml"
    config.write_text(CONFIG)
    verdict = tmp_path / "verdict.json"
    verdict.write_text(json.dumps(ENVELOPE, indent=2))
    monkeypatch.setenv("APPROVER_KEY_PATH", str(key))
    return config, verdict


def wire(monkeypatch: pytest.MonkeyPatch, http: RouteTableHttp) -> None:
    monkeypatch.setattr(cli, "_build_http", lambda: http)
    monkeypatch.setattr(
        cli,
        "_build_runner",
        lambda: RecordedRunner([CommandResult(0, "SHA2-256(stdin)= 0a0b\n", "")]),
    )


def invoke(config: Path, verdict: Path, *extra: str) -> Any:
    return runner.invoke(
        cli.app,
        [
            "post-verdict",
            PR_ARG,
            "--verdict",
            str(verdict),
            "--project-config",
            str(config),
            *extra,
        ],
    )


# Rich styles option tokens and wraps to the terminal width, so an option name
# arrives split by escape codes wherever colour is on (CI is). Asking for a wide,
# colourless render keeps it a contiguous token to assert on.
PLAIN_HELP_ENV = {"NO_COLOR": "1", "FORCE_COLOR": None, "TERM": "dumb", "COLUMNS": "200"}


def help_output(*args: str) -> str:
    return runner.invoke(cli.app, [*args, "--help"], env=PLAIN_HELP_ENV).output


def test_post_verdict_is_a_registered_verb() -> None:
    assert "post-verdict" in runner.invoke(cli.app, ["--help"]).output


def test_help_lists_the_three_inputs() -> None:
    output = help_output("post-verdict")
    for token in ("PR", "--verdict", "--project-config"):
        assert token in output


def test_the_happy_path_posts_and_reports_the_review_on_stdout(
    workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    config, verdict = workspace
    http = transport(BASE_ROUTES)
    wire(monkeypatch, http)
    result = invoke(config, verdict)
    assert result.exit_code == 0
    (posted,) = http.posted_reviews()
    assert posted["event"] == "COMMENT"
    assert posted["commit_id"] == HEAD
    assert posted["body"] == verdict.read_text()
    assert posted["comments"][0]["path"] == APP_PY
    assert "posted: review 99" in result.output


def test_a_finding_with_no_placeable_anchor_is_named_on_stdout(
    workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    config, verdict = workspace
    envelope = json.loads(verdict.read_text())
    envelope["findings"][0]["evidence"] = "nothing locatable"
    verdict.write_text(json.dumps(envelope))
    http = transport(BASE_ROUTES)
    wire(monkeypatch, http)
    result = invoke(config, verdict)
    assert result.exit_code == 0
    assert "no line in the diff for finding correctness.r1.f1" in result.output


def test_the_verdict_is_required(
    workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _ = workspace
    http = transport({})
    wire(monkeypatch, http)
    result = runner.invoke(cli.app, ["post-verdict", PR_ARG, "--project-config", str(config)])
    assert result.exit_code == 2
    assert http.calls == []


class TestARejectedVerdictCostsNoApiCall:
    def run_with(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
    ) -> tuple[Any, RouteTableHttp]:
        key = tmp_path / "app.pem"
        key.write_text("-----BEGIN PRIVATE KEY-----\n")
        config = tmp_path / "project-config.toml"
        config.write_text(CONFIG)
        verdict = tmp_path / "verdict.json"
        verdict.write_text(body)
        monkeypatch.setenv("APPROVER_KEY_PATH", str(key))
        http = transport({})
        wire(monkeypatch, http)
        return invoke(config, verdict), http

    def test_a_verdict_file_that_is_not_there_is_the_unreadable_error(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config, _ = workspace
        http = transport({})
        wire(monkeypatch, http)
        result = invoke(config, tmp_path / "nowhere" / "verdict.json")
        assert result.exit_code == 2
        assert ErrorCode.PRECONDITION_VERDICT_UNREADABLE.value in result.output
        assert http.calls == []

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param("not json at all", id="a-file-that-is-not-json"),
            pytest.param("[]", id="a-json-array-rather-than-an-object"),
            pytest.param('"a string"', id="a-json-string-rather-than-an-object"),
            pytest.param("{}", id="an-envelope-with-no-head-sha"),
            pytest.param('{"head_sha": 7, "findings": []}', id="a-numeric-head-sha"),
            pytest.param('{"head_sha": null, "findings": []}', id="a-null-head-sha"),
            pytest.param('{"head_sha": "", "findings": []}', id="an-empty-head-sha"),
            pytest.param('{"head_sha": "abc", "findings": []}', id="an-abbreviated-head-sha"),
            pytest.param('{"head_sha": "' + HEAD + '"}', id="an-envelope-with-no-findings"),
            pytest.param(
                '{"head_sha": "' + HEAD + '", "findings": {}}', id="findings-as-an-object"
            ),
            pytest.param(
                '{"head_sha": "' + HEAD + '", "findings": "none"}', id="findings-as-a-string"
            ),
            pytest.param(
                '{"head_sha": "' + HEAD + '", "findings": [7]}', id="a-finding-that-is-a-number"
            ),
            pytest.param(
                '{"head_sha": "' + HEAD + '", "findings": [{}]}', id="a-finding-with-no-id"
            ),
            pytest.param(
                '{"head_sha": "' + HEAD + '", "findings": [{"id": 7}]}',
                id="a-finding-with-a-numeric-id",
            ),
            pytest.param(
                '{"head_sha": "' + HEAD + '", "findings": [{"id": " "}]}',
                id="a-finding-with-a-blank-id",
            ),
            pytest.param(
                '{"head_sha": "' + HEAD + '", "findings": [{"id": "f1", "evidence": 7}]}',
                id="a-finding-with-numeric-evidence",
            ),
            pytest.param(
                '{"head_sha": "' + HEAD + '", "findings": [{"id": "f1", "claim": []}]}',
                id="a-finding-with-a-list-claim",
            ),
            pytest.param(
                '{"head_sha": "' + HEAD + '", "findings": [{"id": "f1"}]}',
                id="a-finding-with-neither-evidence-nor-claim",
            ),
            pytest.param(
                '{"head_sha": "' + HEAD + '", "findings": [{"id": "f1", "evidence": "  "}]}',
                id="a-finding-whose-evidence-is-blank",
            ),
            pytest.param(
                '{"head_sha": "' + HEAD + '", "findings": [{"id": "f1", "claim": "", '
                '"evidence": ""}]}',
                id="a-finding-whose-evidence-and-claim-are-both-empty",
            ),
        ],
    )
    def test_a_malformed_verdict_is_the_malformed_error(
        self, body: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, http = self.run_with(tmp_path, monkeypatch, body)
        assert result.exit_code == 2
        assert ErrorCode.PRECONDITION_VERDICT_MALFORMED.value in result.output
        assert http.calls == []

    def test_a_verdict_that_is_not_utf8_is_the_malformed_error(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, verdict = workspace
        verdict.write_bytes(b'{"head_sha": "\xff\xfe"}')
        http = transport({})
        wire(monkeypatch, http)
        result = invoke(config, verdict)
        assert result.exit_code == 2
        assert ErrorCode.PRECONDITION_VERDICT_MALFORMED.value in result.output
        assert http.calls == []

    def test_a_verdict_past_the_body_limit_is_refused_rather_than_truncated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oversized = dict(ENVELOPE)
        oversized["findings"] = [{"id": "f1", "type": "advisory", "evidence": "x" * MAX_BODY_CHARS}]
        result, http = self.run_with(tmp_path, monkeypatch, json.dumps(oversized))
        assert result.exit_code == 2
        assert ErrorCode.PRECONDITION_VERDICT_TOO_LARGE.value in result.output
        assert http.calls == []

    def test_a_verdict_exactly_at_the_body_limit_is_accepted(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The refusal is on exceeding the limit, not on reaching it: a verdict the
        # API would accept must not be refused locally.
        config, verdict = workspace
        envelope = json.loads(verdict.read_text())
        envelope["findings"][0]["claim"] = ""
        envelope["findings"][0]["claim"] = "x" * (MAX_BODY_CHARS - len(json.dumps(envelope)))
        padded = json.dumps(envelope)
        assert len(padded) == MAX_BODY_CHARS
        verdict.write_text(padded)
        http = transport(BASE_ROUTES)
        wire(monkeypatch, http)
        assert invoke(config, verdict).exit_code == 0


class TestFailuresAreCodedNotTracebacks:
    def test_a_moved_head_refuses_at_the_precondition_exit_code(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, verdict = workspace
        routes = dict(BASE_ROUTES)
        routes[("GET", PULL)] = (200, {"head": {"sha": MOVED}})
        http = transport(routes)
        wire(monkeypatch, http)
        result = invoke(config, verdict)
        assert result.exit_code == 2
        assert ErrorCode.PRECONDITION_APPROVER_HEAD_MOVED.value in result.output
        assert http.posted_reviews() == []

    def test_a_missing_approver_block_is_refused_before_any_api_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = tmp_path / "project-config.toml"
        config.write_text('[merge-policy]\nmerge-authorization = "explicit"\n')
        verdict = tmp_path / "verdict.json"
        verdict.write_text(json.dumps(ENVELOPE))
        http = transport({})
        wire(monkeypatch, http)
        result = invoke(config, verdict)
        assert result.exit_code == 2
        assert ErrorCode.PRECONDITION_APPROVER_CONFIG.value in result.output
        assert http.calls == []

    def test_a_rejected_submission_exits_with_the_terminal_environment_code(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, verdict = workspace
        routes = dict(BASE_ROUTES)
        routes[("POST", f"{PULL}/reviews")] = (422, {"message": "unprocessable"})
        wire(monkeypatch, transport(routes))
        result = invoke(config, verdict)
        assert result.exit_code == 77
        assert ErrorCode.RUNTIME_APPROVER_API_FAILED.value in result.output

    def test_a_failed_files_listing_exits_with_the_terminal_environment_code(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, verdict = workspace
        routes = dict(BASE_ROUTES)
        routes[("GET", f"{PULL}/files?per_page={FILES_PER_PAGE}&page=1")] = (403, {"m": "denied"})
        http = transport(routes)
        wire(monkeypatch, http)
        result = invoke(config, verdict)
        assert result.exit_code == 77
        assert ErrorCode.RUNTIME_APPROVER_API_FAILED.value in result.output
        assert http.posted_reviews() == []


class TestOutsideTheGroomingLoop:
    def test_a_store_that_cannot_be_built_does_not_prevent_a_posting(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, verdict = workspace

        def unusable_store(_name: str | None) -> object:
            raise PreconditionError(ErrorCode.PRECONDITION_STORE_UNAVAILABLE)

        monkeypatch.setattr(cli, "_build_store", unusable_store)
        http = transport(BASE_ROUTES)
        wire(monkeypatch, http)
        result = invoke(config, verdict)
        assert result.exit_code == 0
        assert len(http.posted_reviews()) == 1

    def test_post_verdict_is_not_a_verb_the_run_aggregate_can_thread(self) -> None:
        # run drives exactly the callables Verbs carries, and builds its pipeline
        # from those fields alone; no slot for it means no path to it.
        from dataclasses import fields

        assert "post_verdict" not in {field.name for field in fields(Verbs)}


class TestNoRetryAndNoApproval:
    def test_a_failing_route_is_called_exactly_once(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, verdict = workspace
        routes = dict(BASE_ROUTES)
        routes[("POST", f"{PULL}/reviews")] = (500, {"message": "boom"})
        http = transport(routes)
        wire(monkeypatch, http)
        assert invoke(config, verdict).exit_code == 77
        submissions = [url for method, url, _, _ in http.calls if method == "POST"]
        assert submissions.count(f"https://api.github.com{PULL}/reviews") == 1

    def test_no_option_offers_to_approve_alongside_the_verdict(self) -> None:
        assert "--approve" not in help_output("post-verdict")


class TestDefaultProjectConfigPath:
    def test_the_default_config_is_the_one_in_the_current_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        key = tmp_path / "app.pem"
        key.write_text("-----BEGIN PRIVATE KEY-----\n")
        (tmp_path / "project-config.toml").write_text(CONFIG)
        verdict = tmp_path / "verdict.json"
        verdict.write_text(json.dumps(ENVELOPE))
        monkeypatch.setenv("APPROVER_KEY_PATH", str(key))
        monkeypatch.chdir(tmp_path)
        http = transport(BASE_ROUTES)
        wire(monkeypatch, http)
        result = runner.invoke(cli.app, ["post-verdict", PR_ARG, "--verdict", str(verdict)])
        assert result.exit_code == 0
        assert len(http.posted_reviews()) == 1


def test_an_uppercase_head_sha_is_lowercased_before_it_is_compared_and_pinned(
    workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # GitHub reports a head in lowercase, so a verdict written in uppercase must be
    # folded before the comparison or it reads as a head that moved.
    config, verdict = workspace
    envelope = json.loads(verdict.read_text())
    envelope["head_sha"] = HEAD.upper()
    verdict.write_text(json.dumps(envelope))
    http = transport(BASE_ROUTES)
    wire(monkeypatch, http)
    result = invoke(config, verdict)
    assert result.exit_code == 0
    (posted,) = http.posted_reviews()
    assert posted["commit_id"] == HEAD


def test_a_bad_verdict_is_reported_even_when_the_config_is_bad_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The verdict is read first, so the caller learns which of the two inputs to
    # fix rather than being sent to the config for a fault that is not there.
    config = tmp_path / "project-config.toml"
    config.write_text('[merge-policy]\nmerge-authorization = "explicit"\n')
    verdict = tmp_path / "verdict.json"
    verdict.write_text("not json at all")
    http = transport({})
    wire(monkeypatch, http)
    result = invoke(config, verdict)
    assert result.exit_code == 2
    assert ErrorCode.PRECONDITION_VERDICT_MALFORMED.value in result.output
    assert ErrorCode.PRECONDITION_APPROVER_CONFIG.value not in result.output
    assert http.calls == []


class TestTheAppKeyReachesTheCallerThroughThisVerb:
    """Each App-key failure has its own code, and each must arrive through here.

    Reaching them only through the approving verb would leave this one free to
    swallow, mislabel, or never reach any of them.
    """

    def test_an_unset_key_env_var_is_refused_before_any_api_call(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, verdict = workspace
        monkeypatch.delenv("APPROVER_KEY_PATH", raising=False)
        http = transport({})
        wire(monkeypatch, http)
        result = invoke(config, verdict)
        assert result.exit_code == 2
        assert ErrorCode.PRECONDITION_APPROVER_KEY_ENV_UNSET.value in result.output
        assert http.calls == []

    def test_a_key_that_is_not_there_is_refused_before_any_api_call(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config, verdict = workspace
        monkeypatch.setenv("APPROVER_KEY_PATH", str(tmp_path / "nowhere" / "app.pem"))
        http = transport({})
        wire(monkeypatch, http)
        result = invoke(config, verdict)
        assert result.exit_code == 2
        assert ErrorCode.PRECONDITION_APPROVER_KEY_UNREADABLE.value in result.output
        assert http.calls == []

    def test_a_failed_signature_exits_with_the_terminal_environment_code(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, verdict = workspace
        http = transport(BASE_ROUTES)
        monkeypatch.setattr(cli, "_build_http", lambda: http)
        monkeypatch.setattr(
            cli, "_build_runner", lambda: RecordedRunner([CommandResult(1, "", "bad decrypt")])
        )
        result = invoke(config, verdict)
        assert result.exit_code == 77
        assert ErrorCode.RUNTIME_APPROVER_SIGN_FAILED.value in result.output
        assert http.calls == []


def test_the_verb_builds_no_store_so_it_can_read_or_write_no_grooming_state(
    workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The lock is taken through the store, so a verb that builds none takes none
    # and reaches no grooming state at all.
    built: list[str | None] = []
    monkeypatch.setattr(cli, "_build_store", lambda name: built.append(name))
    config, verdict = workspace
    http = transport(BASE_ROUTES)
    wire(monkeypatch, http)
    assert invoke(config, verdict).exit_code == 0
    assert built == []
