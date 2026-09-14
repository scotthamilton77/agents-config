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
from prgroom.lifecycle.post_verdict import (
    MAX_BODY_CHARS,
    Verdict,
    envelope_of,
    load_criteria,
    render_body,
    render_comment,
)
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


def run_cli(*args: str) -> Any:
    """Invoke the CLI and require the failure contract every path it takes must meet.

    A coded exit is the whole of what this verb reports, so a traceback reaching
    the operator means an exception escaped its handler — and the exit status
    alone cannot tell the two apart. Asserting it here rather than in each error
    test covers the paths this module gains later as well as the ones it has.
    """
    result = runner.invoke(cli.app, list(args))
    assert "Traceback" not in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    return result


def invoke(config: Path, verdict: Path, *extra: str) -> Any:
    return run_cli(
        "post-verdict", PR_ARG, "--verdict", str(verdict), "--project-config", str(config), *extra
    )


# Rich styles option tokens and wraps to the terminal width, so an option name
# arrives split by escape codes wherever colour is on (CI is). Asking for a wide,
# colourless render keeps it a contiguous token to assert on.
PLAIN_HELP_ENV = {"NO_COLOR": "1", "FORCE_COLOR": None, "TERM": "dumb", "COLUMNS": "200"}


def help_output(*args: str) -> str:
    return runner.invoke(cli.app, [*args, "--help"], env=PLAIN_HELP_ENV).output


def test_post_verdict_is_a_registered_verb() -> None:
    assert "post-verdict" in runner.invoke(cli.app, ["--help"]).output


