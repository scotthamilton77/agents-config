#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4", "pytest>=8"]
# ///
"""Tests for the two generators that fill a change record from the tracker and from GitHub.

A shim answers every call a generator makes to ``work`` or ``gh``. The shim
replays a table of answers, and each answer has the shape of one recorded
from a live repository.

Run: uv run change_record_context_test.py
"""

from __future__ import annotations

# The fence goes up when conftest is imported. This import comes first, so the
# fence also holds while this file runs as a script, before pytest starts.
import conftest  # noqa: F401

# isort: split

import copy
import json
import random
import re
import shlex
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import change_record

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SCRIPT = HERE / "change_record.py"
EXAMPLE = json.loads((SKILL / "examples" / "pr-843.json").read_text(encoding="utf-8"))

# Answers that `work` and `gh` gave in a live repository, keyed by the arguments of each call.
RECORDED = json.loads((SKILL / "evals" / "context" / "recorded.json").read_text(encoding="utf-8"))

OPEN_PULLS = "api repos/{owner}/{repo}/pulls?state=open&per_page=100&page="

# One recorded answer of each kind. A scenario's answers are copies of these
# with a few fields changed, so every answer a shim gives has a recorded shape.
SHOWN = RECORDED["work"]["--format json show agents-config-9k9.484.2.3"]["stdout"]
LISTED = RECORDED["work"]["--format json list --parent agents-config-9k9.484.2"]["stdout"]["data"]["items"][0]
EDGES = RECORDED["work"]["--format json dep list agents-config-9k9.484.2.1"]["stdout"]["data"]
UNKNOWN = RECORDED["work"]["--format json show agents-config-zzz.999"]
PULL = RECORDED["gh"][OPEN_PULLS + "1"]["stdout"][0]
FILE = RECORDED["gh"]["api repos/{owner}/{repo}/pulls/860/files?per_page=100&page=1"]["stdout"][0]
assert "previous_filename" not in FILE
VIEWED = RECORDED["gh"]["pr view 859 --json number,state,title"]["stdout"]

# The program behind each shim. It writes the call down, then gives the answer
# its table holds for the call's arguments. A call the table does not answer
# fails, and so does the call whose number the table says to fail.
REPLAY = """\
import json
import sys

table_path, log_path, name, *arguments = sys.argv[1:]
with open(table_path, encoding="utf-8") as handle:
    table = json.load(handle)
with open(log_path, "a+", encoding="utf-8") as log:
    log.seek(0)
    earlier = sum(1 for line in log if json.loads(line)[0] == name)
    log.write(json.dumps([name, *arguments]) + "\\n")
call = " ".join(arguments)
if table["fail_on_call"] == earlier + 1:
    sys.exit(f"{name}: the shim was told to fail this call")
answer = table["answers"].get(call)
if answer is None:
    sys.exit(f"{name}: the shim holds no answer for `{call}`")
out = answer.get("stdout", "")
sys.stdout.write(out if isinstance(out, str) else json.dumps(out))
sys.stderr.write(answer.get("stderr", ""))
sys.exit(answer.get("exit", 0))
"""


def shim(shim_dir: Path, tmp_path: Path, name: str, answers: dict[str, Any], fail_on_call: int | None = None) -> None:
    """Put an executable called ``name`` on the search path that replays ``answers`` and logs each call."""
    replay = tmp_path / "replay.py"
    replay.write_text(REPLAY, encoding="utf-8")
    table = tmp_path / f"{name}.answers.json"
    table.write_text(json.dumps({"answers": answers, "fail_on_call": fail_on_call}), encoding="utf-8")
    words = [str(replay), str(table), str(tmp_path / "calls.log"), name]
    path = shim_dir / name
    path.write_text(f'#!/bin/sh\nexec python3 {" ".join(shlex.quote(word) for word in words)} "$@"\n', encoding="utf-8")
    path.chmod(0o755)


def calls(tmp_path: Path, name: str) -> list[str]:
    """Return the arguments of each call the shim called ``name`` answered, in order."""
    log = tmp_path / "calls.log"
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return [" ".join(call[1:]) for call in map(json.loads, lines) if call[0] == name]


def is_read(call: str) -> bool:
    """Say whether a call to ``gh`` only reads.

    Viewing a pull request reads. So does an API call that names no method
    and sends no field, because ``gh api`` then makes a GET request.
    """
    words = call.split()
    writing = ("-X", "--method", "-f", "-F", "--field", "--raw-field", "--input")
    if words[:2] == ["pr", "view"]:
        return True
    return words[:1] == ["api"] and not any(word.startswith(writing) for word in words[1:])


@pytest.fixture(autouse=True)
def cr_c8_every_gh_call_of_the_case_is_a_read(tmp_path: Path) -> Iterator[None]:
    """Check, as each case ends, that the ``gh`` shim's call log holds reads only."""
    yield
    for call in calls(tmp_path, "gh"):
        assert is_read(call), f"`gh {call}` is not a read"


def item(
    item_id: str, title: str, parent: str | None, kind: str = "feature", status: str = "open",
    notes: str = "", description: str = "",
) -> dict[str, Any]:
    """Return a tracker item with the fields a recorded item carries."""
    changed = {
        "id": item_id, "title": title, "parent": parent, "type": kind, "status": status,
        "notes": notes, "description": description,
    }
    return SHOWN["data"]["items"][0] | changed


def answered(data: Any) -> dict[str, Any]:
    """Return ``data`` inside the envelope ``work`` wraps every answer in."""
    return {"stdout": SHOWN | {"data": data}}


def tracker(*items: dict[str, Any], discovered: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """Return the answers ``work`` gives about ``items``.

    Each item is answered for ``show``, for ``list --parent`` and for
    ``dep list``. A listed child carries only the fields a recorded listing
    carries, and the listing comes newest first, as the recorded one does.
    ``discovered`` maps an item to the items found while working on it, in
    the order one ``show`` call asks for them.
    """
    by_id = {entry["id"]: entry for entry in items}
    answers = {}
    for entry in items:
        children = [child for child in reversed(items) if child["parent"] == entry["id"]]
        shown = entry | {"children": [child["id"] for child in children]}
        unknown = {"unknown_relations": LISTED["unknown_relations"]}
        listed = [{name: child[name] for name in LISTED} | unknown for child in children]
        found = (discovered or {}).get(entry["id"], [])
        edges = [{"id": other, "type": "discovered-from", "status": by_id[other]["status"]} for other in found]
        blocked = [edge for edge in EDGES["dependents"] if edge["type"] == "blocks"]
        answers[f"--format json show {entry['id']}"] = answered({"items": [shown]})
        answers[f"--format json list --parent {entry['id']}"] = answered({"items": listed})
        answers[f"--format json dep list {entry['id']}"] = answered({"depends_on": [], "dependents": edges + blocked})
        if found:
            answers[f"--format json show {' '.join(found)}"] = answered({"items": [by_id[other] for other in found]})
    return answers


def pull(number: int, title: str) -> dict[str, Any]:
    """Return an open pull request with the fields a recorded one carries."""
    return PULL | {"number": number, "title": title}


def files_of(number: int, page: int) -> str:
    """Return the arguments of the call that asks for one page of a pull request's files."""
    return f"api repos/{{owner}}/{{repo}}/pulls/{number}/files?per_page=100&page={page}"


def github(
    pages: list[list[dict[str, Any]]] | None = None, views: list[dict[str, Any]] | None = None,
    files: dict[int, list[str]] | None = None,
) -> dict[str, Any]:
    """Return the answers ``gh`` gives.

    ``pages`` are the pages of open pull requests, and an empty page follows
    the last of them. ``views`` are pull requests looked up by number.
    ``files`` maps a pull request to the paths it touches, which come as one
    page of files with an empty page after it.
    """
    answers = {}
    for number, page in enumerate([*(pages or []), []], start=1):
        answers[f"{OPEN_PULLS}{number}"] = {"stdout": page}
    for viewed in views or []:
        answers[f"pr view {viewed['number']} --json number,state,title"] = {"stdout": viewed}
    for number, paths in (files or {}).items():
        answers[files_of(number, 1)] = {"stdout": [FILE | {"filename": path} for path in paths]}
        answers[files_of(number, 2)] = {"stdout": []}
    return answers


def viewed(number: int, title: str, state: str = "MERGED") -> dict[str, Any]:
    """Return what ``gh pr view`` prints for a pull request in ``state``."""
    assert set(VIEWED) == {"number", "state", "title"}
    return {"number": number, "state": state, "title": title}


def written(tmp_path: Path, record: dict[str, Any]) -> Path:
    """Write ``record`` to a file as ``init`` lays one out, and return the file."""
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def run(generator: str, path: Path) -> subprocess.CompletedProcess[str]:
    """Run the subcommand ``generator`` over the record at ``path`` in a child process."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), generator, str(path)], capture_output=True, text=True, check=False
    )


def filled(generator: str, path: Path) -> dict[str, Any]:
    """Run ``generator`` over the record at ``path``, and return the record it left."""
    proc = run(generator, path)
    assert proc.returncode == 0, proc.stderr
    assert sorted(path.parent.glob("record.json*")) == [path]
    return json.loads(path.read_text(encoding="utf-8"))


def lint(path: Path) -> dict[str, Any]:
    """Run the lint over the record at ``path`` and return its result."""
    proc = subprocess.run([sys.executable, str(SCRIPT), "lint", str(path)], capture_output=True, text=True, check=False)
    return json.loads(proc.stdout)


def example(**pr: Any) -> dict[str, Any]:
    """Return the example record with no generated part, and with ``pr`` set over its pull request's fields."""
    record = copy.deepcopy(EXAMPLE)
    del record["where_this_fits"]
    record["pr"].update(pr)
    return record


# The example record's work item, in a tree three items deep. The work item's
# id says its parent is the milestone, and its parent field names the epic.
WORK_ITEM = EXAMPLE["work_item"]["id"]
NUMBER = EXAMPLE["pr"]["number"]
MILESTONE = item("agents-config-9k9", "Harness rework", None, kind="milestone")
EPIC = item("agents-config-9k9.77", "Every review seat is pinned as data", MILESTONE["id"], kind="epic")
THIS = item(WORK_ITEM, "Pin effort and tools per reviewer slot", EPIC["id"], status="in_progress")


class TestCrX1Ancestry:
    def test_cr_x1_the_ancestry_follows_the_parent_field_where_a_dotted_id_disagrees_with_it(
        self, shim_dir: Path, tmp_path: Path
    ):
        assert WORK_ITEM.rsplit(".", 1)[0] == MILESTONE["id"] != THIS["parent"]
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, THIS))
        shim(shim_dir, tmp_path, "gh", github())
        record = filled("context", written(tmp_path, example()))
        assert record["where_this_fits"]["ancestry"] == [
            {"id": "agents-config-9k9", "title": "Harness rework", "type": "milestone"},
            {"id": "agents-config-9k9.77", "title": "Every review seat is pinned as data", "type": "epic"},
            {"id": "agents-config-9k9.408", "title": "Pin effort and tools per reviewer slot", "type": "feature"},
        ]
        assert calls(tmp_path, "work")[:3] == [
            "--format json show agents-config-9k9.408",
            "--format json show agents-config-9k9.77",
            "--format json show agents-config-9k9",
        ]

    def test_cr_x1_an_entry_carries_the_trackers_type_for_its_item(self, shim_dir: Path, tmp_path: Path):
        chore = THIS | {"type": "chore"}
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, chore))
        shim(shim_dir, tmp_path, "gh", github())
        record = filled("context", written(tmp_path, example()))
        assert [entry["type"] for entry in record["where_this_fits"]["ancestry"]] == ["milestone", "epic", "chore"]


