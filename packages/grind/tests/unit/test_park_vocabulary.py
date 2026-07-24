"""The park vocabulary contract: two axes, one table, and one exit.

These tests pin decisions, not the language. The failure axis is not grind's
to choose -- it is the shared park-reason contract that the `work` facade also
implements, and the two must stay member-for-member identical or the executor
has to translate a reason at the call site, which is the drift this vocabulary
exists to remove.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from grind.fold import fold
from grind.model import PARK_REASONS, ParkingEntry
from tests.unit.builders import event, seed_event

# The failure axis is not grind's to define: it is the shared park-reason
# contract, which `packages/workcli` implements as `work park --reason`. The
# packages are isolated uv projects with no cross-import, so a transcription
# in either test file would only catch a *forgetful* one-sided edit -- update
# the other package and its own copied expectation together and both gates
# stay green while the two runtimes disagree. Reading the one contract file
# closes that: changing the vocabulary means editing this file plus both
# tables, and skipping either table fails that table's own gate.
#
# Deliberately not guarded with a skip-if-missing: this package's tests are
# run from the repo, and a silent skip would reopen the hole the file exists
# to close.
_CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "park-reasons.toml"


def _contract_reasons() -> dict[str, str]:
    with _CONTRACT.open("rb") as handle:
        return dict(tomllib.load(handle)["reasons"])


def test_failure_axis_matches_the_shared_park_reason_contract() -> None:
    failure_axis = {
        reason: category for reason, (axis, category) in PARK_REASONS.items() if axis == "failure"
    }

    assert failure_axis == _contract_reasons()


def test_scheduling_axis_holds_the_grind_native_sequencing_reasons() -> None:
    # Kept, not folded into the failure axis: a scheduling park is a decision
    # about *when* work runs. `discovered-work` in particular parks an item
    # that never had a PR to fail, so no failure reason can describe it
    # without lying.
    scheduling = {reason for reason, (axis, _) in PARK_REASONS.items() if axis == "scheduling"}

    assert scheduling == {"discovered-work", "later-wave", "deferred"}


def test_every_reason_sits_on_exactly_one_axis_with_a_category() -> None:
    for reason, (axis, category) in PARK_REASONS.items():
        assert axis in {"failure", "scheduling"}, reason
        assert category in {"machine", "human"}, reason


def test_a_scheduling_park_is_never_machine_actionable() -> None:
    # A sequencing decision is a human's; there is no machine cause to spend a
    # budget against.
    for reason, (axis, category) in PARK_REASONS.items():
        if axis == "scheduling":
            assert category == "human", reason


def test_axis_and_category_are_derived_from_the_reason_not_stored() -> None:
    assert ParkingEntry(reason="ci-failure").axis == "failure"
    assert ParkingEntry(reason="ci-failure").category == "machine"
    assert ParkingEntry(reason="later-wave").axis == "scheduling"
    assert ParkingEntry(reason="later-wave").category == "human"


def test_an_untyped_park_is_absent_from_both_axes() -> None:
    entry = ParkingEntry(reason=None, note="pr closed, no typed reason")

    assert entry.axis is None
    assert entry.category is None


def test_a_machine_actionable_park_still_has_only_the_manual_exit() -> None:
    """The charter is categorical: the machine never acts on a parked item of
    its own accord, and there is no automatic TTL action. A machine-actionable
    reason means the executor already spent its bounded budget *before*
    parking -- it buys no routed re-entry afterwards. So `ci-failure` parks
    exactly as `deferred` does, and both wait for an explicit `item_enqueued`.
    """
    machine_parked = fold(
        [seed_event(), event("item_parked", item="wgclw.1", reason="ci-failure", note="red")]
    )
    scheduling_parked = fold(
        [seed_event(), event("item_parked", item="wgclw.2", reason="deferred", note="later")]
    )

    assert "wgclw.1" in machine_parked.parking_lot()
    assert "wgclw.2" in scheduling_parked.parking_lot()
    # Time passing is not an exit: the fold is a pure function of the log, so
    # no further event means no further movement, whatever the reason.
    assert machine_parked.items["wgclw.1"].parked is not None

    resumed = fold(
        [
            seed_event(),
            event("item_parked", item="wgclw.1", reason="ci-failure", note="red"),
            event("item_enqueued", item="wgclw.1", lane="lane-a"),
        ]
    )

    assert resumed.items["wgclw.1"].parked is None
    assert resumed.items["wgclw.1"].status == "queued"
