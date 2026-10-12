#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4", "pytest>=8"]
# ///
"""Tests for the generator that fills a change record's review campaign from a pull request's review verdicts.

Run: uv run change_record_campaign_test.py
"""

from __future__ import annotations

# The fence goes up when conftest is imported. This import comes first, so the
# fence also holds while this file runs as a script, before pytest starts.
import conftest  # noqa: F401

# isort: split

import copy
import inspect
import itertools
import json
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, NamedTuple

import pytest

import change_record

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SCRIPT = HERE / "change_record.py"
EXAMPLE = json.loads((SKILL / "examples" / "pr-843.json").read_text(encoding="utf-8"))

# What `gh api` printed for pull request 843 of the repository this skill was
# written in: the pull request, its reviews and its review comments. Each entry
# keeps the fields a reader of the listing uses and its author's login, id and
# type. The link fields, the node ids, the reactions and the diff hunks are left
# out, because they are most of the bytes and nothing reads them.
RECORDED = SKILL / "evals" / "pr-843"
PULL = json.loads((RECORDED / "pull.json").read_text(encoding="utf-8"))
REVIEWS = json.loads((RECORDED / "reviews.json").read_text(encoding="utf-8"))
COMMENTS = json.loads((RECORDED / "comments.json").read_text(encoding="utf-8"))

APP = "pr-hater[bot]"
AUTHOR = PULL["user"]["login"]

# The recorded reviews in the order GitHub lists them: the eight that carry a
# verdict, then the fifteen empty ones that hold the author's thread replies,
# then the reviewing App's approval, which carries no verdict.
VERDICT_REVIEWS = REVIEWS[:8]
OTHER_REVIEWS = REVIEWS[8:]

# The reviewer rows the recorded reviews give: reviewer, rounds, findings, fixed, rejected, deferred.
# No verdict gives a disposition to the three findings of the claim that was restated,
# so three rows count a finding that is in none of the last three columns.
ROWS_843 = [
    ("correctness", "1 to 4", 3, 3, 0, 0),
    ("security", "1 to 4", 1, 0, 0, 0),
    ("test-adequacy", "1 to 3", 4, 3, 0, 0),
    ("simplification-efficiency", "1 to 2", 1, 1, 0, 0),
    ("documentation-quality", "1 to 3", 7, 6, 0, 0),
    ("internal-consistency", "1 to 3", 2, 2, 0, 0),
    ("global-consistency", "1 to 3", 4, 2, 0, 2),
    ("standalone-read", "1 to 2", 2, 2, 0, 0),
]

SHA = "0123456789abcdef0123456789abcdef01234567"
REAL_ENTRY = "The gates ran on one machine only."
NO_ROUND = "campaign: No review round has run on this pull request."

# The only calls `campaign` makes: the pull request, then a page of its reviews or of its review comments.
READ = re.compile(r"api repos/\{owner\}/\{repo\}/pulls/\d+(?:/(?:reviews|comments)\?per_page=100&page=\d+)?")

_review_ids = itertools.count(7000)
_comment_ids = itertools.count(8000)


def other_than_reads(calls: Iterable[str]) -> list[str]:
    """Return each logged call that is not one of the reads ``campaign`` makes."""
    return [call for call in calls if not READ.fullmatch(call)]


def example() -> dict[str, Any]:
    return copy.deepcopy(EXAMPLE)


def rows(record: dict[str, Any]) -> list[tuple[Any, ...]]:
    """Return the record's reviewer rows as tuples, in the order of ``ROWS_843``."""
    names = ("reviewer", "rounds", "findings", "fixed", "rejected", "deferred")
    return [tuple(row[name] for name in names) for row in record["campaign"]["reviewers"]]


def found(record: dict[str, Any], finding_id: str, claim: str | None = None, kind: str | None = None) -> dict[str, Any]:
    """Return the one campaign finding with this id, and with this claim and class when they are given."""
    matches = [
        entry for entry in record["campaign"]["findings"]
        if entry["id"] == finding_id
        and claim in (None, entry["claim_id"])
        and kind in (None, entry["artifact_class"])
    ]
    assert len(matches) == 1, matches
    return matches[0]


