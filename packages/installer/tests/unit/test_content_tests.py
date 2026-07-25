"""Discovery and execution of the test suites shipped under ``src/``.

Pins the two anti-drift decisions: an unrunnable suite is a failure rather than
a skip (a silently-skipped suite is the failure this module prevents), and a
shipped script without a paired suite is a failure (so adding code to a skill
requires adding tests, rather than requiring someone to notice none arrived).
"""

from __future__ import annotations

from pathlib import Path

from installer.core.content_tests import (
    RUNNERS,
    SubprocessRunner,
    Suite,
    SuiteResult,
    discover_suites,
    run_suites,
)


class _RecordingRunner:
    """Records what it was asked to run and returns a scripted exit code."""

    def __init__(self, codes: dict[str, int] | None = None) -> None:
        self.codes = codes or {}
        self.ran: list[Path] = []

    def run(self, suite: Suite) -> SuiteResult:
        self.ran.append(suite.path)
        code = self.codes.get(suite.path.name, 0)
        return SuiteResult(suite=suite, returncode=code, output=f"output of {suite.path.name}")


def _src(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "src"
    for relpath, text in files.items():
        path = src / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return src


def test_suite_is_discovered_and_matched_to_its_runner(tmp_path: Path) -> None:
    src = _src(tmp_path, {"skills/a/run.js": "", "skills/a/run_test.js": ""})
    suites, violations = discover_suites(src)

    assert violations == []
    assert [s.path.name for s in suites] == ["run_test.js"]
    assert suites[0].argv == RUNNERS[".js"]


def test_shipped_script_without_a_suite_is_a_violation(tmp_path: Path) -> None:
    """Adding code to a skill must require adding tests for it; the alternative is
    hoping a reviewer notices the absence."""
    src = _src(tmp_path, {"skills/a/emit.py": "", "skills/a/emit_test.py": ""})
    _suites, ok_violations = discover_suites(src)
    assert ok_violations == []

    src2 = _src(tmp_path / "other", {"skills/a/emit.py": ""})
    _suites2, violations = discover_suites(src2)
    assert len(violations) == 1
    assert "emit.py" in violations[0]
    assert "emit_test" in violations[0]


def test_a_suite_pairs_across_extensions(tmp_path: Path) -> None:
    """The hook ships a Python script tested by a shell suite. Pairing is by stem,
    so a suite written in another language still counts as coverage."""
    src = _src(tmp_path, {"hooks/fmt.py": "", "hooks/fmt_test.sh": ""})
    suites, violations = discover_suites(src)

    assert violations == []
    assert [s.path.name for s in suites] == ["fmt_test.sh"]


def test_suite_with_no_registered_runner_fails_rather_than_skipping(tmp_path: Path) -> None:
    """A suite nothing knows how to launch must be loud. Skipping it silently is
    indistinguishable from the suite passing, which is the whole failure mode."""
    src = _src(tmp_path, {"skills/a/thing_test.rb": ""})
    suites, violations = discover_suites(src)

    assert suites == []
    assert len(violations) == 1
    assert "no registered runner" in violations[0]


def test_pytest_style_prefix_is_also_a_suite(tmp_path: Path) -> None:
    """``test_*`` is the other convention someone may reach for; treating it as a
    plain script would demand it grow a ``_test`` sibling of its own."""
    src = _src(tmp_path, {"skills/a/test_thing.py": ""})
    suites, violations = discover_suites(src)

    assert [s.path.name for s in suites] == ["test_thing.py"]
    assert violations == []


def test_build_and_cache_directories_are_not_walked(tmp_path: Path) -> None:
    """Vendored code can match every name pattern here; descending into it would
    demand suites for third-party files and run third-party tests in our gate."""
    src = _src(
        tmp_path,
        {
            "skills/a/node_modules/dep/index.js": "",
            "skills/a/node_modules/dep/index_test.js": "",
            "skills/a/__pycache__/x.py": "",
        },
    )
    suites, violations = discover_suites(src)

    assert suites == []
    assert violations == []


def test_missing_src_root_is_nothing_to_run(tmp_path: Path) -> None:
    assert discover_suites(tmp_path / "absent") == ([], [])


def test_non_script_files_need_no_suite(tmp_path: Path) -> None:
    """Only the extensions with runners are code; SKILL.md is prose."""
    src = _src(tmp_path, {"skills/a/SKILL.md": "# doc\n"})
    assert discover_suites(src) == ([], [])


def test_every_suite_runs_even_after_one_fails(tmp_path: Path) -> None:
    """Short-circuiting on the first red suite hides the state of the rest, turning
    one CI run into a queue of them."""
    src = _src(
        tmp_path,
        {
            "skills/a/a.js": "",
            "skills/a/a_test.js": "",
            "skills/b/b.js": "",
            "skills/b/b_test.js": "",
        },
    )
    suites, _violations = discover_suites(src)
    runner = _RecordingRunner(codes={"a_test.js": 1})

    results = run_suites(suites, runner=runner)

    assert [p.name for p in runner.ran] == ["a_test.js", "b_test.js"]
    assert [r.ok for r in results] == [False, True]


def test_subprocess_runner_launches_the_suite_from_its_own_directory(tmp_path: Path) -> None:
    """Suites resolve the module under test relative to themselves, so the working
    directory must be the suite's own — and the path handed to the interpreter must
    survive that change of directory."""
    src = _src(
        tmp_path,
        {
            "skills/a/fixture.txt": "present\n",
            "skills/a/probe.sh": "",
            "skills/a/probe_test.sh": "test -f fixture.txt && echo found\n",
        },
    )
    suites, _violations = discover_suites(src)

    result = SubprocessRunner().run(suites[0])

    assert result.ok
    assert "found" in result.output


def test_subprocess_runner_reports_a_failing_suites_exit_and_output(tmp_path: Path) -> None:
    src = _src(
        tmp_path,
        {"skills/a/probe.sh": "", "skills/a/probe_test.sh": 'echo "boom" >&2\nexit 3\n'},
    )
    suites, _violations = discover_suites(src)

    result = SubprocessRunner().run(suites[0])

    assert result.returncode == 3
    assert not result.ok
    assert "boom" in result.output
