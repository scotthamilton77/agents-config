"""Golden-master parity scenarios: bash ``install.sh`` vs Python ``install.py``.

Each scenario runs BOTH installers into isolated temp HOME trees and asserts the
results match (JSON semantic, every other file byte-wise, executable bit
included). Marked ``golden_master`` so they stay out of the fast coverage gate;
run them with ``make golden-master-installer``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from tests.golden_master._runner import run_parity

pytestmark = pytest.mark.golden_master


_CLAUDE_ARGS = ["--tools=claude", "--plugins=", "--yes"]


def _tool_isolated_path(tmp_path: Path) -> str:
    """A PATH that hides the opencode/gemini/codex CLIs so auto-detect is
    deterministic — none are found on PATH, and a fresh HOME has none of their
    config dirs — while keeping the binaries the bash installer needs reachable.
    A symlink farm holds jq (bash's hard precondition, often Homebrew-only on
    macOS) plus bash/git; /usr/bin:/bin supplies the coreutils. The third-party
    tool CLIs are never symlinked and don't live in /usr/bin:/bin, so both
    ``command -v opencode`` (bash) and ``which("opencode")`` (Python) miss."""
    farm = tmp_path / "isolated_bin"
    farm.mkdir()
    for tool in ("jq", "bash", "git"):
        resolved = shutil.which(tool)
        if resolved is not None:
            (farm / tool).symlink_to(resolved)
    return os.pathsep.join([str(farm), "/usr/bin", "/bin"])


def test_bare_install_single_tool_no_plugins(tmp_path: Path) -> None:
    """Clean HOME, one tool, no plugins — the simplest end-to-end parity check."""
    result = run_parity(tmp_path, args=_CLAUDE_ARGS)

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()


def test_hooks_namespace_staged_with_exec_bit(tmp_path: Path) -> None:
    """The real ``src/user/.claude/hooks/`` namespace installs to ``~/.claude/hooks/``
    at parity, preserving each script's source mode bit: ``ruff-postedit.py`` is
    git-tracked 100755 and must land executable, while ``ruff-postedit_test.sh`` is
    100644 and must land non-executable. The bare-install scenario already compares
    the exec bit tree-wide; this pins the hooks/ namespace explicitly (8.7 parity
    with install.sh's hooks/ subdir staging + cp mode preservation), so a future
    regression in either installer surfaces here by name rather than as an opaque
    tree diff."""
    result = run_parity(tmp_path, args=_CLAUDE_ARGS)

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()

    hooks_b = result.home_b / ".claude" / "hooks"
    exec_hook = hooks_b / "ruff-postedit.py"
    plain_hook = hooks_b / "ruff-postedit_test.sh"
    assert exec_hook.is_file(), "hook script must install to ~/.claude/hooks/"
    assert plain_hook.is_file(), "non-exec hook sibling must install to ~/.claude/hooks/"
    assert exec_hook.stat().st_mode & 0o111, "executable source hook must land +x"
    assert not (plain_hook.stat().st_mode & 0o111), "non-executable source hook must stay -x"


def test_pre_existing_settings_merge(tmp_path: Path) -> None:
    """A pre-existing user settings.json is union-merged by both installers. The
    bash side uses jq, the Python side json_union — the differ compares JSON
    semantically, so formatting differences never register."""

    def seed(home: Path) -> None:
        claude = home / ".claude"
        claude.mkdir(parents=True, exist_ok=True)
        (claude / "settings.json").write_text('{"userKey": "keep-me"}\n')

    result = run_parity(tmp_path, args=_CLAUDE_ARGS, seed=seed)

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()


def test_user_modified_file_is_backed_up(tmp_path: Path) -> None:
    """A user-modified deployed file is backed up (timestamped) then overwritten;
    both installers place the backup identically (G.1) and the differ normalises
    the timestamp, so parity holds and the backup is actually present."""

    def seed(home: Path) -> None:
        claude = home / ".claude"
        claude.mkdir(parents=True, exist_ok=True)
        (claude / "CLAUDE.md").write_text("USER LOCAL EDIT\n")

    result = run_parity(tmp_path, args=_CLAUDE_ARGS, seed=seed)

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()
    backups = list(result.home_b.glob(".claude/CLAUDE.md.backup-*"))
    assert backups, "expected a timestamped backup of the user-modified CLAUDE.md"


def test_settings_merge_with_overlapping_array(tmp_path: Path) -> None:
    """A user settings.json whose permissions.deny overlaps the template exercises
    array union. bash's jq sorts the merged array; json_union keeps first-seen
    order. The differ compares settings arrays order-insensitively, so element
    parity holds despite the (accepted) order divergence."""

    def seed(home: Path) -> None:
        claude = home / ".claude"
        claude.mkdir(parents=True, exist_ok=True)
        (claude / "settings.json").write_text('{"permissions": {"deny": ["Custom(user-rule)"]}}')

    result = run_parity(tmp_path, args=_CLAUDE_ARGS, seed=seed)

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()


def test_bare_install_codex(tmp_path: Path) -> None:
    """Single-tool parity for Codex — a dot-dir tool with its own templates."""
    result = run_parity(tmp_path, args=["--tools=codex", "--plugins=", "--yes"])

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()


def test_bare_install_gemini(tmp_path: Path) -> None:
    """Single-tool parity for Gemini — another dot-dir tool, flat instruction
    file. The agent frontmatter transform is a surgical line port of the bash
    awk (inline ``tools: [...]`` wrapping the raw value, Claude-only keys
    stripped, every other line byte-identical), so a real agent's block-scalar
    ``description`` survives unreflowed."""
    result = run_parity(tmp_path, args=["--tools=gemini", "--plugins=", "--yes"])

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()


def test_bare_install_opencode(tmp_path: Path) -> None:
    """Single-tool parity for OpenCode — the XDG (~/.config/opencode) tool that
    skips shared agents/ and inlines rules into AGENTS.md (no standalone rules/
    namespace; the adapter drops rules from the plan after the ALL-RULES flatten,
    mirroring install.sh Phase 7's rules/-subdir sync skip)."""
    result = run_parity(tmp_path, args=["--tools=opencode", "--plugins=", "--yes"])

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()


def test_autodetect_fresh_home(tmp_path: Path) -> None:
    """No --tools: auto-detect against an empty HOME. Both installers treat
    Claude as always-on (bash's ``TOOLS=(claude)`` floor; the Python port's
    ClaudeAdapter is unconditionally detected), so a fresh machine installs
    exactly Claude and reaches parity.

    Tool-detection is isolated via a pinned PATH (``_tool_isolated_path``):
    opencode/gemini/codex CLIs are absent so neither installer auto-adds them
    (which would otherwise drag in still-diverging install paths), while jq
    stays reachable for bash's hard precondition."""
    if shutil.which("jq") is None:
        pytest.skip("bash installer requires jq on PATH")
    result = run_parity(
        tmp_path,
        args=["--plugins=", "--yes"],
        env={"PATH": _tool_isolated_path(tmp_path)},
    )

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()


def test_warmup_run_failure_is_surfaced(tmp_path: Path) -> None:
    """A failing warm-up run (repeat>1) must raise, not be silently discarded —
    otherwise a first-run install failure in an idempotency scenario would be
    masked by a later run's exit code. Bogus ``--tools`` makes the warm-up run
    fail fast at argument validation."""
    with pytest.raises(RuntimeError, match="warm-up"):
        run_parity(tmp_path, args=["--tools=bogus-tool", "--plugins=", "--yes"], repeat=2)


def test_reinstall_is_idempotent(tmp_path: Path) -> None:
    """Running each installer twice into the same HOME must converge to the same
    tree. ``_install_dir`` skips an unchanged directory (no spurious second-run
    backup), and the differ accepts bash's lone settings.json re-merge backup —
    the on-disk trace of the array-order divergence it already normalises away."""
    result = run_parity(tmp_path, args=_CLAUDE_ARGS, repeat=2)

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr
    diff = result.diff()
    assert diff.is_parity(), diff.render()
