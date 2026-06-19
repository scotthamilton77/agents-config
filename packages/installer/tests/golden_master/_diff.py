"""Comparison helpers for the golden-master parity harness.

The harness installs via bash and via Python into two HOME trees, then compares
them. JSON files are compared *semantically* (parse + deep-equal) so formatting
artifacts — key order, whitespace, jq quirks — never register as a diff; every
other file is compared byte-wise. Backup-filename timestamps are normalised so
the two runs' differing clocks don't diverge, and the executable bit is compared
because parity includes file mode.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# Backup suffix emitted by both installers: ``<name>.backup-YYYYMMDD-HHMMSS``
# (bash ``date +%Y%m%d-%H%M%S``; Python ``core.backup``). The two runs stamp
# different clock values, so the timestamp is normalised away before comparison.
_BACKUP_TS_RE = re.compile(r"\.backup-\d{8}-\d{6}")
_BACKUP_TS_PLACEHOLDER = ".backup-<TS>"


def normalize_relpath(relpath: str) -> str:
    """Collapse any backup-timestamp suffix in ``relpath`` to a stable placeholder.

    The two installers run a few clock-ticks apart, so a backup written as
    ``foo.md.backup-20260615-120000`` by one and ``...-120005`` by the other must
    map to the same logical path. Non-backup paths pass through untouched.
    """
    return _BACKUP_TS_RE.sub(_BACKUP_TS_PLACEHOLDER, relpath)


def _order_insensitive(value: object) -> object:
    """Canonicalise a parsed JSON value so array ORDER is ignored.

    ``json_union`` unions settings arrays (``permissions.deny``, ``hooks.*``) in
    first-seen order; bash's jq ``unique`` sorts them. Same elements, different
    order is an *accepted* deliberate divergence (Python preserves authored hook
    order that jq would scramble), so the differ compares arrays as multisets —
    it still catches an element added or dropped, only ignores a pure reorder.
    """
    if isinstance(value, dict):
        return {k: _order_insensitive(v) for k, v in value.items()}
    if isinstance(value, list):
        return sorted(
            (_order_insensitive(v) for v in value),
            key=lambda v: json.dumps(v, sort_keys=True),
        )
    return value


def json_semantically_equal(a: bytes, b: bytes) -> bool:
    """True if ``a`` and ``b`` parse as JSON to the same value, ignoring array order.

    A parse failure on either side yields ``False`` — the caller treats that as a
    mismatch rather than guessing.
    """
    try:
        return _order_insensitive(json.loads(a)) == _order_insensitive(json.loads(b))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False


@dataclass(frozen=True)
class TreeDiff:
    """The four ways two installed HOME trees can diverge. Empty everywhere == parity."""

    only_in_a: tuple[str, ...]
    only_in_b: tuple[str, ...]
    content_mismatch: tuple[str, ...]
    mode_mismatch: tuple[str, ...]

    def is_parity(self) -> bool:
        return not (self.only_in_a or self.only_in_b or self.content_mismatch or self.mode_mismatch)

    def render(self) -> str:
        if self.is_parity():
            return "parity: trees match"
        groups = (
            ("only in A (bash)", self.only_in_a),
            ("only in B (python)", self.only_in_b),
            ("content differs", self.content_mismatch),
            ("mode differs", self.mode_mismatch),
        )
        lines = [f"  [{label}] {item}" for label, items in groups for item in items]
        return "tree diff:\n" + "\n".join(lines)


# Bash deploys AGENTS.md/CLAUDE.md/GEMINI.md found inside a namespace dir
# (source-dir dev-docs); the Python installer correctly omits them via its
# DEAD_MARKERS rule. They are never a real parity divergence, so the harness
# drops them on both sides. The tool-root instruction file (parent is the tool
# dir, not a namespace) is not matched and still compares.
_DEAD_MARKER_NAMES = frozenset({"AGENTS.md", "CLAUDE.md", "GEMINI.md"})
_NAMESPACE_DIRS = frozenset({"skills", "agents", "rules", "commands", "hooks"})


def _is_namespace_dead_marker(relpath: str) -> bool:
    parts = relpath.split("/")
    return len(parts) >= 2 and parts[-1] in _DEAD_MARKER_NAMES and parts[-2] in _NAMESPACE_DIRS


def _index_tree(root: Path) -> dict[str, Path]:
    """Map every file under ``root`` to its normalised POSIX relpath.

    Namespace-level dead markers are skipped — see ``_is_namespace_dead_marker``.
    """
    index: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_file():
            rel = normalize_relpath(path.relative_to(root).as_posix())
            if _is_namespace_dead_marker(rel):
                continue
            if rel in index:
                # Two real files collapsed to one key (e.g. two backups of the
                # same name). Surfacing loudly beats silently dropping one and
                # comparing only the survivor — that would be a false-green.
                msg = (
                    f"backup-normalisation collision under {root}: "
                    f"{index[rel]} and {path} both map to {rel!r}"
                )
                raise ValueError(msg)
            index[rel] = path
    return index


def _is_accepted_settings_backup(
    relpath: str, index_a: dict[str, Path], index_b: dict[str, Path]
) -> bool:
    """Whether a bash-only ``<x>.json.backup-<TS>`` is the accepted artifact of the
    settings array-order divergence (see ``_order_insensitive``).

    On a re-install, bash's jq ``unique`` sorts ``permissions.deny`` / ``hooks.*``
    when it re-merges the settings file, so it sees a "change" and backs up the
    prior copy; Python's order-preserving union is idempotent and writes no backup.
    That surplus backup is the same accepted divergence leaking onto disk — accept
    it, but only narrowly: the backup must target a ``.json`` file whose live copy
    exists on BOTH sides and is semantically equal. A non-``.json`` backup, a
    missing live counterpart, or a genuinely different target (element added or
    dropped, not a pure reorder) is not exempt and still flags. The exemption is
    deliberately one-sided — a Python-only backup means Python itself was
    non-idempotent, the very regression this scenario guards, so the caller applies
    this only to ``only_in_a`` (bash)."""
    if not relpath.endswith(_BACKUP_TS_PLACEHOLDER):
        return False
    target = relpath[: -len(_BACKUP_TS_PLACEHOLDER)]
    if not target.endswith(".json"):
        return False
    live_a, live_b = index_a.get(target), index_b.get(target)
    if live_a is None or live_b is None:
        return False
    return json_semantically_equal(live_a.read_bytes(), live_b.read_bytes())


def _is_executable(path: Path) -> bool:
    # Any execute bit (owner/group/other), matching POSIX ``test -x`` intent —
    # not just owner-execute. Git stores only 0o644/0o755, so the two agree on
    # real inputs; 0o111 is the correct idiom and guards non-git-tracked modes.
    return bool(path.stat().st_mode & 0o111)


def _files_equal(relpath: str, a: Path, b: Path) -> bool:
    data_a, data_b = a.read_bytes(), b.read_bytes()
    if relpath.endswith(".json"):
        return json_semantically_equal(data_a, data_b)
    return data_a == data_b


def diff_trees(root_a: Path, root_b: Path) -> TreeDiff:
    """Compare two installed HOME trees comparison-type-aware.

    ``.json`` entries are compared semantically, all others byte-wise; backup
    timestamps are normalised and the executable bit is compared. ``root_a`` is
    the bash result, ``root_b`` the Python result.
    """
    index_a = _index_tree(root_a)
    index_b = _index_tree(root_b)
    keys_a, keys_b = set(index_a), set(index_b)

    content_mismatch: list[str] = []
    mode_mismatch: list[str] = []
    for relpath in sorted(keys_a & keys_b):
        path_a, path_b = index_a[relpath], index_b[relpath]
        if not _files_equal(relpath, path_a, path_b):
            content_mismatch.append(relpath)
        if _is_executable(path_a) != _is_executable(path_b):
            mode_mismatch.append(relpath)

    only_in_a = tuple(
        sorted(
            rel
            for rel in keys_a - keys_b
            if not _is_accepted_settings_backup(rel, index_a, index_b)
        )
    )
    return TreeDiff(
        only_in_a=only_in_a,
        only_in_b=tuple(sorted(keys_b - keys_a)),
        content_mismatch=tuple(content_mismatch),
        mode_mismatch=tuple(mode_mismatch),
    )
