"""Tests for the version rule: the partial label, and the bump guard over it."""

import runpy
import subprocess
from pathlib import Path

import pytest

from installer import version_guard_cli
from installer.core.versions import (
    WATCHED_PACKAGE,
    bump_refusal,
    is_partial,
    project_version,
    release,
    touches_watched,
    version_in,
)

_SRC = f"{WATCHED_PACKAGE}/src/prgroom/cli.py"


def test_release_ignores_the_local_label() -> None:
    """A partial version compares as the release it is a tweak on top of."""
    assert release("0.2.0+partial") == (0, 2, 0)
    assert release("0.2.0") == (0, 2, 0)


def test_release_rejects_what_is_not_three_integers() -> None:
    """A version the rule cannot compare is an error rather than a silent pass."""
    with pytest.raises(ValueError, match=r"neither x\.y\.z"):
        release("0.2")


def test_only_bounded_ascii_digits_are_a_version() -> None:
    """
    Given digits that are not ASCII, or more of them than a version ever holds
    When they are parsed
    Then they are malformed, and the long one refuses rather than raising from
    the integer conversion underneath.

    Unicode decimal digits read as digits to a permissive pattern and compare as
    the number they resemble, so a version nobody can type would sort as current.
    """
    for raw in (
        "\u0660.\u0662.\u0660",
        "\uff10.\uff12.\uff10",
        "1234567890.0.0",
        "1" * 5000 + ".0.0",
    ):
        with pytest.raises(ValueError, match=r"neither x\.y\.z"):
            release(raw)
        assert not is_partial(f"{raw}+partial")
    assert release("0.2.0") == (0, 2, 0)
    assert release("0.2.0+partial") == (0, 2, 0)


def test_is_partial_reads_only_the_one_label_on_a_well_formed_version() -> None:
    """A label other than the one label is malformed, and malformed is not partial."""
    assert is_partial("0.2.0+partial")
    assert not is_partial("0.2.0")
    assert not is_partial("bogus+partial")
    assert not is_partial("0.2.0+other")


def test_release_rejects_any_label_but_the_one_label() -> None:
    """
    Given a version carrying some other local label
    When it is parsed
    Then it is malformed, rather than the release part with the label discarded.
    """
    with pytest.raises(ValueError, match=r"neither x\.y\.z"):
        release("0.2.0+other")


def test_guard_fails_versions_wearing_a_label_that_is_not_the_label() -> None:
    """
    Given a source change whose version is not one of the two allowed shapes
    When the guard runs
    Then it refuses both: a stray label must not read as a bump, and a malformed
    release must not read as partial.
    """
    assert bump_refusal(changed=[_SRC], base_version="0.1.0", head_version="0.2.0+other")
    assert bump_refusal(changed=[_SRC], base_version="0.1.0", head_version="bogus+partial")


def test_guard_fails_a_source_change_with_no_bump() -> None:
    """
    Given source under the watched package changed and the version is unchanged
    When the guard runs
    Then it refuses, naming both versions and both ways out.
    """
    refusal = bump_refusal(changed=[_SRC], base_version="0.1.0", head_version="0.1.0")
    assert refusal is not None
    assert "0.1.0" in refusal
    assert "+partial" in refusal


def test_guard_passes_a_bumped_release() -> None:
    assert bump_refusal(changed=[_SRC], base_version="0.1.0", head_version="0.2.0") is None


def test_guard_passes_a_partial_on_the_released_version() -> None:
    """A partial rides on the release the base already names, so it compares equal."""
    assert bump_refusal(changed=[_SRC], base_version="0.1.0", head_version="0.1.0+partial") is None


def test_guard_refuses_a_bump_that_also_wears_the_label() -> None:
    """
    Given a version that bumps the release and marks it partial at once
    When the guard runs
    Then it refuses, naming both shapes.

    No state satisfies that version: the installer refuses to deploy a partial,
    and the round's check reads the bump and demands the install just refused.
    """
    refusal = bump_refusal(changed=[_SRC], base_version="0.1.0", head_version="0.2.0+partial")
    assert refusal is not None
    assert "0.1.0+partial" in refusal
    assert "bare release" in refusal


