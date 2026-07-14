"""`read_critical_paths` — the sole I/O boundary for the consequence axis."""

from __future__ import annotations

from pathlib import Path

import pytest

from vizsuite.adapters.critical_paths import read_critical_paths
from vizsuite.envelope import ErrorCode, VizError


def test_reads_lines_from_an_existing_marker_file(tmp_path: Path):
    (tmp_path / ".critical-paths").write_text("packages/**\nMakefile\n", encoding="utf-8")

    assert read_critical_paths(tmp_path) == ["packages/**", "Makefile"]


def test_absent_marker_file_returns_empty_list(tmp_path: Path):
    assert read_critical_paths(tmp_path) == []


def test_unreadable_marker_file_alarms_as_adapter_failure(tmp_path: Path):
    (tmp_path / ".critical-paths").write_bytes(b"\xff\xfe not valid utf-8 \x80\x81")

    with pytest.raises(VizError) as excinfo:
        read_critical_paths(tmp_path)

    assert excinfo.value.code == ErrorCode.ADAPTER_FAILURE
