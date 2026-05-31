"""Filesystem-backed Idea storage — the MVP backend behind `IdeaStorage`.

One YAML document per Idea at ``<root>/ideas/<idea_id>.yml``. This is the
MVP storage adapter named in ADR-0001; it conforms to the `IdeaStorage`
seam so a later Dolt/SQLite/cloud backend can replace it by configuration
without touching the service layer.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import yaml

from holding_place.idea import Idea


class IdeaNotFoundError(LookupError):
    """Raised when an Idea id has no document on disk."""


class FilesystemIdeaStorage:
    """Stores each Idea as a YAML document under ``<root>/ideas/``.

    Structurally satisfies `IdeaStorage`. The directory is created on first
    write so callers need only supply a root path.
    """

    def __init__(self, root: Path) -> None:
        self._ideas_dir = root / "ideas"

    def _path_for(self, idea_id: str) -> Path:
        # Safe today: ids are machine-minted upstream (id_factory / promote).
        # Revisit with explicit validation if externally-sourced ids ever reach
        # here — a ``../`` or absolute-path id would escape the ideas root.
        return self._ideas_dir / f"{idea_id}.yml"

    def get(self, idea_id: str) -> Idea:
        path = self._path_for(idea_id)
        if not path.exists():
            raise IdeaNotFoundError(idea_id)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return Idea(**data)

    def put(self, idea: Idea) -> None:
        self._ideas_dir.mkdir(parents=True, exist_ok=True)
        self._path_for(idea.id).write_text(
            yaml.safe_dump(asdict(idea), sort_keys=True),
            encoding="utf-8",
        )

    def exists(self, idea_id: str) -> bool:
        return self._path_for(idea_id).exists()
