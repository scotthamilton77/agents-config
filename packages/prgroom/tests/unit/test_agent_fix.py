"""Tests for ``run_fix`` orchestration (assemble → dispatch → parse → audit → stash).

``run_fix`` is the heart of the 8.7 boundary: it reads git (via the injected
``GitClient``), runs the three audits, builds per-item ``Disposition`` objects
and a list of ``Escalation`` objects, and performs the ``git stash`` isolation
effect on a hard violation. It returns a :class:`FixRunResult` — it NEVER mutates
``PRGroomingState`` (it is never passed one), never calls ``Sink.emit``, and never
sets ``state.last_error``. The fakes mirror the ``FixContract`` / ``GitClient``
Protocols exactly.
"""

from __future__ import annotations

from datetime import UTC, datetime

from prgroom.agent.contracts import FixInput, FixItemResult, FixOutput, MemoryEntry
from prgroom.agent.dispatcher import AllProvidersFailedError
from prgroom.agent.fix import run_fix
from prgroom.escalation import Severity
from prgroom.prsession.enums import DispositionKind, ItemKind
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import Disposition, Identity, ReviewItem

_NOW = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
_REF = PRRef("octo", "demo", 7)


def _item(gh_id: str) -> ReviewItem:
    return ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id=gh_id, thread_id=f"PRT_{gh_id}"),
        author="copilot",
        body_excerpt="x",
        seen_at=_NOW,
    )


def _req(*gh_ids: str, memory_dir: str = "/run/mem") -> FixInput:
    return FixInput(
        pr=_REF,
        cluster_id="c-1",
        item_gh_ids=list(gh_ids),
        items=[_item(g) for g in gh_ids],
        pr_detail_path="/d",
        branch_state_path="/b",
        memory_dir=memory_dir,
        response_outbox_dir="/o",
    )


class FixDispatcherStub:
    """A ``FixContract`` fake: returns a canned output or raises a canned error."""

    def __init__(self, outcome: FixOutput | Exception) -> None:
        self._outcome = outcome
        self.calls = 0

    def fix(self, request: FixInput) -> FixOutput:
        del request  # canned outcome; mirrors the FixContract Protocol signature
        self.calls += 1
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class FakeGit:
    """A ``GitClient`` fake. ``pre``/``post`` script head_sha; ``rev_list`` is keyed.

    ``rev_list`` returns ``ancestors`` for the bare-``pre`` query and ``new`` for
    the ``pre..post`` range query, mirroring the real ``git rev-list`` surface.
    ``stash`` records its call count so a test can prove stash-or-not.
    """

    def __init__(self, *, pre: str, post: str, ancestors: list[str], new: list[str]) -> None:
        self._heads = [pre, post]
        self._pre = pre
        self._post = post
        self._ancestors = ancestors
        self._new = new
        self.head_calls = 0
        self.stash_calls = 0
        self.pushes: list[tuple[str, str]] = []

    def head_sha(self) -> str:
        self.head_calls += 1
        return self._heads.pop(0)

    def rev_list(self, range_: str) -> list[str]:
        if range_ == self._pre:
            return list(self._ancestors)
        if range_ == f"{self._pre}..{self._post}":
            return list(self._new)
        msg = f"unexpected rev_list range: {range_!r}"
        raise AssertionError(msg)

    def push(self, remote: str, branch: str) -> None:
        # run_fix never pushes; the method exists only so FakeGit structurally
        # satisfies GitClient. Recording the args keeps the Protocol mirror honest.
        self.pushes.append((remote, branch))

    def stash(self) -> None:
        self.stash_calls += 1


def _git(*, ancestors: list[str] | None = None, new: list[str] | None = None) -> FakeGit:
    return FakeGit(pre="pre", post="post", ancestors=ancestors or ["pre"], new=new or [])


# ───────────────────────── both-fail ─────────────────────────


def test_both_fail_flips_every_item_to_failed_with_escalation_and_no_stash() -> None:
    req = _req("C_1", "C_2")
    disp = FixDispatcherStub(AllProvidersFailedError(detail="ollama down; opus down"))
    git = _git()
    res = run_fix(req, disp, git, now=_NOW, decided_by="prgroom")
    assert {g: d.kind for g, d in res.dispositions.items()} == {
        "C_1": DispositionKind.FAILED,
        "C_2": DispositionKind.FAILED,
    }
    assert all("ollama down" in d.rationale for d in res.dispositions.values())
    assert len(res.escalations) == 2
    assert res.stashed is False
    assert git.stash_calls == 0  # nothing was produced — nothing to isolate