# The epic's other children, one in each state the scope table tells apart.
# The first is closed, and its delivery names the pull request that carried it.
DONE = item(
    "agents-config-9k9.401", "One routing table names the model behind each tier", EPIC["id"], status="closed",
    notes="Claimed for the routing work.\n[work] delivered: 803",
)
IN_FLIGHT = item(
    "agents-config-9k9.409", "A clean report shows its reviewer opened the change", EPIC["id"], status="in_progress"
)
WAITING = item("agents-config-9k9.410", "The criteria attack panel takes the same pins", EPIC["id"])
FAMILY = (MILESTONE, EPIC, DONE, THIS, IN_FLIGHT, WAITING)

# An open pull request whose title closes with the short id of the item in flight.
OTHER = pull(850, "feat(review-panel): a clean report shows its reviewer opened the change [9k9.409]")
ROUTING = viewed(803, "feat(routing): one table names the model behind each provider and tier [9k9.401]")

# Paths the record's own pull request changes, and paths that share none with them.
OWN_PATHS = ["src/panel/gate.py", "src/panel/contracts.json"]
APART = ["packages/tool/cli.py", "docs/guides/panel.md"]


def scope_of(record: dict[str, Any]) -> list[dict[str, Any]]:
    return record["where_this_fits"]["scope"]


class TestCrX2Scope:
    def test_cr_x2_the_scope_table_gives_each_child_its_title_and_one_of_the_four_statuses(
        self, shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", tracker(*FAMILY))
        shim(shim_dir, tmp_path, "gh", github([[OTHER]], [ROUTING], {NUMBER: OWN_PATHS, 850: APART}))
        record = filled("context", written(tmp_path, example()))
        assert scope_of(record) == [
            {"slice": "agents-config-9k9.401", "covers": DONE["title"], "status": "done"},
            {"slice": "agents-config-9k9.408", "covers": THIS["title"], "status": "this PR"},
            {"slice": "agents-config-9k9.409", "covers": IN_FLIGHT["title"], "status": "in flight", "pr": 850},
            {"slice": "agents-config-9k9.410", "covers": WAITING["title"], "status": "open"},
        ]
        assert "--format json list --parent agents-config-9k9.77" in calls(tmp_path, "work")

    @pytest.mark.parametrize(
        ("title", "status"),
        [
            ("feat(review-panel): a clean report needs evidence [9k9.409]", "in flight"),
            ("feat(review-panel): a clean report needs evidence [agents-config-9k9.409]", "in flight"),
            ("feat(review-panel): a clean report needs evidence [9k9.409]  ", "in flight"),
            ("feat(9k9.409): a clean report needs evidence", "open"),
            ("feat(review-panel): [9k9.409] a clean report needs evidence", "open"),
            ("feat(review-panel): a clean report needs evidence [9k9.4091]", "open"),
            ("feat(review-panel): a clean report needs evidence", "open"),
        ],
    )
    def test_cr_x2_an_open_pull_request_names_an_item_by_the_bracketed_id_that_closes_its_title(
        self, title: str, status: str, shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", tracker(*FAMILY))
        shim(shim_dir, tmp_path, "gh", github([[pull(850, title)]], [ROUTING], {NUMBER: OWN_PATHS, 850: APART}))
        record = filled("context", written(tmp_path, example()))
        row = scope_of(record)[2]
        carrier = 850 if status == "in flight" else None
        assert (row["slice"], row["status"], row.get("pr")) == (IN_FLIGHT["id"], status, carrier)

    def test_cr_x2_a_closed_child_is_done_though_an_open_pull_request_names_it(self, shim_dir: Path, tmp_path: Path):
        late = pull(851, "fix(routing): the table drops a retired model [9k9.401]")
        shim(shim_dir, tmp_path, "work", tracker(*FAMILY))
        shim(shim_dir, tmp_path, "gh", github([[late]], [ROUTING], {NUMBER: OWN_PATHS, 851: APART}))
        record = filled("context", written(tmp_path, example()))
        assert scope_of(record)[0] == {"slice": DONE["id"], "covers": DONE["title"], "status": "done"}

    def test_cr_x2_the_records_work_item_is_this_pr_whatever_its_status_and_whatever_names_it(
        self, shim_dir: Path, tmp_path: Path
    ):
        closed = THIS | {"status": "closed", "notes": f"[work] delivered: {NUMBER}"}
        again = pull(852, "fix(review-panel): a pin survives a retried run [9k9.408]")
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, closed, WAITING))
        shim(shim_dir, tmp_path, "gh", github([[again]], [], {NUMBER: OWN_PATHS, 852: APART}))
        record = filled("context", written(tmp_path, example()))
        assert scope_of(record)[0] == {"slice": WORK_ITEM, "covers": THIS["title"], "status": "this PR"}
        # Its own delivery is not something it builds on.
        assert record["where_this_fits"]["builds_on"] == []

    @pytest.mark.parametrize("status", ["open", "in_progress", "deferred", "blocked"])
    def test_cr_x2_a_child_that_is_not_closed_and_that_no_open_pull_request_names_is_open(
        self, status: str, shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, THIS, WAITING | {"status": status}))
        shim(shim_dir, tmp_path, "gh", github())
        record = filled("context", written(tmp_path, example()))
        assert scope_of(record)[1] == {"slice": WAITING["id"], "covers": WAITING["title"], "status": "open"}

    def test_cr_x2_the_rows_come_in_the_order_a_reader_counts_ids(self, shim_dir: Path, tmp_path: Path):
        ninth = item("agents-config-9k9.77.9", "The ninth part", EPIC["id"])
        tenth = item("agents-config-9k9.77.10", "The tenth part", EPIC["id"])
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, tenth, THIS, ninth))
        shim(shim_dir, tmp_path, "gh", github())
        record = filled("context", written(tmp_path, example()))
        assert [row["slice"] for row in scope_of(record)] == [ninth["id"], tenth["id"], WORK_ITEM]

    def test_cr_x2_the_lowest_numbered_of_two_open_pull_requests_that_name_one_item_is_the_one_shown(
        self, shim_dir: Path, tmp_path: Path
    ):
        later = pull(853, "test(review-panel): the read-evidence gate has a negative control [9k9.409]")
        shim(shim_dir, tmp_path, "work", tracker(*FAMILY))
        shim(shim_dir, tmp_path, "gh", github([[later, OTHER]], [ROUTING], {NUMBER: OWN_PATHS, 850: APART, 853: APART}))
        record = filled("context", written(tmp_path, example()))
        assert scope_of(record)[2]["pr"] == 850


def delivered(suffix: str, evidence: str, status: str = "closed") -> dict[str, Any]:
    """Return a child of the epic whose notes record its delivery with ``evidence``."""
    notes = f"Claimed for the pin work.\n[work] delivered: {evidence}\nReviewed in one round."
    return item(f"agents-config-9k9.{suffix}", f"Part {suffix} of the pin work", EPIC["id"], status=status, notes=notes)