def body_of(text: str) -> str:
    """Return a review body that carries ``text`` the way the reviewing App posts a verdict.

    The fence is one backtick longer than the longest run in the text, so no
    line of the text closes it.
    """
    fence = "`" * max(3, max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
    return (
        "## Review verdict\n\nHead 01234567.\n\n"
        f"<details>\n<summary>Verdict envelope</summary>\n\n{fence}json\n{text}\n{fence}\n\n</details>"
    )


def envelope_of(review: dict[str, Any]) -> dict[str, Any]:
    """Return the verdict a posted review carries, read apart from the script under test."""
    block = re.search(r"\n(`{3,})json\n(.*)\n\1\n", review["body"], re.DOTALL)
    assert block, review["id"]
    return json.loads(block.group(2))


def review(
    envelope: dict[str, Any] | str, *, login: str = APP, kind: str = "Bot", state: str = "COMMENTED"
) -> dict[str, Any]:
    """Return a review as GitHub lists it, carrying ``envelope`` as its verdict."""
    text = envelope if isinstance(envelope, str) else json.dumps(envelope, indent=2)
    return {
        "id": next(_review_ids),
        "user": {"login": login, "id": 1, "type": kind},
        "body": body_of(text),
        "state": state,
        "commit_id": SHA,
        "submitted_at": "2026-01-01T00:00:00Z",
    }


def reposted(
    recorded: dict[str, Any], change: Callable[[dict[str, Any]], Any] | None = None, **fields: Any
) -> dict[str, Any]:
    """Return a copy of a recorded review with its verdict edited by ``change`` and its own fields replaced."""
    posted = copy.deepcopy(recorded)
    if change is not None:
        envelope = envelope_of(posted)
        change(envelope)
        posted["body"] = body_of(json.dumps(envelope, indent=2))
    return {**posted, **fields}


def finding(
    finding_id: str, lens: str = "correctness", claim: str = "The gate lets a bad value through.",
    kind: str = "mechanical",
) -> dict[str, Any]:
    return {
        "id": finding_id, "lens": lens, "type": kind, "ac": "the gate refuses a bad value", "claim": claim,
        "evidence": "tests/test_gate.py::test_a_bad_value fails at this head.",
    }


def prior(
    finding_id: str, disposition: str, evidence: str = "The test fails without the change and passes with it.",
    **more: Any,
) -> dict[str, Any]:
    return {"round": 1, "id": finding_id, "disposition": disposition, "evidence": evidence, **more}


def verdict(
    number: int = 1, *, claim: str = "claim-a", kind: str = "typed-code", lenses: Iterable[str] = ("correctness",),
    findings: Iterable[dict[str, Any]] = (), priors: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Return a review verdict that the verdict schema accepts."""
    findings = list(findings)
    raising = {entry["lens"] for entry in findings}
    return {
        "schema_version": "3",
        "artifact_class": kind,
        "round": number,
        "base_sha": "f" * 40,
        "head_sha": SHA,
        "claim_id": claim,
        "retained_categories": [],
        "staffing_record": {"digest": "sha256:" + "0" * 64},
        "lenses": [
            {
                "lens": name, "verdict": "findings" if name in raising else "clean",
                "vendor": "a vendor", "transport": "a route", "model": "a model",
            }
            for name in lenses
        ],
        "prior_dispositions": list(priors),
        "verdict": "findings" if findings else "clean",
        "findings": findings,
    }


def thread(posted: dict[str, Any], raised: dict[str, Any]) -> dict[str, Any]:
    """Return the inline comment the reviewing App posts for a finding of the review ``posted``."""
    record = json.dumps(raised, indent=2)
    return {
        "id": next(_comment_ids),
        "pull_request_review_id": posted["id"],
        "user": posted["user"],
        "body": (
            f"**{raised['lens']}** (mechanical)\n\n{raised['claim']}\n\n"
            f"<details>\n<summary>Finding record</summary>\n\n```json\n{record}\n```\n\n</details>"
        ),
    }


def reply(to: dict[str, Any], body: str, login: str = AUTHOR) -> dict[str, Any]:
    """Return a reply on the thread that the inline comment ``to`` opened."""
    return {
        "id": next(_comment_ids),
        "pull_request_review_id": next(_review_ids),
        "in_reply_to_id": to["id"],
        "user": {"login": login, "id": 2, "type": "User"},
        "body": body,
    }


def split(entries: list[Any], pages: int) -> list[list[Any]]:
    """Split ``entries`` into ``pages`` pages of three entries each, with the rest on the last page.

    Short early pages put a verdict on every page of the recorded reviews, so
    a reader that stops early or skips a page loses rounds.
    """
    if pages == 1:
        return [entries] if entries else []
    cuts = [3 * index for index in range(pages)] + [len(entries)]
    return [entries[start:end] for start, end in itertools.pairwise(cuts)]


def paged(endpoint: str, pages: list[list[Any]]) -> dict[str, Any]:
    """Return the answers to a listing read a page at a time: each page, then an empty one."""
    return {f"api {endpoint}?per_page=100&page={number}": page for number, page in enumerate([*pages, []], 1)}


class Raw(str):
    """An answer the shim prints as it is written, where every other answer is written as JSON."""


class Ran(NamedTuple):
    code: int
    out: str
    err: str


class Pull:
    """A pull request served through a ``gh`` shim, and the record ``campaign`` is run over."""

    def __init__(self, shim_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        self.shim_dir = shim_dir
        self.tmp_path = tmp_path
        self.capsys = capsys
        self.path = tmp_path / "record.json"
        self.log = tmp_path / "no-shim.log"
        self.served = 0

    def serve(
        self, reviews: list[Any], comments: list[Any] | None = None, *, pages: int = 1, comment_pages: int = 1,
        issue_comments: list[Any] | None = None, fail_on: int | None = None, number: int = 843,
        spoiled: dict[str, Callable[[Any], Any]] | None = None,
    ) -> None:
        """Put a ``gh`` on the search path that answers for the pull request and logs each call.

        The shim answers the pull request, each page of its reviews and of its
        review comments, and each page of its issue comments. It exits 1 on
        any other call, and on call number ``fail_on``. ``spoiled`` names a
        call and gives what changes that call's answer.
        """
        self.served += 1
        state = self.tmp_path / f"gh-{self.served}"
        state.mkdir()
        self.log = state / "calls.log"
        base = f"repos/{{owner}}/{{repo}}/pulls/{number}"
        answers = {f"api {base}": {**PULL, "number": number}}
        answers |= paged(f"{base}/reviews", split(reviews, pages))
        answers |= paged(f"{base}/comments", split(comments or [], comment_pages))
        answers |= paged(f"repos/{{owner}}/{{repo}}/issues/{number}/comments", split(issue_comments or [], 1))
        for call, change in (spoiled or {}).items():
            answers[call] = change(answers[call])
        cases = []
        for index, (call, answer) in enumerate(answers.items()):
            file = state / f"answer-{index}.json"
            file.write_text(answer if isinstance(answer, Raw) else json.dumps(answer), encoding="utf-8")
            cases.append(f"  {shlex.quote(call)}) /bin/cat {shlex.quote(str(file))} ;;\n")
        log = shlex.quote(str(self.log))
        shim = self.shim_dir / "gh"
        shim.write_text(
            f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {log}\n"
            f"calls=0\nwhile read -r _; do calls=$((calls + 1)); done < {log}\n"
            f'if [ "$calls" -eq {fail_on or 0} ]; then echo "HTTP 502: the shim fails this call" >&2; exit 1; fi\n'
            'case "$*" in\n' + "".join(cases)
            + '  *) echo "the shim has no answer for: $*" >&2; exit 1 ;;\nesac\n',
            encoding="utf-8",
        )
        shim.chmod(0o755)

    def write(self, record: dict[str, Any]) -> bytes:
        """Write ``record`` in the layout the script writes, and return the file's bytes."""
        self.path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return self.path.read_bytes()

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def run(self, *argv: str, pr: int | None = 843) -> Ran:
        """Run ``campaign`` over the record, and check that every call the shim logged is a read.

        Every case runs the command through here, so no case passes with a
        call in the log that is anything but one of the command's own reads.
        """
        number = [] if pr is None else ["--pr", str(pr)]
        code = change_record.main(["campaign", *number, *argv, str(self.path)])
        out, err = self.capsys.readouterr()
        assert other_than_reads(self.calls()) == []
        return Ran(code, out, err)

    def record(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def filled(
        self, reviews: list[Any], comments: list[Any] | None = None, record: dict[str, Any] | None = None, *argv: str
    ) -> dict[str, Any]:
        """Serve the pull request, run ``campaign`` over ``record``, and return the record it wrote."""
        self.serve(reviews, comments)
        self.write(example() if record is None else record)
        ran = self.run(*argv)
        assert ran.code == 0, ran.err
        return self.record()


@pytest.fixture
def pull(shim_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Pull:
    return Pull(shim_dir, tmp_path, capsys)


def with_heads_up(*entries: str) -> dict[str, Any]:
    record = example()
    record["heads_up"] = list(entries)
    return record


def unreadable(count: int) -> list[dict[str, Any]]:
    """Return ``count`` reviews by the reviewing App whose verdicts the verdict validator rejects."""
    posted = []
    for number in range(1, count + 1):
        envelope = verdict(number)
        del envelope["verdict"]
        posted.append(review(envelope))
    return posted


def empty_campaign() -> dict[str, Any]:
    part = {"reviewers": [], "terminal_sha": "", "findings": []}
    return {**part, "digest": change_record.stamp(part)}


class TestCrC1ReviewersAndPages:
    def test_cr_c1_the_recorded_reviews_split_across_three_pages_give_the_expected_reviewer_rows(self, pull: Pull):
        pull.serve(REVIEWS, COMMENTS, pages=3, comment_pages=2)
        pull.write(example())
        ran = pull.run()
        assert (ran.code, ran.err) == (0, "")
        assert rows(pull.record()) == ROWS_843

    def test_cr_c1_each_listing_is_read_a_page_at_a_time_until_a_page_comes_back_empty(self, pull: Pull):
        pull.serve(REVIEWS, COMMENTS, pages=3, comment_pages=2)
        pull.write(example())
        assert pull.run().code == 0
        base = "api repos/{owner}/{repo}/pulls/843"
        assert pull.calls() == [
            base,
            *(f"{base}/reviews?per_page=100&page={page}" for page in (1, 2, 3, 4)),
            *(f"{base}/comments?per_page=100&page={page}" for page in (1, 2, 3)),
        ]

    def test_cr_c1_a_verdict_alone_on_the_third_page_is_counted(self, pull: Pull):
        late = review(verdict(lenses=["late-reviewer"]))
        pull.serve([*OTHER_REVIEWS[:6], late], pages=3)
        pull.write(example())
        assert pull.run().code == 0
        assert rows(pull.record()) == [("late-reviewer", "1", 0, 0, 0, 0)]

    def test_cr_c1_an_envelope_shaped_issue_comment_is_not_read(self, pull: Pull):
        ghost = review(verdict(lenses=["ghost"], findings=[finding("ghost.r1.f1", "ghost")]))
        pull.serve(REVIEWS, COMMENTS, pages=3, issue_comments=[ghost])
        pull.write(example())
        assert pull.run().code == 0
        assert rows(pull.record()) == ROWS_843
        assert not [call for call in pull.calls() if "issues" in call]

    def test_cr_c1_a_review_that_carries_no_verdict_is_passed_over_without_a_word(self, pull: Pull):
        # The author's thread replies are listed as reviews with an empty body.
        # The App's approval carries no verdict.
        assert [entry["user"]["type"] for entry in OTHER_REVIEWS].count("Bot") == 1
        pull.serve([*OTHER_REVIEWS, review(verdict())])
        pull.write(example())
        ran = pull.run()
        assert (ran.code, ran.err) == (0, "")
        assert rows(pull.record()) == [("correctness", "1", 0, 0, 0, 0)]

    def test_cr_c1_a_row_counts_each_finding_once_under_the_column_of_its_disposition(self, pull: Pull):
        names = ["f1", "f2", "f3", "f4", "f5"]
        record = pull.filled([
            review(verdict(1, findings=[finding(name) for name in names])),
            # A later verdict that lists a finding again does not make a second finding of it.
            review(verdict(2, findings=[finding("f5")], priors=[
                prior("f1", "fixed"),
                prior("f2", "rebutted"),
                prior("f3", "advisory-deferred"),
                prior("f4", "transferred", work_item="proj-a1b.3"),
            ])),
        ])
        assert rows(record) == [("correctness", "1 to 2", 5, 1, 1, 2)]
        assert found(record, "f5")["round"] == 1

    def test_cr_c1_findings_are_told_apart_by_claim_and_class_as_well_as_by_id(self, pull: Pull):
        record = pull.filled([
            review(verdict(claim="claim-a", findings=[finding("f1")])),
            review(verdict(claim="claim-b", findings=[finding("f1")])),
            review(verdict(claim="claim-a", kind="prose", findings=[finding("f1")])),
        ])
        assert rows(record) == [("correctness", "1", 3, 0, 0, 0)]

    def test_cr_c1_rounds_run_from_the_lowest_to_the_highest_across_every_claim_and_class(self, pull: Pull):
        record = pull.filled([
            review(verdict(2, lenses=["correctness", "security"])),
            review(verdict(4, lenses=["correctness"])),
            review(verdict(1, claim="claim-b", lenses=["correctness"])),
            review(verdict(3, kind="prose", lenses=["standalone-read"], findings=[finding("f1", "standalone-read")])),
        ])
        assert rows(record) == [
            ("correctness", "1 to 4", 0, 0, 0, 0), ("security", "2", 0, 0, 0, 0), ("standalone-read", "3", 1, 0, 0, 0),
        ]

    def test_cr_c1_a_reviewer_named_only_by_a_finding_still_gets_a_row(self, pull: Pull):
        record = pull.filled([review(verdict(lenses=["correctness"], findings=[finding("f1", "security")]))])
        assert rows(record) == [("correctness", "1", 0, 0, 0, 0), ("security", "1", 1, 0, 0, 0)]


class TestCrC2Findings:
    def test_cr_c2_the_recorded_reviews_give_one_entry_per_distinct_finding(self, pull: Pull):
        record = pull.filled(REVIEWS, COMMENTS)
        listed = record["campaign"]["findings"]
        names = [(entry["claim_id"], entry["artifact_class"], entry["id"]) for entry in listed]
        assert len(names) == len(set(names)) == 24
        assert sorted({(claim, kind) for claim, kind, _ in names}) == [
            ("9k9.408", "typed-code"), ("9k9.408-r2", "prose"), ("9k9.408-r2", "typed-code"),
        ]
        raised = [envelope_of(posted) for posted in VERDICT_REVIEWS]
        assert names == [
            (envelope["claim_id"], envelope["artifact_class"], entry["id"])
            for envelope in raised for entry in envelope["findings"]
        ]

    def test_cr_c2_an_entry_holds_its_claim_class_first_round_id_claim_disposition_reason_and_commit(self, pull: Pull):
        record = pull.filled(REVIEWS, COMMENTS)
        entry = found(record, "correctness.r2.f1")
        raised = next(item for item in envelope_of(REVIEWS[2])["findings"] if item["id"] == "correctness.r2.f1")
        # The fourth typed-code round is the last verdict that carries this finding's disposition forward.
        carried = envelope_of(REVIEWS[4])["prior_dispositions"]
        settled = next(item for item in carried if item["id"] == "correctness.r2.f1")
        assert entry == {
            "claim_id": "9k9.408-r2", "artifact_class": "typed-code", "round": 2, "id": "correctness.r2.f1",
            "claim": raised["claim"], "disposition": "fixed", "reason": settled["evidence"], "commit": "56130d01",
        }

    def test_cr_c2_a_finding_no_verdict_gives_a_disposition_to_has_none(self, pull: Pull):
        record = pull.filled(REVIEWS, COMMENTS)
        entry = found(record, "security.r1.f1", "9k9.408")
        assert list(entry) == ["claim_id", "artifact_class", "round", "id", "claim", "commit"]

    def test_cr_c2_a_rebutted_finding_carries_the_evidence_given_with_it_as_its_reason(self, pull: Pull):
        evidence = "The path is refused two lines above, as the refusal test at this head shows."

        def rebut(envelope: dict[str, Any]) -> None:
            entry = next(item for item in envelope["prior_dispositions"] if item["id"] == "global-consistency.r1.f2")
            entry.update(disposition="rebutted", evidence=evidence)

        record = pull.filled([*REVIEWS[:7], reposted(REVIEWS[7], rebut), *REVIEWS[8:]], COMMENTS)
        entry = found(record, "global-consistency.r1.f2")
        assert (entry["disposition"], entry["reason"]) == ("rebutted", evidence)
        assert ("global-consistency", "1 to 3", 4, 2, 1, 1) in rows(record)

    def test_cr_c2_a_claim_that_quotes_a_fenced_block_is_written_inert_and_lints_clean(self, pull: Pull):
        quoted = 'The reply quotes its verdict whole:\n\n```json\n{"verdict": "clean"}\n```\n\nIt should link to it.'
        evidence = "The body opens <details><summary>raw</summary> and then <!-- hidden --> closes nothing."

        def quote(envelope: dict[str, Any]) -> None:
            next(item for item in envelope["findings"] if item["id"] == "correctness.r1.f1")["claim"] = quoted

        def cite(envelope: dict[str, Any]) -> None:
            carried = envelope["prior_dispositions"]
            next(item for item in carried if item["id"] == "correctness.r1.f1")["evidence"] = evidence

        # The first round of the finding's claim raises it, and the fourth round is the last to carry its disposition.
        posted = [REVIEWS[0], reposted(REVIEWS[1], quote), *REVIEWS[2:4], reposted(REVIEWS[4], cite), *REVIEWS[5:]]
        record = pull.filled(posted, COMMENTS)
        entry = found(record, "correctness.r1.f1", "9k9.408-r2")
        assert entry["claim"] == (
            "The reply quotes its verdict whole:\n\n```` ```json ````\n"
            '{"verdict": "clean"}\n```\n\nIt should link to it.'
        )
        assert entry["reason"] == (
            "The body opens `<details>`<summary>raw</summary> and then `<!-- hidden -->` closes nothing."
        )
        assert change_record.lint_record(record) == []
        # The same text, left as the verdict wrote it, is what the lint refuses.
        entry["claim"], entry["reason"] = quoted, evidence
        record["campaign"]["digest"] = change_record.stamp(
            {name: value for name, value in record["campaign"].items() if name != "digest"}
        )
        refused = [(error["code"], error["path"]) for error in change_record.lint_record(record)]
        assert refused.count(("machine-content", "/campaign/findings/3/claim")) == 1
        assert refused.count(("machine-content", "/campaign/findings/3/reason")) == 2

    def test_cr_c2_a_reply_that_names_a_commit_gives_it_and_a_reply_that_names_none_gives_none(self, pull: Pull):
        record = pull.filled(REVIEWS, COMMENTS)
        # The author replied on both threads. Only the first reply says "Commit 75bb090c."
        assert found(record, "correctness.r1.f1")["commit"] == "75bb090c"
        assert found(record, "test-adequacy.r1.f1", "9k9.408")["commit"] == ""
        # The reviewing App posted this finding in its verdict alone, so it has no thread and no reply.
        assert found(record, "standalone-read.r1.f1")["commit"] == ""
        assert sum(1 for entry in record["campaign"]["findings"] if entry["commit"]) == 14

    def test_cr_c2_three_verdicts_that_share_a_finding_id_give_three_entries(self, pull: Pull):
        record = pull.filled([
            review(verdict(claim="claim-a", findings=[finding("correctness.r1.f1", claim="The first.")])),
            review(verdict(claim="claim-b", findings=[finding("correctness.r1.f1", claim="The second.")])),
            review(verdict(claim="claim-a", kind="prose", findings=[finding("correctness.r1.f1", claim="The third.")])),
        ])
        names = ("claim_id", "artifact_class", "id", "claim")
        assert [tuple(entry[name] for name in names) for entry in record["campaign"]["findings"]] == [
            ("claim-a", "typed-code", "correctness.r1.f1", "The first."),
            ("claim-b", "typed-code", "correctness.r1.f1", "The second."),
            ("claim-a", "prose", "correctness.r1.f1", "The third."),
        ]

    def test_cr_c2_a_disposition_reaches_only_the_finding_of_its_own_claim_and_class(self, pull: Pull):
        record = pull.filled([
            review(verdict(claim="claim-a", findings=[finding("f1")])),
            review(verdict(claim="claim-b", findings=[finding("f1")])),
            review(verdict(2, claim="claim-b", priors=[prior("f1", "fixed")])),
        ])
        assert "disposition" not in found(record, "f1", "claim-a")
        assert found(record, "f1", "claim-b")["disposition"] == "fixed"

    def test_cr_c2_the_latest_disposition_of_a_finding_is_the_one_written(self, pull: Pull):
        record = pull.filled([
            review(verdict(1, findings=[finding("f1")])),
            review(verdict(2, priors=[prior("f1", "transferred", "It predates the change.", work_item="proj-a1b.3")])),
            review(verdict(3, priors=[prior("f1", "fixed", "The test passes now.")])),
        ])
        assert found(record, "f1") == {
            "claim_id": "claim-a", "artifact_class": "typed-code", "round": 1, "id": "f1",
            "claim": "The gate lets a bad value through.", "disposition": "fixed", "reason": "The test passes now.",
            "commit": "",
        }

    def test_cr_c2_a_deferred_finding_carries_the_item_it_went_to(self, pull: Pull):
        record = pull.filled([
            review(verdict(1, findings=[finding("f1")])),
            review(verdict(2, priors=[prior("f1", "transferred", "It predates the change.", work_item="proj-a1b.3")])),
        ])
        assert list(found(record, "f1"))[5:] == ["disposition", "reason", "work_item", "commit"]
        assert found(record, "f1")["work_item"] == "proj-a1b.3"

    @pytest.mark.parametrize(("body", "commit"), [
        ("**fixed** (round 1). It is refused now. Commit 0a1b2c3d.\n\nThe campaign ended at 5bc9e856.", "0a1b2c3d"),
        (f"Fixed in commit `{SHA}`, after 5bc9e856.", SHA),
        ("Fixed. Commits 0a1b2c3d and 5bc9e856 carry it.", "0a1b2c3d"),
        ("Outcome: Fixed.\nChange: The gate refuses it now. (0a1b2c3d)\nVerification: The test passes.", "0a1b2c3d"),
        ("Outcome: Fixed.\nChange: It is refused. (0a1b2c3d)\nVerification: The test of commit 5bc9e856 passes.", "0a1b2c3d"),
        ("Outcome: Fixed.\nChange: The gate refuses the value now.\nVerification: The test passes at 5bc9e856.", ""),
        ("The value was committed 0a1b2c3d times, and the gate at 5bc9e856 is unchanged.", ""),
        ("No commit was needed. The campaign ended at 5bc9e856.", ""),
    ])
    def test_cr_c2_the_commit_is_the_one_that_closes_the_change_line_or_follows_the_word_commit(
        self, body: str, commit: str, pull: Pull
    ):
        raised = finding("f1")
        posted = review(verdict(findings=[raised]))
        opened = thread(posted, raised)
        record = pull.filled([posted], [opened, reply(opened, body)])
        assert found(record, "f1")["commit"] == commit

    def test_cr_c2_only_the_authors_reply_on_the_findings_own_thread_names_the_commit(self, pull: Pull):
        first, second = finding("f1"), finding("f2")
        posted = review(verdict(findings=[first, second]))
        opened, other = thread(posted, first), thread(posted, second)
        record = pull.filled([posted], [
            opened, other,
            reply(opened, "I would look at commit 1111111 again.", login="a-reviewer"),
            reply(other, "Fixed. Commit 2222222."),
        ])
        assert (found(record, "f1")["commit"], found(record, "f2")["commit"]) == ("", "2222222")

    def test_cr_c2_the_authors_latest_reply_that_names_a_commit_decides(self, pull: Pull):
        raised = finding("f1")
        posted = review(verdict(findings=[raised]))
        opened = thread(posted, raised)
        record = pull.filled([posted], [
            opened,
            reply(opened, "Fixed. Commit 1111111."),
            reply(opened, "The first fix was wrong. Commit 2222222 replaces it."),
            reply(opened, "Yes, the test at 5bc9e856 covers it."),
        ])
        assert found(record, "f1")["commit"] == "2222222"

    def test_cr_c2_no_reply_is_the_authors_when_the_pull_request_has_no_author(self, pull: Pull):
        # The pull request's author is gone, and so is the account that replied. Two missing accounts are not one.
        raised = finding("f1")
        posted = review(verdict(findings=[raised]))
        opened = thread(posted, raised)
        orphan = reply(opened, "Fixed. Commit 2222222.") | {"user": None}
        pull.serve([posted], [opened, orphan], spoiled={PULL_CALL: lambda answer: answer | {"user": None}})
        pull.write(example())
        assert pull.run().code == 0
        assert found(pull.record(), "f1")["commit"] == ""

    @pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
    def test_cr_c2_the_commit_rule_reads_a_reply_alike_whichever_way_its_lines_end(self, ending: str, pull: Pull):
        lines = ["Outcome: Fixed.", "Change: It is fixed. (1111111)", "Verification: Test of commit 2222222 passes."]
        assert change_record.reply_commit(ending.join(lines)) == "1111111"
        assert change_record.reply_commit(ending.join(lines) + ending) == "1111111"
        assert change_record.reply_commit(ending.join([lines[0], "Change: It is fixed.", lines[2]])) == "2222222"
        raised = finding("f1")
        posted = review(verdict(findings=[raised]))
        opened = thread(posted, raised)
        record = pull.filled([posted], [opened, reply(opened, ending.join(lines))])
        assert found(record, "f1")["commit"] == "1111111"

    @pytest.mark.parametrize("record", [
        '{"id": []}', '{"id": 7}', '{"id": {"f": 1}}', '{"id": null}', '{"lens": "correctness"}', "[1, 2]", '"f1"',
        "7", "not json", '{"id": ' + "[" * 1100 + "]" * 1100 + "}", "[" * 100_000 + "]" * 100_000,
        '{"id": "f1", "weight": ' + "9" * 5000 + "}",
    ])
    def test_cr_c2_a_comment_whose_finding_record_gives_no_id_as_text_opens_no_thread(self, record: str, pull: Pull):
        raised = finding("f1")
        posted = review(verdict(findings=[raised]))
        opened = thread(posted, raised)
        odd = thread(posted, raised)
        odd["body"] = (
            f"**correctness**\n\n<details>\n<summary>Finding record</summary>\n\n```json\n{record}\n```\n\n</details>"
        )
        replies = [reply(odd, "Fixed. Commit 1111111."), reply(opened, "Fixed. Commit 2222222.")]
        pull.serve([posted], [opened, odd, *replies])
        pull.write(example())
        ran = pull.run()
        assert (ran.code, ran.err) == (0, "")
        # The odd comment opens no thread, so its reply is nobody's, and the whole thread beside it still counts.
        assert found(pull.record(), "f1")["commit"] == "2222222"

    def test_cr_c2_a_thread_under_a_review_that_was_skipped_names_no_commit(self, pull: Pull):
        raised = finding("f1")
        counted = review(verdict(findings=[raised]))
        skipped = review(verdict(findings=[raised]), kind="User", login="someone")
        opened = thread(skipped, raised)
        record = pull.filled([counted, skipped], [opened, reply(opened, "Fixed. Commit 2222222.")])
        assert found(record, "f1")["commit"] == ""

    def test_cr_c2_a_campaign_built_from_any_text_of_these_pieces_holds_no_machine_content(self):
        # Every text of up to four of these pieces, which between them open and close
        # each construct the lint refuses, inside and outside code spans. Each text
        # stands as a finding's claim and as the evidence of its disposition.
        pieces = ["`", "``", "```", "```json", "~~~json", "~~~", "<details>", "</details>", "<!--", "-->", "\n", " x "]
        texts = ["".join(parts) for length in range(1, 5) for parts in itertools.product(pieces, repeat=length)]
        assert len(texts) == 12 + 12**2 + 12**3 + 12**4
        raised = [finding(f"f{number}", claim=text) for number, text in enumerate(texts)]
        settled = [prior(entry["id"], "rebutted", entry["claim"]) for entry in raised]
        part = change_record.campaign_part([verdict(1, findings=raised), verdict(2, priors=settled)], {})
        assert len(part["findings"]) == len(texts)
        assert list(change_record._machine_content(part)) == []
        # The pieces do hold what the lint refuses when they are left as they are.
        assert len([text for text in texts if change_record.machine_constructs(text)]) > 10000


class TestCrC3EmptyCampaign:
    @pytest.mark.parametrize(("heads_up", "left"), [(["None."], []), ([REAL_ENTRY], [REAL_ENTRY])])
    def test_cr_c3_a_pull_request_with_no_envelope_bearing_review_gets_the_no_round_row(
        self, heads_up: list[str], left: list[str], pull: Pull
    ):
        pull.serve(OTHER_REVIEWS, COMMENTS)
        pull.write(with_heads_up(*heads_up))
        ran = pull.run()
        assert (ran.code, ran.err) == (0, "")
        record = pull.record()
        assert record["campaign"] == empty_campaign()
        assert record["heads_up"] == [*left, NO_ROUND]
        assert record["heads_up"][-1].startswith("campaign: ")
        assert change_record.lint_record(record) == []

    @pytest.mark.parametrize(("heads_up", "left"), [(["None."], []), ([REAL_ENTRY], [REAL_ENTRY])])
    def test_cr_c3_a_pull_request_whose_every_envelope_is_rejected_gets_a_row_with_their_count(
        self, heads_up: list[str], left: list[str], pull: Pull
    ):
        pull.serve([*unreadable(2), *OTHER_REVIEWS])
        pull.write(with_heads_up(*heads_up))
        ran = pull.run()
        assert ran.code == 0
        record = pull.record()
        assert record["campaign"] == empty_campaign()
        row = "campaign: 2 reviews carry verdicts that could not be read, so no review round is counted."
        assert record["heads_up"] == [*left, row]
        assert record["heads_up"][-1].startswith("campaign: ")
        assert change_record.lint_record(record) == []

    def test_cr_c3_one_unreadable_envelope_is_counted_as_one_review(self, pull: Pull):
        record = pull.filled(unreadable(1), None, with_heads_up("None."))
        assert record["heads_up"] == [
            "campaign: 1 review carries a verdict that could not be read, so no review round is counted."
        ]

    def test_cr_c3_a_verdict_that_is_not_json_is_an_unreadable_envelope(self, pull: Pull):
        record = pull.filled([review('{"verdict": "clean"'), *unreadable(1)], None, with_heads_up("None."))
        assert record["heads_up"][0].startswith("campaign: 2 reviews ")

    def test_cr_c3_only_the_apps_own_standing_reviews_count_as_unreadable(self, pull: Pull):
        # A review by someone else and a dismissed review are skipped by name.
        # Neither is an envelope that could not be read.
        pull.serve([
            review(verdict(), kind="User", login="someone"),
            review(verdict(), state="DISMISSED"),
            *OTHER_REVIEWS,
        ])
        pull.write(with_heads_up("None."))
        ran = pull.run()
        assert ran.code == 0
        assert pull.record()["heads_up"] == [NO_ROUND]
        assert len(ran.err.splitlines()) == 2

    def test_cr_c3_an_empty_heads_up_gets_the_row_and_no_none_entry(self, pull: Pull):
        record = pull.filled(OTHER_REVIEWS, None, with_heads_up())
        assert record["heads_up"] == [NO_ROUND]


class TestCrC4SkippedReviews:
    def test_cr_c4_a_verdict_with_its_verdict_field_removed_is_skipped_named_and_the_rest_are_counted(self, pull: Pull):
        rejected = reposted(REVIEWS[2], lambda envelope: envelope.pop("verdict"))
        pull.serve([*REVIEWS[:2], rejected, *REVIEWS[3:]], COMMENTS)
        pull.write(example())
        ran = pull.run()
        assert ran.code == 0
        assert [line for line in ran.err.splitlines() if str(REVIEWS[2]["id"]) in line and "skipped" in line]
        assert len(ran.err.splitlines()) == 1
        record = pull.record()
        # Round two of the typed-code circuit raised three findings, and they went with it.
        assert len(record["campaign"]["findings"]) == 21
        assert rows(record) == [
            ("correctness", "1 to 4", 2, 2, 0, 0),
            ("security", "1 to 4", 1, 0, 0, 0),
            ("test-adequacy", "1 to 3", 3, 2, 0, 0),
            ("simplification-efficiency", "1", 1, 1, 0, 0),
            ("documentation-quality", "1 to 3", 6, 5, 0, 0),
            *ROWS_843[5:],
        ]

    def test_cr_c4_a_verdict_posted_under_another_login_is_skipped_named_and_the_rest_are_counted(self, pull: Pull):
        mine = {"login": "someone", "id": 7, "type": "User"}
        pull.serve([reposted(REVIEWS[0], user=mine), *REVIEWS[1:]], COMMENTS)
        pull.write(example())
        ran = pull.run()
        assert ran.code == 0
        assert ran.err.splitlines() == [
            f"campaign: review {REVIEWS[0]['id']} is skipped, because its author, someone, is not the reviewing App"
        ]
        record = pull.record()
        # The claim that was restated had one round, and its three findings went with it.
        assert len(record["campaign"]["findings"]) == 21
        assert sum(row[2] for row in rows(record)) == 21

    def test_cr_c4_app_keeps_a_second_bot_out_and_without_it_any_bot_is_the_reviewing_app(self, pull: Pull):
        intruder = review(verdict(lenses=["intruder"]), login="another[bot]")
        pull.serve([*REVIEWS, intruder], COMMENTS)
        pull.write(example())
        ran = pull.run("--app", APP)
        assert ran.code == 0
        assert ran.err.splitlines() == [
            f"campaign: review {intruder['id']} is skipped, because its author, another[bot], is not the reviewing App"
        ]
        assert rows(pull.record()) == ROWS_843
        ran = pull.run()
        assert (ran.code, ran.err) == (0, "")
        assert rows(pull.record()) == [*ROWS_843, ("intruder", "1", 0, 0, 0, 0)]

    def test_cr_c4_a_dismissed_review_is_skipped_named_and_the_rest_are_counted(self, pull: Pull):
        pull.serve([*REVIEWS[:7], reposted(REVIEWS[7], state="DISMISSED"), *REVIEWS[8:]], COMMENTS)
        pull.write(example())
        ran = pull.run()
        assert ran.code == 0
        why = "its state is DISMISSED, and only a submitted review that stands is a round"
        assert ran.err.splitlines() == [f"campaign: review {REVIEWS[7]['id']} is skipped, because {why}"]
        record = pull.record()
        # The dismissed review was the last prose round, which carried the prose findings' dispositions forward.
        assert len(record["campaign"]["findings"]) == 24
        assert ("internal-consistency", "1 to 2", 2, 2, 0, 0) in rows(record)

    @pytest.mark.parametrize("state", ["PENDING", "A_STATE_NOBODY_KNOWS"])
    def test_cr_c1_a_review_that_was_never_submitted_is_no_round_and_is_named(self, state: str, pull: Pull):
        drafted = review(verdict(findings=[finding("f1")]), state=state)
        pull.serve([drafted])
        pull.write(with_heads_up("None."))
        ran = pull.run()
        assert ran.code == 0
        why = f"its state is {state}, and only a submitted review that stands is a round"
        assert ran.err.splitlines() == [f"campaign: review {drafted['id']} is skipped, because {why}"]
        record = pull.record()
        assert record["campaign"] == empty_campaign()
        # A draft is no envelope that could not be read, so the row is the one for no round at all.
        assert record["heads_up"] == [NO_ROUND]

    @pytest.mark.parametrize("state", ["COMMENTED", "APPROVED", "CHANGES_REQUESTED"])
    def test_cr_c1_a_submitted_review_counts_in_each_state_github_gives_one(self, state: str, pull: Pull):
        pull.serve([review(verdict(findings=[finding("f1")]), state=state)])
        pull.write(example())
        ran = pull.run()
        assert (ran.code, ran.err) == (0, "")
        assert rows(pull.record()) == [("correctness", "1", 1, 0, 0, 0)]

    @pytest.mark.parametrize("depth", [1100, 100_000])
    def test_cr_c4_a_verdict_nested_too_deeply_to_read_is_skipped_named_and_the_rest_are_counted(
        self, depth: int, pull: Pull
    ):
        # The validator rejects a field it does not know. A field this deep stops a reader before the validator sees it.
        text = json.dumps(verdict(findings=[finding("f1")]))[:-1] + ', "unused": ' + "[" * depth + "]" * depth + "}"
        deep = review(text)
        pull.serve([deep, review(verdict(claim="claim-b", findings=[finding("f1")]))])
        pull.write(example())
        ran = pull.run()
        assert ran.code == 0
        assert len(ran.err.splitlines()) == 1
        assert ran.err.startswith(f"campaign: review {deep['id']} is skipped, because its verdict cannot be read: ")
        record = pull.record()
        assert [(entry["claim_id"], entry["id"]) for entry in record["campaign"]["findings"]] == [("claim-b", "f1")]
        pull.serve([deep])
        pull.write(with_heads_up("None."))
        assert pull.run().code == 0
        assert pull.record()["heads_up"][0].startswith("campaign: 1 review carries a verdict that could not be read")

    @pytest.mark.parametrize(("field", "spoil"), [
        ("/claim_id", lambda held: held.update(claim_id="claim-a <!-- identity -->")),
        ("/artifact_class", lambda held: held.update(artifact_class="typed-code <details>")),
        ("/lenses/0/lens", lambda held: held["lenses"][0].update(lens="<!-- correctness")),
        ("/findings/0/id", lambda held: held["findings"][0].update(id="f1\n```json")),
        ("/findings/0/lens", lambda held: held["findings"][0].update(lens="<DETAILS open>")),
        ("/prior_dispositions/0/work_item", lambda held: held["prior_dispositions"][0].update(work_item="<!--a1-->")),
    ])
    def test_cr_c4_a_verdict_whose_identifier_holds_what_the_lint_refuses_is_skipped_named_and_counted(
        self, field: str, spoil: Callable[[dict[str, Any]], Any], pull: Pull
    ):
        held = verdict(2, findings=[finding("f1")], priors=[prior("f0", "transferred", work_item="proj-a1b.3")])
        spoil(held)
        assert change_record.load_verdict_validator()(held) == {"valid": True}
        spoiled = review(held)
        pull.serve([spoiled, review(verdict(claim="claim-b", findings=[finding("f1")]))])
        pull.write(example())
        ran = pull.run()
        assert ran.code == 0
        assert len(ran.err.splitlines()) == 1
        assert ran.err.startswith(f"campaign: review {spoiled['id']} is skipped, because its verdict cannot be read: ")
        assert f"at {field}," in ran.err
        record = pull.record()
        assert [(entry["claim_id"], entry["id"]) for entry in record["campaign"]["findings"]] == [("claim-b", "f1")]
        assert change_record.lint_record(record) == []
        pull.serve([spoiled])
        pull.write(with_heads_up("None."))
        assert pull.run().code == 0
        assert pull.record()["heads_up"][0].startswith("campaign: 1 review carries a verdict that could not be read")

    def test_cr_c4_a_construct_in_text_the_record_does_not_take_leaves_the_verdict_counted(self, pull: Pull):
        # A route's error is quoted in a verdict as the route gave it, and the record takes none of it.
        held = verdict(findings=[finding("f1")])
        held["lenses"][0]["model"] = "a model <!-- as its route named it -->"
        held["findings"][0]["ac"] = "<details> are refused"
        pull.serve([review(held)])
        pull.write(example())
        ran = pull.run()
        assert (ran.code, ran.err) == (0, "")
        assert rows(pull.record()) == [("correctness", "1", 1, 0, 0, 0)]
        assert change_record.lint_record(pull.record()) == []

    def test_cr_c4_a_validator_that_rejects_everything_leaves_the_campaign_empty(
        self, pull: Pull, monkeypatch: pytest.MonkeyPatch
    ):
        def reject(document: Any) -> dict[str, Any]:
            errors = [{"code": "stub", "path": "", "message": "the stub rejects every verdict"}]
            return {"valid": False, "errors": errors}

        monkeypatch.setattr(change_record, "load_verdict_validator", lambda: reject)
        pull.serve(REVIEWS, COMMENTS)
        pull.write(with_heads_up("None."))
        ran = pull.run()
        assert ran.code == 0
        record = pull.record()
        assert record["campaign"] == empty_campaign()
        assert record["heads_up"] == [
            "campaign: 8 reviews carry verdicts that could not be read, so no review round is counted."
        ]
        assert len(ran.err.splitlines()) == 8
        assert "the stub rejects every verdict" in ran.err

    def test_cr_c4_the_validator_is_the_one_the_review_verdict_skill_ships(self):
        validate = change_record.load_verdict_validator()
        assert validate.__name__ == "validate_document"
        assert Path(inspect.getsourcefile(validate)) == SKILL.parent / "review-verdict" / "validate_verdict.py"
        assert validate(verdict()) == {"valid": True}
        assert validate({})["valid"] is False

    def test_cr_c4_without_the_review_verdict_skill_beside_it_campaign_exits_2_and_calls_nothing(
        self, pull: Pull, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setattr(change_record, "VERDICT_SKILL", tmp_path / "review-verdict")
        pull.serve(REVIEWS, COMMENTS)
        before = pull.write(example())
        ran = pull.run()
        assert ran.code == 2
        assert "review-verdict" in ran.err
        assert pull.path.read_bytes() == before
        assert pull.calls() == []


class TestCrC6RerunAndReplies:
    def test_cr_c6_a_second_run_over_unchanged_reviews_leaves_the_record_byte_identical(self, pull: Pull):
        pull.serve(REVIEWS, COMMENTS, pages=3)
        before = pull.write(example())
        assert pull.run().code == 0
        first = pull.path.read_bytes()
        assert first != before
        assert pull.run().code == 0
        assert pull.path.read_bytes() == first

    def test_cr_c6_a_second_run_leaves_a_generated_heads_up_row_byte_identical(self, pull: Pull):
        pull.serve(unreadable(2))
        pull.write(with_heads_up(REAL_ENTRY))
        assert pull.run().code == 0
        first = pull.path.read_bytes()
        assert pull.run().code == 0
        assert pull.path.read_bytes() == first

    def test_cr_c6_a_superseded_reply_survives_for_a_finding_the_envelope_marks_fixed(self, pull: Pull):
        record = example()
        mine = record["replies"][0]
        named = (mine["finding_id"], mine["claim_id"], mine["artifact_class"])
        assert named == ("correctness.r1.f1", "9k9.408-r2", "typed-code")
        mine["outcome"] = "Superseded"
        replies = copy.deepcopy(record["replies"])
        written = pull.filled(REVIEWS, COMMENTS, record)
        assert found(written, "correctness.r1.f1")["disposition"] == "fixed"
        assert written["replies"] == replies

    def test_cr_c6_a_run_changes_the_campaign_and_the_heads_up_and_no_other_group(self, pull: Pull):
        record = with_heads_up("None.")
        del record["campaign"]
        written = pull.filled(OTHER_REVIEWS, None, record)
        assert set(written) == {*record, "campaign"}
        for group in record:
            if group != "heads_up":
                assert written[group] == record[group], group


class TestCrC7StaleRows:
    """The two cases that turn on a readable envelope arriving. The terminal state has no row here."""

    @pytest.mark.parametrize(("heads_up", "restored"), [(["None."], ["None."]), ([REAL_ENTRY], [REAL_ENTRY])])
    def test_cr_c7_the_no_round_row_goes_when_a_readable_envelope_arrives(
        self, heads_up: list[str], restored: list[str], pull: Pull
    ):
        record = pull.filled(OTHER_REVIEWS, None, with_heads_up(*heads_up))
        assert NO_ROUND in record["heads_up"]
        pull.serve([*OTHER_REVIEWS, review(verdict())])
        assert pull.run().code == 0
        record = pull.record()
        assert record["heads_up"] == restored
        assert rows(record) == [("correctness", "1", 0, 0, 0, 0)]

    @pytest.mark.parametrize(("heads_up", "restored"), [(["None."], ["None."]), ([REAL_ENTRY], [REAL_ENTRY])])
    def test_cr_c7_the_unreadable_row_goes_when_a_readable_envelope_arrives(
        self, heads_up: list[str], restored: list[str], pull: Pull
    ):
        rejected = unreadable(2)
        record = pull.filled(rejected, None, with_heads_up(*heads_up))
        assert [entry for entry in record["heads_up"] if entry.startswith("campaign: 2 reviews ")]
        pull.serve([*rejected, review(verdict())])
        ran = pull.run()
        assert ran.code == 0
        # The two that cannot be read are still named. They no longer leave the campaign empty.
        assert len(ran.err.splitlines()) == 2
        record = pull.record()
        assert record["heads_up"] == restored
        assert rows(record) == [("correctness", "1", 0, 0, 0, 0)]

    def test_cr_c7_a_row_whose_count_changed_is_replaced_and_never_joined(self, pull: Pull):
        record = pull.filled(unreadable(1), None, with_heads_up(REAL_ENTRY))
        assert record["heads_up"][1].startswith("campaign: 1 review ")
        pull.serve(unreadable(3))
        assert pull.run().code == 0
        heads_up = pull.record()["heads_up"]
        assert len(heads_up) == 2
        assert heads_up[1].startswith("campaign: 3 reviews ")

    def test_cr_c7_one_row_gives_way_to_the_other_when_the_condition_changes(self, pull: Pull):
        record = pull.filled(OTHER_REVIEWS, None, with_heads_up("None."))
        assert record["heads_up"] == [NO_ROUND]
        pull.serve([*OTHER_REVIEWS, *unreadable(1)])
        assert pull.run().code == 0
        heads_up = pull.record()["heads_up"]
        assert len(heads_up) == 1
        assert heads_up[0].startswith("campaign: 1 review ")


PULL_CALL = "api repos/{owner}/{repo}/pulls/843"
REVIEWS_CALL = f"{PULL_CALL}/reviews?per_page=100&page=1"
COMMENTS_CALL = f"{PULL_CALL}/comments?per_page=100&page=1"


def with_first(**fields: Any) -> Callable[[list[Any]], list[Any]]:
    """Return a change to a page that replaces ``fields`` of its first entry."""
    return lambda page: [page[0] | fields, *page[1:]]


def without_first(field: str) -> Callable[[list[Any]], list[Any]]:
    """Return a change to a page that takes ``field`` out of its first entry."""
    return lambda page: [{name: value for name, value in page[0].items() if name != field}, *page[1:]]


# Answers that do not have the shape their call's answer has, by the call and
# by what is wrong. Each is the recorded answer with one thing changed.
MISSHAPEN: dict[str, dict[str, Callable[[Any], Any]]] = {
    PULL_CALL: {
        "a list where the pull request belongs": lambda answer: [answer],
        "no author field": lambda answer: {name: value for name, value in answer.items() if name != "user"},
        "an author with no login": lambda answer: answer | {"user": {"type": "User"}},
        "a login that is a number": lambda answer: answer | {"user": {"login": 7}},
        "an author that is text": lambda answer: answer | {"user": "someone"},
    },
    REVIEWS_CALL: {
        "an object where the page belongs": lambda page: {"reviews": page},
        "an entry that is text": lambda page: [*page, "a review"],
        "an entry with no id": without_first("id"),
        "an id that is text": with_first(id="5408167652"),
        "an entry with no body field": without_first("body"),
        "a body that is a list": with_first(body=["a verdict"]),
        "an entry with no state": without_first("state"),
        "a state that is a number": with_first(state=1),
        "an entry with no author field": without_first("user"),
        "an author with no type": with_first(user={"login": APP}),
        "an author with no login": with_first(user={"type": "Bot"}),
    },
    COMMENTS_CALL: {
        "an object where the page belongs": lambda page: {"comments": page},
        "an entry with no id": without_first("id"),
        "an entry that does not say which review it belongs to": without_first("pull_request_review_id"),
        "a review id that is text": with_first(pull_request_review_id="5408167652"),
        "a reply id that is text": with_first(in_reply_to_id="4179275912"),
        "an entry with no body": without_first("body"),
        "a body that is null": with_first(body=None),
        "an entry with no author field": without_first("user"),
        "an author with no login": with_first(user={"type": "User"}),
    },
}
MISSHAPEN_CASES = [(call, fault) for call, faults in MISSHAPEN.items() for fault in faults]


class TestAnswerShapes:
    @pytest.mark.parametrize(("call", "fault"), MISSHAPEN_CASES)
    def test_cr_x4_an_answer_of_the_wrong_shape_fails_the_run_naming_its_call_and_leaves_the_record(
        self, call: str, fault: str, pull: Pull, tmp_path: Path
    ):
        pull.serve(REVIEWS, COMMENTS, spoiled={call: MISSHAPEN[call][fault]})
        # The record already holds a campaign, so an answer read as empty would take its rows away.
        before = pull.write(example())
        ran = pull.run()
        assert ran.code == 2
        assert f"`gh {call}` gave an answer that cannot be used" in ran.err
        assert pull.path.read_bytes() == before
        assert [path.name for path in tmp_path.iterdir() if path.is_file()] == ["record.json"]

    def test_each_of_the_three_reads_has_misshapen_answers_here(self):
        assert sorted(MISSHAPEN) == sorted([PULL_CALL, REVIEWS_CALL, COMMENTS_CALL])
        assert all(len(faults) >= 5 for faults in MISSHAPEN.values())

    def test_an_account_that_is_gone_is_nobody_and_the_run_goes_on(self, pull: Pull):
        # GitHub gives null for an account that is gone, for a review with no body,
        # and for a comment whose review is gone. None of them is a wrong shape.
        gone = {
            PULL_CALL: lambda answer: answer | {"user": None},
            REVIEWS_CALL: lambda page: [page[0] | {"user": None}, *page[1:], page[-1] | {"id": 99, "body": None}],
            COMMENTS_CALL: lambda page: [
                page[0] | {"user": None, "in_reply_to_id": None}, page[1] | {"pull_request_review_id": None}, *page[2:]
            ],
        }
        pull.serve(REVIEWS, COMMENTS, spoiled=gone)
        pull.write(example())
        ran = pull.run()
        assert ran.code == 0
        assert ran.err.splitlines() == [
            f"campaign: review {REVIEWS[0]['id']} is skipped, because its author, None, is not the reviewing App"
        ]
        record = pull.record()
        assert len(record["campaign"]["findings"]) == 21
        # No reply is the author's when the pull request has no author, so no finding has a commit.
        assert [entry["commit"] for entry in record["campaign"]["findings"]] == [""] * 21


class TestSharedHelpers:
    @pytest.mark.parametrize(("call", "answer"), [
        (PULL_CALL, '{"user": {"login": ' + "7" * 5000 + "}}"),
        (PULL_CALL, "[" * 100_000 + "]" * 100_000),
        (REVIEWS_CALL, '[{"id": ' + "7" * 5000 + "}]"),
        (COMMENTS_CALL, "[" * 100_000 + "]" * 100_000),
    ])
    def test_cr_x4_an_answer_that_cannot_be_loaded_fails_the_run_naming_its_call_and_leaves_the_record(
        self, call: str, answer: str, pull: Pull
    ):
        pull.serve(REVIEWS, COMMENTS, spoiled={call: lambda _: Raw(answer)})
        before = pull.write(example())
        ran = pull.run()
        assert ran.code == 2
        assert f"`gh {call}` gave an answer that cannot be used" in ran.err
        assert len(ran.err) < 1000
        assert pull.path.read_bytes() == before

    def test_two_writers_interleaved_leave_one_whole_record_and_nothing_beside_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        path = tmp_path / "record.json"
        first, second = with_heads_up("The first writer wrote this."), with_heads_up("The second writer wrote this.")
        path.write_text(json.dumps(example()), encoding="utf-8")
        replace, beside = Path.replace, []

        def interleaved(source: Path, target: Path) -> Path:
            # The first writer has written beside the record. The second writes and replaces before the first replaces.
            beside.append(source)
            if len(beside) == 1:
                change_record.write_record(path, second)
            return replace(source, target)

        monkeypatch.setattr(Path, "replace", interleaved)
        change_record.write_record(path, first)
        # Each writer wrote beside the record under a name of its own, and neither wrote through the other's file.
        assert len(set(beside)) == 2
        assert all(source.parent == tmp_path and source.name.startswith("record.json.") for source in beside)
        assert json.loads(path.read_text(encoding="utf-8")) == first
        assert sorted(tmp_path.iterdir()) == [path]

    def test_a_writer_that_is_overtaken_mid_write_does_not_write_into_the_record(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # The first writer has written half of its text beside the record when the second writes and replaces.
        # Under one shared name the first would go on writing into what is by then the record.
        path = tmp_path / "record.json"
        first, second = with_heads_up("The first writer wrote this."), with_heads_up("The second writer wrote this.")
        path.write_text(json.dumps(example()), encoding="utf-8")
        opened, overtaken = Path.open, []

        def halving(self: Path, *args: Any, **kwargs: Any) -> Any:
            handle = opened(self, *args, **kwargs)
            if overtaken or self.parent != tmp_path or self == path:
                return handle
            overtaken.append(self)
            write = handle.write

            def written(text: str) -> int:
                count = write(text[: len(text) // 2])
                handle.flush()
                change_record.write_record(path, second)
                assert json.loads(path.read_text(encoding="utf-8")) == second
                return count + write(text[len(text) // 2 :])

            handle.write = written
            return handle

        monkeypatch.setattr(Path, "open", halving)
        change_record.write_record(path, first)
        monkeypatch.undo()
        assert len(overtaken) == 1
        assert json.loads(path.read_text(encoding="utf-8")) == first
        assert sorted(tmp_path.iterdir()) == [path]


class TestVerdictText:
    """What a reviewer wrote reaches the record whole, or its review is skipped by name. Nothing is raised."""

    @pytest.mark.parametrize("ending", ["\n", "\r", "\r\n"])
    def test_a_line_break_in_a_claim_or_its_evidence_leaves_a_record_that_lints_and_renders_with_its_rows_whole(
        self, ending: str, pull: Pull
    ):
        claim = f"The gate lets a bad value through.{ending}{ending}It should refuse:{ending}- a blank{ending}- a break"
        evidence = f"The value is refused two lines above.{ending}The refusal test shows it."
        record = pull.filled([
            review(verdict(1, findings=[finding("f1", claim=claim), finding("f2")])),
            review(verdict(2, priors=[prior("f1", "rebutted", evidence)])),
        ])
        entry = found(record, "f1")
        assert (entry["claim"], entry["reason"]) == (claim, evidence)
        assert change_record.lint_record(record) == []
        body = change_record.render_body(record)
        section = body[body.index("### Review campaign") : body.index("## Criteria")]
        assert "\r" not in section
        entries = [line for line in section.split("\n") if line.startswith("| ")][5:]
        assert len(entries) == 2
        shown = "The gate lets a bad value through.<br><br>It should refuse:<br>- a blank<br>- a break"
        said = "The value is refused two lines above.<br>The refusal test shows it."
        assert entries[0] == f"| 1 | f1 | {shown} | Rejected | {said} |  |"

    @pytest.mark.parametrize("escaped", [True, False])
    def test_a_verdict_that_holds_half_of_a_surrogate_pair_is_skipped_by_name_and_the_rest_is_counted(
        self, escaped: bool, pull: Pull
    ):
        # The verdict's own JSON may escape the half pair, or GitHub's answer may escape it around the verdict.
        halved = verdict(1, findings=[finding("f1", claim="A broken character, \ud83d, in a claim.")])
        broken = review(halved if escaped else json.dumps(halved, indent=2, ensure_ascii=False))
        whole = review(verdict(1, claim="claim-b", findings=[finding("f1")]))
        pull.serve([broken, whole])
        pull.write(example())
        ran = pull.run()
        assert ran.code == 0
        why = "its verdict cannot be read: it holds text that UTF-8 cannot hold, at /findings/0/claim"
        assert ran.err.splitlines() == [f"campaign: review {broken['id']} is skipped, because {why}"]
        record = pull.record()
        assert [(entry["claim_id"], entry["id"]) for entry in record["campaign"]["findings"]] == [("claim-b", "f1")]
        assert change_record.lint_record(record) == []
        assert "| 1 | f1 | The gate lets a bad value through. |" in change_record.render_body(record)

    def test_a_pull_request_whose_only_verdict_holds_half_of_a_surrogate_pair_gets_the_unreadable_row(self, pull: Pull):
        halved = verdict(1, findings=[finding("f1", claim="A broken character, \udc00, in a claim.")])
        record = pull.filled([review(halved)], None, with_heads_up("None."))
        assert record["campaign"] == empty_campaign()
        assert record["heads_up"] == [
            "campaign: 1 review carries a verdict that could not be read, so no review round is counted."
        ]
        assert change_record.lint_record(record) == []

    def test_a_review_body_whose_lines_end_in_a_carriage_return_still_carries_its_verdict(self, pull: Pull):
        posted = review(verdict(lenses=["correctness"], findings=[finding("f1")]))
        posted["body"] = posted["body"].replace("\n", "\r\n")
        assert rows(pull.filled([posted])) == [("correctness", "1", 1, 0, 0, 0)]


class TestCrC8ReadsOnly:
    def test_cr_c8_a_run_over_the_recorded_reviews_makes_reads_only(self, pull: Pull):
        pull.serve(REVIEWS, COMMENTS)
        pull.write(example())
        assert pull.run().code == 0
        calls = pull.calls()
        assert len(calls) == 5
        assert other_than_reads(calls) == []
        assert all(call.split()[0] == "api" and len(call.split()) == 2 for call in calls)

    def test_cr_c8_the_check_every_case_runs_tells_a_write_from_a_read(self):
        base = "api repos/{owner}/{repo}/pulls/843"
        reads = [base, f"{base}/reviews?per_page=100&page=1", f"{base}/comments?per_page=100&page=12"]
        assert other_than_reads(reads) == []
        others = [
            f"api -X POST {base}/reviews",
            f"api --method PATCH {base}",
            f"api {base}/comments -f body=text",
            f"api {base}/reviews?per_page=100&page=1 --input body.json",
            "api repos/{owner}/{repo}/issues/843/comments?per_page=100&page=1",
            "api repos/{owner}/{repo}/pulls/843/reviews/7/dismissals",
            "pr comment 843 --body text",
            "pr review 843 --approve",
        ]
        assert other_than_reads(reads + others) == others


class TestCrX4FailedCall:
    def test_cr_x4_a_gh_call_that_fails_as_the_second_call_is_named_and_the_record_is_byte_identical(
        self, pull: Pull, tmp_path: Path
    ):
        pull.serve(REVIEWS, COMMENTS, fail_on=2)
        before = pull.write(with_heads_up("None."))
        ran = pull.run()
        assert ran.code == 2
        assert "`gh api repos/{owner}/{repo}/pulls/843/reviews?per_page=100&page=1` exited 1" in ran.err
        assert "HTTP 502" in ran.err
        assert pull.path.read_bytes() == before
        assert len(pull.calls()) == 2
        assert [path.name for path in tmp_path.iterdir() if path.is_file()] == ["record.json"]

    @pytest.mark.parametrize("failing", [1, 3, 4, 5, 6, 7, 8])
    def test_cr_x4_a_gh_call_that_fails_anywhere_in_the_run_leaves_the_record_byte_identical(
        self, failing: int, pull: Pull
    ):
        # The run over these pages makes eight calls, and the record is written only after the last of them.
        pull.serve(REVIEWS, COMMENTS, pages=3, comment_pages=2, fail_on=failing)
        before = pull.write(with_heads_up("None."))
        ran = pull.run()
        assert ran.code == 2
        assert pull.calls()[-1] in ran.err
        assert pull.path.read_bytes() == before
        assert len(pull.calls()) == failing

    def test_cr_x4_a_run_with_no_failing_call_makes_all_eight(self, pull: Pull):
        pull.serve(REVIEWS, COMMENTS, pages=3, comment_pages=2, fail_on=9)
        pull.write(with_heads_up("None."))
        assert pull.run().code == 0
        assert len(pull.calls()) == 8

    def test_cr_x4_a_gh_that_cannot_be_run_is_named_and_the_record_is_byte_identical(self, pull: Pull):
        before = pull.write(example())
        ran = pull.run()
        assert ran.code == 2
        assert "cannot run `gh api repos/{owner}/{repo}/pulls/843`" in ran.err
        assert pull.path.read_bytes() == before

    @pytest.mark.parametrize("answer", ['{"message": "a page that is no list"}', "not json at all"])
    def test_cr_x4_a_page_that_is_not_a_json_list_fails_the_run_and_leaves_the_record_byte_identical(
        self, answer: str, pull: Pull, shim_dir: Path
    ):
        pull.serve(REVIEWS, COMMENTS)
        shim = shim_dir / "gh"
        text = shim.read_text(encoding="utf-8")
        page = "'api repos/{owner}/{repo}/pulls/843/comments?per_page=100&page=1')"
        assert page in text
        answered = f"{page} echo {shlex.quote(answer)}; exit 0 ;;\n  'unused')"
        shim.write_text(text.replace(page, answered), encoding="utf-8")
        before = pull.write(example())
        ran = pull.run()
        assert ran.code == 2
        assert "pulls/843/comments?per_page=100&page=1" in ran.err
        assert pull.path.read_bytes() == before


class TestCampaignCommand:
    def test_a_record_campaign_filled_passes_lint_and_a_hand_edit_fails_it_until_the_next_run(self, pull: Pull):
        pull.serve(REVIEWS, COMMENTS)
        pull.write(example())
        assert pull.run().code == 0
        record = pull.record()
        part = {name: value for name, value in record["campaign"].items() if name != "digest"}
        assert record["campaign"]["digest"] == change_record.stamp(part)
        assert change_record.lint_record(record) == []
        record["campaign"]["reviewers"][0]["fixed"] = 9
        pull.write(record)
        assert [(error["code"], error["path"]) for error in change_record.lint_record(pull.record())] == [
            ("stale-stamp", "/campaign/digest")
        ]
        assert pull.run().code == 0
        assert change_record.lint_record(pull.record()) == []
        assert rows(pull.record()) == ROWS_843

    def test_the_campaign_of_the_recorded_reviews_is_the_example_records_but_for_the_terminal_commit(self, pull: Pull):
        record = pull.filled(REVIEWS, COMMENTS)
        part = {**record["campaign"], "terminal_sha": EXAMPLE["campaign"]["terminal_sha"]}
        del part["digest"]
        assert {**part, "digest": change_record.stamp(part)} == EXAMPLE["campaign"]

    def test_campaign_names_no_terminal_commit_and_writes_no_row_about_one(self, pull: Pull):
        record = pull.filled(REVIEWS, COMMENTS, with_heads_up("None."))
        assert record["campaign"]["terminal_sha"] == ""
        assert record["heads_up"] == ["None."]

    def test_a_record_new_from_init_takes_a_campaign(self, pull: Pull):
        record = change_record.new_record("feat", "a-component", "proj-a1b.3")
        written = pull.filled(REVIEWS, COMMENTS, record)
        assert rows(written) == ROWS_843
        # The author has not said yet whether anything lowers a reader's confidence.
        # The generator does not say it for them.
        assert written["heads_up"] == []
        assert written["pr"]["number"] is None

    def test_the_pull_request_number_comes_from_the_record_when_pr_is_left_out(self, pull: Pull):
        pull.serve(REVIEWS, COMMENTS)
        pull.write(example())
        assert pull.run(pr=None).code == 0
        assert pull.calls()[0] == "api repos/{owner}/{repo}/pulls/843"
        assert rows(pull.record()) == ROWS_843

    def test_a_pr_number_that_is_not_the_records_is_refused_before_any_call(self, pull: Pull):
        pull.serve(REVIEWS, COMMENTS, number=844)
        before = pull.write(example())
        ran = pull.run(pr=844)
        assert ran.code == 2
        assert "843" in ran.err and "844" in ran.err
        assert (pull.path.read_bytes(), pull.calls()) == (before, [])

    def test_a_record_that_names_no_pull_request_needs_pr(self, pull: Pull):
        record = example()
        record["pr"]["number"] = None
        pull.serve(REVIEWS, COMMENTS)
        before = pull.write(record)
        ran = pull.run(pr=None)
        assert ran.code == 2
        assert "--pr" in ran.err
        assert (pull.path.read_bytes(), pull.calls()) == (before, [])

    def test_a_record_the_schema_refuses_is_left_alone(self, pull: Pull):
        record = example()
        del record["heads_up"]
        pull.serve(REVIEWS, COMMENTS)
        before = pull.write(record)
        ran = pull.run()
        assert ran.code == 2
        assert "/heads_up" in ran.err
        assert (pull.path.read_bytes(), pull.calls()) == (before, [])

    def test_a_record_that_cannot_be_read_exits_2(self, pull: Pull):
        ran = pull.run()
        assert ran.code == 2
        assert "cannot read" in ran.err

    def test_campaign_runs_from_the_command_line_and_says_what_it_wrote(self, pull: Pull):
        pull.serve(REVIEWS, COMMENTS)
        pull.write(example())
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "campaign", "--pr", "843", "--app", APP, str(pull.path)],
            capture_output=True, text=True, check=False,
        )
        assert (proc.returncode, proc.stderr) == (0, "")
        assert proc.stdout == f"wrote {pull.path}\n"
        assert rows(pull.record()) == ROWS_843
        assert other_than_reads(pull.calls()) == []

    def test_a_second_run_over_unchanged_reviews_says_the_record_is_already_current(self, pull: Pull):
        pull.serve(REVIEWS, COMMENTS)
        pull.write(example())
        assert pull.run().out == f"wrote {pull.path}\n"
        assert pull.run().out == f"{pull.path} is already current\n"

    def test_a_record_campaign_filled_renders_its_review_campaign(self, pull: Pull):
        record = pull.filled(REVIEWS, COMMENTS)
        body = change_record.render_body(record)
        section = body[body.index("### Review campaign") : body.index("## Criteria")]
        table, fold = section.split("<details><summary>Findings by round</summary>")
        assert [line for line in table.splitlines() if line.startswith("| ")][2:] == [
            "| " + " | ".join(str(cell) for cell in row) + " |" for row in ROWS_843
        ]
        # The generator names no terminal commit, so the body carries no line about one.
        assert "Terminal-clean" not in section
        entries = [line for line in fold.splitlines() if line.startswith("| ")][2:]
        assert len(entries) == 24
        assert entries[3].startswith("| 1 | correctness.r1.f1 | A fourth dead-run claim can bypass")
        assert " | Fixed | Reproduced: " in entries[3] and entries[3].endswith(" | 75bb090c |")
        # A finding no verdict gave a disposition to renders with those cells empty.
        assert entries[0].startswith("| 1 | security.r1.f1 | ") and entries[0].endswith(" |  |  |  |")


class TestCampaignInTheSkillText:
    def test_the_skill_body_has_one_entry_for_campaign_and_says_the_script_fills_all_three_parts(self):
        body = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        assert "uv run scripts/change_record.py campaign [--pr NUMBER] record.json" in body
        assert len([line for line in body.splitlines() if line.startswith("- `campaign` ")]) == 1
        assert "The script fills all three." in body
        assert "Nothing fills" not in body

    def test_the_commands_reference_gives_the_campaign_command_line_its_options_and_its_exit_statuses(self):
        text = (SKILL / "references" / "commands.md").read_text(encoding="utf-8")
        section = text[text.index("## `campaign`") :].split("\n## ")[0]
        assert "scripts/change_record.py campaign [--pr NUMBER] [--app LOGIN] record.json" in section
        said = ("- `--pr NUMBER` ", "- `--app LOGIN` ", "working directory", "`review-verdict` skill", "generators.md")
        assert [words for words in said if words not in section] == []
        assert "Exit 0 the record holds the part, 2 anything failed." in section

    def test_the_generators_reference_says_how_the_campaign_is_derived_and_quotes_the_rows_it_writes(self):
        text = (SKILL / "references" / "generators.md").read_text(encoding="utf-8")
        section = text[text.index("## `campaign`") :].split("\n## ")[0]
        for part in (
            "**Which reviews count.**", "**Which verdicts are unreadable.**", "**Reviewer rows.**", "**Findings.**",
            "**The commit.**", "**The terminal commit.**", "### An empty campaign",
        ):
            assert part in section
        # The rows the reference quotes are the rows the generator writes.
        assert f"`{NO_ROUND}`" in section
        counted = "campaign: " + change_record._empty_campaign_rows(0, 2)[0]
        assert f"`{counted}`" in section
        calls = text[text.index("`campaign` makes these, in order:") :]
        for listing in ('pulls/NUMBER"`', "pulls/NUMBER/reviews?per_page=100&page=N", "pulls/NUMBER/comments?per_page=100&page=N"):
            assert listing in calls

    def test_the_lint_reference_says_the_script_fills_all_three_generated_parts(self):
        text = (SKILL / "references" / "lint-rules.md").read_text(encoding="utf-8")
        assert "The script fills all three generated parts." in text
        assert "generates `campaign` yet" not in text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
