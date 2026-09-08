"""The ``post-verdict`` verb — a review round's verdict as the App's own review.

The verdict is attached to the commit it judged and never committed into the
branch it judges: a branch-resident verdict advances the head it must match, and
is writable by the reviewed party. The medium is one submitted, comment-only
review authored by the App — a rendered summary of the round as the body, with
the verdict file's own text reproduced inside it, an inline comment at each
finding that names a line the diff touches, pinned to the head the verdict
declares.

It refuses when the PR's live head has moved off that declared head, is a no-op
when the App has already posted this exact body there, and never approves:
approval is a separate review the caller decides on separately.

Like ``approve`` it stands outside the grooming loop — no grooming state is read
or written, and no PR lock is taken.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from prgroom.errors import ErrorCode, PreconditionError
from prgroom.gh.app import (
    HttpTransport,
    build_jwt,
    find_own_review,
    iter_files,
    mint_installation_token,
    openssl_signer,
    read_field,
    read_head_sha,
    review_field,
    submit_review,
)
from prgroom.proc import CommandRunner
from prgroom.prsession.pr_ref import PRRef, is_commit_sha

COMMENT_EVENT = "COMMENT"

# The state GitHub reports for a submitted comment-only review — what this verb's
# own posting comes back as, and the only state its idempotence check accepts.
COMMENT_STATE = "COMMENTED"

# The ceiling GitHub puts on a comment body, measured against the body this verb
# renders rather than the file it renders from: the summary is part of what gets
# posted, so a file that fits and a body that fits are different questions. A
# verdict past it is refused rather than truncated: a truncated verdict is a
# different document that still reads as the round's result, and the JSON would no
# longer parse for anyone consuming it. Refusal is on exceeding the ceiling, not
# on reaching it — a body the API would take must not be turned away here.
MAX_BODY_CHARS = 65536

# What the collapsed block holding the envelope is labelled, and the language its
# fenced block declares. A reader after the envelope takes that block's contents,
# not the whole body.
ENVELOPE_SUMMARY = "Verdict envelope"
FENCE_LANGUAGE = "json"

# The side of the diff every anchor is placed against. A finding names a line of
# the code as it now stands, which is the right-hand side; the left side holds
# lines the change deleted, and no finding about the new head is about those.
_RIGHT = "RIGHT"

# A location as findings write one: a path, then a line or an inclusive line
# range. Nothing else is recognized — a bare path names no line, and
# `path:symbol` names a symbol whose line only the repository knows.
#
# The diff decides what a path is; this only finds candidates, and must not
# alter them. So the path is any run of characters that is neither whitespace
# nor the colon before the line, and no narrower: a filename may hold anything a
# filesystem allows, and a set narrow enough to exclude prose also excludes
# legal names. The trailing boundary refuses a number with anything glued to it,
# so `app.py:3junk` names no line rather than line 3, and it bounds the digit
# run, because a line number longer than any file is not a line number.
#
# A path containing a space or a colon is not findable this way, because nothing
# distinguishes the path's own space from the space that ends it, or its own
# colon from the colon before the line; such a finding lands in the body alone.
# Making one findable would need the finding to quote the path.
_ANCHOR = re.compile(r"(?P<path>[^\s:]+):(?P<lines>\d{1,9}(?:-\d{1,9})?)(?![\w-])")

# The header of one unified-diff hunk. Its right-hand count is the number of
# lines the hunk holds on the new side, an absent count meaning one.
# Every digit run is bounded: a line number longer than any file is not a line
# number, and an unbounded one reaches a conversion Python refuses.
_HUNK = re.compile(
    r"^@@ -\d{1,9}(?:,\d{1,9})? \+(?P<start>\d{1,9})(?:,(?P<count>\d{1,9}))? @@",
    re.MULTILINE,
)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Verdict:
    """A verdict file as this verb reads it: its bytes, and the two fields it uses.

    ``text`` is the whole file, and the posted body reproduces it verbatim — the
    verb re-serializes nothing, so the envelope a reader takes back out of the
    review cannot be a rounding of the file. Schema validation belongs to whatever
    assembled the file; this reads only what it must, and says which field failed
    when one is not there.
    """

    text: str
    head_sha: str
    findings: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class Anchor:
    """One placed location: a file in the diff and an inclusive line range in it."""

    path: str
    start: int
    end: int


def load_verdict(path: Path) -> Verdict:
    """Read and shape-check a verdict file, or refuse with the reason it failed.

    Read as bytes and decoded here rather than through text mode, so the envelope
    the body carries is the file's own bytes: text mode rewrites line endings, and
    an envelope that quietly differs from the file defeats both the equality check
    that makes a repost a no-op and any later comparison against what was
    reviewed.

    The size refusal is taken here, against the body the file renders to, so a
    verdict too large to post costs no API call.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PreconditionError(
            ErrorCode.PRECONDITION_VERDICT_UNREADABLE, detail=f"{path}: {exc}"
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        detail = f"{path} is not UTF-8: {exc}"
        raise _malformed(detail) from exc
    try:
        payload = json.loads(text, parse_constant=_not_json)
    except ValueError as exc:
        detail = f"{path} is not JSON: {exc}"
        raise _malformed(detail) from exc
    if not isinstance(payload, dict):
        detail = f"{path} holds {type(payload).__name__}, not an object"
        raise _malformed(detail)
    head_sha = _required(payload, "head_sha", path, want=str)
    if not is_commit_sha(head_sha):
        detail = f"{path}: head_sha {head_sha!r} is not a 40-character commit id"
        raise _malformed(detail)
    findings: list[Any] = _required(payload, "findings", path, want=list)
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            detail = f"{path}: findings[{index}] is {type(finding).__name__}, not an object"
            raise _malformed(detail)
        _required(finding, "id", path, want=str, where=f"findings[{index}]")
        for optional in ("evidence", "claim"):
            if optional in finding and not isinstance(finding[optional], str):
                detail = (
                    f"{path}: findings[{index}].{optional} is "
                    f"{type(finding[optional]).__name__}, not a string"
                )
                raise _malformed(detail)
        # A finding that says neither what it found nor where cannot be placed and
        # cannot be read; it is a shape no round produces, and posting it would
        # put an id on a pull request with nothing attached to it.
        if not any(finding.get(field, "").strip() for field in ("evidence", "claim")):
            detail = f"{path}: findings[{index}] carries neither evidence nor claim"
            raise _malformed(detail)
    verdict = Verdict(text=text, head_sha=head_sha.lower(), findings=tuple(findings))
    rendered = len(render_body(verdict))
    if rendered > MAX_BODY_CHARS:
        raise PreconditionError(
            ErrorCode.PRECONDITION_VERDICT_TOO_LARGE,
            detail=f"{path} renders to {rendered} characters; the limit is {MAX_BODY_CHARS}",
        )
    return verdict


def render_body(verdict: Verdict) -> str:
    """The review body: a summary of the round, then the verdict file itself.

    The envelope is reproduced rather than summarized away, because a later reader
    parses it back out of the review to judge the round. A summary standing in its
    place would leave nothing to parse, and one re-serialized from the parse could
    disagree with the file.

    Nothing here refuses a verdict. The summary is a convenience for whoever opens
    the pull request, so a field it cannot read is a field it leaves out — never a
    posting it prevents.
    """
    payload = _payload(verdict.text)
    sections = [
        _headline(payload),
        _identity(verdict, payload),
        *_halt(payload),
        *_lens_roster(payload),
        *_finding_roster(payload),
        *_priors(payload),
        _envelope_block(verdict.text),
    ]
    return "\n\n".join(sections)


def envelope_of(body: str) -> str:
    """The verdict text a rendered body carries, exactly as the file held it.

    The fence is longer than any run of backticks in the envelope, so no line of
    the envelope can close it, and every summary line starts with prose, so none
    of them can either. The last run of backticks alone on a line is therefore the
    fence that closes the envelope, and the last opener above it is the one that
    starts it.
    """
    lines = body.split("\n")
    close = next((index for index in reversed(range(len(lines))) if _is_fence(lines[index])), None)
    if close is None:
        msg = "the body carries no fenced block"
        raise ValueError(msg)
    opener = lines[close] + FENCE_LANGUAGE
    start = next((index for index in reversed(range(close)) if lines[index] == opener), None)
    if start is None:
        msg = f"the body's last fenced block is not opened as {FENCE_LANGUAGE}"
        raise ValueError(msg)
    return "\n".join(lines[start + 1 : close])


def commentable_spans(patch: str) -> list[tuple[int, int]]:
    """The inclusive right-side line ranges a patch's hunks make commentable.

    The right side takes a comment on an added line and on an unchanged line shown
    for context alike, and every new-side line inside a hunk is one or the other —
    a deleted line consumes no new-side number. The hunk header's right-hand count
    is therefore exactly how many commentable lines the hunk holds, so a hunk
    contributes one contiguous range and needs no walk of its body. A hunk that
    adds nothing on the right (a pure deletion) contributes none.
    """
    spans: list[tuple[int, int]] = []
    for hunk in _HUNK.finditer(patch):
        start = int(hunk["start"])
        count = 1 if hunk["count"] is None else int(hunk["count"])
        if count > 0:
            spans.append((start, start + count - 1))
    return spans


def diff_spans(http: HttpTransport, token: str, ref: PRRef) -> dict[str, list[tuple[int, int]]]:
    """Every file the PR changes, mapped to the line ranges a comment may sit in.

    A file GitHub reports without a patch — a binary, or a diff too large to
    render — maps to no ranges rather than being left out, so it is still a file
    the diff touches and an anchor naming it resolves and then finds no line. A
    patch that is there in some other shape fails the call instead: it is a file
    that may carry an anchor and whose lines could not be read, and treating that
    as "no lines" would demote a placeable anchor without saying so.
    """
    spans: dict[str, list[tuple[int, int]]] = {}
    for entry in iter_files(http, token, ref):
        filename = read_field(entry, "filename", want=str, what="files listing")
        if entry.get("patch") is None:
            spans[filename] = []
            continue
        spans[filename] = commentable_spans(
            read_field(entry, "patch", want=str, what="files listing")
        )
    return spans


def place_anchor(
    finding: Mapping[str, Any], spans: Mapping[str, list[tuple[int, int]]]
) -> Anchor | None:
    """The first location in ``finding`` that lands inside the diff, if any does.

    Evidence is read before the claim because that is where a finding states where
    it looked. A named path resolves when it is a trailing run of path segments of
    exactly one changed file, so a finding may name a file the short way it reads
    in prose; two candidates are an ambiguity that anchors nothing, because a
    comment on the wrong file is worse than a comment only in the body.

    The whole range must sit inside one hunk. A range straddling two hunks covers
    lines the diff does not carry, which GitHub rejects — and rejecting one comment
    rejects the review it arrived in.
    """
    for field in ("evidence", "claim"):
        text = finding.get(field)
        if not isinstance(text, str):
            continue
        for match in _ANCHOR.finditer(text):
            path = _resolve_path(match["path"], spans)
            if path is None:
                continue
            first, _, last = match["lines"].partition("-")
            start = int(first)
            end = int(last) if last else start
            if end < start:
                continue
            if any(low <= start and end <= high for low, high in spans[path]):
                return Anchor(path=path, start=start, end=end)
    return None


def build_comments(
    findings: Sequence[Mapping[str, Any]], spans: Mapping[str, list[tuple[int, int]]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Split findings into placed inline comments and the ids of the unplaced ones.

    A comment's body is the finding's own JSON, so a reader at the line sees the
    same record the envelope carries rather than a rendering of it that could
    disagree. Findings are neither merged nor de-duplicated: two findings about one
    line are two findings, and the panel's count is not this verb's to revise.
    """
    comments: list[dict[str, Any]] = []
    unplaced: list[str] = []
    for finding in findings:
        anchor = place_anchor(finding, spans)
        if anchor is None:
            unplaced.append(str(finding["id"]))
            continue
        comment: dict[str, Any] = {
            "path": anchor.path,
            "line": anchor.end,
            "side": _RIGHT,
            "body": json.dumps(dict(finding), indent=2),
        }
        if anchor.start < anchor.end:
            comment["start_line"] = anchor.start
            comment["start_side"] = _RIGHT
        comments.append(comment)
    return comments, unplaced


def post_verdict_pr(
    *,
    http: HttpTransport,
    runner: CommandRunner,
    ref: PRRef,
    verdict: Verdict,
    app_id: int,
    key_path: Path,
    now: int,
) -> str:
    """Post (or recognize) the App's verdict review; return the lines to print.

    The head is re-read live and compared before anything is read of the diff, so
    a verdict can never be posted against a head it did not review. The event is
    ``COMMENT`` and only ever that: a verdict that arrived as an approval would
    approve a change on the strength of a document that says nothing about
    whether it should merge.
    """
    signer = openssl_signer(runner, key_path)
    minted = mint_installation_token(http, build_jwt(app_id, now, signer), ref)

    live_head = read_head_sha(http, minted.token, ref)
    if live_head != verdict.head_sha:
        raise PreconditionError(
            ErrorCode.PRECONDITION_APPROVER_HEAD_MOVED,
            detail=(
                f"{ref.display()} now heads at {live_head}, not the reviewed {verdict.head_sha}"
            ),
        )

    # Rendered once and compared whole. The rendering is a pure function of the
    # verdict, so the body a repost builds is the body the first posting left, and
    # equality on it is still equality on the verdict behind it.
    body = render_body(verdict)
    existing = find_own_review(
        http,
        minted.token,
        ref,
        minted.login,
        # Comment-only, because an approval carrying this body would still be an
        # approval: recognizing one as the verdict already posted would leave the
        # round's result unposted and an approval standing in its place.
        match=lambda review: (
            review_field(review, "state") == COMMENT_STATE
            and review_field(review, "commit_id") == verdict.head_sha
            and review_field(review, "body") == body
        ),
    )
    if existing is not None:
        return (
            f"already posted by {minted.login} at {verdict.head_sha} "
            f"(review {existing}) — nothing posted"
        )

    comments, unplaced = build_comments(verdict.findings, diff_spans(http, minted.token, ref))
    review_id = submit_review(
        http,
        minted.token,
        ref,
        event=COMMENT_EVENT,
        body=body,
        commit_id=verdict.head_sha,
        comments=comments,
    )
    lines = [f"no line in the diff for finding {finding_id}" for finding_id in unplaced]
    lines.append(
        f"posted: review {review_id} by {minted.login} pinned to {verdict.head_sha} "
        f"with {len(comments)} inline comment(s)"
    )
    return "\n".join(lines)


def _payload(text: str) -> Mapping[str, Any]:
    """The envelope's fields, or nothing at all when the text holds no object.

    The loader has already proven that a file it accepted parses. Reading it a
    second time here, rather than carrying the parse on the verdict, keeps the
    renderer usable on any text at all — including one no loader produced.
    """
    try:
        parsed = json.loads(text)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _headline(payload: Mapping[str, Any]) -> str:
    """The heading: what the round concluded, which round it was, and about what."""
    word = _line(payload.get("verdict"))
    qualifiers = []
    number = payload.get("round")
    # A bool is an int to Python and a round number to nobody, so it is excluded
    # rather than printed as the 0 or 1 it would become.
    if isinstance(number, int) and not isinstance(number, bool):
        qualifiers.append(f"round {number}")
    artifact_class = _line(payload.get("artifact_class"))
    if artifact_class:
        qualifiers.append(artifact_class)
    heading = f"## Review verdict: {word}" if word else "## Review verdict"
    return f"{heading} ({', '.join(qualifiers)})" if qualifiers else heading


def _identity(verdict: Verdict, payload: Mapping[str, Any]) -> str:
    """What was reviewed: the head the verdict pins to, its base, and the claim."""
    parts = [f"Head {_short(verdict.head_sha)}"]
    base = _line(payload.get("base_sha"))
    if base:
        parts.append(f"base {_short(base)}")
    claim = _line(payload.get("claim_id"))
    if claim:
        parts.append(f"claim {claim}")
    return ", ".join(parts) + "."


def _halt(payload: Mapping[str, Any]) -> list[str]:
    """Why a halted round stopped, and which staffed lenses it never dispatched."""
    halt = payload.get("halt")
    if not isinstance(halt, Mapping):
        return []
    reason = _line(halt.get("reason"))
    sentences = [f"**Halted:** {reason}." if reason else "**Halted.**"]
    abandoned = _lines(halt.get("abandoned_lenses"))
    if abandoned:
        sentences.append(f"Lenses never dispatched: {', '.join(abandoned)}.")
    return [" ".join(sentences)]


def _lens_roster(payload: Mapping[str, Any]) -> list[str]:
    """One line per lens: what it found, and what actually ran it."""
    rows = []
    for entry in _objects(payload.get("lenses")):
        name = _line(entry.get("lens"))
        if not name:
            continue
        detail = ", ".join(part for part in (_line(entry.get("verdict")), _ran_on(entry)) if part)
        row = f"{name}: {detail}" if detail else name
        note = _substitution(entry.get("substitution"))
        rows.append(f"- {row} {note}" if note else f"- {row}")
    return [_section("Lenses", rows)] if rows else []


def _finding_roster(payload: Mapping[str, Any]) -> list[str]:
    """One entry per finding: what it is, which lens raised it, and what it says."""
    rows = []
    for entry in _objects(payload.get("findings")):
        identifier = _line(entry.get("id"))
        if not identifier:
            continue
        tags = [
            tag
            for tag in (_line(entry.get("type")), _line(entry.get("lens")), _line(entry.get("ac")))
            if tag
        ]
        head = f"{identifier} ({', '.join(tags)})" if tags else identifier
        claim = _line(entry.get("claim"))
        rows.append(f"- {head}: {claim}" if claim else f"- {head}")
    return [_section("Findings", rows)] if rows else []


def _priors(payload: Mapping[str, Any]) -> list[str]:
    """How much earlier rounds carried in, and how those findings were dispositioned."""
    carried = payload.get("prior_dispositions")
    if not isinstance(carried, list) or not carried:
        return []
    counts = Counter(
        word for entry in _objects(carried) if (word := _line(entry.get("disposition")))
    )
    tally = f"Prior dispositions carried forward: {len(carried)}"
    if not counts:
        return [f"{tally}."]
    detail = ", ".join(f"{count} {word}" for word, count in sorted(counts.items()))
    return [f"{tally} ({detail})."]


def _envelope_block(text: str) -> str:
    """The verdict's own text, verbatim, inside a collapsed block a reader can open.

    The fence is one backtick longer than the longest run the text holds, so the
    text cannot close the block early however many backticks it carries. A
    ``</details>`` inside the text is inert for the same reason: it sits in a
    fenced block, where it is content rather than markup.
    """
    fence = "`" * max(3, _longest_backtick_run(text) + 1)
    return (
        f"<details>\n<summary>{ENVELOPE_SUMMARY}</summary>\n\n"
        f"{fence}{FENCE_LANGUAGE}\n{text}\n{fence}\n\n</details>"
    )


def _section(label: str, rows: list[str]) -> str:
    body = "\n".join(rows)
    return f"**{label}**\n\n{body}"


def _ran_on(entry: Mapping[str, Any]) -> str:
    """How a lens ran, as far as its record says: the model, and the route to it."""
    model = _line(entry.get("model"))
    transport = _line(entry.get("transport"))
    if model and transport:
        return f"{model} via {transport}"
    if transport:
        return f"via {transport}"
    return model


def _substitution(value: Any) -> str:
    """That a lens ran on something other than what its registry declared, if it did.

    The record's reason is left in the envelope. It runs to a paragraph, and a
    paragraph per lens is the summary nobody reads.
    """
    if not isinstance(value, Mapping):
        return ""
    declared = _ran_on(
        {"model": value.get("declared_model"), "transport": value.get("declared_transport")}
    )
    return f"(substituted for {declared})" if declared else "(substituted)"


def _line(value: Any) -> str:
    """One line of text from a field meant to hold one, or nothing usable.

    Whitespace is collapsed because every string the summary shows sits inside a
    heading or a bullet, where a newline through the middle of it would break the
    markdown around it. Collapsing also keeps every summary line from being a run
    of backticks alone, which is what would otherwise close the envelope's fence
    before the envelope started.
    """
    return " ".join(value.split()) if isinstance(value, str) else ""


def _lines(value: Any) -> list[str]:
    """Every usable string in a field meant to hold a list of them."""
    if not isinstance(value, list):
        return []
    return [text for text in (_line(item) for item in value) if text]


def _objects(value: Any) -> list[Mapping[str, Any]]:
    """Every object in a field meant to hold a list of them, in the order given."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _short(sha: str) -> str:
    """A commit id in the short form a reader recognizes, or the value untouched."""
    return sha[:8] if is_commit_sha(sha) else sha


def _longest_backtick_run(text: str) -> int:
    return max((len(run) for run in re.findall(r"`+", text)), default=0)


def _is_fence(line: str) -> bool:
    return len(line) >= 3 and set(line) == {"`"}


# What prose wraps a path in, and never part of the path itself.
_DELIMITERS = "`'\"()[]{}<>,;!?"


def _resolve_path(named: str, spans: Mapping[str, list[tuple[int, int]]]) -> str | None:
    """The one changed file ``named`` identifies, or nothing if zero or several do.

    The token is tried exactly as written before it is tried trimmed, because
    trimming is a fallback for prose that wrapped a path and never a rewrite of
    one: a file whose name ends in punctuation would otherwise be shadowed by the
    file whose name is that one trimmed.
    """
    for candidate in (named, named.strip(_DELIMITERS)):
        segments = candidate.split("/")
        matches = [path for path in spans if path.split("/")[-len(segments) :] == segments]
        if len(matches) == 1:
            return matches[0]
        if matches:
            # The token names changed files, just not one of them. Trimming from
            # here could only reach a file the finding did not write.
            return None
    return None


def _required(
    payload: Mapping[str, Any], key: str, path: Path, *, want: type[T], where: str = ""
) -> T:
    """Read one field the verb needs, naming it and its file when it is not usable."""
    prefix = f"{path}: {where}.{key}" if where else f"{path}: {key}"
    if key not in payload:
        detail = f"{prefix} is missing"
        raise _malformed(detail)
    value = payload[key]
    if not isinstance(value, want):
        detail = f"{prefix} is {type(value).__name__}, not {want.__name__}"
        raise _malformed(detail)
    if isinstance(value, str) and not value.strip():
        detail = f"{prefix} is empty"
        raise _malformed(detail)
    return value


def _not_json(name: str) -> Any:
    """Refuse the JavaScript constants Python's decoder accepts and JSON has not.

    A verdict is posted verbatim, so a document that only Python can read would
    go out as one anything else rejects.
    """
    msg = f"{name} is not a JSON value"
    raise ValueError(msg)


def _malformed(detail: str) -> PreconditionError:
    return PreconditionError(ErrorCode.PRECONDITION_VERDICT_MALFORMED, detail=detail)