class TestCrX3BuildsOn:
    def test_cr_x3_builds_on_lists_the_merged_pull_requests_of_closed_children_and_leaves_out_one_closed_unmerged(
        self, shim_dir: Path, tmp_path: Path
    ):
        children = (delivered("402", "812"), delivered("401", "803"), delivered("403", "820"))
        views = [
            viewed(803, "feat(routing): one table names the model behind each tier [9k9.401]"),
            viewed(812, "feat(review-panel): every seat reads its pin from the table [9k9.402]"),
            viewed(820, "feat(review-panel): a seat may override its pin [9k9.403]", state="CLOSED"),
        ]
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, *children, THIS))
        shim(shim_dir, tmp_path, "gh", github([], views))
        record = filled("context", written(tmp_path, example()))
        assert record["where_this_fits"]["builds_on"] == [
            {"pr": 803, "gloss": "feat(routing): one table names the model behind each tier [9k9.401]"},
            {"pr": 812, "gloss": "feat(review-panel): every seat reads its pin from the table [9k9.402]"},
        ]
        assert calls(tmp_path, "gh")[1:] == [
            f"pr view {number} --json number,state,title" for number in (803, 812, 820)
        ]

    @pytest.mark.parametrize(
        "evidence",
        ["803", "#803", "PR #803", "https://github.com/example/repo/pull/803", "example/repo#803"],
    )
    def test_cr_x3_a_delivery_names_its_pull_request_by_number_or_by_url(
        self, evidence: str, shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, delivered("401", evidence), THIS))
        shim(shim_dir, tmp_path, "gh", github([], [ROUTING]))
        record = filled("context", written(tmp_path, example()))
        assert record["where_this_fits"]["builds_on"] == [{"pr": 803, "gloss": ROUTING["title"]}]

    @pytest.mark.parametrize("evidence", ["trivial", "items:agents-config-9k9.12,agents-config-9k9.13"])
    def test_cr_x3_a_delivery_with_no_pull_request_adds_nothing(self, evidence: str, shim_dir: Path, tmp_path: Path):
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, delivered("401", evidence), THIS))
        shim(shim_dir, tmp_path, "gh", github())
        record = filled("context", written(tmp_path, example()))
        assert record["where_this_fits"]["builds_on"] == []

    def test_cr_x3_a_pull_request_recorded_on_a_child_that_is_not_closed_is_not_looked_up(
        self, shim_dir: Path, tmp_path: Path
    ):
        # An item delivered by several pull requests stays open until the last, and its notes may name the earlier ones.
        ongoing = delivered("404", "830", status="in_progress")
        mentioned = item(
            "agents-config-9k9.405", "The pins are documented", EPIC["id"], status="closed",
            notes="Superseded by PR #831, see https://github.com/example/repo/pull/832.",
        )
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, ongoing, mentioned, THIS))
        shim(shim_dir, tmp_path, "gh", github())
        record = filled("context", written(tmp_path, example()))
        assert record["where_this_fits"]["builds_on"] == []
        assert calls(tmp_path, "gh") == [OPEN_PULLS + "1"]

    def test_cr_x3_one_pull_request_that_delivered_two_children_is_listed_once(self, shim_dir: Path, tmp_path: Path):
        twice = (delivered("401", "803"), delivered("402", "#803"))
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, *twice, THIS))
        shim(shim_dir, tmp_path, "gh", github([], [ROUTING]))
        record = filled("context", written(tmp_path, example()))
        assert record["where_this_fits"]["builds_on"] == [{"pr": 803, "gloss": ROUTING["title"]}]


    def test_cr_x3_a_sibling_that_this_same_pull_request_delivered_is_not_something_it_builds_on(
        self, shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, delivered("401", str(NUMBER)), THIS))
        shim(shim_dir, tmp_path, "gh", github())
        record = filled("context", written(tmp_path, example()))
        assert record["where_this_fits"]["builds_on"] == []


# Two open pull requests beside the record's own. The first changes a path the record's own changes.
SHARING = pull(850, "fix(review-panel): the gate reads a pin it cannot parse as absent [9k9.418]")
ELSEWHERE = pull(851, "docs(tool): the guide names the new flag [9k9.420]")
SHARED = ["src/panel/gate.py", "src/panel/gate_test.py"]

# The row `context` adds to the heads-up list when it could not check the other open pull requests.
NOT_CHECKED = "context: " + change_record.NO_NUMBER


def concurrent_of(record: dict[str, Any]) -> list[dict[str, Any]]:
    return record["where_this_fits"]["concurrent"]


class TestCrX8Concurrent:
    def test_cr_x8_concurrent_lists_the_open_pull_request_that_shares_a_path_and_leaves_out_the_one_that_does_not(
        self, shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, THIS))
        shim(shim_dir, tmp_path, "gh", github([[ELSEWHERE, SHARING]], [], {NUMBER: OWN_PATHS, 850: SHARED, 851: APART}))
        record = filled("context", written(tmp_path, example()))
        assert concurrent_of(record) == [{"pr": 850, "gloss": SHARING["title"]}]
        assert calls(tmp_path, "gh") == [
            OPEN_PULLS + "1", OPEN_PULLS + "2",
            *(files_of(number, page) for number in (NUMBER, 850, 851) for page in (1, 2)),
        ]

    def test_cr_x8_the_records_own_pull_request_among_the_open_ones_is_left_out(self, shim_dir: Path, tmp_path: Path):
        own = pull(NUMBER, EXAMPLE["pr"]["title"])
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, THIS))
        shim(shim_dir, tmp_path, "gh", github([[own, SHARING]], [], {NUMBER: OWN_PATHS, 850: SHARED}))
        record = filled("context", written(tmp_path, example()))
        assert concurrent_of(record) == [{"pr": 850, "gloss": SHARING["title"]}]
        assert calls(tmp_path, "gh").count(files_of(NUMBER, 1)) == 1

    def test_cr_x8_a_sharing_pull_request_that_sits_alone_on_the_second_page_is_found(
        self, shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, THIS))
        files = {NUMBER: OWN_PATHS, 850: SHARED, 851: APART}
        shim(shim_dir, tmp_path, "gh", github([[ELSEWHERE], [SHARING]], [], files))
        record = filled("context", written(tmp_path, example()))
        assert concurrent_of(record) == [{"pr": 850, "gloss": SHARING["title"]}]
        assert calls(tmp_path, "gh")[:3] == [OPEN_PULLS + "1", OPEN_PULLS + "2", OPEN_PULLS + "3"]

    def test_cr_x8_the_pages_are_read_until_one_comes_back_empty_however_short_a_page_is(
        self, shim_dir: Path, tmp_path: Path
    ):
        pages = [[pull(number, f"docs(tool): page {number} of the guide [9k9.{number}]")] for number in (861, 862, 863)]
        files = {NUMBER: OWN_PATHS, 861: APART, 862: APART, 863: SHARED}
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, THIS))
        shim(shim_dir, tmp_path, "gh", github(pages, [], files))
        record = filled("context", written(tmp_path, example()))
        assert [entry["pr"] for entry in concurrent_of(record)] == [863]
        assert calls(tmp_path, "gh")[:4] == [OPEN_PULLS + str(page) for page in (1, 2, 3, 4)]

    def test_cr_x8_a_renamed_file_counts_under_its_old_path_as_well(self, shim_dir: Path, tmp_path: Path):
        answers = github([[SHARING]], [], {NUMBER: OWN_PATHS, 850: ["src/panel/checks.py"]})
        moved = answers[files_of(850, 1)]["stdout"][0]
        moved.update(status="renamed", previous_filename="src/panel/gate.py")
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, THIS))
        shim(shim_dir, tmp_path, "gh", answers)
        record = filled("context", written(tmp_path, example()))
        assert [entry["pr"] for entry in concurrent_of(record)] == [850]

    def test_cr_x8_a_shared_path_on_the_second_page_of_a_pull_requests_files_is_found(
        self, shim_dir: Path, tmp_path: Path
    ):
        answers = github([[SHARING]], [], {NUMBER: OWN_PATHS, 850: APART})
        answers[files_of(850, 2)] = {"stdout": [FILE | {"filename": OWN_PATHS[1]}]}
        answers[files_of(850, 3)] = {"stdout": []}
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, THIS))
        shim(shim_dir, tmp_path, "gh", answers)
        record = filled("context", written(tmp_path, example()))
        assert [entry["pr"] for entry in concurrent_of(record)] == [850]

    def test_cr_x8_concurrent_pull_requests_come_lowest_number_first(self, shim_dir: Path, tmp_path: Path):
        later = pull(855, "refactor(review-panel): the gate reads one file [9k9.431]")
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, THIS))
        shim(shim_dir, tmp_path, "gh", github([[later, SHARING]], [], {NUMBER: OWN_PATHS, 850: SHARED, 855: SHARED}))
        record = filled("context", written(tmp_path, example()))
        assert [entry["pr"] for entry in concurrent_of(record)] == [850, 855]

    def test_cr_x8_with_no_other_open_pull_request_the_records_own_paths_are_not_read(
        self, shim_dir: Path, tmp_path: Path
    ):
        own = pull(NUMBER, EXAMPLE["pr"]["title"])
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, THIS))
        shim(shim_dir, tmp_path, "gh", github([[own]]))
        record = filled("context", written(tmp_path, example()))
        assert concurrent_of(record) == []
        assert calls(tmp_path, "gh") == [OPEN_PULLS + "1", OPEN_PULLS + "2"]

    def test_a_record_with_no_pull_request_number_gets_no_concurrent_entry_and_a_heads_up_row_saying_so(
        self, shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", tracker(*FAMILY))
        shim(shim_dir, tmp_path, "gh", github([[SHARING, OTHER]], [ROUTING]))
        path = written(tmp_path, example(number=None))
        record = filled("context", path)
        assert concurrent_of(record) == []
        assert record["heads_up"] == [*EXAMPLE["heads_up"], NOT_CHECKED]
        assert "no pull request" in NOT_CHECKED and "not checked" in NOT_CHECKED
        # The parts that need no number are still filled.
        assert scope_of(record)[2]["status"] == "in flight"
        assert [entry["pr"] for entry in record["where_this_fits"]["builds_on"]] == [803]
        assert_passes_lint(path)
        assert not [call for call in calls(tmp_path, "gh") if "/files?" in call]

    def test_the_heads_up_row_takes_the_place_of_none_and_goes_once_the_record_names_its_pull_request(
        self, shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, THIS))
        shim(shim_dir, tmp_path, "gh", github([[SHARING]], [], {NUMBER: OWN_PATHS, 850: SHARED}))
        unnumbered = example(number=None)
        unnumbered["heads_up"] = ["None."]
        path = written(tmp_path, unnumbered)
        first = filled("context", path)
        assert first["heads_up"] == [NOT_CHECKED]
        first["pr"]["number"] = NUMBER
        second = filled("context", written(tmp_path, first))
        assert second["heads_up"] == ["None."]
        assert concurrent_of(second) == [{"pr": 850, "gloss": SHARING["title"]}]
        assert_passes_lint(path)

    def test_the_heads_up_row_leaves_the_authors_entries_and_an_unfilled_list_as_they_are(
        self, shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, THIS))
        shim(shim_dir, tmp_path, "gh", github([[SHARING]], [], {NUMBER: OWN_PATHS, 850: APART}))
        numbered = example()
        numbered["heads_up"] = []
        assert filled("context", written(tmp_path, numbered))["heads_up"] == []
        unnumbered = example(number=None)
        once = filled("context", written(tmp_path, unnumbered))["heads_up"]
        twice = filled("context", tmp_path / "record.json")["heads_up"]
        assert once == twice == [*EXAMPLE["heads_up"], NOT_CHECKED]

    @pytest.mark.parametrize("heads_up", [[], ["None."], ["The gate ran on one machine."]])
    def test_a_record_with_no_number_gets_no_row_when_no_other_pull_request_is_open(
        self, heads_up: list[str], shim_dir: Path, tmp_path: Path
    ):
        # With nothing open beside it, no pull request went unchecked, so there is nothing to warn of.
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, THIS))
        shim(shim_dir, tmp_path, "gh", github())
        unnumbered = example(number=None)
        unnumbered["heads_up"] = list(heads_up)
        record = filled("context", written(tmp_path, unnumbered))
        assert record["heads_up"] == heads_up
        assert concurrent_of(record) == []