def test_both_fail_does_not_read_head_or_rev_list() -> None:
    # No work was produced, so run_fix must short-circuit before computing sets.
    req = _req("C_1")
    disp = FixDispatcherStub(AllProvidersFailedError(detail="down"))
    git = FakeGit(pre="pre", post="post", ancestors=["pre"], new=[])
    run_fix(req, disp, git, now=_NOW, decided_by="prgroom")
    # head_sha was read once (pre); post was never consumed because the both-fail
    # short-circuit returns before computing the commit sets.
    assert git.head_calls == 1


# ───────────────────────── clean passthrough ─────────────────────────


def test_clean_output_maps_dispositions_straight_through() -> None:
    req = _req("C_1", "C_2")
    out = FixOutput(
        items=[
            FixItemResult(
                gh_id="C_1",
                disposition=DispositionKind.FIXED,
                commit_shas=["n1"],
                rationale="fixed it",
                recommended_gate="full",
                response_path="/o/C_1.md",
            ),
            FixItemResult(gh_id="C_2", disposition=DispositionKind.WONT_FIX, rationale="by design"),
        ]
    )
    disp = FixDispatcherStub(out)
    git = _git(ancestors=["pre"], new=["n1"])
    res = run_fix(req, disp, git, now=_NOW, decided_by="prgroom")
    c1 = res.dispositions["C_1"]
    assert c1.kind is DispositionKind.FIXED
    assert c1.commits == ["n1"]
    assert c1.rationale == "fixed it"
    assert c1.gate == "full"
    assert c1.response_path == "/o/C_1.md"
    assert c1.decided_at == _NOW
    assert c1.decided_by == "prgroom"
    assert res.dispositions["C_2"].kind is DispositionKind.WONT_FIX
    assert res.escalations == []
    assert res.stashed is False


# ───────────────────────── per-item audit failure ─────────────────────────


def test_item_with_audit_violation_flips_to_failed_only_for_that_item() -> None:
    req = _req("C_1", "C_2")
    out = FixOutput(
        items=[
            FixItemResult(
                gh_id="C_1",
                disposition=DispositionKind.FIXED,
                commit_shas=["n1"],
                recommended_gate="full",
            ),
            FixItemResult(
                gh_id="C_2", disposition=DispositionKind.FIXED, commit_shas=[]
            ),  # no commits
        ]
    )
    disp = FixDispatcherStub(out)
    git = _git(ancestors=["pre"], new=["n1"])
    res = run_fix(req, disp, git, now=_NOW, decided_by="prgroom")
    assert res.dispositions["C_1"].kind is DispositionKind.FIXED
    assert res.dispositions["C_2"].kind is DispositionKind.FAILED
    assert any(e.item is not None and e.item.identity.gh_id == "C_2" for e in res.escalations)
    # A per-item audit failure that added no orphan commits does NOT stash.
    assert res.stashed is False


# ───────────────────────── cluster-flip cause + orphan bypass ─────────────────────────


def test_cluster_flip_rationale_carries_the_hard_violation_detail() -> None:
    # A clean item swept up by a cluster-wide hard violation must carry the cause in
    # its disposition.rationale (the lifecycle reads rationale, not last_error), not
    # a generic marker. Here C_1 is a valid 'fixed' but n2 is an unclaimed orphan.
    out = FixOutput(
        items=[FixItemResult(gh_id="C_1", disposition=DispositionKind.FIXED, commit_shas=["n1"])]
    )
    git = _git(ancestors=["pre"], new=["n1", "n2"])
    res = run_fix(_req("C_1"), FixDispatcherStub(out), git, now=_NOW, decided_by="prgroom")
    assert res.stashed is True
    flipped = res.dispositions["C_1"]
    assert flipped.kind is DispositionKind.FAILED
    assert "n2" in flipped.rationale  # the orphan detail, not a generic marker


