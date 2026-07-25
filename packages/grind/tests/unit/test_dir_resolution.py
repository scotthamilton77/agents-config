"""The `--dir` resolution contract: the omitted-flag path can never silently
act on a different state than the explicit-flag path.

Every test here is a variation on the reported defect -- create with an
explicit `--dir`, then omit it on a later call -- and asserts one of the only
two acceptable outcomes: the *same* grind, or a loud command error. There is
no third outcome where an empty board is reported as fact.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest

from grind.cli import main
from grind.resolve import resolve_existing, resolve_for_create, search_upward

_SEED = {
    "title": "Widget grind",
    "repo": "acme/widgets",
    "mission": {"goal": "ship widgets"},
    "protocols": {},
    "lanes": [{"id": "lane-a", "queue": [{"id": "wgclw.1", "title": "First item"}]}],
}

_NOW: Callable[[], datetime] = lambda: datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)  # noqa: E731

# Every verb but `create` acts on a grind that already exists, so every one of
# them is exposed to the defect.
_STATE_READING_INVOCATIONS = [
    ["status"],
    ["status", "--full"],
    ["check"],
    ["render"],
    ["log", "item_started", "--json", json.dumps({"item": "wgclw.1"})],
    ["finish", "--summary", "shipped it"],
]

_ARTIFACTS = ("events.jsonl", "state.json", "dashboard.html")


def _run(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    read_file: dict[str, str] | None = None,
) -> tuple[int, dict, str]:
    out, err = StringIO(), StringIO()
    exit_code = main(
        list(argv),
        out=out,
        err=err,
        now=_NOW,
        read_file=(lambda p: (read_file or {})[p]) if read_file is not None else None,
        cwd=cwd,
        env=env or {},
    )
    return exit_code, json.loads(out.getvalue()), err.getvalue()


def _seeded_grind(tmp_path: Path) -> Path:
    grind_dir = tmp_path / "run"
    exit_code, _envelope, _err = _run(
        ["create", "--file", "seed.json", "--dir", str(grind_dir)],
        cwd=tmp_path,
        read_file={"seed.json": json.dumps(_SEED)},
    )
    assert exit_code == 0
    return grind_dir


_IDS = [" ".join(inv[:2]) for inv in _STATE_READING_INVOCATIONS]


@pytest.mark.parametrize("invocation", _STATE_READING_INVOCATIONS, ids=_IDS)
def test_omitted_flag_far_from_the_grind_fails_loudly_and_writes_nothing(
    tmp_path: Path, invocation: list[str]
):
    """The reported defect, verb by verb: created under `--dir run/`, invoked
    from an unrelated cwd without the flag. Previously each of these folded an
    empty cwd and answered confidently; now none of them can."""
    grind_dir = _seeded_grind(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    exit_code, envelope, err = _run(invocation, cwd=elsewhere)

    assert exit_code != 0
    assert envelope["ok"] is False
    assert "no grind state found" in envelope["error"]["message"]
    assert err == ""
    # No orphan state split off into the cwd, and the real grind is untouched.
    for artifact in _ARTIFACTS:
        assert not (elsewhere / artifact).exists()
    assert json.loads((grind_dir / "state.json").read_text(encoding="utf-8"))["finished"] is False


@pytest.mark.parametrize("invocation", _STATE_READING_INVOCATIONS, ids=_IDS)
def test_omitted_flag_inside_the_grind_matches_the_explicit_flag_exactly(
    tmp_path: Path, invocation: list[str]
):
    """The other half of the contract: where the omitted-flag path *does*
    answer, it answers identically to the explicit-flag path."""
    explicit_dir = _seeded_grind(tmp_path / "explicit")
    implicit_dir = _seeded_grind(tmp_path / "implicit")

    explicit_code, explicit_envelope, _ = _run(
        [*invocation, "--dir", str(explicit_dir)], cwd=tmp_path
    )
    implicit_code, implicit_envelope, _ = _run(invocation, cwd=implicit_dir)

    assert implicit_code == explicit_code
    # `render` reports the directory it wrote to, which is the one difference
    # two separate grinds are entitled to have.
    explicit_envelope.pop("path", None)
    implicit_envelope.pop("path", None)
    assert implicit_envelope == explicit_envelope


def test_omitted_flag_in_a_subdirectory_resolves_upward_to_the_grind(tmp_path: Path):
    grind_dir = _seeded_grind(tmp_path)
    nested = grind_dir / "notes" / "scratch"
    nested.mkdir(parents=True)

    exit_code, envelope, _err = _run(["status"], cwd=nested)

    assert exit_code == 0
    assert envelope["state_summary"]["title"] == "Widget grind"
    for artifact in _ARTIFACTS:
        assert not (nested / artifact).exists()


def test_omitted_flag_log_appends_to_the_resolved_grind_not_an_orphan_log(tmp_path: Path):
    grind_dir = _seeded_grind(tmp_path)
    nested = grind_dir / "notes"
    nested.mkdir()

    exit_code, envelope, _err = _run(
        ["log", "item_started", "--json", json.dumps({"item": "wgclw.1"})], cwd=nested
    )

    assert exit_code == 0
    assert envelope["delta"]["new_status"] == "in-progress"
    assert not (nested / "events.jsonl").exists()
    assert len((grind_dir / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()) == 2


def test_grind_dir_env_var_is_honoured_when_the_flag_is_absent(tmp_path: Path):
    grind_dir = _seeded_grind(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    exit_code, envelope, _err = _run(["status"], cwd=elsewhere, env={"GRIND_DIR": str(grind_dir)})

    assert exit_code == 0
    assert envelope["state_summary"]["title"] == "Widget grind"


def test_explicit_flag_beats_the_env_var(tmp_path: Path):
    flagged = _seeded_grind(tmp_path / "flagged")
    from_env = _seeded_grind(tmp_path / "env")
    _run(["finish", "--summary", "env grind is done", "--dir", str(from_env)], cwd=tmp_path)

    exit_code, envelope, _err = _run(
        ["status", "--dir", str(flagged)], cwd=tmp_path, env={"GRIND_DIR": str(from_env)}
    )

    assert exit_code == 0
    assert envelope["state_summary"]["finished"] is False


def test_blank_env_var_is_treated_as_unset(tmp_path: Path):
    grind_dir = _seeded_grind(tmp_path)

    exit_code, envelope, _err = _run(["status"], cwd=grind_dir, env={"GRIND_DIR": "   "})

    assert exit_code == 0
    assert envelope["state_summary"]["title"] == "Widget grind"


def test_env_var_naming_an_empty_directory_fails_loudly(tmp_path: Path):
    _seeded_grind(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()

    exit_code, envelope, _err = _run(["status"], cwd=tmp_path, env={"GRIND_DIR": str(empty)})

    assert exit_code != 0
    assert envelope["ok"] is False
    assert "GRIND_DIR" in envelope["error"]["message"]


def test_explicit_flag_at_a_stateless_directory_fails_loudly(tmp_path: Path):
    """A mistyped `--dir` is the same failure as a missing one -- an empty fold
    reported as fact -- so it gets the same refusal, not an empty board."""
    _seeded_grind(tmp_path)

    exit_code, envelope, _err = _run(["status", "--dir", str(tmp_path / "typo")], cwd=tmp_path)

    assert exit_code != 0
    assert envelope["ok"] is False
    assert "--dir" in envelope["error"]["message"]


def test_create_still_defaults_to_the_current_directory(tmp_path: Path):
    """`create` is the one verb whose target legitimately holds no state, so it
    keeps the spec's documented `default: cwd` and never searches upward."""
    _seeded_grind(tmp_path)
    nested = tmp_path / "run" / "second"
    nested.mkdir()

    exit_code, envelope, _err = _run(
        ["create", "--file", "seed.json"],
        cwd=nested,
        read_file={"seed.json": json.dumps(_SEED)},
    )

    assert exit_code == 0
    assert envelope["ok"] is True
    assert (nested / "events.jsonl").exists()


