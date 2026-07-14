"""Emit merge-guard's legacy pr-inventory format alongside prgroom state.

``merge-guard``'s ``check-merge-eligibility.sh`` clears its ``untriaged_feedback``
blocker ONLY from the legacy ``~/.claude/state/pr-inventory`` inventory (a
per-head-SHA JSON file plus a ``.replyids`` sidecar). prgroom persists its own
state under ``~/.local/state/prgroom`` in a different schema — invisible to
merge-guard — so a PR prgroom has fully dispositioned could never reach merge
eligibility. This module bridges the gap: at persist time prgroom ALSO emits the
legacy files, byte-compatible with what the consumer reads. Neither merge-guard
nor the prose skills change.

Design:

* The translation is a set of PURE functions (:func:`to_legacy_inventory`,
  :func:`to_replyids_lines`, :func:`legacy_inventory_path`) — heavily tested.
* :class:`LegacyExportStore` is a decorator Store that wraps the production
  :class:`~prgroom.prsession.file.FileStore`. ``write`` persists inner state
  FIRST (primary, atomic — never weakened), then best-effort emits the legacy
  files inside a ``try/except`` that logs and never re-raises: state persistence
  is primary, and merge-guard reads fail-closed, so a missing export merely keeps
  the PR blocked (safe).

The disposition→classification table is fail-closed and exhaustive: an unknown
:class:`DispositionKind` raises (``KeyError``) rather than silently clearing a
merge blocker.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from contextlib import AbstractContextManager
from pathlib import Path

from prgroom.prsession.enums import DispositionKind, ItemKind
from prgroom.prsession.file import write_atomic
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import JsonObj, PRGroomingState, ReviewItem
from prgroom.prsession.store import Store

_logger = logging.getLogger(__name__)

LEGACY_SCHEMA_VERSION = 1
LEGACY_DIR_ENV_VAR = "PRGROOM_LEGACY_INVENTORY_DIR"

# Fail-closed disposition table. ``(classification, fix_outcome)`` per the
# consumer's ``terminal_ok`` predicate: an item clears iff classification=="SKIP"
# OR (classification=="FIX" AND fix_outcome in {"committed","already_addressed"}).
# ESCALATE and FIX/failed are terminal but BLOCK (non-clearing) — safe defaults.
# Keyed on every DispositionKind so a future member must be added deliberately;
# a missing key raises KeyError (fail loud) rather than defaulting to CLEAR.
_DISPOSITION_TO_LEGACY: dict[DispositionKind, tuple[str, str | None]] = {
    DispositionKind.SKIPPED: ("SKIP", None),
    DispositionKind.WONT_FIX: ("SKIP", None),
    DispositionKind.FIXED: ("FIX", "committed"),
    DispositionKind.ALREADY_ADDRESSED: ("FIX", "already_addressed"),
    DispositionKind.DEFERRED: ("ESCALATE", None),
    DispositionKind.ESCALATED: ("ESCALATE", None),
    DispositionKind.FAILED: ("FIX", "failed"),
}


def resolve_legacy_dir(
    override: Path | None = None, *, env: Mapping[str, str] | None = None
) -> Path:
    """Resolve the legacy pr-inventory export dir.

    Precedence: explicit ``override`` arg > ``$PRGROOM_LEGACY_INVENTORY_DIR`` >
    the merge-guard default ``~/.claude/state/pr-inventory``. ``Path.home()`` is
    resolved lazily here (never at import time) so tests can inject a ``tmp_path``.
    A blank env value is treated as unset (POSIX convention).
    """
    if override is not None:
        return override
    environ = env if env is not None else os.environ
    raw = environ.get(LEGACY_DIR_ENV_VAR)
    if raw:
        return Path(raw)
    return Path.home() / ".claude" / "state" / "pr-inventory"


def _head_sha(state: PRGroomingState) -> str:
    """The PR's current head SHA the legacy filename pins to.

    ``last_review_invalidated_sha`` is set on *every* head change — prgroom's own
    push (``push.py``) and an external push (``poll.py``'s sha attribution) — so it
    tracks the current head, leading ``last_poll_sha`` only in the "pushed but not
    yet re-polled" window. ``last_pushed_head_sha`` must NOT be used: it is set
    solely by prgroom's own push and is never re-cleared, so after an external push
    it goes stale and would pin the export to an old head (filename mismatch +
    ``head_sha_after_push`` older than ``head_sha_at_inventory``). Falls back to
    ``last_poll_sha`` for the bootstrap poll, which sets no invalidated sha.
    """
    return state.last_review_invalidated_sha or state.last_poll_sha


def legacy_inventory_path(export_dir: Path, state: PRGroomingState) -> Path:
    """``{export_dir}/{owner}-{repo}-{number}-{head_sha}.json`` (consumer filename)."""
    pr = state.pr
    stem = f"{pr.owner}-{pr.repo}-{pr.number}-{_head_sha(state)}"
    return export_dir / f"{stem}.json"


def _legacy_item(item: ReviewItem) -> JsonObj:
    """Translate one dispositioned ReviewItem into a legacy inventory item.

    Precondition: ``item.disposition is not None`` (untriaged items are filtered
    by :func:`to_legacy_inventory` — they carry no terminal decision and the live
    GitHub scan catches them fail-closed).
    """
    disposition = item.disposition
    assert disposition is not None  # noqa: S101  # caller-guaranteed; see docstring
    classification, fix_outcome = _DISPOSITION_TO_LEGACY[disposition.kind]
    identity = item.identity
    entry: JsonObj = {
        "kind": item.kind.value,
        "classification": classification,
        "fix_outcome": fix_outcome,
        "posted_reply_id": item.own_reply_id or None,
    }
    if item.kind is ItemKind.ISSUE_COMMENT:
        entry["issue_comment_id"] = int(identity.gh_id)
    elif item.kind is ItemKind.REVIEW_SUMMARY:
        entry["review_id"] = int(identity.gh_id)
    else:  # ItemKind.REVIEW_THREAD
        entry["reply_to_comment_id"] = identity.reply_to_comment_id or int(identity.gh_id)
        entry["thread_id"] = identity.thread_id or None
    return entry


def to_legacy_inventory(state: PRGroomingState) -> JsonObj:
    """Translate grooming state into the legacy pr-inventory JSON object.

    Only items WITH a disposition are emitted (an untriaged item has no terminal
    decision). ``skill_a_completed`` is always ``True`` — the consumer counts NO
    terminal dispositions from an inventory that lacks it. ``bot_review_cap_exhausted``
    is always ``False`` (fail-closed: false keeps force-merge locked).
    """
    items = [_legacy_item(it) for it in state.items if it.disposition is not None]
    copilot_status = "review_found" if state.reviewers else "not_requested"
    head_sha = _head_sha(state)
    return {
        "schema_version": LEGACY_SCHEMA_VERSION,
        "pr": {
            "owner": state.pr.owner,
            "repo": state.pr.repo,
            "number": state.pr.number,
            "head_sha_at_inventory": state.last_poll_sha,
            "head_sha_after_push": head_sha,
        },
        "polling": {
            "copilot_status": copilot_status,
            "rereview_round_count": state.pr_review_retries_used,
            "bot_review_cap_exhausted": False,
        },
        "items": items,
        "crash_recovery": {
            "skill_a_completed": True,
            "last_completed_phase": str(state.phase),
        },
    }


def to_replyids_lines(state: PRGroomingState) -> list[JsonObj]:
    """The ``.replyids`` sidecar rows: one per item with a non-zero own_reply_id.

    The consumer only collects ``.rid`` (to exclude prgroom's own reply comments
    from the live issue-comment feed); ``k``/``v`` mirror the legacy key/value for
    fidelity. Regenerated fully each write — never appended.
    """
    lines: list[JsonObj] = []
    for item in state.items:
        if item.own_reply_id == 0:
            continue
        identity = item.identity
        if item.kind is ItemKind.ISSUE_COMMENT:
            key, value = "issue_comment_id", str(identity.gh_id)
        elif item.kind is ItemKind.REVIEW_SUMMARY:
            key, value = "review_id", str(identity.gh_id)
        else:  # ItemKind.REVIEW_THREAD
            key, value = "reply_to_comment_id", str(identity.reply_to_comment_id or identity.gh_id)
        lines.append({"k": key, "v": value, "rid": item.own_reply_id})
    return lines


def export_legacy_inventory(state: PRGroomingState, export_dir: Path) -> None:
    """Atomically write the legacy inventory JSON + ``.replyids`` sidecar.

    Skips entirely when there is no head SHA yet (bootstrap — nothing meaningful
    to emit). Both files go through :func:`~prgroom.prsession.file.write_atomic`
    (tempfile + fsync + ``os.replace``); the sidecar is regenerated in full, not
    appended.
    """
    if not _head_sha(state):
        return
    export_dir.mkdir(parents=True, exist_ok=True)
    inventory_path = legacy_inventory_path(export_dir, state)
    inventory_bytes = json.dumps(to_legacy_inventory(state), indent=2, sort_keys=True).encode(
        "utf-8"
    )
    write_atomic(inventory_path, inventory_bytes)

    lines = to_replyids_lines(state)
    sidecar_text = "\n".join(json.dumps(line) for line in lines) + "\n"
    sidecar_path = inventory_path.with_name(inventory_path.name + ".replyids")
    write_atomic(sidecar_path, sidecar_text.encode("utf-8"))


class LegacyExportStore:
    """Decorator Store: persist via ``inner``, then best-effort legacy export.

    Structurally satisfies the :class:`~prgroom.prsession.store.Store` Protocol.
    Every method but ``write`` delegates straight to ``inner``. ``write`` calls
    ``inner.write`` first (primary, atomic — never weakened), then emits the
    legacy pr-inventory inside a ``try/except`` that logs a warning and never
    re-raises: a failed export must not break grooming, and merge-guard reads
    fail-closed so a missing export simply keeps the PR blocked (safe).
    """

    def __init__(
        self,
        inner: Store,
        *,
        export_dir: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._inner = inner
        self._export_dir = resolve_legacy_dir(export_dir, env=env)

    # -- Store protocol --

    def read(self, ref: PRRef) -> PRGroomingState:
        return self._inner.read(ref)

    def write(self, ref: PRRef, state: PRGroomingState) -> None:
        self._inner.write(ref, state)
        try:
            export_legacy_inventory(state, self._export_dir)
        except Exception:
            # Best-effort: state is already durably persisted above; a failed
            # legacy export must never break grooming (the consumer fail-closes,
            # so a missing export only keeps the merge blocked — safe).
            _logger.warning(
                "legacy pr-inventory export failed for %s", ref.display(), exc_info=True
            )

    def lock(self, ref: PRRef) -> AbstractContextManager[None]:
        return self._inner.lock(ref)

    def list_refs(self) -> list[PRRef]:
        return self._inner.list_refs()

    def delete(self, ref: PRRef) -> None:
        self._inner.delete(ref)
