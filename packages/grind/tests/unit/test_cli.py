"""`grind.cli.main`: argv parsing, the four verbs end-to-end, and the envelope/
exit-code contract (spec: "all output is a JSON envelope on stdout ... exit
code 0 unless the command itself failed")."""

from __future__ import annotations

import json
from collections.abc import Sequence
from io import StringIO
from pathlib import Path

from grind.cli import main

_SEED = {
    "title": "Widget grind",
    "repo": "acme/widgets",
    "mission": {"goal": "ship widgets"},
    "protocols": {},
    "lanes": [{"id": "lane-a", "queue": [{"id": "wgclw.1", "title": "First item"}]}],
}


def _run(argv: Sequence[str], read_file: dict[str, str] | None = None) -> tuple[int, dict, str]:
    out, err = StringIO(), StringIO()
    exit_code = main(
        list(argv),
        out=out,
        err=err,
        read_file=(lambda p: (read_file or {})[p]) if read_file is not None else None,
    )
    return exit_code, json.loads(out.getvalue()), err.getvalue()


def test_create_via_file_flag(tmp_path: Path):
    grind_dir = tmp_path / "run"
    exit_code, envelope, _err = _run(
        ["create", "--file", "seed.json", "--dir", str(grind_dir)],
        read_file={"seed.json": json.dumps(_SEED)},
    )

    assert exit_code == 0
    assert envelope["ok"] is True
    assert (grind_dir / "events.jsonl").exists()
    assert (grind_dir / "state.json").exists()


def test_create_refusal_yields_nonzero_exit_and_error_envelope(tmp_path: Path):
    grind_dir = tmp_path / "run"
    _run(
        ["create", "--file", "seed.json", "--dir", str(grind_dir)],
        read_file={"seed.json": json.dumps(_SEED)},
    )

    exit_code, envelope, err = _run(
        ["create", "--file", "seed.json", "--dir", str(grind_dir)],
        read_file={"seed.json": json.dumps(_SEED)},
    )

    assert exit_code != 0
    assert envelope["ok"] is False
    assert "error" in envelope
    assert err == ""


def test_log_verb_returns_emit_back_envelope_and_exits_zero(tmp_path: Path):
    grind_dir = tmp_path / "run"
    _run(
        ["create", "--file", "seed.json", "--dir", str(grind_dir)],
        read_file={"seed.json": json.dumps(_SEED)},
    )

    exit_code, envelope, _err = _run(
        [
            "log",
            "item_started",
            "--json",
            json.dumps({"item": "wgclw.1"}),
            "--dir",
            str(grind_dir),
        ]
    )

    assert exit_code == 0
    assert envelope["ok"] is True
    assert envelope["applied"] is True
    assert envelope["delta"]["new_status"] == "in-progress"


def test_log_verb_malformed_payload_yields_nonzero_exit(tmp_path: Path):
    grind_dir = tmp_path / "run"
    _run(
        ["create", "--file", "seed.json", "--dir", str(grind_dir)],
        read_file={"seed.json": json.dumps(_SEED)},
    )

    exit_code, envelope, _err = _run(
        ["log", "pr_opened", "--json", json.dumps({"item": "wgclw.1"}), "--dir", str(grind_dir)]
    )

    assert exit_code != 0
    assert envelope["ok"] is False


def test_log_verb_invalid_json_string_yields_nonzero_exit(tmp_path: Path):
    grind_dir = tmp_path / "run"
    _run(
        ["create", "--file", "seed.json", "--dir", str(grind_dir)],
        read_file={"seed.json": json.dumps(_SEED)},
    )

    exit_code, envelope, _err = _run(
        ["log", "item_started", "--json", "{not json", "--dir", str(grind_dir)]
    )

    assert exit_code != 0
    assert envelope["ok"] is False


def test_status_default_and_full(tmp_path: Path):
    grind_dir = tmp_path / "run"
    _run(
        ["create", "--file", "seed.json", "--dir", str(grind_dir)],
        read_file={"seed.json": json.dumps(_SEED)},
    )

    exit_code, envelope, _err = _run(["status", "--dir", str(grind_dir)])
    assert exit_code == 0
    assert "state_summary" in envelope

    exit_code, envelope, _err = _run(["status", "--full", "--dir", str(grind_dir)])
    assert exit_code == 0
    assert "state" in envelope


def test_finish_verb(tmp_path: Path):
    grind_dir = tmp_path / "run"
    _run(
        ["create", "--file", "seed.json", "--dir", str(grind_dir)],
        read_file={"seed.json": json.dumps(_SEED)},
    )

    exit_code, envelope, _err = _run(["finish", "--summary", "shipped it", "--dir", str(grind_dir)])

    assert exit_code == 0
    assert envelope["ok"] is True
    assert envelope["state_summary"]["finished"] is True


def test_dir_defaults_to_cwd(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exit_code, _envelope, _err = _run(
        ["create", "--file", "seed.json"], read_file={"seed.json": json.dumps(_SEED)}
    )

    assert exit_code == 0
    assert (tmp_path / "events.jsonl").exists()


def test_unknown_verb_yields_usage_error_not_a_stack_trace():
    exit_code, envelope, err = _run(["bogus-verb"])

    assert exit_code != 0
    assert envelope["ok"] is False
    assert err == ""


def test_missing_seed_file_yields_error_envelope_not_a_traceback(tmp_path: Path):
    grind_dir = tmp_path / "run"
    exit_code, envelope, _err = _run(
        ["create", "--file", "seed.json", "--dir", str(grind_dir)],
        read_file={},
    )

    assert exit_code != 0
    assert envelope["ok"] is False
