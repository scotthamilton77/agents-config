"""show, list, ready, search — the read-only verbs.

Pure functions over a `Backend`: no subprocess, no I/O beyond the injected
seam. Each returns a `JsonValue` ready to drop straight into the envelope's
`data` field (`cli.py` handles the envelope wrapping and error translation).
"""

from __future__ import annotations

import dataclasses
from argparse import Namespace
from typing import cast

from workcli.backend import Backend
from workcli.envelope import JsonValue
from workcli.model import Item, QueryFilters


def _serialize_item(item: Item) -> dict[str, JsonValue]:
    # `dataclasses.asdict` recurses into the nested `DepEdge` list too, so
    # `deps` comes out already lean (`{id, type, status}`) with no extra work.
    return cast("dict[str, JsonValue]", dataclasses.asdict(item))


def _serialize_items(items: list[Item]) -> JsonValue:
    return {"items": [_serialize_item(item) for item in items]}


def show(backend: Backend, args: Namespace) -> JsonValue:
    """`work show ID...` — one id -> object, 2+ ids -> `{"items": [...]}` (decision 10)."""
    items = backend.batch_get(args.ids)
    if len(items) == 1:
        return _serialize_item(items[0])
    return _serialize_items(items)


def list_(backend: Backend, args: Namespace) -> JsonValue:
    """`work list [--status --label --parent --type --limit]` — unbounded unless `--limit`."""
    filters = QueryFilters(
        status=args.status,
        label=args.label,
        parent=args.parent,
        type=args.type,
        limit=args.limit,
    )
    return _serialize_items(backend.query(filters))


def ready(backend: Backend, args: Namespace) -> JsonValue:
    """`work ready [--label]` — unbounded by default (spec §3)."""
    return _serialize_items(backend.ready(args.label))


def search(backend: Backend, args: Namespace) -> JsonValue:
    """`work search QUERY`."""
    return _serialize_items(backend.search(args.query))
