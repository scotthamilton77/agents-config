"""`grind.cli.main`: argv parsing, the four verbs end-to-end, and the envelope/
exit-code contract (spec: "all output is a JSON envelope on stdout ... exit
code 0 unless the command itself failed")."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
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

_NOW = lambda: datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)  # noqa: E731


def _run(
    argv: Sequence[str],
    read_file: dict[str, str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> tuple[int, dict, str]:
    out, err = StringIO(), StringIO()
    exit_code = main(
        list(argv),
        out=out,
        err=err,
        now=now,
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


def test_create_rejects_non_finite_constant_in_seed(tmp_path: Path):
    grind_dir = tmp_path / "run"
    # A hand-authored seed with a bare `NaN` -- stdlib json.loads would accept
    # it, then re-emit it into events.jsonl/state.json as non-standard JSON.
    seed_text = '{"title":"t","repo":"r","mission":{"goal":NaN},"protocols":{},"lanes":[]}'

    exit_code, envelope, _err = _run(
        ["create", "--file", "seed.json", "--dir", str(grind_dir)],
        read_file={"seed.json": seed_text},
    )

    assert exit_code != 0
    assert envelope["ok"] is False
    assert not (grind_dir / "events.jsonl").exists()


def test_log_rejects_non_finite_constant_in_json_payload(tmp_path: Path):
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
            '{"item": "wgclw.1", "x": Infinity}',
            "--dir",
            str(grind_dir),
        ]
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


def test_check_verb_exits_zero_when_fresh(tmp_path: Path):
    grind_dir = tmp_path / "run"
    _run(
        ["create", "--file", "seed.json", "--dir", str(grind_dir)],
        read_file={"seed.json": json.dumps(_SEED)},
        now=_NOW,
    )

    exit_code, envelope, _err = _run(["check", "--dir", str(grind_dir)], now=_NOW)

    assert exit_code == 0
    assert envelope["ok"] is True
    assert envelope["stale"] is False


def test_check_verb_exits_one_when_stale(tmp_path: Path):
    grind_dir = tmp_path / "run"
    _run(
        ["create", "--file", "seed.json", "--dir", str(grind_dir)],
        read_file={"seed.json": json.dumps(_SEED)},
        now=_NOW,
    )

    exit_code, envelope, _err = _run(
        ["check", "--max-age", "10m", "--dir", str(grind_dir)],
        now=lambda: datetime(2026, 7, 19, 13, 0, 0, tzinfo=UTC),
    )

    assert exit_code == 1
    assert envelope["ok"] is True  # a stale grind is still a successful probe
    assert envelope["stale"] is True


def test_check_verb_empty_log_yields_error_envelope_and_nonzero_exit(tmp_path: Path):
    grind_dir = tmp_path / "run"

    exit_code, envelope, _err = _run(["check", "--dir", str(grind_dir)])

    assert exit_code != 0
    assert envelope["ok"] is False


def test_render_verb(tmp_path: Path):
    grind_dir = tmp_path / "run"
    _run(
        ["create", "--file", "seed.json", "--dir", str(grind_dir)],
        read_file={"seed.json": json.dumps(_SEED)},
    )

    exit_code, envelope, _err = _run(["render", "--dir", str(grind_dir)])

    assert exit_code == 0
    assert envelope["ok"] is True
    assert envelope["path"] == str(grind_dir / "dashboard.html")
    assert (grind_dir / "dashboard.html").exists()


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
