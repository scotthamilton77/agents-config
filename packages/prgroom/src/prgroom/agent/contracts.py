"""Agent-dispatch contract Protocols + their input/output shapes (§5).

Each contract is a **stable, versioned interface** between the CLI and an agent
CLI (``claude -p`` / ``codex exec`` / ``opencode run``). Versioning the contract
is what lets the runtime be swapped without touching lifecycle code. The
foundation defines the surfaces; the concrete provider chains (ollama -> haiku
-> codex-mini for cluster; opus[1m] for fix) and the subprocess plumbing arrive
in later beads.

* **Cluster** (cheap) — groups unprocessed items into fix-bundles; decides NO
  disposition.
* **Fix** (heavy) — per cluster, decides per-item disposition AND implements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from prgroom.prsession.enums import DispositionKind
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import ReviewItem

CONTRACT_VERSION = 1

JsonObj = dict[str, Any]


def _pr_dict(pr: PRRef) -> JsonObj:
    return {"owner": pr.owner, "repo": pr.repo, "number": pr.number}


# ───────────────────────── Cluster contract ─────────────────────────


@dataclass(frozen=True, slots=True)
class ClusterInput:
    """Input to the cluster contract (§5). Written to a file passed to the agent."""

    pr: PRRef
    items: list[ReviewItem]
    pr_context_path: str
    memory_path: str | None = None

    def to_dict(self) -> JsonObj:
        d: JsonObj = {
            "contract_version": CONTRACT_VERSION,
            "pr": _pr_dict(self.pr),
            "items": [item.to_dict() for item in self.items],
            "pr_context_path": self.pr_context_path,
        }
        if self.memory_path is not None:
            d["memory_path"] = self.memory_path
        return d


@dataclass(frozen=True, slots=True)
class ClusterResult:
    """One cluster produced by the cluster contract (§5)."""

    cluster_id: str
    item_gh_ids: list[str]
    rationale: str


@dataclass(frozen=True, slots=True)
class ClusterOutput:
    """Output of the cluster contract (§5)."""

    clusters: list[ClusterResult]

    @classmethod
    def from_dict(cls, d: JsonObj) -> ClusterOutput:
        return cls(
            clusters=[
                ClusterResult(
                    cluster_id=c["cluster_id"],
                    item_gh_ids=list(c["item_gh_ids"]),
                    rationale=c["rationale"],
                )
                for c in d["clusters"]
            ]
        )


@runtime_checkable
class ClusterContract(Protocol):
    """The cluster dispatch surface. A provider groups items into fix-bundles."""

    def cluster(self, request: ClusterInput) -> ClusterOutput: ...  # pragma: no cover


# ───────────────────────── Fix contract ─────────────────────────


@dataclass(frozen=True, slots=True)
class FixInput:
    """Input to the fix contract (§5), once per cluster."""

    pr: PRRef
    cluster_id: str
    item_gh_ids: list[str]
    items: list[ReviewItem]
    pr_detail_path: str
    branch_state_path: str
    memory_dir: str
    response_outbox_dir: str

    def to_dict(self) -> JsonObj:
        return {
            "contract_version": CONTRACT_VERSION,
            "pr": _pr_dict(self.pr),
            "cluster_id": self.cluster_id,
            "item_gh_ids": list(self.item_gh_ids),
            "items": [item.to_dict() for item in self.items],
            "pr_detail_path": self.pr_detail_path,
            "branch_state_path": self.branch_state_path,
            "memory_dir": self.memory_dir,
            "response_outbox_dir": self.response_outbox_dir,
        }


@dataclass(frozen=True, slots=True)
class FixItemResult:
    """One item's disposition produced by the fix contract (§5)."""

    gh_id: str
    disposition: DispositionKind
    commit_shas: list[str] = field(default_factory=list)
    response_path: str | None = None
    rationale: str = ""
    recommended_gate: str = ""


@dataclass(frozen=True, slots=True)
class FixOutput:
    """Output of the fix contract (§5).

    The ``memory_writes`` / ``memory`` channels (§8) are accepted-but-deferred in
    the MVP; the foundation parses the per-item disposition rows that the
    lifecycle audit consumes.
    """

    items: list[FixItemResult]

    @classmethod
    def from_dict(cls, d: JsonObj) -> FixOutput:
        return cls(
            items=[
                FixItemResult(
                    gh_id=row["gh_id"],
                    disposition=DispositionKind(row["disposition"]),
                    commit_shas=list(row.get("commit_shas", [])),
                    response_path=row.get("response_path"),
                    rationale=row.get("rationale", ""),
                    recommended_gate=row.get("recommended_gate", ""),
                )
                for row in d["items"]
            ]
        )


@runtime_checkable
class FixContract(Protocol):
    """The fix dispatch surface. A provider decides disposition AND implements."""

    def fix(self, request: FixInput) -> FixOutput: ...  # pragma: no cover