class TestGeneratorRows:
    def rows(self, entries: list[str], rows: list[str]) -> list[str]:
        record = {"heads_up": list(entries)}
        change_record.set_generator_rows(record, "context", rows)
        return record["heads_up"]

    def test_a_generators_row_opens_with_its_name_and_takes_the_place_of_none(self):
        assert self.rows(["None."], ["Nothing was read."]) == ["context: Nothing was read."]
        assert self.rows([" None.\n"], ["Nothing was read."]) == ["context: Nothing was read."]

    def test_a_generators_row_joins_the_authors_entries_and_another_generators(self):
        entries = ["The gate ran on one machine.", "campaign: No review round has run."]
        assert self.rows(entries, ["Nothing was read."]) == [*entries, "context: Nothing was read."]

    def test_a_generators_next_run_replaces_its_rows_and_no_one_elses(self):
        entries = ["context: An old row.", "The gate ran on one machine.", "campaign: No review round has run."]
        assert self.rows(entries, ["A new row."]) == [*entries[1:], "context: A new row."]
        assert self.rows(entries, []) == entries[1:]

    def test_none_comes_back_when_a_generators_last_row_goes_and_nothing_else_is_left(self):
        assert self.rows(["context: An old row."], []) == ["None."]

    def test_a_list_the_generator_never_wrote_in_is_left_as_it_is(self):
        assert self.rows([], []) == []
        assert self.rows(["None."], []) == ["None."]
        assert self.rows(["contextual notes are the author's."], []) == ["contextual notes are the author's."]


def assert_passes_lint(path: Path) -> None:
    assert lint(path) == {"valid": True}


class TestCrX7NothingAround:
    def test_cr_x7_an_only_child_with_no_pull_request_around_it_gets_one_row_and_none_twice_and_passes_lint(
        self, shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, EPIC, THIS))
        shim(shim_dir, tmp_path, "gh", github())
        path = written(tmp_path, example())
        fits = filled("context", path)["where_this_fits"]
        assert fits["scope"] == [{"slice": WORK_ITEM, "covers": THIS["title"], "status": "this PR"}]
        # An empty list is how the record says none, and the pull request body prints the word.
        assert (fits["builds_on"], fits["concurrent"]) == ([], [])
        assert_passes_lint(path)
        assert calls(tmp_path, "gh") == [OPEN_PULLS + "1"]

    def test_cr_x7_a_work_item_with_no_parent_is_its_own_owning_item(self, shim_dir: Path, tmp_path: Path):
        alone = THIS | {"parent": None}
        shim(shim_dir, tmp_path, "work", tracker(alone))
        shim(shim_dir, tmp_path, "gh", github())
        path = written(tmp_path, example())
        fits = filled("context", path)["where_this_fits"]
        assert fits["ancestry"] == [{"id": WORK_ITEM, "title": THIS["title"], "type": "feature"}]
        assert fits["scope"] == [{"slice": WORK_ITEM, "covers": THIS["title"], "status": "this PR"}]
        assert (fits["builds_on"], fits["concurrent"]) == ([], [])
        assert_passes_lint(path)
        assert calls(tmp_path, "work") == [
            f"--format json show {WORK_ITEM}", f"--format json list --parent {WORK_ITEM}"
        ]

    def test_a_work_item_directly_under_the_root_is_its_own_owning_item(self, shim_dir: Path, tmp_path: Path):
        # Its parent is the root of the whole tree. A scope table of the root's
        # children would list every piece of work in the project.
        under_root = THIS | {"parent": MILESTONE["id"]}
        stranger = item("agents-config-9k9.12", "Something else under the milestone", MILESTONE["id"])
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, stranger, under_root))
        shim(shim_dir, tmp_path, "gh", github())
        path = written(tmp_path, example())
        fits = filled("context", path)["where_this_fits"]
        assert [entry["id"] for entry in fits["ancestry"]] == [MILESTONE["id"], WORK_ITEM]
        assert fits["scope"] == [{"slice": WORK_ITEM, "covers": THIS["title"], "status": "this PR"}]
        assert_passes_lint(path)
        assert f"--format json list --parent {MILESTONE['id']}" not in calls(tmp_path, "work")

    def test_an_item_that_is_its_own_owning_item_shows_its_own_children(self, shim_dir: Path, tmp_path: Path):
        under_root = THIS | {"parent": MILESTONE["id"]}
        first = item("agents-config-9k9.408.1", "The pins are data", WORK_ITEM, status="closed")
        second = item("agents-config-9k9.408.2", "A dying run recovers", WORK_ITEM)
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE, under_root, first, second))
        shim(shim_dir, tmp_path, "gh", github())
        fits = filled("context", written(tmp_path, example()))["where_this_fits"]
        assert fits["scope"] == [
            {"slice": first["id"], "covers": first["title"], "status": "done"},
            {"slice": second["id"], "covers": second["title"], "status": "open"},
        ]


def triaged(scope: str, why: str) -> str:
    """Return a description that ends with a triage record, as the tracker writes one when work is filed."""
    lines = [
        "## Triage",
        f"- Scope: {scope} — {why}",
        "- Priority: P3 — Nothing waits on it.",
        f"- Anchor: {EPIC['id']} — It is pin work.",
    ]
    return "Found while pinning the seats. Its first draft read:\n- Scope: unknown — to be decided\n\n" + "\n".join(lines)


# Two items found while working on the record's work item, one filed under each kind of scope call.
FOUND = (
    item(
        "agents-config-9k9.470", "The gate compares the effort a run used with its pin", EPIC["id"],
        description=triaged("out-of-scope", "It needs its own tests — and a run record to read."),
    ),
    item(
        "agents-config-9k9.471", "The verdict names a round stopped by runs that died", EPIC["id"], status="deferred",
        description=triaged("in-scope — deferred: next-slice", "It changes a schema that another skill owns."),
    ),
)
FILED = [
    {
        "status": "filed", "item": "agents-config-9k9.470",
        "what": "The gate compares the effort a run used with its pin",
        "reason": "It needs its own tests — and a run record to read.",
    },
    {
        "status": "filed", "item": "agents-config-9k9.471",
        "what": "The verdict names a round stopped by runs that died",
        "reason": "It changes a schema that another skill owns.",
    },
]

# The reason the one recorded triage record gives for its scope call.
RECORDED_REASON = (
    "Each erratum is implemented to the spec's evident intent in the slice that reads it; "
    "amending the text invalidates the attack record, so it is one batched amendment, not seven."
)

