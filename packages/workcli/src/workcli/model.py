"""Shapes shared across the verb layer and every Backend adapter.

Normalized, backend-agnostic dataclasses: `Item`/`DepEdge` are what the bd
adapter's parser (`adapters/bd/parse.py`) produces from raw bd JSON, and what
the verb layer serializes into envelope `data` via `dataclasses.asdict`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DepEdge:
    id: str
    type: str  # "blocks" | "related-to" | "parent-child" | "discovered-from" | ...
    status: str  # status of the bead at the other end


@dataclass(frozen=True)
class Item:
    id: str
    title: str
    type: str  # task|bug|feature|epic|milestone (str, not enum: drift tolerance)
    status: str  # open|in_progress|closed|deferred
    priority: str  # "P0".."P4"
    labels: list[str]
    parent: str | None
    deps: list[DepEdge]  # up-edges (what this item depends on)
    children: list[str]
    description: str
    notes: str
    created: str | None  # ISO strings as bd emits them; no datetime parsing in v1
    updated: str | None


@dataclass(frozen=True)
class DepListing:
    up: list[DepEdge]
    down: list[DepEdge]


@dataclass(frozen=True)
class SyncResult:
    synced: bool
    mode: str  # "push" | "pull" | "noop"


@dataclass(frozen=True)
class CreateFields:
    title: str
    description: str | None = None
    type: str | None = None
    priority: str | None = None
    parent: str | None = None
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class UpdateFields:  # replace-semantics fields ONLY; notes never appear here
    title: str | None = None
    priority: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class QueryFilters:
    status: str | None = None
    label: str | None = None
    parent: str | None = None
    type: str | None = None
    limit: int | None = None