def test_help_lists_every_input() -> None:
    output = help_output("post-verdict")
    for token in ("PR", "--verdict", "--project-config", "--criteria"):
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
    assert envelope_of(posted["body"]) == verdict.read_text()
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
    result = run_cli("post-verdict", PR_ARG, "--project-config", str(config))
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
            pytest.param(
                '{"head_sha": "' + "z" * 40 + '", "findings": []}',
                id="a-forty-character-head-sha-that-is-not-hex",
            ),
            pytest.param(
                '{"head_sha": "' + HEAD + '\\n", "findings": []}',
                id="a-head-sha-carrying-a-trailing-newline",
            ),
            pytest.param(
                '{"head_sha": "' + HEAD + 'a", "findings": []}',
                id="a-head-sha-one-character-too-long",
            ),
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
                '{"head_sha": "' + HEAD + '", "findings": [{"id": " ", "evidence": "x.py:1"}]}',
                id="a-blank-id-on-an-otherwise-complete-finding",
            ),
            pytest.param(
                '{"head_sha": "' + HEAD + '", "findings": [], "extra": NaN}',
                id="a-javascript-numeric-constant",
            ),
            pytest.param(
                '{"head_sha": "' + HEAD + '", "findings": [], "extra": Infinity}',
                id="a-javascript-infinity",
            ),
            pytest.param(
                '{"head_sha": "' + HEAD + '", "findings": [], "extra": -Infinity}',
                id="a-javascript-negative-infinity",
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

    def test_a_file_that_fits_is_refused_when_the_summary_takes_it_past_the_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The body is what GitHub measures, and the body is larger than the file it
        # renders from. A file exactly at the ceiling therefore posts nothing, and
        # the refusal names the length that failed rather than the file's.
        envelope = json.loads(json.dumps(ENVELOPE))
        envelope["findings"][0]["claim"] = ""
        envelope["findings"][0]["claim"] = "x" * (MAX_BODY_CHARS - len(json.dumps(envelope)))
        at_the_limit = json.dumps(envelope)
        assert len(at_the_limit) == MAX_BODY_CHARS
        rendered = len(render_body(Verdict(text=at_the_limit, head_sha=HEAD, findings=())))
        assert rendered > MAX_BODY_CHARS
        result, http = self.run_with(tmp_path, monkeypatch, at_the_limit)
        assert result.exit_code == 2
        assert ErrorCode.PRECONDITION_VERDICT_TOO_LARGE.value in result.output
        assert f"renders to {rendered} characters" in " ".join(result.output.split())
        assert http.calls == []

    def test_a_body_exactly_at_the_limit_is_accepted(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The refusal is on exceeding the limit, not on reaching it: a body the API
        # would accept must not be refused locally. The padding sits in a field the
        # summary does not report, so the body grows exactly as the file does.
        config, verdict = workspace
        envelope = json.loads(verdict.read_text())
        envelope["retained_categories"] = [""]
        text = json.dumps(envelope)
        overhead = len(render_body(Verdict(text=text, head_sha=HEAD, findings=()))) - len(text)
        envelope["retained_categories"] = ["x" * (MAX_BODY_CHARS - overhead - len(text))]
        padded = json.dumps(envelope)
        assert len(render_body(Verdict(text=padded, head_sha=HEAD, findings=()))) == MAX_BODY_CHARS
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
        result = run_cli("post-verdict", PR_ARG, "--verdict", str(verdict))
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


@pytest.mark.parametrize(
    ("findings", "comments"),
    [
        pytest.param([{"id": "f1", "evidence": f"{APP_PY}:3"}], 1, id="a-finding-with-evidence"),
        pytest.param([{"id": "f1", "claim": f"{APP_PY}:3"}], 1, id="a-finding-with-only-a-claim"),
        pytest.param([{"id": "f1", "claim": "nowhere"}], 0, id="a-finding-that-anchors-nothing"),
        pytest.param([], 0, id="a-clean-verdict-with-no-findings"),
    ],
)
def test_a_verdict_holding_only_the_fields_this_verb_reads_is_accepted(
    findings: list[dict[str, str]],
    comments: int,
    workspace: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Every shape this verb accepts arrives through the loader, because that is
    # the door a real invocation comes in by. A verdict constructed in a test
    # proves nothing about what the file reader takes.
    config, verdict = workspace
    verdict.write_text(json.dumps({"head_sha": HEAD, "findings": findings}))
    http = transport(BASE_ROUTES)
    wire(monkeypatch, http)
    result = invoke(config, verdict)
    assert result.exit_code == 0
    (posted,) = http.posted_reviews()
    assert envelope_of(posted["body"]) == verdict.read_text()
    assert len(posted.get("comments", [])) == comments


def test_a_line_number_longer_than_any_file_is_not_a_line_number(
    workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Driven through the CLI because the defect this pins is a traceback reaching
    # the operator after the network calls, which a call to the resolver alone
    # would not show.
    config, verdict = workspace
    verdict.write_text(
        json.dumps(
            {"head_sha": HEAD, "findings": [{"id": "f1", "evidence": f"{APP_PY}:{'9' * 5000}"}]}
        )
    )
    http = transport(BASE_ROUTES)
    wire(monkeypatch, http)
    result = invoke(config, verdict)
    assert result.exit_code == 0
    (posted,) = http.posted_reviews()
    assert "comments" not in posted
    assert "no line in the diff for finding f1" in result.output


@pytest.mark.parametrize(
    ("patch", "kind"),
    [
        pytest.param("@@ -1 +" + "9" * 5000 + " @@\n+x\n", "start", id="an-over-long-hunk-start"),
        pytest.param("@@ -1 +1," + "9" * 5000 + " @@\n+x\n", "count", id="an-over-long-hunk-count"),
    ],
)
def test_a_hunk_header_number_longer_than_any_file_yields_no_span(
    patch: str, kind: str, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Driven through the CLI: the failure this pins is a traceback reaching the
    # operator once the diff has already been fetched.
    del kind
    config, verdict = workspace
    routes = dict(BASE_ROUTES)
    routes[("GET", f"{PULL}/files?per_page={FILES_PER_PAGE}&page=1")] = (
        200,
        [{"filename": APP_PY, "patch": patch}],
    )
    http = transport(routes)
    wire(monkeypatch, http)
    result = invoke(config, verdict)
    assert result.exit_code == 0
    assert "comments" not in http.posted_reviews()[0]


def test_a_ten_digit_pull_request_reaches_the_api(
    workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The PR number comes from the operator's own argument. Whatever GitHub will
    # issue, this verb addresses; the parser does not cap what a repository can
    # number a pull request.
    big = 1_000_000_000
    config, verdict = workspace
    pull = f"/repos/octo/demo/pulls/{big}"
    routes = {
        ("GET", "/app"): (200, {"slug": "pr-hater"}),
        ("GET", "/repos/octo/demo/installation"): (200, {"id": 42}),
        ("POST", "/app/installations/42/access_tokens"): (201, {"token": "tok"}),
        ("GET", pull): (200, {"head": {"sha": HEAD}}),
        ("GET", f"{pull}/reviews?per_page={REVIEWS_PER_PAGE}&page=1"): (200, []),
        ("GET", f"{pull}/files?per_page={FILES_PER_PAGE}&page=1"): (200, FILES),
        ("POST", f"{pull}/reviews"): (200, {"id": 99}),
    }
    http = transport(routes)
    wire(monkeypatch, http)
    result = run_cli(
        "post-verdict",
        f"octo/demo#{big}",
        "--verdict",
        str(verdict),
        "--project-config",
        str(config),
    )
    assert result.exit_code == 0
    assert len(http.posted_reviews()) == 1


CRITERIA_FILE = """\
# Acceptance criteria for the change under review

- **AC-2** The field is read behind a guard, so a malformed payload is refused rather than indexed.
"""

AC_2_SENTENCE = (
    "The field is read behind a guard, so a malformed payload is refused rather than indexed."
)
AC_2_GLOSS = "The field is read behind a guard, so a malformed payload is..."


class TestTheCriteriaTheRoundJudgedAgainst:
    """The criterion a finding names, reaching both surfaces through the verb."""

    def criteria(self, tmp_path: Path, text: str = CRITERIA_FILE) -> Path:
        path = tmp_path / "criteria.md"
        path.write_text(text)
        return path

    def test_the_option_is_offered_on_the_verb(self) -> None:
        assert "--criteria" in help_output("post-verdict")

    def test_the_criterion_reaches_the_line_comment_in_full_and_the_body_glossed(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config, verdict = workspace
        http = transport(BASE_ROUTES)
        wire(monkeypatch, http)
        result = invoke(config, verdict, "--criteria", str(self.criteria(tmp_path)))
        assert result.exit_code == 0
        (posted,) = http.posted_reviews()
        assert f"Criterion AC-2: {AC_2_SENTENCE}" in posted["comments"][0]["body"]
        assert f"AC-2: {AC_2_GLOSS}" in posted["body"]
        assert envelope_of(posted["body"]) == verdict.read_text()

    def test_without_the_option_both_surfaces_name_the_criterion_alone(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, verdict = workspace
        http = transport(BASE_ROUTES)
        wire(monkeypatch, http)
        assert invoke(config, verdict).exit_code == 0
        (posted,) = http.posted_reviews()
        assert "fails AC-2" in posted["comments"][0]["body"]
        assert AC_2_SENTENCE not in posted["body"]
        assert "AC-2" in posted["body"]

    def test_a_criteria_file_naming_something_else_leaves_the_finding_as_written(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config, verdict = workspace
        other = self.criteria(tmp_path, "- **AC-9** Something the finding does not name.\n")
        http = transport(BASE_ROUTES)
        wire(monkeypatch, http)
        assert invoke(config, verdict, "--criteria", str(other)).exit_code == 0
        (posted,) = http.posted_reviews()
        assert "fails AC-2" in posted["comments"][0]["body"]
        assert "Something the finding does not name" not in posted["body"]

    def test_a_criteria_path_that_cannot_be_read_is_refused_before_any_api_call(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config, verdict = workspace
        missing = tmp_path / "nowhere" / "criteria.md"
        http = transport({})
        wire(monkeypatch, http)
        result = invoke(config, verdict, "--criteria", str(missing))
        assert result.exit_code == 2
        output = " ".join(result.output.split())
        assert ErrorCode.PRECONDITION_CRITERIA_UNREADABLE.value in output
        assert str(missing) in output
        assert http.calls == []

    def test_the_gloss_is_measured_against_the_ceiling_like_the_rest_of_the_body(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # The ceiling is measured against the body that gets posted, and the gloss
        # is part of that body. The same verdict is posted without the option and
        # refused with it, so the measurement can only be reading the gloss. The
        # padding sits in a field the summary does not report, so the body grows
        # exactly as the file does.
        config, verdict = workspace
        criteria = load_criteria(self.criteria(tmp_path))
        envelope = json.loads(verdict.read_text())
        envelope["retained_categories"] = [""]
        text = json.dumps(envelope)
        glossed = Verdict(text=text, head_sha=HEAD, findings=(), criteria=criteria)
        overhead = len(render_body(glossed)) - len(text)
        envelope["retained_categories"] = ["x" * (MAX_BODY_CHARS + 1 - overhead - len(text))]
        padded = json.dumps(envelope)
        verdict.write_text(padded)
        assert len(render_body(Verdict(text=padded, head_sha=HEAD, findings=()))) <= MAX_BODY_CHARS

        http = transport(BASE_ROUTES)
        wire(monkeypatch, http)
        assert invoke(config, verdict).exit_code == 0

        refused = transport({})
        wire(monkeypatch, refused)
        result = invoke(config, verdict, "--criteria", str(self.criteria(tmp_path)))
        assert result.exit_code == 2
        assert ErrorCode.PRECONDITION_VERDICT_TOO_LARGE.value in result.output
        assert refused.calls == []


def envelope_whose_comment_renders_to(length: int) -> dict[str, Any]:
    """One finding whose line comment comes out at exactly ``length`` characters.

    The padding goes in the evidence, which the comment prints once as prose and
    once inside the record, so each character added costs two. Whatever is left
    over is spent on the id, which only the record carries.
    """
    finding = dict(ENVELOPE["findings"][0], evidence=f"{APP_PY}:3 x")
    finding["evidence"] += "x" * ((length - len(render_comment(finding))) // 2)
    while len(render_comment(finding)) < length:
        finding["id"] += "x"
    assert len(render_comment(finding)) == length
    return dict(ENVELOPE, findings=[finding])


class TestAnInlineCommentTooLargeToPost:
    """The ceiling applies to each comment, not only to the body above them.

    GitHub rejects the whole review when one comment in it is oversized, so a
    comment past the ceiling loses the body and every other comment with it. The
    diff decides which findings anchor and the diff costs a call, so every
    finding's comment is measured rather than only the ones that would be posted.
    """

    def write(self, workspace: tuple[Path, Path], length: int) -> tuple[Path, Path]:
        config, verdict = workspace
        verdict.write_text(json.dumps(envelope_whose_comment_renders_to(length)))
        return config, verdict

    def test_a_comment_exactly_at_the_ceiling_is_accepted(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The refusal is on exceeding the ceiling, not on reaching it: a comment
        # the API would take must not be turned away here.
        config, verdict = self.write(workspace, MAX_BODY_CHARS)
        http = transport(BASE_ROUTES)
        wire(monkeypatch, http)
        assert invoke(config, verdict).exit_code == 0
        (posted,) = http.posted_reviews()
        assert len(posted["comments"][0]["body"]) == MAX_BODY_CHARS

    def test_a_comment_one_character_past_it_is_refused_before_any_api_call(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config, verdict = self.write(workspace, MAX_BODY_CHARS + 1)
        identifier = json.loads(verdict.read_text())["findings"][0]["id"]
        http = transport({})
        wire(monkeypatch, http)
        result = invoke(config, verdict)
        assert result.exit_code == 2
        output = " ".join(result.output.split())
        assert ErrorCode.PRECONDITION_VERDICT_TOO_LARGE.value in output
        assert f"the comment for finding {identifier} renders to {MAX_BODY_CHARS + 1}" in output
        assert http.calls == []

    def test_a_body_that_fits_does_not_excuse_an_oversized_comment(
        self, workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The evidence is the whole of the padding, and the body prints it once
        # while the comment prints it twice, so this is a verdict whose body is
        # comfortably inside the ceiling and whose comment is not.
        config, verdict = self.write(workspace, MAX_BODY_CHARS + 1)
        text = verdict.read_text()
        assert len(render_body(Verdict(text=text, head_sha=HEAD, findings=()))) < MAX_BODY_CHARS
        http = transport({})
        wire(monkeypatch, http)
        assert invoke(config, verdict).exit_code == 2
        assert http.calls == []
