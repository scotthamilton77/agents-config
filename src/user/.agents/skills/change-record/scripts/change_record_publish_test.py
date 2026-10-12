#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4", "pytest>=8"]
# ///
"""Tests for the subcommand that posts a change record on its pull request and sets the body from it.

Run: uv run change_record_publish_test.py
"""

from __future__ import annotations

# The fence goes up when conftest is imported. This import comes first, so the
# fence also holds while this file runs as a script, before pytest starts.
import conftest

# isort: split

import copy
import hashlib
import json
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NamedTuple

import pytest

import change_record

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SCRIPT = HERE / "change_record.py"
REFERENCES = SKILL / "references"
EXAMPLE = json.loads((SKILL / "examples" / "pr-843.json").read_text(encoding="utf-8"))

NUMBER = EXAMPLE["pr"]["number"]
WORK_ITEM = EXAMPLE["work_item"]["id"]
LIMIT = 65536

# The pull request as GitHub serves it. Its head is not the commit the record
# says the gates ran at, so a case can tell the two apart.
PULL_URL = f"https://github.com/example/repo/pull/{NUMBER}"
HEAD = "89abcdef" * 5
assert HEAD != EXAMPLE["pr"]["head_sha"]

# The id GitHub gives the comment a run creates, which is ten digits long as a real one is.
NEW_ID = 6123456789

# Every call `publish` makes of its own, as the shim logs it.
PULL_PATH = f"repos/{{owner}}/{{repo}}/pulls/{NUMBER}"
COMMENTS_PATH = f"repos/{{owner}}/{{repo}}/issues/{NUMBER}/comments"
READ_PULL = f"gh api {PULL_PATH}"
CREATE = f"gh api {COMMENTS_PATH} --method POST -F body=@-"
EDIT = f"gh api {PULL_PATH} --method PATCH -F body=@-"

# The calls the three generators make, which `publish` repeats before it posts a first comment.
SHOW = f"work --format json show {WORK_ITEM}"
CHILDREN = f"work --format json list --parent {WORK_ITEM}"
EDGES = f"work --format json dep list {WORK_ITEM}"
OPEN_PULLS = "gh api repos/{owner}/{repo}/pulls?state=open&per_page=100&page="
REVIEWS = f"gh api {PULL_PATH}/reviews?per_page=100&page=1"
REVIEW_COMMENTS = f"gh api {PULL_PATH}/comments?per_page=100&page=1"

# The two markers another tool puts around the region of a body that it owns.
OPENING = "<!-- prgroom:decisions:start -->"
CLOSING = "<!-- prgroom:decisions:end -->"
DECISIONS = (
    f"{OPENING}\n"
    "## Decisions\n"
    "<!-- d:r1:thread-7 --> - **[r1]** Keep the pin table flat. _(decided_by: author)_\n"
    "<details><summary>Earlier rounds</summary>\n"
    "\n"
    "<!-- d:r0:thread-2 --> - **[r0]** Trailing spaces and a carriage return stay.  \r\n"
    "</details>\n"
    f"{CLOSING}"
)

# The program behind both shims. It writes the call down, with whatever the
# call was sent on its standard input, then prints the answer its table holds
# for the call. A call the table does not answer fails, and so does the call
# whose number the table says to fail. An answer that carries a body comes back
# with the body that was sent, as GitHub's does.
REPLAY = """\
import json
import sys

table_path, log_path, name, *arguments = sys.argv[1:]
with open(table_path, encoding="utf-8") as handle:
    table = json.load(handle)
call = " ".join([name, *arguments])
sent = sys.stdin.buffer.read().decode("utf-8") if "body=@-" in arguments else None
with open(log_path, "a+", encoding="utf-8") as log:
    log.seek(0)
    earlier = sum(1 for _ in log)
    log.write(json.dumps({"call": call, "sent": sent}) + "\\n")
if table["fail_on"] == earlier + 1:
    sys.exit("HTTP 502: the shim was told to fail this call")
if call not in table["answers"]:
    sys.exit(f"the shim holds no answer for `{call}`")
answer = table["answers"][call]
if sent is not None and isinstance(answer, dict) and "body" in answer:
    answer["body"] = sent
sys.stdout.write(json.dumps(answer))
"""


