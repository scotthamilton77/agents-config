"""Unit tests for the pure legacy pr-inventory translation (bead abn9.8.13.1).

merge-guard's ``check-merge-eligibility.sh`` clears its ``untriaged_feedback``
blocker ONLY from the legacy ``~/.claude/state/pr-inventory`` inventory. These
tests pin the pure translation prgroom emits into that format: the fail-closed
disposition table, the per-kind id fields, filename/head-sha derivation, and the
``.replyids`` sidecar — plus the consumer's own clearing predicate re-implemented
as an oracle so a skipped item is proven to CLEAR and a failed item to BLOCK.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from prgroom.prsession.enums import DispositionKind, ItemKind, PRPhase
from prgroom.prsession.legacy_export import (
    _DISPOSITION_TO_LEGACY,
    export_legacy_inventory,
    legacy_inventory_path,
    resolve_legacy_dir,
    to_legacy_inventory,
    to_replyids_lines,
)
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    Disposition,
    Identity,
    PRGroomingState,
    QuiescenceState,
    ReviewItem,
)

_T = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)
_REF = PRRef("octo-org", "demo-repo", 42)


def _item(
    kind: ItemKind,
    *,
    gh_id: str,
    disposition: DispositionKind | None,
    own_reply_id: int = 0,
    reply_to_comment_id: int = 0,
    thread_id: str = "",
) -> ReviewItem:
    disp = (
        None
        if disposition is None
        else Disposition(kind=disposition, decided_at=_T, decided_by="fix-agent")
    )
    return ReviewItem(
        kind=kind,
        identity=Identity(
            gh_id=gh_id,
            thread_id=thread_id,
            reply_to_comment_id=reply_to_comment_id,
        ),
        author="reviewer",
        body_excerpt="...",
        seen_at=_T,
        disposition=disp,
        own_reply_id=own_reply_id,
    )


def _state(
    *,
    items: list[ReviewItem] | None = None,
    last_poll_sha: str = "pollsha",
    last_pushed_head_sha: str = "",
    reviewers_present: bool = False,
    phase: PRPhase = PRPhase.QUIESCED,
) -> PRGroomingState:
    from prgroom.prsession.enums import ReviewerKind, ReviewerStatus
    from prgroom.prsession.state import ReviewerState

    reviewers = {}
    if reviewers_present:
        reviewers["copilot"] = ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.REVIEW_FOUND,
            required=True,
            last_request_at=_T,
        )
    return PRGroomingState(
        pr=_REF,
        phase=phase,
        pr_review_retries_used=2,
        last_polled_at=_T,
        last_activity_at=_T,
        quiescence=QuiescenceState(),
        last_poll_sha=last_poll_sha,
        last_pushed_head_sha=last_pushed_head_sha,
        reviewers=reviewers,
        items=items or [],
    )


# ── Disposition table: exhaustive + fail-closed ─────────────────────────────


def test_disposition_table_covers_every_kind() -> None:
    # Exhaustiveness proof: a future DispositionKind must be added deliberately,
    # not silently default to CLEAR. The map is the merge-safety boundary.
    assert set(_DISPOSITION_TO_LEGACY) == set(DispositionKind)


@pytest.mark.parametrize(
    ("disposition", "classification", "fix_outcome"),
    [
        (DispositionKind.SKIPPED, "SKIP", None),
        (DispositionKind.WONT_FIX, "SKIP", None),
        (DispositionKind.FIXED, "FIX", "committed"),
        (DispositionKind.ALREADY_ADDRESSED, "FIX", "already_addressed"),
        (DispositionKind.DEFERRED, "ESCALATE", None),
        (DispositionKind.ESCALATED, "ESCALATE", None),
        (DispositionKind.FAILED, "FIX", "failed"),
    ],
)
def test_disposition_maps_to_expected_classification(
    disposition: DispositionKind, classification: str, fix_outcome: str | None
) -> None:
    assert _DISPOSITION_TO_LEGACY[disposition] == (classification, fix_outcome)


def test_unknown_disposition_raises_rather_than_clears() -> None:
    # An enum value absent from the table must fail loudly (KeyError), never
    # silently clear a blocker. Simulated with a bogus key since we cannot mint
    # a new enum member.
    with pytest.raises(KeyError):
        _DISPOSITION_TO_LEGACY["not_a_real_disposition"]  # type: ignore[index]


# ── Item translation ────────────────────────────────────────────────────────


def test_untriaged_items_are_omitted() -> None:
    inv = to_legacy_inventory(
        _state(
            items=[
                _item(ItemKind.ISSUE_COMMENT, gh_id="1", disposition=None),
                _item(ItemKind.ISSUE_COMMENT, gh_id="2", disposition=DispositionKind.SKIPPED),
            ]
        )
    )
    assert [i["issue_comment_id"] for i in inv["items"]] == [2]


def test_issue_comment_id_field() -> None:
    inv = to_legacy_inventory(
        _state(
            items=[_item(ItemKind.ISSUE_COMMENT, gh_id="777", disposition=DispositionKind.FIXED)]
        )
    )
    item = inv["items"][0]
    assert item["kind"] == "issue_comment"
    assert item["issue_comment_id"] == 777
    assert item["classification"] == "FIX"
    assert item["fix_outcome"] == "committed"


def test_review_summary_id_field() -> None:
    inv = to_legacy_inventory(
        _state(
            items=[_item(ItemKind.REVIEW_SUMMARY, gh_id="555", disposition=DispositionKind.SKIPPED)]
        )
    )
    item = inv["items"][0]
    assert item["kind"] == "review_summary"
    assert item["review_id"] == 555


def test_review_thread_id_fields_prefer_reply_to_comment_id() -> None:
    inv = to_legacy_inventory(
        _state(
            items=[
                _item(
                    ItemKind.REVIEW_THREAD,
                    gh_id="999",
                    disposition=DispositionKind.FIXED,
                    reply_to_comment_id=321,
                    thread_id="PRRT_abc",
                )
            ]
        )
    )
    item = inv["items"][0]
    assert item["kind"] == "review_thread"
    assert item["reply_to_comment_id"] == 321
    assert item["thread_id"] == "PRRT_abc"


def test_review_thread_falls_back_to_gh_id_and_null_thread() -> None:
    inv = to_legacy_inventory(
        _state(
            items=[
                _item(
                    ItemKind.REVIEW_THREAD,
                    gh_id="888",
                    disposition=DispositionKind.FIXED,
                )
            ]
        )
    )
    item = inv["items"][0]
    assert item["reply_to_comment_id"] == 888
    assert item["thread_id"] is None


def test_posted_reply_id_passthrough_and_null() -> None:
    inv = to_legacy_inventory(
        _state(
            items=[
                _item(
                    ItemKind.ISSUE_COMMENT,
                    gh_id="1",
                    disposition=DispositionKind.SKIPPED,
                    own_reply_id=42,
                ),
                _item(ItemKind.ISSUE_COMMENT, gh_id="2", disposition=DispositionKind.SKIPPED),
            ]
        )
    )
    assert inv["items"][0]["posted_reply_id"] == 42
    assert inv["items"][1]["posted_reply_id"] is None


# ── Envelope fields ─────────────────────────────────────────────────────────


def test_envelope_skill_a_completed_and_polling_defaults() -> None:
    inv = to_legacy_inventory(_state(reviewers_present=False))
    assert inv["schema_version"] == 1
    assert inv["crash_recovery"]["skill_a_completed"] is True
    assert inv["crash_recovery"]["last_completed_phase"] == "quiesced"
    assert inv["polling"]["bot_review_cap_exhausted"] is False
    assert inv["polling"]["copilot_status"] == "not_requested"
    assert inv["polling"]["rereview_round_count"] == 2


def test_copilot_status_review_found_when_reviewers_present() -> None:
    inv = to_legacy_inventory(_state(reviewers_present=True))
    assert inv["polling"]["copilot_status"] == "review_found"


def test_pr_head_sha_fields() -> None:
    inv = to_legacy_inventory(_state(last_poll_sha="poll", last_pushed_head_sha="pushed"))
    assert inv["pr"] == {
        "owner": "octo-org",
        "repo": "demo-repo",
        "number": 42,
        "head_sha_at_inventory": "poll",
        "head_sha_after_push": "pushed",
    }


# ── Head-sha / filename precedence ──────────────────────────────────────────


def test_filename_prefers_pushed_head_sha(tmp_path: Path) -> None:
    path = legacy_inventory_path(
        tmp_path, _state(last_poll_sha="poll", last_pushed_head_sha="pushed")
    )
    assert path == tmp_path / "octo-org-demo-repo-42-pushed.json"


def test_filename_falls_back_to_poll_sha(tmp_path: Path) -> None:
    path = legacy_inventory_path(tmp_path, _state(last_poll_sha="poll", last_pushed_head_sha=""))
    assert path == tmp_path / "octo-org-demo-repo-42-poll.json"


def test_export_skips_when_no_head_sha(tmp_path: Path) -> None:
    export_legacy_inventory(_state(last_poll_sha="", last_pushed_head_sha=""), tmp_path)
    assert list(tmp_path.iterdir()) == []


# ── Sidecar generation ──────────────────────────────────────────────────────


def test_sidecar_only_items_with_reply_id() -> None:
    lines = to_replyids_lines(
        _state(
            items=[
                _item(
                    ItemKind.ISSUE_COMMENT,
                    gh_id="1",
                    disposition=DispositionKind.SKIPPED,
                    own_reply_id=0,
                ),
                _item(
                    ItemKind.ISSUE_COMMENT,
                    gh_id="2",
                    disposition=DispositionKind.SKIPPED,
                    own_reply_id=100,
                ),
            ]
        )
    )
    assert lines == [{"k": "issue_comment_id", "v": "2", "rid": 100}]


def test_sidecar_kv_per_kind() -> None:
    lines = to_replyids_lines(
        _state(
            items=[
                _item(
                    ItemKind.ISSUE_COMMENT,
                    gh_id="10",
                    disposition=DispositionKind.SKIPPED,
                    own_reply_id=1,
                ),
                _item(
                    ItemKind.REVIEW_SUMMARY,
                    gh_id="20",
                    disposition=DispositionKind.SKIPPED,
                    own_reply_id=2,
                ),
                _item(
                    ItemKind.REVIEW_THREAD,
                    gh_id="30",
                    disposition=DispositionKind.SKIPPED,
                    own_reply_id=3,
                    reply_to_comment_id=333,
                ),
            ]
        )
    )
    assert lines == [
        {"k": "issue_comment_id", "v": "10", "rid": 1},
        {"k": "review_id", "v": "20", "rid": 2},
        {"k": "reply_to_comment_id", "v": "333", "rid": 3},
    ]


def test_sidecar_thread_v_falls_back_to_gh_id() -> None:
    lines = to_replyids_lines(
        _state(
            items=[
                _item(
                    ItemKind.REVIEW_THREAD,
                    gh_id="30",
                    disposition=DispositionKind.SKIPPED,
                    own_reply_id=3,
                ),
            ]
        )
    )
    assert lines == [{"k": "reply_to_comment_id", "v": "30", "rid": 3}]


def test_sidecar_regenerates_fully_no_append(tmp_path: Path) -> None:
    state = _state(
        items=[
            _item(
                ItemKind.ISSUE_COMMENT,
                gh_id="1",
                disposition=DispositionKind.SKIPPED,
                own_reply_id=5,
            )
        ]
    )
    export_legacy_inventory(state, tmp_path)
    export_legacy_inventory(state, tmp_path)
    sidecar = tmp_path / "octo-org-demo-repo-42-pollsha.json.replyids"
    non_empty = [ln for ln in sidecar.read_text().splitlines() if ln.strip()]
    assert len(non_empty) == 1


# ── resolve_legacy_dir ──────────────────────────────────────────────────────


def test_resolve_legacy_dir_override_wins(tmp_path: Path) -> None:
    assert resolve_legacy_dir(tmp_path, env={}) == tmp_path


def test_resolve_legacy_dir_env(tmp_path: Path) -> None:
    assert resolve_legacy_dir(None, env={"PRGROOM_LEGACY_INVENTORY_DIR": str(tmp_path)}) == tmp_path


def test_resolve_legacy_dir_default_home() -> None:
    assert resolve_legacy_dir(None, env={}) == Path.home() / ".claude" / "state" / "pr-inventory"


# ── End-to-end oracle: the consumer's clearing predicate ────────────────────


def _clears(item: dict[str, object]) -> bool:
    """Re-implements merge-guard ``terminal_ok`` (check-merge-eligibility.sh)."""
    classification = item["classification"]
    fix_outcome = item["fix_outcome"]
    return classification == "SKIP" or (
        classification == "FIX" and fix_outcome in {"committed", "already_addressed"}
    )


def test_e2e_skipped_item_clears_and_sidecar_has_rid(tmp_path: Path) -> None:
    state = _state(
        items=[
            _item(
                ItemKind.REVIEW_SUMMARY,
                gh_id="555",
                disposition=DispositionKind.SKIPPED,
                own_reply_id=9001,
            )
        ]
    )
    export_legacy_inventory(state, tmp_path)
    inv_path = tmp_path / "octo-org-demo-repo-42-pollsha.json"
    inv = json.loads(inv_path.read_text())

    assert inv["crash_recovery"]["skill_a_completed"] is True
    (only,) = inv["items"]
    assert _clears(only), "a skipped item MUST clear the untriaged_feedback blocker"

    sidecar = json.loads(
        (tmp_path / "octo-org-demo-repo-42-pollsha.json.replyids").read_text().strip()
    )
    assert sidecar["rid"] == 9001


def test_e2e_failed_item_blocks(tmp_path: Path) -> None:
    state = _state(
        items=[_item(ItemKind.REVIEW_SUMMARY, gh_id="555", disposition=DispositionKind.FAILED)]
    )
    export_legacy_inventory(state, tmp_path)
    inv = json.loads((tmp_path / "octo-org-demo-repo-42-pollsha.json").read_text())
    (only,) = inv["items"]
    assert not _clears(only), "a failed item MUST NOT clear (fail-closed)"
