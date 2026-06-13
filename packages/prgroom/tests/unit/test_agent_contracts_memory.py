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