def test_guard_reads_the_packages_own_pyproject_as_a_change() -> None:
    """
    Given only the package's pyproject changed
    When the guard runs
    Then it compares: the file carries the version and the dependency set, both
    of which decide what the installed tool is.
    """
    changed = [f"{WATCHED_PACKAGE}/pyproject.toml"]
    assert bump_refusal(changed=changed, base_version="0.1.0", head_version="0.1.0") is not None


def test_guard_ignores_a_change_outside_the_watched_source() -> None:
    """
    Given only the package's tests and guidance changed
    When the guard runs
    Then it says nothing: neither changes the tool on PATH.
    """
    changed = [f"{WATCHED_PACKAGE}/tests/test_cli.py", f"{WATCHED_PACKAGE}/AGENTS.md", "README.md"]
    assert bump_refusal(changed=changed, base_version="0.1.0", head_version="0.1.0") is None


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("9" * 5000, id="past-the-digit-limit"),
        pytest.param("[" * 3000 + "]" * 3000, id="nested-past-the-recursion-limit"),
    ],
)
def test_a_version_the_parser_cannot_survive_is_malformed_not_raised(
    tmp_path: Path, value: str
) -> None:
    """Whatever the parser raises on a pathological value, both readers say malformed."""
    text = f"[project]\nversion = {value}\n"
    assert version_in(text) == ""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(text, encoding="utf-8")
    assert project_version(pyproject) == ""


def test_guard_fails_a_malformed_version() -> None:
    """A version neither form accepts cannot be compared, so it does not ship."""
    refusal = bump_refusal(changed=[_SRC], base_version="0.1.0", head_version="0.1")
    assert refusal is not None
    assert "0.1" in refusal


def test_guard_says_nothing_when_the_base_declares_no_version() -> None:
    """The branch that introduces the package has nothing to bump against."""
    assert bump_refusal(changed=[_SRC], base_version=None, head_version="0.1.0") is None


def test_guard_quotes_the_versions_it_echoes() -> None:
    """
    Given a version string carrying a terminal escape sequence
    When the refusal names it
    Then it is quoted rather than replayed: the string comes off disk, and the
    operator reads the message in a terminal that acts on control characters.
    """
    refusal = bump_refusal(
        changed=[_SRC], base_version="0.1.0", head_version="0.1.0+partial\x1b[2J"
    )
    assert refusal is not None
    assert "\x1b[2J" not in refusal
    assert "\\x1b" in refusal


def test_guard_fails_a_malformed_base_version() -> None:
    refusal = bump_refusal(changed=[_SRC], base_version="oops", head_version="0.2.0")
    assert refusal is not None
    assert "base revision" in refusal


def test_version_in_survives_a_pyproject_that_declares_none() -> None:
    assert version_in("[project]\nname = 'x'\n") == ""
    assert version_in("not = = toml") == ""
    assert version_in("project = 'a string'") == ""


def test_project_version_of_an_unreadable_file_is_empty(tmp_path: Path) -> None:
    """An unreadable pyproject must not read as partial: uv reports it better."""
    assert project_version(tmp_path / "absent.toml") == ""


def test_base_revision_names_the_pull_requests_base() -> None:
    assert version_guard_cli.base_revision({"GITHUB_BASE_REF": "main"}) == "origin/main"


def test_base_revision_is_absent_on_a_push() -> None:
    """A push to the default branch has no base, so the guard is skipped there."""
    assert version_guard_cli.base_revision({"GITHUB_ACTIONS": "true"}) is None


def test_base_revision_off_ci_is_the_default_branch() -> None:
    assert version_guard_cli.base_revision({}) == "origin/main"