def test_swept_item_rationale_is_the_spec_string_with_no_added_prefix() -> None:
    # §8.6: on a containment sweep each affected item's FAILED rationale is exactly
    # "memory containment violation: <path>". The swept-up marker must NOT prepend
    # "cluster failed: " — that diverges from the documented contract string the
    # lifecycle/resolver read as the source of truth for the cause.
    out = FixOutput(
        items=[FixItemResult(gh_id="C_1", disposition=DispositionKind.FIXED, commit_shas=["n1"])],
        memory_writes=["/etc/passwd"],  # escapes memory_dir → hard containment BLOCK
    )
    git = _git(ancestors=["pre"], new=["n1"])  # n1 claimed → no orphan, only containment
    res = run_fix(_req("C_1"), FixDispatcherStub(out), git, now=_NOW, decided_by="prgroom")
    assert res.stashed is True
    assert res.dispositions["C_1"].rationale == "memory containment violation: /etc/passwd"


def test_ghost_row_cannot_suppress_orphan_detection() -> None:
    # A GHOST (unrequested) row claiming the new commit must not hide the orphan:
    # the orphan still fires, the cluster flips, and stash isolates the contamination.
    out = FixOutput(
        items=[
            FixItemResult(gh_id="C_1", disposition=DispositionKind.FIXED, commit_shas=["n1"]),
            FixItemResult(gh_id="GHOST", disposition=DispositionKind.FIXED, commit_shas=["n2"]),
        ]
    )
    git = _git(ancestors=["pre"], new=["n1", "n2"])
    res = run_fix(_req("C_1"), FixDispatcherStub(out), git, now=_NOW, decided_by="prgroom")
    assert res.stashed is True  # orphan detected despite the GHOST's claim
    assert "GHOST" not in res.dispositions  # unrequested rows are never dispositioned


# ───────────────────────── reconciliation against requested item set ─────────────────────────


def _malformed(disposition: Disposition) -> bool:
    return (
        disposition.kind is DispositionKind.FAILED
        and "fix output omitted requested item" in disposition.rationale
    )


def test_requested_item_missing_from_output_gets_failed_disposition_and_escalation() -> None:
    # req=[A,B] but the agent's output omits B entirely. Every requested item MUST
    # get a disposition: B is synthesized FAILED (CONTRACT_FIX_MALFORMED) + escalation.
    req = _req("A", "B")
    out = FixOutput(
        items=[
            FixItemResult(
                gh_id="A",
                disposition=DispositionKind.FIXED,
                commit_shas=["n1"],
                recommended_gate="full",
            ),
        ]
    )
    disp = FixDispatcherStub(out)
    git = _git(ancestors=["pre"], new=["n1"])
    res = run_fix(req, disp, git, now=_NOW, decided_by="prgroom")
    # Keys are exactly the authoritative requested set.
    assert set(res.dispositions) == {"A", "B"}
    assert res.dispositions["A"].kind is DispositionKind.FIXED
    assert _malformed(res.dispositions["B"])
    assert "B" in res.dispositions["B"].rationale
    # B's omission produced an escalation tied to the missing item.
    assert any(e.item is not None and e.item.identity.gh_id == "B" for e in res.escalations)
    # A bookkeeping-shape violation does not stash — no contamination on the branch.
    assert res.stashed is False


def test_extra_unrequested_item_escalates_but_gets_no_disposition() -> None:
    # The agent emits a GHOST item never requested. It MUST NOT become a disposition
    # (we never dispose an item we didn't ask about), but it IS surfaced as an escalation.
    req = _req("A")
    out = FixOutput(
        items=[
            FixItemResult(
                gh_id="A",
                disposition=DispositionKind.FIXED,
                commit_shas=["n1"],
                recommended_gate="full",
            ),
            FixItemResult(gh_id="GHOST", disposition=DispositionKind.WONT_FIX, rationale="huh"),
        ]
    )
    disp = FixDispatcherStub(out)
    git = _git(ancestors=["pre"], new=["n1"])
    res = run_fix(req, disp, git, now=_NOW, decided_by="prgroom")
    assert set(res.dispositions) == {"A"}  # GHOST is NOT disposed
    assert res.dispositions["A"].kind is DispositionKind.FIXED
    # GHOST is surfaced for visibility.
    assert any("GHOST" in e.reason for e in res.escalations)


