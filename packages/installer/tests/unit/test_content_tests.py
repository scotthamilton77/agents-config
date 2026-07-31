"""Discovery and execution of the test suites shipped under ``src/``.

Pins the three anti-drift decisions: an unrunnable suite is a failure rather
than a skip (a silently-skipped suite is the failure this module prevents), a
shipped script without a paired suite is a failure (so adding code to a skill
requires adding tests, rather than requiring someone to notice none arrived),
and a suite that exits 0 without reporting a clean pass is a failure (so an
empty or swallowed run cannot read as a green one).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.content_tests import (
    RUNNERS,
    SubprocessRunner,
    Suite,
    SuiteResult,
    discover_suites,
    run_suites,
)

# What a clean node:test run prints under the pinned TAP reporter. The fixtures
# below are all .js, so this is what a passing fake has to emit.
_CLEAN_JS = "# pass 1\n"


class _RecordingRunner:
    """Records what it was asked to run and returns a scripted exit code."""

    def __init__(self, codes: dict[str, int] | None = None) -> None:
        self.codes = codes or {}
        self.ran: list[Path] = []

    def run(self, suite: Suite) -> SuiteResult:
        self.ran.append(suite.path)
        code = self.codes.get(suite.path.name, 0)
        return SuiteResult(suite=suite, returncode=code, output=_CLEAN_JS)


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
    assert suites[0].runner is RUNNERS[".js"]


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


def test_a_pytest_style_suite_counts_as_coverage_for_its_script(tmp_path: Path) -> None:
    """``test_foo.py`` is recognised as a suite, so it must also satisfy ``foo.py``'s
    pairing requirement. Recognising one convention while demanding the other tells
    a contributor who wrote real tests that they have none — the gate lying in the
    one direction that makes people distrust it."""
    src = _src(tmp_path, {"skills/a/emit.py": "", "skills/a/test_emit.py": ""})
    suites, violations = discover_suites(src)

    assert violations == []
    assert [s.path.name for s in suites] == ["test_emit.py"]


def test_the_pairing_violation_names_both_accepted_conventions(tmp_path: Path) -> None:
    """The message is the only instruction a contributor gets; naming one form when
    two are accepted sends them to the narrower one for no reason."""
    src = _src(tmp_path, {"skills/a/emit.py": ""})
    _suites, violations = discover_suites(src)

    assert "emit_test.*" in violations[0]
    assert "test_emit.*" in violations[0]


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
            "skills/a/probe_test.sh": 'test -f fixture.txt && echo found\necho "PASS=1 FAIL=0"\n',
        },
    )
    suites, _violations = discover_suites(src)

    result = SubprocessRunner().run(suites[0])

    assert result.ok
    assert "found" in result.output


def test_a_hanging_suite_is_a_failed_suite_not_a_hung_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shipped suite that waits on a port, a prompt, or a lock would otherwise
    hang `make ci` until the job-level kill — which reports as infrastructure flake
    rather than as the suite that caused it, and takes every suite behind it down
    unrun. The kill is reported as one failed suite so the rest still run."""
    monkeypatch.setattr("installer.core.content_tests._SUITE_TIMEOUT", 1)
    src = _src(tmp_path, {"skills/a/probe.sh": "", "skills/a/probe_test.sh": "sleep 30\n"})
    suites, _violations = discover_suites(src)

    result = SubprocessRunner().run(suites[0])

    assert not result.ok
    assert result.returncode == 124
    assert "timed out after 1s" in result.output


def test_partial_output_from_a_killed_suite_survives_whatever_form_it_arrives_in() -> None:
    """``TimeoutExpired`` carries whatever the suite buffered before the kill — the
    only clue to where it hung — and does not honour ``text=True`` consistently. The
    decode is lossy on purpose: a multibyte character truncated at the cut point
    must not turn a reported timeout into a decode traceback."""
    from installer.core.content_tests import _decode

    assert _decode(None) == ""
    assert _decode("partial\n") == "partial\n"
    assert _decode(b"partial\n") == "partial\n"
    assert _decode(b"cut \xff here") == "cut � here"


def _result(suffix: str, output: str, returncode: int = 0) -> SuiteResult:
    suite = Suite(path=Path(f"probe_test{suffix}"), runner=RUNNERS[suffix])
    return SuiteResult(suite=suite, returncode=returncode, output=output)


@pytest.mark.parametrize(
    ("suffix", "output"),
    [
        (".py", "......                          [100%]\n55 passed in 0.42s\n"),
        (".js", "# tests 13\n# suites 0\n# pass 13\n# fail 0\n"),
        (".sh", "----\nPASS=16 FAIL=0\n"),
    ],
)
def test_a_real_clean_run_of_each_runner_is_recognised(suffix: str, output: str) -> None:
    """The marker patterns are only worth anything if they match what these
    runners actually print. Each string here is captured verbatim from a shipped
    suite, so a runner whose argv changes out from under its pattern — a swapped
    node reporter, pytest losing ``-q`` — turns this red instead of turning the
    whole gate into a rubber stamp that matches nothing and fails everything."""
    assert _result(suffix, output).ok


@pytest.mark.parametrize(
    ("suffix", "output"),
    [
        (".js", "# tests 0\n# pass 0\n# fail 0\n"),
        (".sh", "PASS=0 FAIL=0\n"),
    ],
)
def test_a_suite_that_ran_no_tests_is_a_failure(suffix: str, output: str) -> None:
    """The marker alone is not enough: a suite whose cases all failed to register
    still prints one, with a count of zero. Exit code cannot see this — node and
    bash both exit 0 for it — so the count is what separates a suite that passed
    from a suite that did nothing."""
    result = _result(suffix, output)

    assert not result.ok
    assert result.failure == "exited 0 having run no tests"


def test_a_suite_that_swallowed_its_frameworks_verdict_is_a_failure() -> None:
    """A PEP 723 suite that calls ``pytest.main`` and drops the return value exits
    0 with its failures printed above. Judging it by exit code alone reports the
    red suite as green, which is the failure mode this gate was built to stop."""
    result = _result(".py", "F....\n1 failed, 54 passed in 0.42s\n")

    assert not result.ok
    assert "without reporting a clean pass" in str(result.failure)


def test_a_suite_that_exits_zero_silently_is_a_failure(tmp_path: Path) -> None:
    """The end-to-end shape of the hole: a shell suite whose body never ran — a
    guard clause returned early, a `set -e` fired in a subshell — exits 0 with no
    tally. It is indistinguishable from a passing suite by every signal except
    the marker."""
    src = _src(tmp_path, {"skills/a/probe.sh": "", "skills/a/probe_test.sh": "exit 0\n"})
    suites, _violations = discover_suites(src)

    result = SubprocessRunner().run(suites[0])

    assert result.returncode == 0
    assert not result.ok
    assert "PASS=" in str(result.failure)


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
