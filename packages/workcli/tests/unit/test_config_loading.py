"""Behavioral tests for workcli.config.load_config."""

from __future__ import annotations

from pathlib import Path

import pytest

from workcli.config import load_config
from workcli.envelope import ErrorCode, WorkError

VALID_TRACKS = """
[tracks]
names = ["alpha", "beta", "gamma"]
organizing-only = ["gamma"]
enforcement = "advisory"

[operating-model]
milestone-wip-cap = 2
wip-exempt-milestones = ["proj-m1"]
"""


def _repo(tmp_path: Path, config_text: str | None = VALID_TRACKS) -> Path:
    """A fake git repo root: .git marker + optional project-config.toml."""
    (tmp_path / ".git").mkdir()
    if config_text is not None:
        (tmp_path / "project-config.toml").write_text(config_text, encoding="utf-8")
    return tmp_path


def test_finds_config_upward_from_repo_subdirectory(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    subdir = root / "packages" / "workcli"
    subdir.mkdir(parents=True)

    config = load_config(subdir)

    assert config.names == ("alpha", "beta", "gamma")
    assert config.organizing_only == ("gamma",)
    assert config.enforcement == "advisory"
    assert config.milestone_wip_cap == 2
    assert config.wip_exempt_milestones == ("proj-m1",)


def test_search_stops_at_git_root(tmp_path: Path) -> None:
    # Config ABOVE the git root must not be found: the root bounds the search.
    (tmp_path / "project-config.toml").write_text(VALID_TRACKS, encoding="utf-8")
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()

    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.code is ErrorCode.NOT_CONFIGURED
    assert exc_info.value.detail["reason"] == "not-found"


def test_outside_any_git_repo_is_not_configured(tmp_path: Path) -> None:
    # No .git anywhere on the walk -> treated as "no config found",
    # even when a project-config.toml exists in a parent dir. REGRESSION PIN:
    # a naive walk that checks for the config file before establishing a git
    # root adopts that unrelated parent config instead of failing safe --
    # this test is the tripwire for that ordering bug.
    (tmp_path / "project-config.toml").write_text(VALID_TRACKS, encoding="utf-8")
    workdir = tmp_path / "nested"
    workdir.mkdir()

    with pytest.raises(WorkError) as exc_info:
        load_config(workdir)
    assert exc_info.value.detail["reason"] == "not-found"


def test_explicit_config_flag_overrides_search(tmp_path: Path) -> None:
    root = _repo(tmp_path)  # valid config at root...
    elsewhere = tmp_path / "elsewhere.toml"
    elsewhere.write_text(
        VALID_TRACKS.replace('"alpha", "beta", "gamma"', '"delta"').replace('["gamma"]', "[]"),
        encoding="utf-8",
    )

    config = load_config(root, explicit_path=str(elsewhere))
    assert config.names == ("delta",)


def test_explicit_config_flag_missing_path_is_not_configured(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    with pytest.raises(WorkError) as exc_info:
        load_config(root, explicit_path=str(tmp_path / "nope.toml"))
    assert exc_info.value.code is ErrorCode.NOT_CONFIGURED


def test_malformed_toml_is_invalid_and_names_the_problem(tmp_path: Path) -> None:
    root = _repo(tmp_path, config_text="[tracks\nnames = not toml")
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.code is ErrorCode.NOT_CONFIGURED
    assert exc_info.value.detail["reason"] == "invalid"
    assert "malformed TOML" in exc_info.value.message


def test_non_utf8_config_is_invalid_not_a_crash(tmp_path: Path) -> None:
    # REGRESSION PIN (Codex finding): read_text(encoding="utf-8") raises
    # UnicodeDecodeError on undecodable bytes -- uncaught, that would surface
    # as E_INTERNAL instead of the track layer's own typed failure.
    root = _repo(tmp_path, config_text=None)
    (root / "project-config.toml").write_bytes(b"[tracks]\nnames = [\xff\xfe]\n")
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.code is ErrorCode.NOT_CONFIGURED
    assert exc_info.value.detail["reason"] == "invalid"
    assert "not valid UTF-8" in exc_info.value.message


def test_missing_tracks_table_reads_as_not_found(tmp_path: Path) -> None:
    root = _repo(tmp_path, config_text='[project]\nname = "x"\n')
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "not-found"


def test_non_list_names_is_invalid(tmp_path: Path) -> None:
    root = _repo(tmp_path, config_text='[tracks]\nnames = "alpha"\n')
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "invalid"
    assert "[tracks].names" in exc_info.value.message


def test_enforcement_omitted_defaults_to_advisory(tmp_path: Path) -> None:
    # The config-layer leg: an omitted enforcement key parses as advisory.
    root = _repo(tmp_path, config_text='[tracks]\nnames = ["alpha"]\n')
    assert load_config(root).enforcement == "advisory"


def test_bogus_enforcement_value_is_invalid(tmp_path: Path) -> None:
    root = _repo(tmp_path, config_text='[tracks]\nnames = ["alpha"]\nenforcement = "yolo"\n')
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "invalid"


def test_organizing_only_outside_names_is_invalid(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        config_text='[tracks]\nnames = ["alpha"]\norganizing-only = ["beta"]\n',
    )
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "invalid"


def test_operating_model_absent_yields_no_wip_cap(tmp_path: Path) -> None:
    root = _repo(tmp_path, config_text='[tracks]\nnames = ["alpha"]\n')
    config = load_config(root)
    assert config.milestone_wip_cap is None
    assert config.wip_exempt_milestones == ()


def test_non_table_operating_model_is_invalid(tmp_path: Path) -> None:
    # Malformed, not omitted: must fail loud, never silently disable lint's
    # WIP check. (Top-level key must precede the [tracks] table in TOML.)
    root = _repo(tmp_path, config_text='operating-model = "bad"\n[tracks]\nnames = ["alpha"]\n')
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "invalid"
    assert "[operating-model]" in exc_info.value.message


# -- [operating-model].backlog-groom-nag-days / .groom-state-bead (groom state) --


def test_groom_fields_parsed(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        config_text="""
[tracks]
names = ["alpha"]

[operating-model]
backlog-groom-nag-days = 7
groom-state-bead = "proj-groom1"
""",
    )
    config = load_config(root)
    assert config.backlog_groom_nag_days == 7
    assert config.groom_state_bead == "proj-groom1"


def test_groom_fields_omitted_are_none(tmp_path: Path) -> None:
    root = _repo(tmp_path, config_text='[tracks]\nnames = ["alpha"]\n')
    config = load_config(root)
    assert config.backlog_groom_nag_days is None
    assert config.groom_state_bead is None


def test_groom_state_bead_empty_string_is_none(tmp_path: Path) -> None:
    # A repo may ship groom-state-bead = "" as a placeholder until its
    # groom-state bead is minted -- empty string means "not yet configured",
    # not an error.
    root = _repo(
        tmp_path,
        config_text='[tracks]\nnames = ["alpha"]\n[operating-model]\ngroom-state-bead = ""\n',
    )
    assert load_config(root).groom_state_bead is None


def test_groom_state_bead_non_string_is_invalid(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        config_text='[tracks]\nnames = ["alpha"]\n[operating-model]\ngroom-state-bead = 5\n',
    )
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "invalid"
    assert "groom-state-bead" in exc_info.value.message


def test_backlog_groom_nag_days_bool_is_invalid(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        config_text=(
            '[tracks]\nnames = ["alpha"]\n[operating-model]\nbacklog-groom-nag-days = true\n'
        ),
    )
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "invalid"
    assert "backlog-groom-nag-days" in exc_info.value.message


def test_backlog_groom_nag_days_negative_is_invalid(tmp_path: Path) -> None:
    # REGRESSION PIN (Codex finding): a negative threshold makes day 0
    # (immediately after `work groom --done`) already breached (0 > -1),
    # defeating the reset --done is meant to guarantee.
    root = _repo(
        tmp_path,
        config_text=(
            '[tracks]\nnames = ["alpha"]\n[operating-model]\nbacklog-groom-nag-days = -1\n'
        ),
    )
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "invalid"
    assert "backlog-groom-nag-days" in exc_info.value.message


def test_git_file_marker_counts_as_root(tmp_path: Path) -> None:
    # Linked worktrees have a .git FILE, not a dir -- the search must still
    # treat that directory as the root boundary.
    root = tmp_path / "wt"
    root.mkdir()
    (root / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
    (root / "project-config.toml").write_text(VALID_TRACKS, encoding="utf-8")

    assert load_config(root).names == ("alpha", "beta", "gamma")


# -- [extraction.pressure] / [extraction.eligibility] (extraction policy) --


def test_extraction_tables_absent_yield_safe_defaults(tmp_path: Path) -> None:
    root = _repo(tmp_path, config_text='[tracks]\nnames = ["alpha"]\n')
    config = load_config(root)
    assert config.extraction_max_track_backlog is None
    assert config.extraction_external_consumer_tracks == ()
    assert config.extraction_independent_release_tracks == ()
    assert config.extraction_max_cross_track_edges is None


def test_extraction_pressure_and_eligibility_parsed(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        config_text="""
[tracks]
names = ["alpha", "beta"]

[extraction.pressure]
max-track-backlog = 100
external-consumer-tracks = ["alpha"]
independent-release-tracks = ["beta"]

[extraction.eligibility]
max-cross-track-edges = 3
""",
    )
    config = load_config(root)
    assert config.extraction_max_track_backlog == 100
    assert config.extraction_external_consumer_tracks == ("alpha",)
    assert config.extraction_independent_release_tracks == ("beta",)
    assert config.extraction_max_cross_track_edges == 3


def test_external_consumer_tracks_outside_names_is_invalid(tmp_path: Path) -> None:
    # REGRESSION PIN (Codex finding): a typo'd track name in a declared
    # pressure list must fail loud, not silently produce zero pressure
    # signal -- mirrors [tracks].organizing-only's existing vocabulary check.
    root = _repo(
        tmp_path,
        config_text='[tracks]\nnames = ["alpha"]\n'
        '[extraction.pressure]\nexternal-consumer-tracks = ["prgoom"]\n',
    )
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "invalid"
    assert "external-consumer-tracks" in exc_info.value.message
    assert "prgoom" in exc_info.value.message


def test_independent_release_tracks_outside_names_is_invalid(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        config_text='[tracks]\nnames = ["alpha"]\n'
        '[extraction.pressure]\nindependent-release-tracks = ["ghost"]\n',
    )
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "invalid"
    assert "independent-release-tracks" in exc_info.value.message
    assert "ghost" in exc_info.value.message


def test_non_table_extraction_is_invalid(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        config_text='extraction = "bad"\n[tracks]\nnames = ["alpha"]\n',
    )
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "invalid"
    assert "[extraction]" in exc_info.value.message


def test_non_table_extraction_pressure_is_invalid(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        config_text='[tracks]\nnames = ["alpha"]\n[extraction]\npressure = "bad"\n',
    )
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "invalid"
    assert "[extraction.pressure]" in exc_info.value.message


def test_non_table_extraction_eligibility_is_invalid(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        config_text='[tracks]\nnames = ["alpha"]\n[extraction]\neligibility = "bad"\n',
    )
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "invalid"
    assert "[extraction.eligibility]" in exc_info.value.message


def test_max_track_backlog_bool_is_invalid(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        config_text='[tracks]\nnames = ["alpha"]\n'
        "[extraction.pressure]\nmax-track-backlog = true\n",
    )
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "invalid"
    assert "max-track-backlog" in exc_info.value.message


def test_max_cross_track_edges_bool_is_invalid(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        config_text='[tracks]\nnames = ["alpha"]\n'
        "[extraction.eligibility]\nmax-cross-track-edges = false\n",
    )
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "invalid"
    assert "max-cross-track-edges" in exc_info.value.message


def test_external_consumer_tracks_non_list_is_invalid(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        config_text='[tracks]\nnames = ["alpha"]\n'
        '[extraction.pressure]\nexternal-consumer-tracks = "alpha"\n',
    )
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "invalid"
    assert "external-consumer-tracks" in exc_info.value.message
