"""PRRef — the per-PR identity used as the Store key (§2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PRRef:
    """Identifies one PR. Frozen + slots so it is hashable and usable as a dict key."""

    owner: str
    repo: str
    number: int

    def slug(self) -> str:
        """Filesystem-/label-safe stem: ``<owner>-<repo>-<n>`` (§2 file adapter, bd label)."""
        return f"{self.owner}-{self.repo}-{self.number}"

    def display(self) -> str:
        """Human-facing GitHub shorthand: ``<owner>/<repo>#<n>``."""
        return f"{self.owner}/{self.repo}#{self.number}"

    def to_dict(self) -> dict[str, Any]:
        """The ``{owner, repo, number}`` JSON shape used in state + contract payloads."""
        return {"owner": self.owner, "repo": self.repo, "number": self.number}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PRRef:
        return cls(owner=d["owner"], repo=d["repo"], number=d["number"])
