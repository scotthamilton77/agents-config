"""Tests for the §8.5 memory-channel extension to ``FixOutput`` (additive).

The fix contract output grows two channels (§8.5): ``memory_writes`` (scratch
paths declared by the agent) and a classified ``memory`` channel. Parsing is
deliberately LENIENT — validation is the audit layer's job (§8.6), so a bad
memory entry must survive ``from_dict`` as data and fail later in the audit, not
trip a parse error that the dispatcher would mistake for a malformed chain link.
"""

from __future__ import annotations

from prgroom.agent.contracts import FixOutput, MemoryEntry
from prgroom.prsession.enums import DispositionKind


def test_fix_output_defaults_memory_channels_empty() -> None:
    # Backward-compat: a pre-§8.5 payload (no memory keys) parses with empty
    # channels, so the dispatcher + existing tests keep passing.
    out = FixOutput.from_dict(
        {"items": [{"gh_id": "C_1", "disposition": "skipped", "rationale": "x"}]}
    )
    assert out.memory_writes == []
    assert out.memory == []
    assert out.items[0].disposition is DispositionKind.SKIPPED


def test_fix_output_parses_memory_writes_list() -> None:
    out = FixOutput.from_dict({"items": [], "memory_writes": ["scratch/a.md", "scratch/b.md"]})
    assert out.memory_writes == ["scratch/a.md", "scratch/b.md"]


def test_memory_entry_parses_inline_content_form() -> None:
    out = FixOutput.from_dict(
        {
            "items": [],
            "memory": [{"content": "adopt Result<T>", "classification": "CONTEXTUAL"}],
        }
    )
    assert out.memory == [MemoryEntry(classification="CONTEXTUAL", content="adopt Result<T>")]


def test_memory_entry_parses_file_form_with_target_hint() -> None:
    out = FixOutput.from_dict(
        {
            "items": [],
            "memory": [
                {"path": "scratch/note.md", "classification": "CONTEXTUAL", "target_hint": "PRT_1"}
            ],
        }
    )
    assert out.memory == [
        MemoryEntry(classification="CONTEXTUAL", path="scratch/note.md", target_hint="PRT_1")
    ]


def test_memory_entry_keeps_unknown_classification_as_raw_string() -> None:
    # Lenient parse: an unknown classification must come through as data so the
    # AUDIT (not the parser) rejects it. Enum-parsing here would mis-route a bad
    # value into a dispatcher chain-fallthrough.
    out = FixOutput.from_dict(
        {"items": [], "memory": [{"content": "x", "classification": "BOGUS"}]}
    )
    assert out.memory[0].classification == "BOGUS"


def test_memory_entry_missing_classification_defaults_empty() -> None:
    # A missing classification is not a parse error — it becomes "" and the audit
    # flags it as an unknown class.
    entry = MemoryEntry.from_dict({"content": "x"})
    assert entry.classification == ""
    assert entry.content == "x"
    assert entry.path is None
    assert entry.target_hint is None


def test_memory_writes_non_list_parses_empty_not_raises() -> None:
    # Leniency is type-level too: an agent emitting `null` / a string / a non-list
    # for memory_writes must NOT raise (which the dispatcher would mistake for a
    # malformed chain link and fall through, discarding valid item dispositions).
    for bad in (None, "scratch/a.md", 42, {"a": 1}):
        out = FixOutput.from_dict({"items": [], "memory_writes": bad})
        assert out.memory_writes == []


def test_memory_non_list_parses_empty_not_raises() -> None:
    for bad in (None, "CONTEXTUAL", 7):
        out = FixOutput.from_dict({"items": [], "memory": bad})
        assert out.memory == []


def test_memory_writes_keeps_only_string_elements() -> None:
    # A non-string element cannot be a real write path and would crash the §8.6
    # containment check (os.path on a non-str); drop it rather than carry a landmine.
    out = FixOutput.from_dict({"items": [], "memory_writes": ["scratch/a.md", 5, None]})
    assert out.memory_writes == ["scratch/a.md"]


def test_memory_skips_non_dict_entries() -> None:
    # A non-dict memory entry is malformed shape, not a routable entry; skip it so
    # the valid entries (and the item dispositions) survive the parse.
    out = FixOutput.from_dict(
        {
            "items": [],
            "memory": ["not-a-dict", {"content": "x", "classification": "CONTEXTUAL"}, 9],
        }
    )
    assert out.memory == [MemoryEntry(classification="CONTEXTUAL", content="x")]
