"""`grind.store`: events.jsonl I/O, the write-path torn-tail repair, and
refold-from-zero (spec "Torn tail" + "The fold refolds from zero on every
command"). Read-side torn-tail tolerance itself is `grind.log`'s job (already
tested); this module is what makes the log appendable again after a crash."""

from __future__ import annotations

import json
from pathlib import Path

from grind.store import (
    append_event,
    events_path,
    is_log_nonempty,
    load_events,
    quarantine_path,
    read_raw_log,
    repair_torn_tail,
)


def _write_raw(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_is_log_nonempty_false_for_missing_and_empty_and_whitespace_only(tmp_path: Path):
    assert is_log_nonempty(tmp_path) is False
    _write_raw(events_path(tmp_path), "")
    assert is_log_nonempty(tmp_path) is False
    _write_raw(events_path(tmp_path), "\n\n")
    assert is_log_nonempty(tmp_path) is False


def test_is_log_nonempty_true_once_an_event_line_exists(tmp_path: Path):
    _write_raw(events_path(tmp_path), '{"ts":"t","type":"grind_created"}\n')
    assert is_log_nonempty(tmp_path) is True


def test_repair_torn_tail_no_op_when_file_ends_with_newline(tmp_path: Path):
    _write_raw(events_path(tmp_path), '{"ts":"t","type":"item_started","item":"a"}\n')
    assert repair_torn_tail(tmp_path) is None
    assert read_raw_log(tmp_path).endswith("\n")


def test_repair_torn_tail_no_op_when_no_log_exists(tmp_path: Path):
    assert repair_torn_tail(tmp_path) is None


def test_repair_torn_tail_appends_missing_newline_for_a_complete_last_line(tmp_path: Path):
    complete_event = '{"ts":"t","type":"item_started","item":"a"}'
    _write_raw(events_path(tmp_path), complete_event)  # no trailing newline

    repair = repair_torn_tail(tmp_path)

    assert repair is not None
    assert repair.quarantined is False
    assert read_raw_log(tmp_path) == complete_event + "\n"
    # The event itself survives -- it was a durable transition, only the
    # newline was lost mid-crash.
    events = load_events(tmp_path)
    assert events == [{"ts": "t", "type": "item_started", "item": "a"}]


def test_repair_torn_tail_quarantines_an_unparsable_fragment(tmp_path: Path):
    good_line = '{"ts":"t1","type":"item_started","item":"a"}\n'
    fragment = '{"ts":"t2","type":"pr_opened","item'  # truncated mid-write
    _write_raw(events_path(tmp_path), good_line + fragment)

    repair = repair_torn_tail(tmp_path)

    assert repair is not None
    assert repair.quarantined is True
    assert read_raw_log(tmp_path) == good_line
    assert load_events(tmp_path) == [{"ts": "t1", "type": "item_started", "item": "a"}]
    quarantined = quarantine_path(tmp_path).read_text(encoding="utf-8")
    assert fragment in quarantined


def test_repair_torn_tail_quarantine_sidecar_is_append_only(tmp_path: Path):
    _write_raw(events_path(tmp_path), "not json at all")
    repair_torn_tail(tmp_path)
    _write_raw(events_path(tmp_path), "also not json")
    repair_torn_tail(tmp_path)

    quarantined_lines = quarantine_path(tmp_path).read_text(encoding="utf-8").splitlines()
    assert quarantined_lines == ["not json at all", "also not json"]


def test_append_event_creates_the_directory_and_the_log(tmp_path: Path):
    grind_dir = tmp_path / "nested" / "grind"
    append_event(grind_dir, {"ts": "t", "type": "grind_created"})

    assert load_events(grind_dir) == [{"ts": "t", "type": "grind_created"}]


def test_append_event_repairs_a_torn_tail_before_appending(tmp_path: Path):
    complete_event = '{"ts":"t1","type":"item_started","item":"a"}'
    _write_raw(events_path(tmp_path), complete_event)  # missing trailing newline

    repair = append_event(tmp_path, {"ts": "t2", "type": "pr_opened", "item": "a", "pr": 1})

    assert repair is not None
    assert repair.quarantined is False
    events = load_events(tmp_path)
    assert events == [
        {"ts": "t1", "type": "item_started", "item": "a"},
        {"ts": "t2", "type": "pr_opened", "item": "a", "pr": 1},
    ]


def test_append_event_serializes_json_one_line_per_event(tmp_path: Path):
    append_event(tmp_path, {"ts": "t1", "type": "grind_created"})
    append_event(tmp_path, {"ts": "t2", "type": "item_started", "item": "a"})

    lines = read_raw_log(tmp_path).splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["type"] == "grind_created"
    assert json.loads(lines[1])["type"] == "item_started"
