"""Tests for the agent-dispatch contract surfaces (§5).

The contracts are stable, versioned interfaces between the CLI and the agent
CLI. The foundation pins:

* ``CONTRACT_VERSION`` is the wire integer (1) emitted in every contract JSON.
* The Cluster contract's *input* serializes to the §5 shape (contract_version,
  pr, items, paths).
* The Cluster contract's *output* parses the §5 cluster array, and the Fix
  contract's output parses per-item disposition rows — these are the boundary
  shapes prgroom must read back from an agent subprocess.

The Protocols themselves are structural (mypy --strict checks the fit); a fake
provider here proves a conformant implementation can be *driven* through the
Protocol's call surface, which is the behavior that matters.
"""

from __future__ import annotations

from datetime import UTC, datetime

from prgroom.agent.contracts import (
    CONTRACT_VERSION,
    ClusterContract,
    ClusterInput,
    ClusterOutput,
    ClusterResult,
    FixContract,
    FixInput,
    FixItemResult,
    FixOutput,
)
from prgroom.prsession.enums import DispositionKind, ItemKind
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import Identity, ReviewItem

_T = datetime(2026, 6, 9, tzinfo=UTC)
_REF = PRRef("octo", "demo", 7)


def _item(gh_id: str) -> ReviewItem:
    return ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id=gh_id, thread_id=f"PRT_{gh_id}"),
        author="copilot",
        body_excerpt="please extract a helper",
        seen_at=_T,
    )


def test_contract_version_is_one_on_the_wire() -> None:
    assert CONTRACT_VERSION == 1
    payload = ClusterInput(
        pr=_REF, items=[_item("C_1")], pr_context_path="/ctx", memory_path=None
    ).to_dict()
    assert payload["contract_version"] == 1


def test_cluster_input_serializes_items_and_paths() -> None:
    payload = ClusterInput(
        pr=_REF, items=[_item("C_1"), _item("C_2")], pr_context_path="/ctx.md", memory_path="/mem"
    ).to_dict()
    assert payload["pr"] == {"owner": "octo", "repo": "demo", "number": 7}
    assert [i["identity"]["gh_id"] for i in payload["items"]] == ["C_1", "C_2"]
    assert payload["pr_context_path"] == "/ctx.md"
    assert payload["memory_path"] == "/mem"


def test_cluster_input_omits_memory_path_when_absent() -> None:
    payload = ClusterInput(
        pr=_REF, items=[_item("C_1")], pr_context_path="/ctx.md", memory_path=None
    ).to_dict()
    assert "memory_path" not in payload


def test_cluster_output_parses_cluster_rows() -> None:
    out = ClusterOutput.from_dict(
        {
            "clusters": [
                {"cluster_id": "c-1", "item_gh_ids": ["C_1", "C_2"], "rationale": "same file"},
            ]
        }
    )
    assert out.clusters == [
        ClusterResult(cluster_id="c-1", item_gh_ids=["C_1", "C_2"], rationale="same file")
    ]


def test_fix_input_serializes_to_the_contract_shape() -> None:
    payload = FixInput(
        pr=_REF,
        cluster_id="c-1",
        item_gh_ids=["C_1"],
        items=[_item("C_1")],
        pr_detail_path="/detail.md",
        branch_state_path="/branch.md",
        memory_dir="/mem",
        response_outbox_dir="/out",
    ).to_dict()
    assert payload["contract_version"] == CONTRACT_VERSION
    assert payload["cluster_id"] == "c-1"
    assert payload["item_gh_ids"] == ["C_1"]
    assert payload["pr_detail_path"] == "/detail.md"
    assert payload["branch_state_path"] == "/branch.md"
    assert payload["memory_dir"] == "/mem"
    assert payload["response_outbox_dir"] == "/out"
    assert [i["identity"]["gh_id"] for i in payload["items"]] == ["C_1"]


def test_fix_output_parses_per_item_dispositions() -> None:
    out = FixOutput.from_dict(
        {
            "contract_version": 1,
            "items": [
                {
                    "gh_id": "C_1",
                    "disposition": "fixed",
                    "commit_shas": ["abc"],
                    "rationale": "",
                    "recommended_gate": "full",
                },
                {
                    "gh_id": "C_2",
                    "disposition": "wont_fix",
                    "rationale": "intentional",
                },
            ],
        }
    )
    assert out.items[0] == FixItemResult(
        gh_id="C_1",
        disposition=DispositionKind.FIXED,
        commit_shas=["abc"],
        rationale="",
        recommended_gate="full",
    )
    assert out.items[1].disposition is DispositionKind.WONT_FIX
    assert out.items[1].commit_shas == []


def test_a_fake_provider_is_driveable_through_the_cluster_protocol() -> None:
    class FakeClusterProvider:
        def cluster(self, request: ClusterInput) -> ClusterOutput:
            return ClusterOutput(
                clusters=[
                    ClusterResult(
                        cluster_id="c-1",
                        item_gh_ids=[i.identity.gh_id for i in request.items],
                        rationale="all of them",
                    )
                ]
            )

    provider: ClusterContract = FakeClusterProvider()
    result = provider.cluster(
        ClusterInput(pr=_REF, items=[_item("C_1")], pr_context_path="/c", memory_path=None)
    )
    assert result.clusters[0].item_gh_ids == ["C_1"]


def test_a_fake_provider_is_driveable_through_the_fix_protocol() -> None:
    class FakeFixProvider:
        def fix(self, request: FixInput) -> FixOutput:
            return FixOutput(
                items=[
                    FixItemResult(gh_id=gh_id, disposition=DispositionKind.SKIPPED, rationale="ack")
                    for gh_id in request.item_gh_ids
                ]
            )

    provider: FixContract = FakeFixProvider()
    result = provider.fix(
        FixInput(
            pr=_REF,
            cluster_id="c-1",
            item_gh_ids=["C_1", "C_2"],
            items=[_item("C_1"), _item("C_2")],
            pr_detail_path="/d",
            branch_state_path="/b",
            memory_dir="/m",
            response_outbox_dir="/o",
        )
    )
    assert [r.gh_id for r in result.items] == ["C_1", "C_2"]