def test_duplicate_gh_id_in_output_fails_that_item_with_one_disposition() -> None:
    # The agent lists A twice. Last-write-wins would silently clobber; instead A is
    # flipped to FAILED (CONTRACT_FIX_MALFORMED) with exactly one disposition per id.
    req = _req("A")
    out = FixOutput(
        items=[
            FixItemResult(gh_id="A", disposition=DispositionKind.FIXED, commit_shas=["n1"]),
            FixItemResult(gh_id="A", disposition=DispositionKind.WONT_FIX, rationale="other"),
        ]
    )
    disp = FixDispatcherStub(out)
    git = _git(ancestors=["pre"], new=["n1"])
    res = run_fix(req, disp, git, now=_NOW, decided_by="prgroom")
    assert set(res.dispositions) == {"A"}  # exactly one disposition for the id
    assert res.dispositions["A"].kind is DispositionKind.FAILED
    assert any(e.item is not None and e.item.identity.gh_id == "A" for e in res.escalations)


def test_duplicate_with_real_audit_violation_keeps_the_richer_violation_detail() -> None:
    # When a duplicated id's first row ALSO has a genuine audit violation (here a
    # 'fixed' with no commits), the richer per-item detail wins over the generic
    # duplicate-shape message — both flip to FAILED, but the actionable cause is kept.
    req = _req("A")
    out = FixOutput(
        items=[
            FixItemResult(gh_id="A", disposition=DispositionKind.FIXED, commit_shas=[]),
            FixItemResult(gh_id="A", disposition=DispositionKind.WONT_FIX, rationale="other"),
        ]
    )
    disp = FixDispatcherStub(out)
    git = _git(ancestors=["pre"], new=[])
    res = run_fix(req, disp, git, now=_NOW, decided_by="prgroom")
    assert res.dispositions["A"].kind is DispositionKind.FAILED
    # The per-item audit detail (no commits) is preserved, not overwritten by the
    # duplicate-shape message.
    assert "claims no commits" in res.dispositions["A"].rationale


# ───────────────────────── orphan → cluster FAILED + stash ─────────────────────────


def test_orphan_flips_all_cluster_items_to_failed_and_stashes_once() -> None:
    req = _req("C_1", "C_2")
    out = FixOutput(
        items=[
            FixItemResult(
                gh_id="C_1",
                disposition=DispositionKind.FIXED,
                commit_shas=["n1"],
                recommended_gate="full",
            ),
            FixItemResult(gh_id="C_2", disposition=DispositionKind.WONT_FIX, rationale="ok"),
        ]
    )
    disp = FixDispatcherStub(out)
    # n2 is a new commit no item claimed → orphan.
    git = _git(ancestors=["pre"], new=["n1", "n2"])
    res = run_fix(req, disp, git, now=_NOW, decided_by="prgroom")
    assert res.dispositions["C_1"].kind is DispositionKind.FAILED
    assert res.dispositions["C_2"].kind is DispositionKind.FAILED
    assert res.stashed is True
    assert git.stash_calls == 1


# ───────────────────────── containment BLOCK + stash ─────────────────────────


def test_containment_violation_flips_cluster_and_stashes() -> None:
    req = _req("C_1", "C_2", memory_dir="/run/mem")
    out = FixOutput(
        items=[
            FixItemResult(gh_id="C_1", disposition=DispositionKind.SKIPPED, rationale="x"),
            FixItemResult(gh_id="C_2", disposition=DispositionKind.SKIPPED, rationale="y"),
        ],
        memory_writes=["/etc/passwd"],
    )
    disp = FixDispatcherStub(out)
    git = _git(ancestors=["pre"], new=[])
    res = run_fix(req, disp, git, now=_NOW, decided_by="prgroom")
    assert res.dispositions["C_1"].kind is DispositionKind.FAILED
    assert res.dispositions["C_2"].kind is DispositionKind.FAILED
    assert res.stashed is True
    assert git.stash_calls == 1
    assert any(e.severity.value == "block" for e in res.escalations)


# ───────────────────────── soft memory WARN does not cluster-flip ─────────────────────────


def test_warn_memory_violation_surfaces_escalation_without_flip_or_stash() -> None:
    # §8.6: a soft per-entry WARN (here: unknown classification) means the memory
    # bookkeeping is malformed, but the actual fix commits are valid. The cluster
    # MUST NOT flip and MUST NOT stash; the WARN is surfaced as an escalation only.
    req = _req("C_1", "C_2", memory_dir="/run/mem")
    out = FixOutput(
        items=[
            FixItemResult(
                gh_id="C_1",
                disposition=DispositionKind.FIXED,
                commit_shas=["n1"],
                recommended_gate="full",
            ),
            FixItemResult(gh_id="C_2", disposition=DispositionKind.WONT_FIX, rationale="ok"),
        ],
        memory=[MemoryEntry(classification="BOGUS", content="x")],
    )
    disp = FixDispatcherStub(out)
    git = _git(ancestors=["pre"], new=["n1"])
    res = run_fix(req, disp, git, now=_NOW, decided_by="prgroom")
    # Items keep their agent dispositions — the WARN did not flip them.
    assert res.dispositions["C_1"].kind is DispositionKind.FIXED
    assert res.dispositions["C_2"].kind is DispositionKind.WONT_FIX
    # No stash for a soft WARN.
    assert res.stashed is False
    assert git.stash_calls == 0
    # The WARN is still surfaced as a WARN-severity escalation.
    assert any(e.severity is Severity.WARN for e in res.escalations)


