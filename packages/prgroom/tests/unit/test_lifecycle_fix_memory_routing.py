"""Tests for routable-memory resolution in ``fix_pr`` (§8.3).

Two layers:

* ``resolve_routed_memory`` (helper) — resolves routable CONTEXTUAL entries into
  ``RoutedMemory`` with a realpath/no-symlink containment check immediately before
  any path-form read. A symlink inside ``memory_dir`` resolving OUTSIDE it is a hard
  breach (``blocked is not None``, route nothing); an unreadable contained path is a
  soft skip; content-form and contained path-form resolve verbatim.
* The wiring in ``_fix_one_cluster`` — a realpath breach flips the whole cluster to
  FAILED + stash + routes no memory (parity with the lexical BLOCK in
  ``agent/fix._build_result``); a clean run extends ``state.pending_memory``.

The integration tests drive ``fix_pr`` end-to-end through the harness in
``tests/unit/test_lifecycle_fix.py`` (fakes reused via import).
"""

from __future__ import annotations

from pathlib import Path

from prgroom.agent.contracts import FixInput, FixItemResult, FixOutput, MemoryEntry
from prgroom.config import PrgroomConfig
from prgroom.lifecycle.fix import fix_pr, resolve_routed_memory
from prgroom.prsession.enums import DispositionKind
from prgroom.prsession.state import RoutedMemory
from tests.unit.test_lifecycle_fix import (
    _REF,
    FakeGit,
    FixDispatcherStub,
    RecordingSink,
    _deps,
    _gh_per_cluster,
    _item,
    _out,
    _run,
    _state,
)


class _Entry:  # minimal MemoryEntry-shaped stub for the resolver
    def __init__(
        self,
        content: str | None = None,
        path: str | None = None,
        target_hint: str | None = None,
    ) -> None:
        self.classification = "CONTEXTUAL"
        self.content = content
        self.path = path
        self.target_hint = target_hint


# ───────────────────────── resolve_routed_memory (helper) ─────────────────────────


def test_content_form_resolved_verbatim(tmp_path: Path) -> None:
    warnings: list[str] = []
    routed, blocked = resolve_routed_memory(
        [_Entry(content="decided X", target_hint="PRRT_a")],
        memory_dir=str(tmp_path),
        retry=2,
        decided_by="agent",
        cluster_id="c1",
        warn=warnings.append,
    )
    assert blocked is None
    assert routed == [
        RoutedMemory(
            content="decided X",
            retry=2,
            source_item="c1#0",
            decided_by="agent",
            target_hint="PRRT_a",
        )
    ]


def test_path_form_read_verbatim(tmp_path: Path) -> None:
    f = tmp_path / "note.md"
    f.write_text("file body", encoding="utf-8")
    routed, blocked = resolve_routed_memory(
        [_Entry(path=str(f))],
        memory_dir=str(tmp_path),
        retry=1,
        decided_by="agent",
        cluster_id="c1",
        warn=lambda _m: None,
    )
    assert blocked is None
    assert routed[0].content == "file body"


def test_relative_path_is_anchored_to_memory_dir_not_cwd(tmp_path: Path) -> None:
    # The agent declares entry.path RELATIVE to memory_dir (§8.5). A relative path must
    # anchor to memory_dir, NOT resolve against CWD — else it false-BLOCKs (cluster-flip)
    # and reads the wrong file. Regression for the bare-realpath(entry.path) bug.
    (tmp_path / "note.md").write_text("anchored body", encoding="utf-8")
    routed, blocked = resolve_routed_memory(
        [_Entry(path="note.md")],
        memory_dir=str(tmp_path),
        retry=1,
        decided_by="agent",
        cluster_id="c1",
        warn=lambda _m: None,
    )
    assert blocked is None  # NOT a false containment BLOCK
    assert routed[0].content == "anchored body"  # read from memory_dir, not CWD


