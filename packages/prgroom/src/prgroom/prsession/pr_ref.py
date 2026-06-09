"""PRRef — the per-PR identity used as the Store key (§2)."""

from __future__ import annotations

from dataclasses import dataclass


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