def put_shims(shims: Path, state: Path, answers: dict[str, Any], fail_on: int | None = None) -> Path:
    """Put a ``gh`` and a ``work`` on the search path that replay ``answers``, and return the log they share."""
    state.mkdir()
    (state / "replay.py").write_text(REPLAY, encoding="utf-8")
    (state / "answers.json").write_text(json.dumps({"answers": answers, "fail_on": fail_on}), encoding="utf-8")
    log = state / "calls.log"
    for name in ("gh", "work"):
        words = [str(state / "replay.py"), str(state / "answers.json"), str(log), name]
        shim = shims / name
        shim.write_text(f'#!/bin/sh\nexec python3 {" ".join(map(shlex.quote, words))} "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
    return log


def logged(log: Path) -> list[dict[str, Any]]:
    """Return each call in ``log`` in order, as its command line and what it was sent."""
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def is_read(call: str) -> bool:
    """Say whether a call only reads.

    A ``gh api`` call reads when it names no method and sends no field,
    because it then makes a GET request. A ``work`` call reads when it shows
    or lists.
    """
    tool, *words = call.split()
    if tool == "work":
        return words[:2] == ["--format", "json"] and (words[2] in ("show", "list") or words[2:4] == ["dep", "list"])
    writing = ("-X", "--method", "-f", "-F", "--field", "--raw-field", "--input")
    return words[:1] == ["api"] and not any(word.startswith(writing) for word in words[1:])


def writes(calls: list[dict[str, Any]]) -> list[str]:
    """Return the command line of each logged call that is not a read."""
    return [entry["call"] for entry in calls if not is_read(entry["call"])]


# Every sequence of writes one run of `publish` may make: none, either of the two alone, or the comment then the body.
ALLOWED_WRITES = ([], [CREATE], [EDIT], [CREATE, EDIT])


def comment(comment_id: int, body: str) -> dict[str, Any]:
    """Return a comment on the pull request as GitHub lists one."""
    return {
        "id": comment_id,
        "body": body,
        "html_url": f"{PULL_URL}#issuecomment-{comment_id}",
        "user": {"login": "the-author", "type": "User"},
    }


def digest_of(record: dict[str, Any]) -> str:
    """Return the record's digest, worked out apart from the script under test."""
    content = {name: group for name, group in record.items() if name != "record"}
    written = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(written.encode("utf-8")).hexdigest()


def marker(revision: int, digest: str, number: int = NUMBER) -> str:
    return f"<!-- change-record v1 pr={number} rev={revision} sha256={digest} -->"


def record_comment(comment_id: int, revision: int, digest: str, number: int = NUMBER) -> dict[str, Any]:
    """Return a record comment an earlier run left, with a fold this suite never opens."""
    fold = f"<details><summary>Change record, revision {revision}</summary>\n\n```json\n{{}}\n```\n\n</details>\n"
    return comment(comment_id, f"{marker(revision, digest, number)}\n{fold}")


# The whole of a record comment: the marker line, then the record as one line of JSON in a fold.
COMMENT_FORM = re.compile(
    r"(?P<marker><!-- [^\n]* -->)\n"
    r"<details><summary>Change record, revision (?P<revision>\d+)</summary>\n\n"
    r"```json\n(?P<json>[^\n]*)\n```\n\n</details>\n"
)


def held_in(text: str) -> dict[str, Any]:
    """Return the record a record comment holds, read apart from the script under test."""
    form = COMMENT_FORM.fullmatch(text)
    assert form, text[:200]
    return json.loads(form["json"])


def answers_for(
    body: str | None = "", pages: list[list[dict[str, Any]]] | None = None, head: str = HEAD
) -> dict[str, Any]:
    """Return what the tracker and GitHub answer about the example's work item and its pull request.

    The work item has no parent and no child, nothing was discovered from it,
    its pull request is the only open one, and no review round has run.
    ``pages`` are the pages of the pull request's comments, and an empty page
    follows the last of them.
    """
    pull = {
        "number": NUMBER, "html_url": PULL_URL, "body": body, "head": {"sha": head},
        "user": {"login": "the-author", "type": "User"},
    }
    item = {
        "id": WORK_ITEM, "title": "Pin effort and tools per reviewer slot", "type": "feature",
        "status": "in_progress", "parent": None, "notes": None, "description": "",
    }
    answers = {
        READ_PULL: pull,
        EDIT: pull,
        CREATE: comment(NEW_ID, ""),
        SHOW: {"data": {"items": [item]}},
        CHILDREN: {"data": {"items": []}},
        EDGES: {"data": {"depends_on": [], "dependents": []}},
        OPEN_PULLS + "1": [{"number": NUMBER, "title": EXAMPLE["pr"]["title"]}],
        OPEN_PULLS + "2": [],
        REVIEWS: [],
        REVIEW_COMMENTS: [],
    }
    for number, page in enumerate([*(pages or []), []], start=1):
        answers[f"gh api {COMMENTS_PATH}?per_page=100&page={number}"] = page
    return answers


COMMENTS_1 = f"gh api {COMMENTS_PATH}?per_page=100&page=1"
COMMENTS_2 = f"gh api {COMMENTS_PATH}?per_page=100&page=2"


def lint_clean(record: dict[str, Any]) -> bool:
    return change_record.lint_record(record) == []


class Prepared(NamedTuple):
    record: dict[str, Any]
    reads: list[str]


@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Prepared]:
    """Return the example record as the three generators leave it over the shims' answers, and the reads they made.

    The generators themselves write the parts, so the record is current by
    their own account whatever they come to write.
    """
    root = tmp_path_factory.mktemp("prepared")
    path = root / "record.json"
    path.write_text(json.dumps(EXAMPLE), encoding="utf-8")
    log = put_shims(conftest.SHIMS, root / "state", answers_for())
    for generator in ("context", "discovered", "campaign"):
        assert change_record.main([generator, str(path)]) == 0
    for shim in conftest.SHIMS.iterdir():
        shim.unlink()
    record = json.loads(path.read_text(encoding="utf-8"))
    assert lint_clean(record)
    yield Prepared(record, [entry["call"] for entry in logged(log)])


@pytest.fixture
def current(prepared: Prepared) -> dict[str, Any]:
    """Return a record that passes lint and that every generator would leave as it is."""
    return copy.deepcopy(prepared.record)


class Ran(NamedTuple):
    code: int
    out: str
    err: str
    calls: list[dict[str, Any]]

    @property
    def writes(self) -> list[str]:
        return writes(self.calls)

    @property
    def errors(self) -> list[dict[str, str]]:
        """Return the findings of the JSON result that closes stderr."""
        result = json.loads(self.err.strip().splitlines()[-1])
        assert result["valid"] is False
        return result["errors"]

    def sent(self, call: str) -> str:
        """Return what the one logged call with this command line was sent."""
        (entry,) = [entry for entry in self.calls if entry["call"] == call]
        return entry["sent"]