def test_symlink_escape_is_blocked_not_read(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET", encoding="utf-8")
    mem = tmp_path / "mem"
    mem.mkdir()
    link = mem / "evil"
    link.symlink_to(secret)  # symlink INSIDE memory_dir -> resolves OUTSIDE
    routed, blocked = resolve_routed_memory(
        [_Entry(path=str(link))],
        memory_dir=str(mem),
        retry=1,
        decided_by="agent",
        cluster_id="c1",
        warn=lambda _m: None,
    )
    assert routed == []
    assert blocked is not None
    assert "TOPSECRET" not in (blocked or "")


def test_unreadable_contained_path_is_soft_warn(tmp_path: Path) -> None:
    missing = tmp_path / "gone.md"  # contained, but does not exist
    warnings: list[str] = []
    routed, blocked = resolve_routed_memory(
        [_Entry(path=str(missing))],
        memory_dir=str(tmp_path),
        retry=1,
        decided_by="agent",
        cluster_id="c1",
        warn=warnings.append,
    )
    assert routed == []
    assert blocked is None  # soft skip, not a BLOCK
    assert warnings and "gone.md" in warnings[0]


# ───────────────────────── wiring into _fix_one_cluster ─────────────────────────


def test_clean_routable_extends_pending_memory(tmp_path: Path) -> None:
    # A thread-less CONTEXTUAL content entry is routable regardless of thread set;
    # a clean FIXED disposition (commit reported in pre..post) keeps run_fix clean.
    a = _item("a")
    dispatcher = FixDispatcherStub(
        [
            _out(
                FixItemResult(
                    gh_id="a",
                    disposition=DispositionKind.FIXED,
                    commit_shas=["s1"],
                    recommended_gate="full",
                ),
                memory=[MemoryEntry(classification="CONTEXTUAL", content="why")],
            )
        ]
    )
    out, _sink, _git = _run(_state(a), dispatcher, tmp_path, git=FakeGit(new_commits=["s1"]))
    assert [m.content for m in out.pending_memory] == ["why"]
    # The clean run kept its (non-FAILED) agent disposition.
    assert out.items[0].disposition is not None
    assert out.items[0].disposition.kind is DispositionKind.FIXED


class _SymlinkPlantingDispatcher:
    """At ``fix()`` time, plants a symlink-escape INSIDE memory_dir and returns a
    path-form CONTEXTUAL entry pointing at it. The lexical audit only checks
    ``memory_writes`` (empty here), so run_fix returns clean — the realpath flip in
    the wiring must be the SOLE cause of the FAILED flip.
    """

    def __init__(self, gh_id: str) -> None:
        self.gh_id = gh_id
        self.calls = 0
        self.requests: list[FixInput] = []

    def fix(self, request: FixInput) -> FixOutput:
        self.calls += 1
        self.requests.append(request)
        mem = Path(request.memory_dir)
        secret = mem.parent / "leaked_secret.txt"  # OUTSIDE memory_dir
        secret.write_text("TOPSECRET", encoding="utf-8")
        link = mem / "evil"  # lexically INSIDE memory_dir
        link.symlink_to(secret)
        return FixOutput(
            items=[
                FixItemResult(
                    gh_id=self.gh_id,
                    disposition=DispositionKind.FIXED,
                    commit_shas=["s1"],
                    recommended_gate="full",
                )
            ],
            memory=[MemoryEntry(classification="CONTEXTUAL", path=str(link))],
        )


def test_symlink_escape_flips_cluster_and_routes_nothing(tmp_path: Path) -> None:
    # Drive fix_pr directly (not via _run): the planter is a bespoke FixContract, not
    # a FixDispatcherStub. git=FakeGit(new_commits=["s1"]) makes the FIXED/commit audit
    # in run_fix pass CLEANLY, so the realpath flip in the wiring is the SOLE cause of
    # the FAILED flip and the one stash.
    a = _item("a")
    dispatcher = _SymlinkPlantingDispatcher(gh_id="a")
    sink = RecordingSink()
    git = FakeGit(new_commits=["s1"])
    out = fix_pr(
        _state(a),
        ref=_REF,
        gh=_gh_per_cluster(1),
        git=git,
        deps=_deps(),
        config=PrgroomConfig(),
        dispatcher=dispatcher,
        sink=sink,
        decided_by="claude opus[1m]",
        scratch_dir=tmp_path,
    )
    for item in out.items:
        assert item.disposition is not None
        assert item.disposition.kind is DispositionKind.FAILED
    assert out.pending_memory == []
    assert len(sink.emitted) >= 1
    assert git.stash_calls == 1