# The first not-filed row and the first in-flight row that the example's author wrote.
NOT_FILED, FLYING = EXAMPLE["discovered"]["rows"][:2]


def discovering(rows: list[Any]) -> dict[str, Any]:
    """Return the example record with ``rows`` as its discovered work."""
    record = copy.deepcopy(EXAMPLE)
    record["discovered"] = {"rows": copy.deepcopy(rows)}
    return record


# The tracker's answers about the whole family and the two items found from the work item.
FAMILY_WITH_FOUND = tracker(*FAMILY, *FOUND, discovered={WORK_ITEM: [entry["id"] for entry in FOUND]})


def found_from(*found: dict[str, Any]) -> dict[str, Any]:
    """Return the tracker's answers when ``found`` are the items discovered from the record's work item."""
    return tracker(MILESTONE, EPIC, THIS, *found, discovered={WORK_ITEM: [entry["id"] for entry in found]})


class TestCrX5Discovered:
    def test_cr_x5_discovered_writes_a_filed_row_for_each_discovered_item_ahead_of_the_rows_the_author_wrote(
        self, shim_dir: Path, tmp_path: Path
    ):
        assert (NOT_FILED["status"], FLYING["status"]) == ("not filed", "in flight")
        shim(shim_dir, tmp_path, "work", found_from(*FOUND))
        path = written(tmp_path, discovering([NOT_FILED, FLYING]))
        record = filled("discovered", path)
        assert record["discovered"]["rows"] == [*FILED, NOT_FILED, FLYING]
        assert [row["status"] for row in record["discovered"]["rows"]] == ["filed", "filed", "not filed", "in flight"]
        assert record["discovered"]["filed_digest"] == change_record.stamp(FILED)
        assert_passes_lint(path)
        assert calls(tmp_path, "work") == [
            f"--format json dep list {WORK_ITEM}",
            "--format json show agents-config-9k9.470 agents-config-9k9.471",
        ]
        assert calls(tmp_path, "gh") == []

    def test_cr_x5_the_authors_rows_stay_in_the_order_the_author_wrote_them(self, shim_dir: Path, tmp_path: Path):
        authored = [EXAMPLE["discovered"]["rows"][index] for index in (2, 0, 1, 3)]
        assert [row["status"] for row in authored] == ["in flight", "not filed", "in flight", "not filed"]
        shim(shim_dir, tmp_path, "work", found_from(*FOUND))
        record = filled("discovered", written(tmp_path, discovering(authored)))
        assert record["discovered"]["rows"] == [*FILED, *authored]

    def test_cr_x5_only_an_item_whose_edge_says_discovered_from_gets_a_row(self, shim_dir: Path, tmp_path: Path):
        answers = found_from(FOUND[0])
        edges = answers[f"--format json dep list {WORK_ITEM}"]["stdout"]["data"]["dependents"]
        assert sorted(edge["type"] for edge in edges) == ["blocks", "blocks", "discovered-from"]
        shim(shim_dir, tmp_path, "work", answers)
        record = filled("discovered", written(tmp_path, discovering([NOT_FILED])))
        assert record["discovered"]["rows"] == [FILED[0], NOT_FILED]

    def test_cr_x5_the_filed_rows_come_in_the_order_a_reader_counts_ids(self, shim_dir: Path, tmp_path: Path):
        later = triaged("out-of-scope", "Later.")
        ninth = item("agents-config-9k9.77.9", "The ninth thing found", EPIC["id"], description=later)
        tenth = item("agents-config-9k9.77.10", "The tenth thing found", EPIC["id"], description=later)
        answers = tracker(MILESTONE, EPIC, THIS, ninth, tenth, discovered={WORK_ITEM: [ninth["id"], tenth["id"]]})
        # The tracker lists the edges in an order of its own.
        answers[f"--format json dep list {WORK_ITEM}"]["stdout"]["data"]["dependents"].reverse()
        shim(shim_dir, tmp_path, "work", answers)
        record = filled("discovered", written(tmp_path, discovering(["None."])))
        assert [row["item"] for row in record["discovered"]["rows"]] == [ninth["id"], tenth["id"]]

    def test_cr_x5_a_later_run_replaces_the_filed_rows_and_drops_one_whose_item_is_no_longer_discovered(
        self, shim_dir: Path, tmp_path: Path
    ):
        stale = dict(FILED[1], reason="An older reason.")
        gone = {"status": "filed", "item": "agents-config-9k9.499", "what": "Refiled elsewhere", "reason": "It moved."}
        shim(shim_dir, tmp_path, "work", found_from(*FOUND))
        record = filled("discovered", written(tmp_path, discovering([NOT_FILED, stale, gone, FLYING])))
        assert record["discovered"]["rows"] == [*FILED, NOT_FILED, FLYING]

    def test_cr_x5_a_filed_row_takes_the_place_of_the_none_entry(self, shim_dir: Path, tmp_path: Path):
        shim(shim_dir, tmp_path, "work", found_from(FOUND[0]))
        path = written(tmp_path, discovering(["None."]))
        assert filled("discovered", path)["discovered"]["rows"] == [FILED[0]]
        assert_passes_lint(path)

    @pytest.mark.parametrize("rows", [["None."], [], [NOT_FILED, FLYING]], ids=["none", "unfilled", "the author's"])
    def test_cr_x5_with_nothing_discovered_the_rows_stay_as_they_are_and_the_stamp_covers_no_row(
        self, rows: list[Any], shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", found_from())
        record = filled("discovered", written(tmp_path, discovering(rows)))
        assert record["discovered"] == {"rows": rows, "filed_digest": change_record.stamp([])}
        assert calls(tmp_path, "work") == [f"--format json dep list {WORK_ITEM}"]

    def test_cr_x5_a_discovered_item_with_no_triage_record_fails_naming_it_and_leaves_the_record(
        self, shim_dir: Path, tmp_path: Path
    ):
        untriaged = item("agents-config-9k9.472", "An edge added by hand", EPIC["id"], description="- Scope: none given")
        shim(shim_dir, tmp_path, "work", found_from(FOUND[0], untriaged))
        path = written(tmp_path, discovering([NOT_FILED]))
        before = path.read_bytes()
        proc = run("discovered", path)
        assert proc.returncode != 0
        assert "agents-config-9k9.472" in proc.stderr and "triage" in proc.stderr
        assert path.read_bytes() == before

    def test_cr_x5_the_reason_is_the_one_the_recorded_triage_record_gives(self):
        shown = RECORDED["work"]["--format json show agents-config-9k9.484.3"]["stdout"]["data"]["items"][0]
        assert "\n\n## Triage\n- Scope: out-of-scope — " in shown["description"]
        assert change_record.TRIAGE_SCOPE.findall(shown["description"]) == [RECORDED_REASON]


def unchanged_by(generator: str, path: Path) -> subprocess.CompletedProcess[str]:
    """Run ``generator``, and assert it exits with an error and leaves the record file and its directory alone."""
    before = path.read_bytes()
    beside = sorted(path.parent.glob("record.json*"))
    proc = run(generator, path)
    assert proc.returncode != 0
    assert path.read_bytes() == before
    assert sorted(path.parent.glob("record.json*")) == beside
    return proc


# Every call `context` makes over the family when the record names its pull
# request and one other is open, in order, by the executable that takes it.
CONTEXT_CALLS = {
    "work": [
        "--format json show agents-config-9k9.408",
        "--format json show agents-config-9k9.77",
        "--format json show agents-config-9k9",
        "--format json list --parent agents-config-9k9.77",
    ],
    "gh": [
        OPEN_PULLS + "1",
        OPEN_PULLS + "2",
        "pr view 803 --json number,state,title",
        *(files_of(number, page) for number in (NUMBER, 850) for page in (1, 2)),
    ],
}


def family_shims(shim_dir: Path, tmp_path: Path, **failing: int) -> None:
    """Shim both executables over the family, and make the one named in ``failing`` fail the call it numbers."""
    shim(shim_dir, tmp_path, "work", tracker(*FAMILY), failing.get("work"))
    shim(shim_dir, tmp_path, "gh", github([[OTHER]], [ROUTING], {NUMBER: OWN_PATHS, 850: OWN_PATHS}), failing.get("gh"))


class TestCrX4Failure:
    def test_cr_x4_context_given_an_id_the_tracker_does_not_know_names_it_and_leaves_the_record(
        self, shim_dir: Path, tmp_path: Path
    ):
        unknown = "agents-config-zzz.999"
        shim(shim_dir, tmp_path, "work", {f"--format json show {unknown}": UNKNOWN})
        shim(shim_dir, tmp_path, "gh", github())
        record = copy.deepcopy(EXAMPLE)
        record["work_item"]["id"] = unknown
        proc = unchanged_by("context", written(tmp_path, record))
        assert unknown in proc.stderr
        assert calls(tmp_path, "gh") == []

    def test_cr_x4_discovered_given_an_id_the_tracker_does_not_know_names_it_and_leaves_the_record(
        self, shim_dir: Path, tmp_path: Path
    ):
        unknown = "agents-config-zzz.999"
        shim(shim_dir, tmp_path, "work", {
            f"--format json dep list {unknown}": RECORDED["work"][f"--format json dep list {unknown}"]
        })
        record = discovering([NOT_FILED, FLYING])
        record["work_item"]["id"] = unknown
        proc = unchanged_by("discovered", written(tmp_path, record))
        assert unknown in proc.stderr

    def test_the_family_makes_context_call_what_the_failure_cases_number(self, shim_dir: Path, tmp_path: Path):
        family_shims(shim_dir, tmp_path)
        filled("context", written(tmp_path, copy.deepcopy(EXAMPLE)))
        assert {name: calls(tmp_path, name) for name in ("work", "gh")} == CONTEXT_CALLS

    @pytest.mark.parametrize(
        ("name", "call"),
        [(name, call) for name, made in CONTEXT_CALLS.items() for call in range(1, len(made) + 1)],
    )
    def test_cr_x4_context_leaves_the_record_when_a_shim_fails_any_one_of_its_calls_the_second_of_two_included(
        self, name: str, call: int, shim_dir: Path, tmp_path: Path
    ):
        family_shims(shim_dir, tmp_path, **{name: call})
        proc = unchanged_by("context", written(tmp_path, copy.deepcopy(EXAMPLE)))
        assert f"`{name} {CONTEXT_CALLS[name][call - 1]}`" in proc.stderr
        assert len(calls(tmp_path, name)) == call

    @pytest.mark.parametrize("call", [1, 2])
    def test_cr_x4_discovered_leaves_the_record_when_the_shim_fails_the_second_of_its_two_calls_or_the_first(
        self, call: int, shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", found_from(*FOUND), call)
        proc = unchanged_by("discovered", written(tmp_path, discovering([NOT_FILED, FLYING])))
        made = [f"--format json dep list {WORK_ITEM}", "--format json show agents-config-9k9.470 agents-config-9k9.471"]
        assert f"`work {made[call - 1]}`" in proc.stderr
        assert calls(tmp_path, "work") == made[:call]

    @pytest.mark.parametrize("generator", ["context", "discovered"])
    def test_cr_x4_a_generator_fails_cleanly_when_its_executable_is_not_on_the_search_path(
        self, generator: str, tmp_path: Path
    ):
        proc = unchanged_by(generator, written(tmp_path, copy.deepcopy(EXAMPLE)))
        assert "cannot run `work" in proc.stderr and "Traceback" not in proc.stderr

    def test_cr_x4_an_item_whose_parent_the_tracker_cannot_answer_fails_and_is_never_taken_for_a_root(
        self, shim_dir: Path, tmp_path: Path
    ):
        # A field the tracker cannot answer is absent from the item and named in a list beside it.
        answers = tracker(*FAMILY)
        unanswered = answers[f"--format json show {EPIC['id']}"]["stdout"]["data"]["items"][0]
        del unanswered["parent"]
        unanswered["unknown_relations"] = ["parent"]
        shim(shim_dir, tmp_path, "work", answers)
        shim(shim_dir, tmp_path, "gh", github())
        proc = unchanged_by("context", written(tmp_path, copy.deepcopy(EXAMPLE)))
        assert "'parent'" in proc.stderr and "Traceback" not in proc.stderr

    def test_cr_x4_parent_fields_that_lead_back_to_an_item_fail_and_do_not_run_for_ever(
        self, shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", tracker(MILESTONE | {"parent": WORK_ITEM}, EPIC, THIS))
        shim(shim_dir, tmp_path, "gh", github())
        proc = unchanged_by("context", written(tmp_path, copy.deepcopy(EXAMPLE)))
        assert WORK_ITEM in proc.stderr and "back to itself" in proc.stderr
        assert len(calls(tmp_path, "work")) == 3

    @pytest.mark.parametrize("printed", ["not json", '{"message": "a page that is no list"}'])
    def test_cr_x4_an_answer_that_is_not_what_was_asked_for_fails_naming_the_call(
        self, printed: str, shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", tracker(*FAMILY))
        shim(shim_dir, tmp_path, "gh", {OPEN_PULLS + "1": {"stdout": printed}})
        proc = unchanged_by("context", written(tmp_path, copy.deepcopy(EXAMPLE)))
        assert f"`gh {OPEN_PULLS}1`" in proc.stderr


class TestCrX6SecondRun:
    def test_cr_x6_a_second_run_of_context_leaves_the_record_byte_identical_and_keeps_the_slice_line(
        self, shim_dir: Path, tmp_path: Path
    ):
        family_shims(shim_dir, tmp_path)
        path = written(tmp_path, example())
        before = path.read_bytes()
        first = filled("context", path)
        after_first = path.read_bytes()
        assert after_first != before
        second = filled("context", path)
        assert path.read_bytes() == after_first
        assert first["work_item"]["slice"] == second["work_item"]["slice"] == EXAMPLE["work_item"]["slice"]
        assert len(calls(tmp_path, "work")) == 2 * len(CONTEXT_CALLS["work"])

    def test_cr_x6_a_second_run_of_discovered_leaves_the_record_byte_identical_and_keeps_the_slice_line(
        self, shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", found_from(*FOUND))
        path = written(tmp_path, discovering([NOT_FILED, FLYING]))
        before = path.read_bytes()
        first = filled("discovered", path)
        after_first = path.read_bytes()
        assert after_first != before
        second = filled("discovered", path)
        assert path.read_bytes() == after_first
        assert first["work_item"]["slice"] == second["work_item"]["slice"] == EXAMPLE["work_item"]["slice"]

    def test_cr_x6_each_generator_run_after_the_other_leaves_the_others_part_and_the_authors_fields_alone(
        self, shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", FAMILY_WITH_FOUND)
        shim(shim_dir, tmp_path, "gh", github([[OTHER]], [ROUTING], {NUMBER: OWN_PATHS, 850: APART}))
        path = written(tmp_path, discovering([NOT_FILED, FLYING]))
        filled("context", path)
        filled("discovered", path)
        both = path.read_bytes()
        record = filled("context", path)
        filled("discovered", path)
        assert path.read_bytes() == both
        authored = set(EXAMPLE) - {"where_this_fits", "discovered"}
        assert {group: record[group] for group in authored} == {group: EXAMPLE[group] for group in authored}

    def test_cr_x6_the_file_holds_the_groups_in_the_schemas_order_whichever_generator_ran_first(
        self, shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", FAMILY_WITH_FOUND)
        shim(shim_dir, tmp_path, "gh", github([[OTHER]], [ROUTING], {NUMBER: OWN_PATHS, 850: APART}))
        results = []
        for order in (("context", "discovered"), ("discovered", "context")):
            path = written(tmp_path, example())
            for generator in order:
                filled(generator, path)
            results.append(path.read_bytes())
        assert results[0] == results[1]
        schema = json.loads((SKILL / "references" / "record.schema.json").read_text(encoding="utf-8"))
        assert list(json.loads(results[0])) == [name for name in schema["properties"] if name in EXAMPLE]


# One hand edit of each part a generator writes, by the generator and the stamp the edit leaves stale.
HAND_EDITS = {
    ("context", "/where_this_fits/digest"): lambda record: record["where_this_fits"]["scope"][3].update(status="done"),
    ("discovered", "/discovered/filed_digest"): lambda record: record["discovered"]["rows"][0].update(reason="Small."),
}


class TestFilledRecord:
    def fill_both(self, shim_dir: Path, tmp_path: Path) -> Path:
        """Run both generators over the example record, and return the record file."""
        shim(shim_dir, tmp_path, "work", FAMILY_WITH_FOUND)
        shim(shim_dir, tmp_path, "gh", github([[OTHER, SHARING]], [ROUTING], {NUMBER: OWN_PATHS, 850: SHARED}))
        path = written(tmp_path, example())
        filled("context", path)
        filled("discovered", path)
        return path

    def test_a_record_that_both_generators_filled_passes_lint_with_its_stamps(self, shim_dir: Path, tmp_path: Path):
        path = self.fill_both(shim_dir, tmp_path)
        record = json.loads(path.read_text(encoding="utf-8"))
        stamped = {f"/{group}/{key}": content for group, key, content in change_record.generated_parts(record)}
        assert record["where_this_fits"]["digest"] == change_record.stamp(stamped["/where_this_fits/digest"])
        assert record["discovered"]["filed_digest"] == change_record.stamp(stamped["/discovered/filed_digest"])
        assert stamped["/discovered/filed_digest"] == FILED
        assert_passes_lint(path)

    @pytest.mark.parametrize(("generator", "stale"), sorted(HAND_EDITS))
    def test_a_hand_edit_of_a_part_a_generator_wrote_fails_lint_until_that_generator_runs_again(
        self, generator: str, stale: str, shim_dir: Path, tmp_path: Path
    ):
        path = self.fill_both(shim_dir, tmp_path)
        generated = path.read_bytes()
        record = json.loads(generated)
        HAND_EDITS[generator, stale](record)
        written(tmp_path, record)
        result = lint(path)
        assert [(error["code"], error["path"]) for error in result["errors"]] == [("stale-stamp", stale)]
        filled(generator, path)
        assert path.read_bytes() == generated
        assert_passes_lint(path)


# Text with a construct that belongs in an artifact a machine reads, and the same text with the construct quoted.
QUOTED = {
    "Drop the <details> fold from the body": "Drop the `<details>` fold from the body",
    "Keep the <details open> fold": "Keep the `<details open>` fold",
    "<DETAILS>": "`<DETAILS>`",
    "Strip the <!-- marker --> from the body": "Strip the `<!-- marker -->` from the body",
    "An opening <!-- with nothing to close it": "An opening `<!--` with nothing to close it",
    "A <details> fold and a <!-- note --> together": "A `<details>` fold and a `<!-- note -->` together",
    "One quoted `<details>` and one bare <details>": "One quoted `<details>` and one bare `<details>`",
    "A fold <details `with` a span in its tag>": "A fold `<details ``with` a span in its tag>",
    "A fold beside a span, <details>`here`": "A fold beside a span, `<details>``here`",
    "Two lines.\r\n<details>\nA third.": "Two lines.\r\n`<details>`\nA third.",
}

# Text whose construct a code span cannot quote where it stands, and the same text with its line quoted whole.
QUOTED_WHOLE = {
    "```json": "```` ```json ````",
    "~~~json": "` ~~~json `",
    "> ```JSON": "```` > ```JSON ````",
    "- ~~~~ json": "` - ~~~~ json `",
    "An escaped \\<details> fold": "` An escaped \\<details> fold `",
    "An open `span and a <details> fold": "`` An open `span and a <details> fold ``",
    "Kept.\n```json\nKept.": "Kept.\n```` ```json ````\nKept.",
}

# Text that holds nothing a machine reads, or holds it only inside a code span.
ALREADY_INERT = [
    "",
    "Pin effort and tools per reviewer slot",
    "Quote `<details>` and `<!-- a comment -->` in backticks",
    "A fence in another language is no construct:\n```python\nprint()\n```",
    "The word details and a lone < or -- are plain text",
    "A span that starts a line is no fence: ```json```",
]

# Pieces a hostile title could be made of. Random runs of them stand in for every text a tracker could hold.
PIECES = [
    "<details>", "<details open>", "<DETAILS ", "<!--", "-->", "`", "``", "```", "```json", "~~~json", "json",
    "\\", " ", "x", "\n", "\r\n", "> ", "- ", "1. ", "|", "\u2028",
]


class TestInertText:
    @pytest.mark.parametrize("text", sorted(QUOTED))
    def test_a_fold_or_a_comment_outside_a_code_span_is_quoted_as_one(self, text: str):
        assert change_record.inert(text) == QUOTED[text]

    @pytest.mark.parametrize("text", sorted(QUOTED_WHOLE))
    def test_a_line_whose_construct_no_span_can_quote_in_place_is_quoted_whole(self, text: str):
        assert change_record.inert(text) == QUOTED_WHOLE[text]

    @pytest.mark.parametrize("text", ALREADY_INERT)
    def test_text_that_holds_no_construct_comes_back_as_it_was(self, text: str):
        assert change_record.machine_constructs(text) == []
        assert change_record.inert(text) == text

    @pytest.mark.parametrize("text", sorted({**QUOTED, **QUOTED_WHOLE}))
    def test_the_quoted_text_holds_no_construct_and_the_text_it_came_from_did(self, text: str):
        assert change_record.machine_constructs(text)
        assert change_record.machine_constructs(change_record.inert(text)) == []

    def test_whatever_the_text_the_result_holds_no_construct_and_a_second_pass_changes_nothing(self):
        # The same seed gives the same texts on every run, so a failure can be run again.
        chooser = random.Random(843)
        texts = ["".join(chooser.choices(PIECES, k=chooser.randint(1, 9))) for _ in range(4000)]
        held = [text for text in texts if change_record.machine_constructs(text)]
        assert len(held) > 1000
        for text in texts:
            once = change_record.inert(text)
            assert change_record.machine_constructs(once) == [], repr(text)
            assert change_record.inert(once) == once, repr(text)
            if text not in held:
                assert once == text, repr(text)

    def test_the_lint_reports_through_the_same_reading_the_quoting_checks_itself_with(self, tmp_path: Path):
        record = copy.deepcopy(EXAMPLE)
        record["design_notes"] = "A fold:\n<details>\nand a fence:\n```json\n{}\n```"
        named = change_record.machine_constructs(record["design_notes"])
        assert named == ["a `<details>` fold", "a fenced `json` block"]
        found = [error for error in lint(written(tmp_path, record))["errors"] if error["code"] == "machine-content"]
        assert [error["message"].split(" holds ")[1].split(", which")[0] for error in found] == named


# Titles and a reason as a tracker and GitHub could hold them, each with a construct a machine reads.
FOLDED = "Fold the scope table in <details> on a long item"
NOTED = "Carry the <!-- prgroom --> block over"
FENCED = "```json"


class TestGeneratedTextIsInert:
    def fill_from_hostile_sources(self, shim_dir: Path, tmp_path: Path) -> Path:
        """Run both generators over a tracker and a GitHub whose every title holds a construct."""
        epic = EPIC | {"title": FOLDED}
        done = DONE | {"title": NOTED}
        found = FOUND[0] | {"title": FENCED, "description": triaged("out-of-scope", NOTED)}
        answers = tracker(MILESTONE, epic, done, THIS | {"title": FOLDED}, found, discovered={WORK_ITEM: [found["id"]]})
        routing = viewed(803, NOTED)
        sharing = pull(850, f"{FOLDED} [9k9.418]")
        shim(shim_dir, tmp_path, "work", answers)
        shim(shim_dir, tmp_path, "gh", github([[sharing]], [routing], {NUMBER: OWN_PATHS, 850: SHARED}))
        path = written(tmp_path, example())
        filled("context", path)
        filled("discovered", path)
        return path

    def test_a_record_filled_from_titles_that_hold_constructs_passes_lint(self, shim_dir: Path, tmp_path: Path):
        path = self.fill_from_hostile_sources(shim_dir, tmp_path)
        assert_passes_lint(path)
        for _, text in change_record._strings(json.loads(path.read_text(encoding="utf-8"))):
            assert change_record.machine_constructs(text) == []

    def test_each_title_and_reason_is_written_with_its_construct_quoted(self, shim_dir: Path, tmp_path: Path):
        record = json.loads(self.fill_from_hostile_sources(shim_dir, tmp_path).read_text(encoding="utf-8"))
        folded, noted = change_record.inert(FOLDED), change_record.inert(NOTED)
        assert (folded, noted) == (
            "Fold the scope table in `<details>` on a long item", "Carry the `<!-- prgroom -->` block over"
        )
        fits = record["where_this_fits"]
        assert [entry["title"] for entry in fits["ancestry"]] == ["Harness rework", folded, folded]
        assert [row["covers"] for row in fits["scope"]] == [noted, folded, "```` ```json ````"]
        assert fits["builds_on"] == [{"pr": 803, "gloss": noted}]
        assert fits["concurrent"] == [{"pr": 850, "gloss": f"{folded} [9k9.418]"}]
        assert record["discovered"]["rows"][0] == {
            "status": "filed", "item": FOUND[0]["id"], "what": "```` ```json ````", "reason": noted,
        }

    def test_an_open_pull_request_still_names_its_item_when_its_title_holds_a_construct(
        self, shim_dir: Path, tmp_path: Path
    ):
        naming = pull(850, f"{FOLDED} [9k9.409]")
        shim(shim_dir, tmp_path, "work", tracker(*FAMILY))
        shim(shim_dir, tmp_path, "gh", github([[naming]], [ROUTING], {NUMBER: OWN_PATHS, 850: APART}))
        record = filled("context", written(tmp_path, example()))
        assert scope_of(record)[2] == {
            "slice": IN_FLIGHT["id"], "covers": IN_FLIGHT["title"], "status": "in flight", "pr": 850
        }

    def test_a_second_run_over_the_same_titles_leaves_the_record_byte_identical(self, shim_dir: Path, tmp_path: Path):
        path = self.fill_from_hostile_sources(shim_dir, tmp_path)
        before = path.read_bytes()
        filled("context", path)
        filled("discovered", path)
        assert path.read_bytes() == before

    def test_the_record_renders_with_each_quoted_title_in_its_place(self, shim_dir: Path, tmp_path: Path):
        path = self.fill_from_hostile_sources(shim_dir, tmp_path)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "render", "body", str(path)], capture_output=True, text=True, check=False
        )
        assert proc.returncode == 0, proc.stderr
        assert "agents-config-9k9.77  Fold the scope table in `<details>` on a long item (epic)" in proc.stdout
        assert "| agents-config-9k9.470 | filed | ```` ```json ```` | Carry the `<!-- prgroom -->` block over |" in proc.stdout


# The record's work item in the recorded answers, and the item whose work turned another up.
LIVE = "agents-config-9k9.484.2.3"
LIVE_SOURCE = "agents-config-9k9.484.2.1"


class TestRecordedAnswers:
    """Both generators run over answers recorded from a live repository, replayed as they were given."""

    def test_context_fills_a_new_record_from_the_recorded_answers(self, shim_dir: Path, tmp_path: Path):
        shim(shim_dir, tmp_path, "work", RECORDED["work"])
        shim(shim_dir, tmp_path, "gh", RECORDED["gh"])
        new = change_record.new_record("feat", "change-record", LIVE)
        fits = filled("context", written(tmp_path, new))["where_this_fits"]
        assert [(entry["id"], entry["type"]) for entry in fits["ancestry"]] == [
            ("agents-config-9k9", "milestone"),
            ("agents-config-9k9.484", "feature"),
            ("agents-config-9k9.484.2", "task"),
            ("agents-config-9k9.484.2.3", "feature"),
        ]
        assert fits["ancestry"][0]["title"] == "Harness rework"
        assert [(row["slice"].removeprefix("agents-config-9k9.484.2."), row["status"]) for row in fits["scope"]] == [
            ("1", "in flight"), ("2", "open"), ("3", "this PR"), ("4", "open"),
            ("5", "open"), ("6", "open"), ("7", "open"), ("8", "open"),
        ]
        assert fits["scope"][0]["pr"] == 860
        assert fits["scope"][2]["covers"] == fits["ancestry"][3]["title"]
        assert (fits["builds_on"], fits["concurrent"]) == ([], [])
        assert calls(tmp_path, "work") == [
            "--format json show agents-config-9k9.484.2.3",
            "--format json show agents-config-9k9.484.2",
            "--format json show agents-config-9k9.484",
            "--format json show agents-config-9k9",
            "--format json list --parent agents-config-9k9.484.2",
        ]
        assert calls(tmp_path, "gh") == [OPEN_PULLS + "1", OPEN_PULLS + "2"]

    def test_context_reads_the_recorded_paths_of_the_recorded_open_pull_request(self, shim_dir: Path, tmp_path: Path):
        # The recording holds one open pull request and its paths. The record's
        # own pull request is given the same paths, which makes the two concurrent.
        own = pull(861, "feat(change-record): two generators fill the record [9k9.484.2.3]")
        answers = RECORDED["gh"] | {
            OPEN_PULLS + "1": {"stdout": [own, *RECORDED["gh"][OPEN_PULLS + "1"]["stdout"]]},
            files_of(861, 1): RECORDED["gh"][files_of(860, 1)],
            files_of(861, 2): RECORDED["gh"][files_of(860, 2)],
        }
        shim(shim_dir, tmp_path, "work", RECORDED["work"])
        shim(shim_dir, tmp_path, "gh", answers)
        record = change_record.new_record("feat", "change-record", LIVE)
        record["pr"]["number"] = 861
        record = filled("context", written(tmp_path, record))
        assert record["where_this_fits"]["concurrent"] == [{"pr": 860, "gloss": PULL["title"]}]
        assert record["heads_up"] == []
        assert calls(tmp_path, "gh")[2:] == [files_of(number, page) for number in (861, 860) for page in (1, 2)]

    def test_discovered_fills_a_new_record_from_the_recorded_answers(self, shim_dir: Path, tmp_path: Path):
        shim(shim_dir, tmp_path, "work", RECORDED["work"])
        record = filled("discovered", written(tmp_path, change_record.new_record("feat", "change-record", LIVE_SOURCE)))
        assert record["discovered"]["rows"] == [
            {
                "status": "filed",
                "item": "agents-config-9k9.484.3",
                "what": "The change-record spec's errata are amended in one pass and re-attacked once",
                "reason": RECORDED_REASON,
            }
        ]
        assert calls(tmp_path, "work") == [
            "--format json dep list agents-config-9k9.484.2.1", "--format json show agents-config-9k9.484.3"
        ]

    def test_the_recorded_answer_for_an_id_the_tracker_does_not_know_is_an_error_on_stdout(self):
        assert (UNKNOWN["exit"], UNKNOWN["stderr"]) == (1, "")
        assert UNKNOWN["stdout"]["error"]["code"] == "E_NOT_FOUND"


class TestCrC8ReadsOnly:
    @pytest.mark.parametrize(
        "call",
        [OPEN_PULLS + "1", "pr view 803 --json number,state,title", files_of(843, 1)],
    )
    def test_cr_c8_each_call_the_generators_make_to_gh_is_a_read(self, call: str):
        assert is_read(call)

    @pytest.mark.parametrize(
        "call",
        [
            "pr comment 843 --body text",
            "pr edit 843 --body-file body.md",
            "pr create --title text",
            "pr merge 843 --squash",
            "pr review 843 --approve",
            "issue comment 843 --body text",
            "api repos/{owner}/{repo}/issues/843/comments -f body=text",
            "api repos/{owner}/{repo}/issues/843/comments --field body=text",
            "api -X POST repos/{owner}/{repo}/issues/843/comments",
            "api --method PATCH repos/{owner}/{repo}/pulls/843",
            "api repos/{owner}/{repo}/pulls/843 --input body.json",
        ],
    )
    def test_cr_c8_the_check_every_case_runs_refuses_a_call_that_writes(self, call: str):
        assert not is_read(call)

    def test_cr_c8_a_case_that_made_a_write_would_fail_as_it_ends(self, shim_dir: Path, tmp_path: Path):
        shim(shim_dir, tmp_path, "gh", {"pr comment 843 --body text": {"stdout": ""}})
        subprocess.run(["gh", "pr", "comment", "843", "--body", "text"], check=True)
        logged = calls(tmp_path, "gh")
        assert logged == ["pr comment 843 --body text"]
        assert not all(is_read(call) for call in logged)
        # The log is cleared so that this case, which wrote on purpose, ends clean.
        (tmp_path / "calls.log").unlink()

    def test_cr_c8_discovered_never_calls_gh(self, shim_dir: Path, tmp_path: Path):
        shim(shim_dir, tmp_path, "work", found_from(*FOUND))
        shim(shim_dir, tmp_path, "gh", {})
        filled("discovered", written(tmp_path, discovering(["None."])))
        assert calls(tmp_path, "gh") == []


class TestGeneratorCommandLine:
    @pytest.mark.parametrize("generator", ["context", "discovered"])
    def test_a_record_that_cannot_be_read_exits_2_and_makes_no_call(self, generator: str, shim_dir: Path, tmp_path: Path):
        shim(shim_dir, tmp_path, "work", {})
        proc = run(generator, tmp_path / "absent.json")
        assert proc.returncode == 2
        assert "cannot read" in proc.stderr
        assert calls(tmp_path, "work") == []

    @pytest.mark.parametrize("generator", ["context", "discovered"])
    def test_a_record_that_does_not_fit_the_schema_is_refused_before_any_call(
        self, generator: str, shim_dir: Path, tmp_path: Path
    ):
        shim(shim_dir, tmp_path, "work", {})
        record = copy.deepcopy(EXAMPLE)
        del record["work_item"]["id"]
        proc = unchanged_by(generator, written(tmp_path, record))
        assert proc.returncode == 2
        assert "/work_item/id" in proc.stderr
        assert calls(tmp_path, "work") == []

    @pytest.mark.parametrize("argv", [("context",), ("discovered",), ("context", "a.json", "b.json")])
    def test_a_call_the_parser_cannot_read_exits_2(self, argv: tuple[str, ...]):
        proc = subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, check=False)
        assert proc.returncode == 2
        assert "usage:" in proc.stderr

    @pytest.mark.parametrize("generator", ["context", "discovered"])
    def test_a_run_says_whether_it_wrote_the_record(self, generator: str, shim_dir: Path, tmp_path: Path):
        family_shims(shim_dir, tmp_path)
        path = written(tmp_path, copy.deepcopy(EXAMPLE))
        first, second = run(generator, path), run(generator, path)
        assert (first.returncode, first.stdout) == (0, f"wrote {path}\n")
        assert (second.returncode, second.stdout) == (0, f"{path} is already current\n")

    def test_a_record_file_that_cannot_be_replaced_exits_2_and_keeps_its_content(self, shim_dir: Path, tmp_path: Path):
        family_shims(shim_dir, tmp_path)
        locked = tmp_path / "locked"
        locked.mkdir()
        path = written(locked, copy.deepcopy(EXAMPLE))
        before = path.read_bytes()
        locked.chmod(0o555)
        try:
            proc = run("context", path)
        finally:
            locked.chmod(0o755)
        assert proc.returncode == 2
        assert "cannot write" in proc.stderr
        assert path.read_bytes() == before


# Marks of this repository that text shipped to other projects cannot carry:
# its tracker's prefix, its criterion ids, a numbered section and a path to its specs.
HOUSE_MARKS = re.compile(r"agents-config|9k9|\bCR-[A-Z]+\d|[Ss]ection \d|docs/specs")


class TestDeployedText:
    @pytest.mark.parametrize(
        "name", ["SKILL.md", "references/commands.md", "references/generators.md", "scripts/change_record.py"]
    )
    def test_the_shipped_text_names_both_generators_and_carries_no_mark_of_this_repository(self, name: str):
        text = (SKILL / name).read_text(encoding="utf-8")
        assert "context" in text and "discovered" in text
        assert HOUSE_MARKS.findall(text) == []

    def test_the_skill_body_has_an_entry_for_each_generator_and_points_at_both_references(self):
        body = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        entries = [line for line in body.splitlines() if line.startswith("- `")]
        for generator in ("context", "discovered"):
            assert f"uv run scripts/change_record.py {generator} record.json" in body
            assert len([entry for entry in entries if entry.startswith(f"- `{generator}` ")]) == 1
        assert "references/commands.md" in body and "references/generators.md" in body
        assert "Nothing in this skill fills" not in body

    def test_the_commands_reference_gives_both_command_lines_where_to_run_them_and_the_exit_statuses(self):
        text = (SKILL / "references" / "commands.md").read_text(encoding="utf-8")
        section = text[text.index("## `context` and `discovered`"):].split("\n## ")[0]
        for generator in ("context", "discovered"):
            assert f"scripts/change_record.py {generator} record.json" in section
        assert "working directory" in section
        assert "Exit 0 the record holds the part, 2 anything failed." in section
        assert "generators.md" in section

    def test_the_generators_reference_leaves_the_command_lines_to_the_commands_reference(self):
        text = (SKILL / "references" / "generators.md").read_text(encoding="utf-8")
        assert "commands.md" in text
        assert "uv run" not in text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