def test_create_honours_the_env_var(tmp_path: Path):
    target = tmp_path / "from-env"

    exit_code, _envelope, _err = _run(
        ["create", "--file", "seed.json"],
        cwd=tmp_path,
        env={"GRIND_DIR": str(target)},
        read_file={"seed.json": json.dumps(_SEED)},
    )

    assert exit_code == 0
    assert (target / "events.jsonl").exists()
    assert not (tmp_path / "events.jsonl").exists()


def test_no_verb_yields_a_usage_error_envelope_not_a_traceback(tmp_path: Path):
    """The no-verb namespace carries no `--dir` at all; resolving one before
    checking the verb turned this into an "internal error" envelope."""
    exit_code, envelope, err = _run([], cwd=tmp_path)

    assert exit_code != 0
    assert envelope["ok"] is False
    assert "no verb given" in envelope["error"]["message"]
    assert err == ""


def test_search_upward_finds_nothing_above_a_bare_tree(tmp_path: Path):
    assert search_upward(tmp_path) is None


def test_resolve_for_create_prefers_the_flag_over_the_env_var(tmp_path: Path):
    resolved = resolve_for_create(
        str(tmp_path / "flagged"), cwd=tmp_path, env={"GRIND_DIR": str(tmp_path / "env")}
    )

    assert resolved.path == tmp_path / "flagged"
    assert resolved.source == "--dir"


def test_resolve_existing_reports_the_search_as_its_source(tmp_path: Path):
    grind_dir = _seeded_grind(tmp_path)

    resolved = resolve_existing(None, cwd=grind_dir, env={})

    assert resolved.path == grind_dir
    assert resolved.source == "search"