class Hub:
    """A pull request and its tracker item behind ``gh`` and ``work`` shims, and the record ``publish`` runs over."""

    def __init__(self, shim_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        self.shim_dir = shim_dir
        self.tmp_path = tmp_path
        self.capsys = capsys
        self.path = tmp_path / "record.json"
        self.log = tmp_path / "no-shim.log"
        self.served = 0

    def serve(
        self, body: str | None = "", pages: list[list[dict[str, Any]]] | None = None, *, head: str = HEAD,
        fail_on: int | None = None, spoiled: dict[str, Callable[[Any], Any]] | None = None,
    ) -> None:
        """Serve the pull request with this body, these pages of comments and this head, on a log of its own.

        The shims exit 1 on call number ``fail_on``. ``spoiled`` names a call
        and gives what changes that call's answer.
        """
        answers = answers_for(body, pages, head)
        for call, change in (spoiled or {}).items():
            answers[call] = change(answers[call])
        self.served += 1
        self.log = put_shims(self.shim_dir, self.tmp_path / f"served-{self.served}", answers, fail_on)

    def write(self, record: dict[str, Any]) -> bytes:
        """Write ``record`` in the layout the script writes, and return the file's bytes."""
        self.path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return self.path.read_bytes()

    def record(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def run(self, *argv: str) -> Ran:
        """Run ``publish`` over the record, and check the writes the shims logged for this run.

        Every case runs the command through here, so no case passes with a
        write in its log other than one comment created and one body set.
        """
        before = len(logged(self.log))
        code = change_record.main(["publish", *argv, str(self.path)])
        out, err = self.capsys.readouterr()
        ran = Ran(code, out, err, logged(self.log)[before:])
        assert ran.writes in ALLOWED_WRITES, ran.writes
        return ran

    def child(self, *argv: str) -> subprocess.CompletedProcess[bytes]:
        """Run ``publish`` over the record in a child process, and return what it wrote, as bytes."""
        return subprocess.run(
            [sys.executable, str(SCRIPT), "publish", *argv, str(self.path)], capture_output=True, check=False
        )

    def published(self, record: dict[str, Any], body: str | None = "") -> Ran:
        """Publish ``record`` on the pull request with this body and no record comment, and return the run."""
        self.serve(body)
        self.write(record)
        ran = self.run()
        assert (ran.code, ran.writes) == (0, [CREATE, EDIT]), ran.err
        return ran

    def left_by(self, ran: Ran) -> dict[str, Any]:
        """Return what GitHub holds once ``ran`` has posted its comment and set its body."""
        return {"body": ran.sent(EDIT), "pages": [[comment(NEW_ID, ran.sent(CREATE))]]}


@pytest.fixture
def hub(shim_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Hub:
    return Hub(shim_dir, tmp_path, capsys)


@pytest.fixture(autouse=True)
def cr_p7_every_write_of_the_case_is_the_comment_or_the_body(tmp_path: Path) -> Iterator[None]:
    """Check, as each case ends, that every write in every log is one comment created or one body set."""
    yield
    for log in sorted(tmp_path.glob("served-*/calls.log")):
        for entry in logged(log):
            assert is_read(entry["call"]) or entry["call"] in (CREATE, EDIT), entry["call"]
            assert (entry["sent"] is None) == is_read(entry["call"])


def posting(record: dict[str, Any], revision: int, head: str = HEAD) -> dict[str, Any]:
    """Return ``record`` as a run posts it at ``revision``: with its revision, its digest and the head, and no comment id."""
    kept = {name: value for name, value in record["record"].items() if name != "comment_id"}
    return {**record, "record": {**kept, "revision": revision, "digest": digest_of(record), "head_sha": head}}


def new_url(comment_id: int = NEW_ID) -> str:
    return f"{PULL_URL}#issuecomment-{comment_id}"


class TestCrP11Digest:
    def test_cr_p11_the_digest_is_the_sha256_of_the_sorted_json_without_the_record_group(self):
        assert change_record.record_digest(EXAMPLE) == digest_of(EXAMPLE)
        assert re.fullmatch(r"[0-9a-f]{64}", change_record.record_digest(EXAMPLE))

    def test_cr_p11_reordering_keys_leaves_the_digest_unchanged(self):
        def reversed_keys(node: Any) -> Any:
            if isinstance(node, dict):
                return {name: reversed_keys(node[name]) for name in reversed(list(node))}
            return [reversed_keys(entry) for entry in node] if isinstance(node, list) else node

        turned = reversed_keys(EXAMPLE)
        assert list(turned) != list(EXAMPLE) and turned == EXAMPLE
        assert change_record.record_digest(turned) == change_record.record_digest(EXAMPLE)

    def test_cr_p11_changing_the_record_group_leaves_the_digest_unchanged(self):
        published = copy.deepcopy(EXAMPLE)
        published["record"] = {
            "schema_version": 1, "revision": 4, "digest": "c" * 64, "comment_id": NEW_ID, "head_sha": HEAD,
        }
        assert published["record"] != EXAMPLE["record"]
        assert change_record.record_digest(published) == change_record.record_digest(EXAMPLE)

    @pytest.mark.parametrize("group", [name for name in EXAMPLE if name != "record"])
    def test_cr_p11_changing_any_other_group_changes_the_digest(self, group: str):
        def nudged(node: Any) -> Any:
            """Return ``node`` with the first text or number in it changed by one character."""
            if isinstance(node, dict):
                first = next(iter(node))
                return {**node, first: nudged(node[first])}
            if isinstance(node, list):
                return [nudged(node[0]), *node[1:]]
            return node + 1 if isinstance(node, int) else f"{node}."

        changed = {**EXAMPLE, group: nudged(EXAMPLE[group])}
        assert changed != EXAMPLE
        assert change_record.record_digest(changed) != change_record.record_digest(EXAMPLE)

    def test_cr_p11_one_changed_character_changes_the_digest(self):
        changed = copy.deepcopy(EXAMPLE)
        changed["campaign"]["findings"][-1]["claim"] += " "
        assert change_record.record_digest(changed) != change_record.record_digest(EXAMPLE)


# A hand edit of each generated part that `lint` accepts once the part is stamped again.
HAND_EDITS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "where_this_fits": lambda record: record["where_this_fits"]["scope"][0].update(covers="Everything the item asks for"),
    "discovered": lambda record: record["discovered"]["rows"].insert(
        0, {"status": "filed", "item": "proj-a1b.9", "what": "A gate for the pins", "reason": "It is its own change."}
    ),
    "campaign": lambda record: record["campaign"].update(terminal_sha=HEAD),
}


class TestCrP1FirstPublish:
    def test_cr_p1_a_record_that_fails_lint_is_refused_with_the_lint_output_and_an_empty_call_log(
        self, hub: Hub, current: dict[str, Any]
    ):
        current["summary"] = "One sentence is too few."
        hub.serve()
        before = hub.write(current)
        ran = hub.run()
        assert ran.code == 1
        assert ran.errors == change_record.lint_record(current)
        assert [error["code"] for error in ran.errors] == ["summary-length"]
        assert ran.calls == [] and ran.out == ""
        assert hub.path.read_bytes() == before

    @pytest.mark.parametrize("group", sorted(HAND_EDITS))
    def test_cr_p1_a_generated_group_edited_by_hand_under_a_recomputed_stamp_is_refused_naming_the_group(
        self, group: str, hub: Hub, current: dict[str, Any]
    ):
        HAND_EDITS[group](current)
        change_record.stamp_generated(current)
        assert lint_clean(current)
        hub.serve()
        before = hub.write(current)
        ran = hub.run()
        assert ran.code == 1
        assert [(error["code"], error["path"]) for error in ran.errors] == [("stale-part", f"/{group}")]
        assert change_record.GENERATED_PARTS[group] in ran.errors[0]["message"]
        assert ran.writes == [] and ran.out == ""
        assert hub.path.read_bytes() == before

    def test_cr_p1_a_first_publish_creates_revision_1_then_sets_the_body_then_writes_the_record(
        self, hub: Hub, current: dict[str, Any], prepared: Prepared
    ):
        hub.serve("An earlier body.\n")
        hub.write(current)
        ran = hub.run()
        assert ran.code == 0, ran.err
        # The run reads the pull request and its comments, then what the three generators read, then writes twice.
        assert [entry["call"] for entry in ran.calls] == [READ_PULL, COMMENTS_1, *prepared.reads, CREATE, EDIT]
        posted = ran.sent(CREATE)
        assert posted.split("\n")[0] == marker(1, digest_of(current))
        assert held_in(posted) == posting(current, 1)
        assert "comment_id" not in held_in(posted)["record"]
        body = ran.sent(EDIT)
        assert body == change_record.render_body(posting(current, 1), "", new_url())
        assert f"\nRendered from change record {new_url()}, revision 1.\n" in body
        assert "An earlier body." not in body
        assert hub.record() == {**current, "record": {**posting(current, 1)["record"], "comment_id": NEW_ID}}
        assert ran.out == f"published revision 1 at {new_url()} (new comment, new body)\n"

    def test_the_record_comment_is_the_marker_line_then_the_record_in_a_fold(self, hub: Hub, current: dict[str, Any]):
        posted = hub.published(current).sent(CREATE)
        form = COMMENT_FORM.fullmatch(posted)
        assert form and form["marker"] == marker(1, digest_of(current)) and form["revision"] == "1"
        # The record is one line of JSON, so a reader that takes the last fenced `json` block gets all of it.
        assert json.loads(change_record.fenced_json(posted)) == posting(current, 1)
        assert digest_of(held_in(posted)) == re.search(r"sha256=([0-9a-f]{64})", form["marker"])[1]

    def test_publish_writes_the_live_head_into_the_record_and_leaves_the_gates_commit_alone(
        self, hub: Hub, current: dict[str, Any]
    ):
        ran = hub.published(current)
        assert hub.record()["record"]["head_sha"] == HEAD
        assert held_in(ran.sent(CREATE))["record"]["head_sha"] == HEAD
        assert hub.record()["pr"]["head_sha"] == EXAMPLE["pr"]["head_sha"] != HEAD

    def test_the_body_carries_the_decisions_block_of_the_body_it_replaces_byte_for_byte(
        self, hub: Hub, current: dict[str, Any]
    ):
        body = hub.published(current, f"A body someone wrote.\n\n{DECISIONS}\n").sent(EDIT)
        assert f"\n{DECISIONS}\n\nRendered from change record {new_url()}, revision 1.\n" in body
        assert "A body someone wrote." not in body

    def test_a_body_with_a_broken_decisions_block_is_refused_before_any_write(self, hub: Hub, current: dict[str, Any]):
        hub.serve(f"{OPENING}\n## Decisions\n")
        before = hub.write(current)
        ran = hub.run()
        assert ran.code == 1 and [error["code"] for error in ran.errors] == ["decisions-block"]
        assert ran.writes == [] and hub.path.read_bytes() == before

    def test_a_commit_message_that_render_refuses_is_refused_before_any_write(self, hub: Hub, current: dict[str, Any]):
        # A table passes `lint`, and the render of the commit message refuses it.
        kept = current["commit"]["change"].rsplit(". ", 1)[0]
        current["commit"]["change"] = f"{kept}.\n\n| Slot | Effort |\n| --- | --- |\n| mid | low |"
        assert lint_clean(current)
        hub.serve()
        before = hub.write(current)
        ran = hub.run()
        assert ran.code == 1 and [error["code"] for error in ran.errors] == ["commit-markup"]
        assert ran.writes == [] and hub.path.read_bytes() == before

    def test_a_pull_request_with_no_body_takes_the_render(self, hub: Hub, current: dict[str, Any]):
        ran = hub.published(current, None)
        assert ran.sent(EDIT) == change_record.render_body(posting(current, 1), "", new_url())

    def test_a_record_that_names_no_pull_request_is_refused_before_any_call(self, hub: Hub, current: dict[str, Any]):
        current["pr"]["number"] = None
        hub.serve()
        before = hub.write(current)
        ran = hub.run()
        assert ran.code == 2 and [error["code"] for error in ran.errors] == ["no-pull-request"]
        assert ran.calls == [] and hub.path.read_bytes() == before

    def test_a_record_that_cannot_be_read_exits_2_before_any_call(self, hub: Hub):
        hub.serve()
        hub.path.write_text("{", encoding="utf-8")
        ran = hub.run()
        assert ran.code == 2 and [error["code"] for error in ran.errors] == ["invalid-json"]
        assert ran.calls == []


class TestCrP2NextRevision:
    def test_cr_p2_a_second_publish_creates_the_next_revision_and_touches_no_earlier_comment(
        self, hub: Hub, current: dict[str, Any]
    ):
        earlier = record_comment(6000000000, 1, "a" * 64)
        # The file is as the first publish left it, and it names that publish's comment.
        current["record"].update(revision=1, digest="a" * 64, comment_id=6000000000, head_sha="1" * 40)
        hub.serve("The body of revision 1.\n", [[earlier]])
        hub.write(current)
        ran = hub.run()
        assert ran.code == 0, ran.err
        # A record comment is there, so no generator runs, and the two writes are the only calls after the reads.
        assert [entry["call"] for entry in ran.calls] == [READ_PULL, COMMENTS_1, COMMENTS_2, CREATE, EDIT]
        assert ran.sent(CREATE).split("\n")[0] == marker(2, digest_of(current))
        assert held_in(ran.sent(CREATE)) == posting(current, 2)
        assert "comment_id" not in held_in(ran.sent(CREATE))["record"]
        assert ran.sent(EDIT) == change_record.render_body(posting(current, 2), "", new_url())
        assert f"Rendered from change record {new_url()}, revision 2." in ran.sent(EDIT)
        assert hub.record()["record"] == {**posting(current, 2)["record"], "comment_id": NEW_ID}

    def test_cr_p2_a_stale_generated_part_is_not_looked_for_once_a_record_comment_is_there(
        self, hub: Hub, current: dict[str, Any]
    ):
        HAND_EDITS["campaign"](current)
        change_record.stamp_generated(current)
        hub.serve("", [[record_comment(6000000000, 1, "a" * 64)]])
        hub.write(current)
        ran = hub.run()
        assert (ran.code, ran.writes) == (0, [CREATE, EDIT]), ran.err


class TestCrP3Rerun:
    def test_cr_p3_a_record_whose_digest_is_the_newest_comment_s_writes_nothing(self, hub: Hub, current: dict[str, Any]):
        first = hub.published(current)
        # The file is laid out as no run of the script lays one out, so a run that wrote it would change its bytes.
        hub.path.write_text(json.dumps(hub.record()), encoding="utf-8")
        after_first = hub.path.read_bytes()
        hub.serve(**hub.left_by(first))
        ran = hub.run()
        assert ran.code == 0, ran.err
        assert [entry["call"] for entry in ran.calls] == [READ_PULL, COMMENTS_1, COMMENTS_2]
        assert hub.path.read_bytes() == after_first
        assert ran.out == f"published revision 1 at {new_url()} (comment already posted, body already current)\n"

    def test_cr_p3_a_body_that_still_names_the_previous_revision_is_set_and_no_comment_is_posted(
        self, hub: Hub, current: dict[str, Any]
    ):
        previous = record_comment(6000000000, 1, "a" * 64)
        newest = record_comment(6000000007, 2, digest_of(current))
        stale = change_record.render_body(posting(current, 1), "", previous["html_url"])
        hub.serve(stale, [[previous, newest]])
        hub.write(current)
        ran = hub.run()
        assert (ran.code, ran.writes) == (0, [EDIT]), ran.err
        assert ran.sent(EDIT) == change_record.render_body(posting(current, 2), "", newest["html_url"])
        assert f"Rendered from change record {newest['html_url']}, revision 2." in ran.sent(EDIT)
        assert hub.record()["record"] == {**posting(current, 2)["record"], "comment_id": 6000000007}
        assert ran.out == f"published revision 2 at {newest['html_url']} (comment already posted, new body)\n"

    def test_cr_p3_a_publish_that_stopped_between_its_two_writes_is_finished_by_a_rerun(
        self, hub: Hub, current: dict[str, Any], prepared: Prepared
    ):
        # The body edit is the last call of a first publish, and the shim fails it.
        hub.serve(fail_on=len(prepared.reads) + 4)
        before = hub.write(current)
        stopped = hub.run()
        assert stopped.code == 2 and stopped.writes == [CREATE, EDIT]
        assert f"`{EDIT}`" in stopped.errors[0]["message"]
        assert hub.path.read_bytes() == before
        hub.serve("", [[comment(NEW_ID, stopped.sent(CREATE))]])
        ran = hub.run()
        assert (ran.code, ran.writes) == (0, [EDIT]), ran.err
        assert ran.sent(EDIT) == stopped.sent(EDIT)
        assert hub.record()["record"] == {**posting(current, 1)["record"], "comment_id": NEW_ID}

    def test_a_record_file_that_fell_behind_its_comment_is_written_and_nothing_else_is(
        self, hub: Hub, current: dict[str, Any]
    ):
        first = hub.published(current)
        hub.write(current)
        hub.serve(**hub.left_by(first))
        ran = hub.run()
        assert (ran.code, ran.writes) == (0, []), ran.err
        assert hub.record()["record"] == {**posting(current, 1)["record"], "comment_id": NEW_ID}


class TestCrP5Newest:
    def test_cr_p5_a_verdict_comment_and_an_author_reply_posted_later_do_not_change_the_newest(
        self, hub: Hub, current: dict[str, Any]
    ):
        newest = record_comment(6000000002, 2, digest_of(current))
        verdict = comment(6000000003, "## Review verdict\n\n```json\n{\"verdict\": \"clean\"}\n```\n")
        # The reply quotes a marker below its first line, which makes it no record comment.
        reply = comment(6000000004, f"Published again.\n\n{marker(99, 'b' * 64)}\n")
        hub.serve("", [[record_comment(6000000001, 1, "a" * 64), newest, verdict, reply]])
        hub.write(current)
        ran = hub.run()
        assert (ran.code, ran.writes) == (0, [EDIT]), ran.err
        assert hub.record()["record"]["comment_id"] == 6000000002
        assert hub.record()["record"]["revision"] == 2

    def test_cr_p5_the_newest_is_the_highest_revision_wherever_github_lists_it(self, hub: Hub, current: dict[str, Any]):
        newest = record_comment(6000000001, 3, digest_of(current))
        hub.serve("", [[newest, record_comment(6000000002, 2, "a" * 64), comment(6000000003, "Thanks.")]])
        hub.write(current)
        ran = hub.run()
        assert (ran.code, ran.writes) == (0, [EDIT]), ran.err
        assert hub.record()["record"]["comment_id"] == 6000000001

    def test_cr_p5_revision_10_is_newer_than_revision_9(self, hub: Hub, current: dict[str, Any]):
        hub.serve("", [[record_comment(6000000001, 10, "a" * 64), record_comment(6000000002, 9, "b" * 64)]])
        hub.write(current)
        ran = hub.run()
        assert (ran.code, ran.writes) == (0, [CREATE, EDIT]), ran.err
        assert ran.sent(CREATE).split("\n")[0] == marker(11, digest_of(current))

    def test_cr_p5_the_newest_record_comment_is_found_alone_on_the_third_page(self, hub: Hub, current: dict[str, Any]):
        newest = record_comment(6000000009, 2, digest_of(current))
        pages = [
            [record_comment(6000000001, 1, "a" * 64), comment(6000000002, "A first reply.")],
            [comment(6000000003, "A second reply."), comment(6000000004, "A third reply.")],
            [newest],
        ]
        hub.serve("", pages)
        hub.write(current)
        ran = hub.run()
        assert (ran.code, ran.writes) == (0, [EDIT]), ran.err
        assert [entry["call"] for entry in ran.calls[1:5]] == [
            f"gh api {COMMENTS_PATH}?per_page=100&page={number}" for number in (1, 2, 3, 4)
        ]
        assert hub.record()["record"]["comment_id"] == 6000000009

    @pytest.mark.parametrize("listed_first", [True, False], ids=["higher-id-first", "higher-id-last"])
    def test_cr_p10_of_two_record_comments_at_one_revision_the_higher_id_is_the_newest(
        self, listed_first: bool, hub: Hub, current: dict[str, Any]
    ):
        winner = record_comment(6000000008, 2, digest_of(current))
        both = [winner, record_comment(6000000005, 2, "a" * 64)]
        hub.serve("", [both if listed_first else both[::-1]])
        hub.write(current)
        ran = hub.run()
        assert (ran.code, ran.writes) == (0, [EDIT]), ran.err
        assert hub.record()["record"]["comment_id"] == 6000000008
        assert f"Rendered from change record {winner['html_url']}, revision 2." in ran.sent(EDIT)

    def test_a_marker_that_names_another_pull_request_is_no_record_comment_of_this_one(
        self, hub: Hub, current: dict[str, Any]
    ):
        hub.serve("", [[record_comment(6000000001, 5, digest_of(current), number=NUMBER + 1)]])
        hub.write(current)
        ran = hub.run()
        assert (ran.code, ran.writes) == (0, [CREATE, EDIT]), ran.err
        assert ran.sent(CREATE).split("\n")[0] == marker(1, digest_of(current))

    @pytest.mark.parametrize(
        "first_line",
        [
            pytest.param(" " + marker(5, "a" * 64), id="indented"),
            pytest.param(marker(5, "a" * 64) + " trailing words", id="words-after"),
            pytest.param("> " + marker(5, "a" * 64), id="quoted"),
            pytest.param(marker(5, "a" * 63), id="short-digest"),
        ],
    )
    def test_a_first_line_that_is_not_the_marker_alone_makes_no_record_comment(
        self, first_line: str, hub: Hub, current: dict[str, Any]
    ):
        hub.serve("", [[comment(6000000001, f"{first_line}\nSome words.\n")]])
        hub.write(current)
        ran = hub.run()
        assert (ran.code, ran.writes) == (0, [CREATE, EDIT]), ran.err
        assert ran.sent(CREATE).split("\n")[0] == marker(1, digest_of(current))

    def test_a_marker_line_that_ends_in_a_carriage_return_is_read_as_the_marker(self, hub: Hub, current: dict[str, Any]):
        # GitHub ends the lines of a comment typed into its web page with a carriage return and a line feed.
        typed = comment(6000000001, f"{marker(4, digest_of(current))}\r\nThe record.\r\n")
        hub.serve("", [[typed]])
        hub.write(current)
        ran = hub.run()
        assert (ran.code, ran.writes) == (0, [EDIT]), ran.err
        assert hub.record()["record"]["revision"] == 4


def padded_reply(length: int) -> dict[str, Any]:
    """Return a reply entry that `lint` accepts and that holds one word ``length`` characters long.

    A reply reaches the record comment and not the body, so the word makes the
    comment longer and leaves the body as it was.
    """
    return {
        "finding_id": "padding.r1.f1", "claim_id": "a-claim", "artifact_class": "typed-code", "outcome": "Fixed",
        "change": "The gate now refuses a pin it cannot read, where it used to take the pin as absent.",
        "verification": (
            "The suite holds a case for a pin with a stray character, and that case fails without the change "
            "and passes with it, as do the cases around it that were there before. " + "x" * length
        ),
    }


def padded_body(length: int) -> str:
    """Return a body whose decisions block holds a line ``length`` characters long."""
    return f"{OPENING}\n## Decisions\n{'x' * length}\n{CLOSING}\n"


class TestCrP6Size:
    def test_cr_p6_an_oversize_record_is_refused_before_any_write_naming_the_size(
        self, hub: Hub, current: dict[str, Any]
    ):
        current["design_notes"] += " " + "word " * 14000
        assert lint_clean(current)
        hub.serve()
        before = hub.write(current)
        ran = hub.run()
        assert ran.code == 1 and ran.writes == [] and ran.out == ""
        assert [error["code"] for error in ran.errors] == ["too-long", "too-long"]
        comment_long = len(change_record.record_comment(posting(current, 1)))
        body_long = len(change_record.render_body(posting(current, 1), "", new_url()))
        assert comment_long > LIMIT and body_long > LIMIT
        assert f"the record comment is {comment_long} characters long" in ran.errors[0]["message"]
        assert f"the pull request body is {body_long} characters long" in ran.errors[1]["message"]
        assert all(str(LIMIT) in error["message"] for error in ran.errors)
        assert hub.path.read_bytes() == before

    def test_cr_p6_a_small_record_is_refused_when_only_the_decisions_block_takes_the_body_over_the_limit(
        self, hub: Hub, current: dict[str, Any]
    ):
        room = LIMIT - len(hub.published(current, padded_body(0)).sent(EDIT))
        hub.serve(padded_body(room + 1))
        before = hub.write(current)
        ran = hub.run()
        assert ran.code == 1 and ran.writes == []
        assert [error["code"] for error in ran.errors] == ["too-long"]
        assert f"the pull request body is {LIMIT + 1} characters long" in ran.errors[0]["message"]
        assert hub.path.read_bytes() == before

    def test_cr_p6_a_body_of_exactly_the_limit_is_accepted(self, hub: Hub, current: dict[str, Any]):
        room = LIMIT - len(hub.published(current, padded_body(0)).sent(EDIT))
        ran = hub.published(current, padded_body(room))
        assert len(ran.sent(EDIT)) == LIMIT
        assert f"x\n{CLOSING}\n\nRendered from change record {new_url()}, revision 1.\n" in ran.sent(EDIT)

    def test_cr_p6_a_record_comment_of_exactly_the_limit_is_accepted(self, hub: Hub, current: dict[str, Any]):
        current["replies"] = [padded_reply(0)]
        room = LIMIT - len(hub.published(current).sent(CREATE))
        current["replies"] = [padded_reply(room)]
        assert lint_clean(current)
        ran = hub.published(current)
        assert len(ran.sent(CREATE)) == LIMIT
        assert len(ran.sent(EDIT)) < LIMIT

    def test_cr_p6_a_record_comment_one_character_over_the_limit_is_refused_though_the_body_fits(
        self, hub: Hub, current: dict[str, Any]
    ):
        current["replies"] = [padded_reply(0)]
        room = LIMIT - len(hub.published(current).sent(CREATE))
        current["replies"] = [padded_reply(room + 1)]
        assert lint_clean(current)
        hub.serve()
        before = hub.write(current)
        ran = hub.run()
        assert ran.code == 1 and ran.writes == []
        assert [error["code"] for error in ran.errors] == ["too-long"]
        assert f"the record comment is {LIMIT + 1} characters long" in ran.errors[0]["message"]
        assert hub.path.read_bytes() == before

    def test_cr_p6_the_body_is_measured_against_a_comment_that_is_already_posted_with_its_own_url(
        self, hub: Hub, current: dict[str, Any]
    ):
        # The posted comment's id is one digit longer than the id a new comment's URL is measured with.
        newest = record_comment(60000000070, 2, digest_of(current))
        room = LIMIT - len(change_record.render_body(posting(current, 2), padded_body(0), newest["html_url"]))
        hub.serve(padded_body(room), [[newest]])
        hub.write(current)
        fits = hub.run()
        assert (fits.code, fits.writes) == (0, [EDIT]) and len(fits.sent(EDIT)) == LIMIT
        hub.serve(padded_body(room + 1), [[newest]])
        over = hub.run()
        assert over.code == 1 and over.writes == []
        assert f"the pull request body is {LIMIT + 1} characters long" in over.errors[0]["message"]


class TestCrP7OnlyTwoWrites:
    def test_cr_p7_a_publish_writes_one_comment_and_one_body_and_nothing_else(self, hub: Hub, current: dict[str, Any]):
        ran = hub.published(current)
        assert ran.writes == [CREATE, EDIT]
        assert [entry["call"] for entry in ran.calls if entry["sent"] is not None] == [CREATE, EDIT]
        assert all(is_read(entry["call"]) for entry in ran.calls[:-2])

    @pytest.mark.parametrize(
        "call",
        [
            pytest.param(f"gh api repos/{{owner}}/{{repo}}/issues/comments/{NEW_ID} --method PATCH -F body=@-", id="edit"),
            pytest.param(f"gh api repos/{{owner}}/{{repo}}/issues/comments/{NEW_ID} -X DELETE", id="delete"),
            pytest.param(f"gh api {PULL_PATH}/reviews --method POST -F body=@-", id="review"),
            pytest.param(f"gh api {PULL_PATH}/comments -f body=words", id="review-comment"),
            pytest.param(f"gh pr comment {NUMBER} --body words", id="pr-comment"),
            pytest.param(f"gh pr merge {NUMBER} --squash", id="merge"),
            pytest.param("work note an-item words", id="tracker-note"),
        ],
    )
    def test_cr_p7_the_check_each_case_runs_counts_any_other_call_as_a_write(self, call: str):
        assert not is_read(call) and call not in (CREATE, EDIT)
        assert writes([{"call": call, "sent": None}]) == [call]
        assert writes([{"call": call, "sent": None}]) not in ALLOWED_WRITES

    def test_cr_p7_two_comments_or_two_bodies_in_one_run_are_not_allowed(self):
        assert [CREATE, CREATE] not in ALLOWED_WRITES and [EDIT, EDIT] not in ALLOWED_WRITES
        assert [EDIT, CREATE] not in ALLOWED_WRITES


class TestCrP12DryRun:
    def test_cr_p12_a_dry_run_prints_the_comment_a_publish_posted_then_the_body_it_set(
        self, hub: Hub, current: dict[str, Any]
    ):
        ran = hub.published(current, f"Someone's words.\n\n{DECISIONS}\n")
        after = hub.path.read_bytes()
        hub.serve(**hub.left_by(ran))
        dry = hub.child("--dry-run")
        assert dry.returncode == 0, dry.stderr
        assert dry.stdout == (ran.sent(CREATE) + ran.sent(EDIT)).encode("utf-8")
        assert dry.stdout.startswith(marker(1, digest_of(current)).encode("utf-8") + b"\n")
        assert all(is_read(entry["call"]) for entry in logged(hub.log)) and len(logged(hub.log)) == 3
        assert hub.path.read_bytes() == after
        assert dry.stderr == b"dry run of revision 1 (comment already posted, body already current)\n"

    def test_cr_p12_a_dry_run_before_the_publish_prints_what_it_posts_with_zeros_for_the_new_comment_s_id(
        self, hub: Hub, current: dict[str, Any], prepared: Prepared
    ):
        existing = f"Someone's words.\n\n{DECISIONS}\n"
        hub.serve(existing)
        before = hub.write(current)
        dry = hub.run("--dry-run")
        assert dry.code == 0, dry.err
        assert [entry["call"] for entry in dry.calls] == [READ_PULL, COMMENTS_1, *prepared.reads]
        assert hub.path.read_bytes() == before
        assert dry.err == "dry run of revision 1 (new comment, new body)\n"
        ran = hub.published(current, existing)
        # The comment's URL is GitHub's to give, so only the id in it differs from what the run then sets.
        stand_in = f"{PULL_URL}#issuecomment-0000000000"
        assert new_url() in ran.sent(EDIT) and len(stand_in) == len(new_url())
        assert dry.out == ran.sent(CREATE) + ran.sent(EDIT).replace(new_url(), stand_in)

    def test_cr_p12_a_dry_run_over_a_stale_body_prints_the_body_a_publish_then_sets_and_writes_nothing(
        self, hub: Hub, current: dict[str, Any]
    ):
        newest = record_comment(6000000007, 2, digest_of(current))
        hub.serve("A stale body.\n", [[newest]])
        before = hub.write(current)
        dry = hub.run("--dry-run")
        assert (dry.code, dry.writes) == (0, []), dry.err
        assert hub.path.read_bytes() == before
        assert dry.err == "dry run of revision 2 (comment already posted, new body)\n"
        ran = hub.run()
        assert ran.writes == [EDIT]
        assert dry.out == newest["body"] + ran.sent(EDIT)

    def test_cr_p12_a_dry_run_refuses_what_a_publish_refuses_and_prints_nothing(self, hub: Hub, current: dict[str, Any]):
        HAND_EDITS["where_this_fits"](current)
        change_record.stamp_generated(current)
        hub.serve()
        hub.write(current)
        dry = hub.run("--dry-run")
        assert dry.code == 1 and dry.out == "" and dry.writes == []
        assert [error["code"] for error in dry.errors] == ["stale-part"]


def without(entry: dict[str, Any], name: str) -> dict[str, Any]:
    return {key: value for key, value in entry.items() if key != name}


# Each read `publish` makes of its own, with an answer of the wrong shape for it.
MISSHAPEN = [
    pytest.param(READ_PULL, lambda pull: [pull], id="pull-a-list"),
    pytest.param(READ_PULL, lambda pull: without(pull, "head"), id="pull-no-head"),
    pytest.param(READ_PULL, lambda pull: {**pull, "head": {"sha": HEAD[:12]}}, id="pull-short-head"),
    pytest.param(READ_PULL, lambda pull: {**pull, "head": {"sha": None}}, id="pull-null-head"),
    pytest.param(READ_PULL, lambda pull: {**pull, "body": 7}, id="pull-body-a-number"),
    pytest.param(READ_PULL, lambda pull: without(pull, "html_url"), id="pull-no-url"),
    pytest.param(COMMENTS_1, lambda page: {"message": "Not Found"}, id="comments-an-object"),
    pytest.param(COMMENTS_1, lambda page: [without(page[0], "id")], id="comment-no-id"),
    pytest.param(COMMENTS_1, lambda page: [{**page[0], "id": "6000000000"}], id="comment-id-a-text"),
    pytest.param(COMMENTS_1, lambda page: [{**page[0], "body": None}], id="comment-null-body"),
    pytest.param(COMMENTS_1, lambda page: [without(page[0], "html_url")], id="comment-no-url"),
    pytest.param(COMMENTS_2, lambda page: "[]", id="second-page-a-text"),
    # The generators shape their own reads, and `publish` stops on each of those as well.
    pytest.param(SHOW, lambda answer: {"data": {"items": []}}, id="tracker-no-item"),
    pytest.param(CHILDREN, lambda answer: {"data": {}}, id="tracker-no-children"),
    pytest.param(EDGES, lambda answer: {"data": {"dependents": [{"id": WORK_ITEM}]}}, id="tracker-edge-no-type"),
    pytest.param(OPEN_PULLS + "1", lambda page: {"message": "Not Found"}, id="open-pulls-an-object"),
    pytest.param(OPEN_PULLS + "2", lambda page: None, id="open-pulls-second-page-null"),
    # The pull request is read twice, and the second read is for its author.
    pytest.param(READ_PULL, lambda pull: without(pull, "user"), id="pull-no-author"),
    pytest.param(REVIEWS, lambda page: [{"id": 1}], id="review-no-state"),
    pytest.param(REVIEW_COMMENTS, lambda page: [{"id": 1}], id="review-comment-no-body"),
]


class TestFailedCalls:
    """A call that fails, or whose answer has the wrong shape, exits 2 naming the call and stops the run there."""

    def test_each_read_of_a_first_publish_that_fails_stops_the_run_with_nothing_written(
        self, hub: Hub, current: dict[str, Any], prepared: Prepared
    ):
        reads = [READ_PULL, COMMENTS_1, COMMENTS_2, *prepared.reads]
        for number, call in enumerate(reads, start=1):
            hub.serve("", [[comment(6000000000, "A reply.")]], fail_on=number)
            before = hub.write(current)
            ran = hub.run()
            assert ran.code == 2, call
            assert [entry["call"] for entry in ran.calls] == reads[:number]
            assert f"`{call}` exited 1" in ran.errors[0]["message"]
            assert ran.writes == [] and ran.out == ""
            assert hub.path.read_bytes() == before

    def test_each_read_of_a_later_publish_that_fails_stops_the_run_with_nothing_written(
        self, hub: Hub, current: dict[str, Any]
    ):
        reads = [READ_PULL, COMMENTS_1, COMMENTS_2]
        for number, call in enumerate(reads, start=1):
            hub.serve("", [[record_comment(6000000000, 1, "a" * 64)]], fail_on=number)
            before = hub.write(current)
            ran = hub.run()
            assert ran.code == 2 and f"`{call}` exited 1" in ran.errors[0]["message"]
            assert ran.writes == [] and hub.path.read_bytes() == before

    @pytest.mark.parametrize(("call", "spoil"), MISSHAPEN)
    def test_a_read_whose_answer_has_the_wrong_shape_stops_the_run_with_nothing_written(
        self, call: str, spoil: Callable[[Any], Any], hub: Hub, current: dict[str, Any]
    ):
        hub.serve("", [[comment(6000000000, "A reply.")]], spoiled={call: spoil})
        before = hub.write(current)
        ran = hub.run()
        assert ran.code == 2, ran.err
        assert f"`{call}`" in ran.errors[0]["message"]
        assert "Traceback" not in ran.err
        assert ran.writes == [] and ran.out == ""
        assert hub.path.read_bytes() == before

    @pytest.mark.parametrize(
        "broken",
        [
            pytest.param({"fail_on": 4}, id="fails"),
            pytest.param({"spoiled": {CREATE: lambda created: without(created, "id")}}, id="no-id"),
            pytest.param({"spoiled": {CREATE: lambda created: without(created, "html_url")}}, id="no-url"),
            pytest.param({"spoiled": {CREATE: lambda created: [created]}}, id="a-list"),
        ],
    )
    def test_a_comment_create_that_fails_or_answers_wrongly_leaves_the_body_and_the_record_alone(
        self, broken: dict[str, Any], hub: Hub, current: dict[str, Any]
    ):
        # A record comment is there, so the create is the fourth call, after the pull request and two pages.
        hub.serve("", [[record_comment(6000000000, 1, "a" * 64)]], **broken)
        before = hub.write(current)
        ran = hub.run()
        assert ran.code == 2 and ran.writes == [CREATE]
        assert f"`{CREATE}`" in ran.errors[0]["message"]
        assert hub.path.read_bytes() == before

    def test_a_body_edit_that_fails_leaves_the_record_alone(self, hub: Hub, current: dict[str, Any]):
        hub.serve("", [[record_comment(6000000000, 1, digest_of(current))]], fail_on=4)
        before = hub.write(current)
        ran = hub.run()
        assert ran.code == 2 and ran.writes == [EDIT]
        assert f"`{EDIT}` exited 1" in ran.errors[0]["message"]
        assert hub.path.read_bytes() == before

    def test_a_generator_that_reads_more_than_its_answer_s_shape_promises_fails_the_run_and_not_the_process(
        self, hub: Hub, current: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ):
        def fill(record: dict[str, Any]) -> None:
            record["an answer"]["lacks this"] = 1

        monkeypatch.setitem(change_record.GENERATORS, "campaign", ("campaign", fill))
        hub.serve()
        before = hub.write(current)
        ran = hub.run()
        assert ran.code == 2 and [error["code"] for error in ran.errors] == ["answer-shape"]
        assert ran.writes == [] and hub.path.read_bytes() == before


class TestCommandLine:
    def test_the_help_names_the_dry_run_and_the_exit_statuses(self, capsys: pytest.CaptureFixture[str]):
        with pytest.raises(SystemExit) as stopped:
            change_record.main(["publish", "--help"])
        said = " ".join(capsys.readouterr().out.split())
        assert stopped.value.code == 0
        assert "--dry-run" in said and "write nothing" in said
        assert "Exit 0 published, 1 refused, 2 unreadable or unparseable, or a call failed." in said

    @pytest.mark.parametrize("argv", [("publish",), ("publish", "--create", "record.json"), ("merge", "843")])
    def test_a_call_the_parser_cannot_read_exits_2(self, argv: tuple[str, ...], capsys: pytest.CaptureFixture[str]):
        with pytest.raises(SystemExit) as stopped:
            change_record.main(list(argv))
        capsys.readouterr()
        assert stopped.value.code == 2

    def test_the_usage_at_the_top_of_the_script_gives_the_command_line(self):
        assert "uv run change_record.py publish [--dry-run] <record.json>" in change_record.__doc__


# Marks of the repository this skill was written in, which text shipped to other projects cannot carry.
HOUSE_MARKS = re.compile(r"agents-config|9k9|\bCR-[A-Z]+\d|[Ss]ection \d|docs/specs")

# What only a later change adds: a subcommand that merges, a flag that opens a pull request,
# and a check of the body and the record comment under `lint --pr`.
NOT_YET = re.compile(r"`merge`|change_record\.py merge|--create|gh pr merge|gh pr create")


def shipped_text() -> dict[str, str]:
    """Return every text the skill ships that an agent reads, by its path under the skill."""
    paths = [SKILL / "SKILL.md", SCRIPT, *sorted(REFERENCES.glob("*.md"))]
    return {str(path.relative_to(SKILL)): path.read_text(encoding="utf-8") for path in paths}


class TestPublishInTheSkillText:
    def section(self) -> str:
        text = (REFERENCES / "commands.md").read_text(encoding="utf-8")
        return text[text.index("## `publish`") :].split("\n## ")[0]

    def test_the_skill_body_has_one_entry_for_publish_and_its_command_line(self):
        body = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        assert "change_record.py publish [--dry-run] record.json" in body
        assert len([line for line in body.splitlines() if line.startswith("- `publish` ")]) == 1

    def test_the_commands_reference_describes_publish_its_dry_run_and_its_exit_statuses(self):
        section = self.section()
        assert "scripts/change_record.py publish [--dry-run] record.json" in section
        said = ("`--dry-run`", "working directory", "`stale-part`", "`too-long`", "65,536", "`pr.number`")
        assert [words for words in said if words not in section] == []
        assert "Exit 0 published, 1 refused, 2 unreadable or unparseable, or a call failed." in section

    def test_the_commands_reference_gives_the_record_comment_s_form_and_how_the_newest_is_found(self):
        section = self.section()
        assert "### The record comment" in section
        assert "`<!-- change-record v1 pr=NUMBER rev=REVISION sha256=DIGEST -->`" in section
        assert "Rendered from change record URL, revision REVISION." in section
        for words in ("first line", "highest revision", "higher id", "every page", "`record` group"):
            assert words in section, words

    def test_the_commands_reference_lists_the_calls_publish_makes_in_order(self):
        section = self.section()
        calls = [
            'gh api "repos/{owner}/{repo}/pulls/NUMBER"',
            'gh api "repos/{owner}/{repo}/issues/NUMBER/comments?per_page=100&page=N"',
            'gh api "repos/{owner}/{repo}/issues/NUMBER/comments" --method POST -F body=@-',
            'gh api "repos/{owner}/{repo}/pulls/NUMBER" --method PATCH -F body=@-',
        ]
        places = [section.index(call) for call in calls]
        assert places == sorted(places)
        # The calls the reference gives are the calls the script makes.
        for call in (READ_PULL, COMMENTS_1, CREATE, EDIT):
            written = re.sub(r"(repos/\S+)", r'"\1"', call).replace(str(NUMBER), "NUMBER").replace("&page=1", "&page=N")
            assert written in calls, written

    def test_the_lint_reference_lists_the_two_codes_publish_refuses_under(self):
        table = (REFERENCES / "lint-rules.md").read_text(encoding="utf-8")
        assert "| `stale-part` | Under `publish` only: " in table
        assert "| `too-long` | Under `publish` only: " in table

    def test_no_shipped_text_describes_what_a_later_change_adds(self):
        for name, text in shipped_text().items():
            assert NOT_YET.findall(text) == [], name

    def test_the_text_about_publish_carries_no_mark_of_this_repository(self):
        for name in ("SKILL.md", "references/commands.md", "scripts/change_record.py"):
            text = shipped_text()[name]
            assert "publish" in text and HOUSE_MARKS.findall(text) == [], name
        rows = (REFERENCES / "lint-rules.md").read_text(encoding="utf-8").splitlines()
        added = [row for row in rows if row.startswith(("| `stale-part` ", "| `too-long` "))]
        assert len(added) == 2 and HOUSE_MARKS.findall("\n".join(added)) == []

    def test_lint_is_not_said_to_check_the_body_or_the_record_comment(self):
        text = (REFERENCES / "commands.md").read_text(encoding="utf-8")
        lint = text[text.index("## `lint`") :].split("\n## ")[0]
        assert "record comment" not in lint and "pointer" not in lint and "the body" not in lint


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