def test_cli_skips_without_a_base(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    assert version_guard_cli.main([]) == 0
    assert "skipped" in capsys.readouterr().out


def test_cli_reports_a_base_it_cannot_diff(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shallow clone without the base branch is an unanswerable run, not a pass."""
    monkeypatch.setattr(version_guard_cli, "changed_paths", lambda *_a: None)
    assert version_guard_cli.main([".", "--base", "origin/main"]) == 2
    assert "cannot diff" in capsys.readouterr().err


def test_cli_fails_on_the_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given the watched source changed and the tree declares the base version
    When the guard CLI runs
    Then it exits 1 with the refusal on stderr.
    """
    pyproject = tmp_path / WATCHED_PACKAGE / "pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
    monkeypatch.setattr(version_guard_cli, "changed_paths", lambda *_a: [_SRC])
    monkeypatch.setattr(version_guard_cli, "base_version", lambda *_a: "0.1.0")
    assert version_guard_cli.main([str(tmp_path), "--base", "origin/main"]) == 1
    assert "still '0.1.0'" in capsys.readouterr().err


def test_cli_reads_no_version_when_nothing_watched_changed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a change touching nothing under the watched package, and a package
    version that is malformed
    When the guard runs
    Then it passes without reading either version: a change with no question to
    answer must not fail on the state of a file it never touched.
    """
    pyproject = tmp_path / WATCHED_PACKAGE / "pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text('[project]\nversion = "not-a-version"\n', encoding="utf-8")

    read: list[str] = []

    def _unread(*_args: object) -> str:
        read.append("version")
        return "not-a-version"

    monkeypatch.setattr(version_guard_cli, "changed_paths", lambda *_a: ["README.md"])
    monkeypatch.setattr(version_guard_cli, "base_version", _unread)
    monkeypatch.setattr(version_guard_cli, "project_version", _unread)
    assert version_guard_cli.main([str(tmp_path), "--base", "origin/main"]) == 0
    assert "clear" in capsys.readouterr().out
    assert read == []


def test_cli_passes_a_clear_change(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(version_guard_cli, "changed_paths", lambda *_a: ["README.md"])
    monkeypatch.setattr(version_guard_cli, "base_version", lambda *_a: "0.1.0")
    assert version_guard_cli.main([str(tmp_path), "--base", "origin/main"]) == 0
    assert "clear" in capsys.readouterr().out


def test_changed_paths_and_base_version_read_real_git(tmp_path: Path) -> None:
    """
    Given a repository with one commit on a base branch and a change on top
    When the git-reading helpers run
    Then they report the changed path and the base revision's declared version.

    Pins the two subprocess helpers against real git, which is the only place
    the argv and the revision syntax can be wrong.
    """

    def git(*args: str) -> None:
        subprocess.run(  # noqa: S603  # fixed argv into git, in a temp repository
            ["git", "-C", str(tmp_path), *args],  # noqa: S607
            check=True,
            capture_output=True,
        )

    git("init", "-b", "base")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Test")
    pyproject = tmp_path / WATCHED_PACKAGE / "pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "base")
    git("checkout", "-b", "work")
    source = tmp_path / _SRC
    source.parent.mkdir(parents=True)
    source.write_text("x = 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "work")

    assert version_guard_cli.changed_paths(tmp_path, "base") == [_SRC]
    assert version_guard_cli.base_version(tmp_path, "base") == "0.1.0"
    assert version_guard_cli.base_version(tmp_path, "nonexistent-ref") is None
    assert version_guard_cli.changed_paths(tmp_path, "nonexistent-ref") is None

    # An uncommitted edit counts too, so a local run of the gate answers about
    # the tree the author is actually looking at.
    pyproject.write_text('[project]\nversion = "0.1.0"\nname = "x"\n', encoding="utf-8")
    assert version_guard_cli.changed_paths(tmp_path, "base") == [
        f"{WATCHED_PACKAGE}/pyproject.toml",
        _SRC,
    ]


def test_a_base_that_is_there_but_unusable_is_not_a_new_package(tmp_path: Path) -> None:
    """
    Given a base revision whose prgroom pyproject does not parse
    When the guard reads it
    Then it reads as empty rather than as absent, so the change refuses: only a
    base with no such file at all is the package's introduction.
    """

    def git(*args: str) -> None:
        subprocess.run(  # noqa: S603  # fixed argv into git, in a temp repository
            ["git", "-C", str(tmp_path), *args],  # noqa: S607
            check=True,
            capture_output=True,
        )

    git("init", "-b", "base")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Test")
    pyproject = tmp_path / WATCHED_PACKAGE / "pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text("this is = = not toml\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "base")

    assert version_guard_cli.base_version(tmp_path, "base") == ""
    assert bump_refusal(changed=[_SRC], base_version="", head_version="0.1.0") is not None

    # A base with no such file is the genuine new-package case, and it passes.
    git("checkout", "-b", "no-package")
    pyproject.unlink()
    git("commit", "-am", "no package")
    assert version_guard_cli.base_version(tmp_path, "no-package") is None
    assert bump_refusal(changed=[_SRC], base_version=None, head_version="0.1.0") is None


def test_a_path_git_would_quote_still_matches(tmp_path: Path) -> None:
    """
    Given a changed watched file whose name carries a non-ASCII character
    When the guard reads the changed paths
    Then it sees the real path, not git's quoted rendering of it — otherwise the
    one file with an unusual name is the one file that ships unbumped.
    """

    def git(*args: str) -> None:
        subprocess.run(  # noqa: S603  # fixed argv into git, in a temp repository
            ["git", "-C", str(tmp_path), *args],  # noqa: S607
            check=True,
            capture_output=True,
        )

    git("init", "-b", "base")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Test")
    pyproject = tmp_path / WATCHED_PACKAGE / "pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "base")
    git("checkout", "-b", "work")
    quoted = f"{WATCHED_PACKAGE}/src/prgroom/caf\u00e9.py"
    source = tmp_path / quoted
    source.parent.mkdir(parents=True)
    source.write_text("x = 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "work")

    changed = version_guard_cli.changed_paths(tmp_path, "base")
    assert changed == [quoted]
    assert bump_refusal(changed=changed or [], base_version="0.1.0", head_version="0.1.0")


def test_a_file_moved_out_of_the_watched_package_is_still_a_watched_change(
    tmp_path: Path,
) -> None:
    """
    Given a watched file moved, unchanged, to a path outside the watched package
    When the guard reads the changed paths
    Then the path it left is among them — git reports a detected rename by its
    destination alone, and a package that lost a file has changed.
    """

    def git(*args: str) -> None:
        subprocess.run(  # noqa: S603  # fixed argv into git, in a temp repository
            ["git", "-C", str(tmp_path), *args],  # noqa: S607
            check=True,
            capture_output=True,
        )

    git("init", "-b", "base")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Test")
    pyproject = tmp_path / WATCHED_PACKAGE / "pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
    source = tmp_path / _SRC
    source.parent.mkdir(parents=True)
    source.write_text("x = 1\n" * 20, encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "base")
    git("checkout", "-b", "work")
    git("mv", _SRC, "elsewhere.py")
    git("commit", "-m", "work")

    changed = version_guard_cli.changed_paths(tmp_path, "base")
    assert changed == ["elsewhere.py", _SRC]
    assert bump_refusal(changed=changed or [], base_version="0.1.0", head_version="0.1.0")


def test_a_path_that_is_not_text_in_the_locale_is_still_compared(tmp_path: Path) -> None:
    """
    Given a changed file, outside the watched package, whose name holds a byte
    that is not valid in the locale's encoding
    When the guard reads the changed paths
    Then it reads them, and the change outside the package is clear, rather than
    raising on a name git was only ever going to report as bytes.
    """

    def git(*args: str | bytes, stdin: bytes | None = None) -> bytes:
        return subprocess.run(  # noqa: S603  # fixed argv into git, in a temp repository
            ["git", "-C", str(tmp_path), *args],  # noqa: S607
            check=True,
            capture_output=True,
            input=stdin,
        ).stdout

    git("init", "-b", "base")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Test")
    pyproject = tmp_path / WATCHED_PACKAGE / "pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "base")
    git("checkout", "-b", "work")
    # The name goes straight into the index: a filesystem may refuse to create
    # it, and git reports it either way.
    blob = git("hash-object", "-w", "--stdin", stdin=b"x\n").strip()
    git(b"update-index", b"--add", b"--cacheinfo", b"100644," + blob + b",docs/caf\xff.md")
    git("commit", "-m", "work")

    changed = version_guard_cli.changed_paths(tmp_path, "base")
    assert changed == ["docs/caf\udcff.md"]
    assert not touches_watched(changed)


def test_module_is_runnable_as_python_dash_m(monkeypatch: pytest.MonkeyPatch) -> None:
    """``python -m installer.version_guard_cli`` is the make-target invocation
    shape; pins the ``__main__`` guard."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    monkeypatch.setattr("sys.argv", ["version-guard"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("installer.version_guard_cli", run_name="__main__")
    assert exc_info.value.code == 0