# ───────────────────────── deferred memory + soft warnings ─────────────────────────


def test_non_contextual_memory_is_returned_as_deferred() -> None:
    req = _req("C_1", memory_dir="/run/mem")
    out = FixOutput(
        items=[FixItemResult(gh_id="C_1", disposition=DispositionKind.SKIPPED, rationale="x")],
        memory=[MemoryEntry(classification="PROJECT", content="a project convention")],
    )
    disp = FixDispatcherStub(out)
    git = _git()
    res = run_fix(req, disp, git, now=_NOW, decided_by="prgroom")
    assert [m.classification for m in res.deferred_memory] == ["PROJECT"]
    assert res.dispositions["C_1"].kind is DispositionKind.SKIPPED  # not a failure


def test_declared_but_unwritten_path_does_not_fail_the_cluster() -> None:
    # written_paths defaults to declared (MVP: declared == written), so a declared
    # path inside memory_dir is treated as written — no false soft-warning, no fail.
    # The unwritten data carried on the result is empty by construction in the MVP.
    req = _req("C_1", memory_dir="/run/mem")
    out = FixOutput(
        items=[FixItemResult(gh_id="C_1", disposition=DispositionKind.SKIPPED, rationale="x")],
        memory_writes=["/run/mem/note.md"],
    )
    disp = FixDispatcherStub(out)
    git = _git()
    res = run_fix(req, disp, git, now=_NOW, decided_by="prgroom")
    assert res.dispositions["C_1"].kind is DispositionKind.SKIPPED
    assert res.stashed is False
    assert res.unwritten == []  # MVP declared==written: soft-warning list is empty


# ───────────────────────── boundary: no state mutation ─────────────────────────


def test_run_fix_signature_takes_no_state_object() -> None:
    # The boundary guarantee: run_fix never receives PRGroomingState, so it cannot
    # mutate it. Reflect the signature to prove no `state` parameter exists.
    import inspect

    params = set(inspect.signature(run_fix).parameters)
    assert "state" not in params
    assert {"req", "dispatcher", "git", "now", "decided_by"} <= params


def test_known_thread_ids_default_to_item_thread_ids() -> None:
    # When known_thread_ids is None, run_fix derives it from the items' thread_ids,
    # so a CONTEXTUAL target_hint naming a cluster item's thread routes cleanly.
    req = _req("C_1", memory_dir="/run/mem")
    out = FixOutput(
        items=[FixItemResult(gh_id="C_1", disposition=DispositionKind.SKIPPED, rationale="x")],
        memory=[MemoryEntry(classification="CONTEXTUAL", content="note", target_hint="PRT_C_1")],
    )
    disp = FixDispatcherStub(out)
    git = _git()
    res = run_fix(req, disp, git, now=_NOW, decided_by="prgroom")
    assert res.dispositions["C_1"].kind is DispositionKind.SKIPPED  # hint resolved, no failure


def test_explicit_known_thread_ids_override_item_thread_ids() -> None:
    # A caller-supplied known_thread_ids set OVERRIDES the item-derived default:
    # a target_hint not among the item threads but present in the override resolves.
    req = _req("C_1", memory_dir="/run/mem")  # item thread is PRT_C_1
    out = FixOutput(
        items=[FixItemResult(gh_id="C_1", disposition=DispositionKind.SKIPPED, rationale="x")],
        memory=[MemoryEntry(classification="CONTEXTUAL", content="note", target_hint="PRT_OTHER")],
    )
    disp = FixDispatcherStub(out)
    git = _git()
    res = run_fix(req, disp, git, now=_NOW, decided_by="prgroom", known_thread_ids={"PRT_OTHER"})
    assert res.dispositions["C_1"].kind is DispositionKind.SKIPPED  # override resolved the hint
