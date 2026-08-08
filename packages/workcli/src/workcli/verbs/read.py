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
from workcli.lifecycle.park import parked_stale
from workcli.model import SEARCH_FIELDS, Item, QueryFilters, SearchFilters
from workcli.tracks import derive_track, require_known_track


def _serialize_item(item: Item) -> dict[str, JsonValue]:
    # `dataclasses.asdict` recurses into the nested `DepEdge` list too, so
    # `deps` comes out already lean (`{id, type, status}`) with no extra work.
    serialized = cast("dict[str, JsonValue]", dataclasses.asdict(item))
    # A relationship the source read could not express is dropped rather than
    # published as `null`/`[]`, and named in `unknown_relations` instead --
    # sorted, and present on every read item so "this verb does not report
    # children" is legible without knowing which verb produced the item. The
    # empty stand-in is the thing being removed: a consumer could not tell it
    # from a true answer, so `search` reported every item as an unparented
    # leaf and `list` reported every epic as childless.
    unknown = sorted(item.unknown_relations)
    for field in unknown:
        del serialized[field]
    serialized["unknown_relations"] = cast("list[JsonValue]", unknown)
    # `acceptance` deliberately stays out of that mechanism. Every read the
    # backend offers carries the criteria, so the field is always present and
    # `null` says the item has none; an absent key would say this read never
    # fetched them, which is a state no read is in. Same principle, different
    # conclusion: the distinction is what matters, not the list.
    # Derived in the verb layer, config-free, so every read envelope carries
    # it regardless of config state (the 1.1 additive field).
    serialized["track"] = derive_track(item.labels)
    return serialized


def _serialize_items(items: list[Item]) -> JsonValue:
    return {"items": [_serialize_item(item) for item in items]}


def show(backend: Backend, args: Namespace) -> JsonValue:
    """`work show ID...` — one id -> object, 2+ ids -> `{"items": [...]}`."""
    items = backend.batch_get(args.ids)
    if len(items) == 1:
        return _serialize_item(items[0])
    return _serialize_items(items)


def list_(backend: Backend, args: Namespace) -> JsonValue:
    """`work list [--status --label --parent --type --limit --track]`.

    `--track` filters on the DERIVED `Item.track` (never raw label presence),
    so filter and envelope field always agree: zero-or-multi-label items
    derive to null and match nothing. Validated against the
    vocabulary for parity with `create --track` -- a typo returns
    E_UNKNOWN_TRACK, not a silently-empty result. Ordering matters twice:
    config loads BEFORE the backend query (E_NOT_CONFIGURED must precede any
    backend error, and an unconfigured call must not read the tracker), and
    --limit applies AFTER the track filter (a bd-side limit would truncate
    the candidate set before filtering and undercount matches). `--limit 0`
    is the existing unbounded sentinel (mirrored from the bd adapter, which
    sends "0" for both an omitted limit and an explicit 0) -- it must not
    slice the filtered set down to zero items. A negative limit is never
    meaningful either -- unlike bd-side slicing, Python's `items[:n]` with a
    negative `n` silently drops trailing items rather than erroring, so
    zero-or-negative both mean unbounded here.
    """
    if args.track is not None:
        require_known_track(args.track, args.load_config())
        unbounded = QueryFilters(
            status=args.status,
            label=args.label,
            parent=args.parent,
            type=args.type,
            limit=None,
        )
        items = [
            item for item in backend.query(unbounded) if derive_track(item.labels) == args.track
        ]
        if args.limit is not None and args.limit > 0:
            items = items[: args.limit]
        return _serialize_items(items)
    filters = QueryFilters(
        status=args.status,
        label=args.label,
        parent=args.parent,
        type=args.type,
        limit=args.limit,
    )
    return _serialize_items(backend.query(filters))


def ready(backend: Backend, args: Namespace) -> JsonValue:
    """`work ready [--label]` — unbounded by default, plus the `parked_stale` block.

    The block is always present — an empty list when nothing qualifies,
    because "no stale parked work" is a reported fact, not a missing field.
    It rides the default threshold and takes no flag of its own; tuning stays
    on `work parked --stale-days`. The parked read runs FIRST, matching the
    order the composed `{parked, ready}` surface reads in — and it is
    fail-closed, so a `ready` list is never handed out beside a surfacing
    that quietly failed.
    """
    block = parked_stale(backend, args.now(), verb="ready")
    items = backend.ready(args.label)
    return {"items": [_serialize_item(item) for item in items], "parked_stale": block}


def search(backend: Backend, args: Namespace) -> JsonValue:
    """`work search QUERY [--in FIELD] [--status S] [--limit N]`.

    Wide by default on all three axes -- every searchable field, every
    status, no bound -- because each narrowing turns a match into an empty
    result indistinguishable from a true "nothing like this exists", and a
    caller checking for prior art reads that as permission to file. Any of
    the three can be asked for explicitly; none is applied unasked.

    `--limit` slices the merged result, never the individual field reads:
    bounding each field before the merge would undercount the union, the
    same ordering `list --track` enforces on its own filter. Zero-or-negative
    means unbounded, matching `list`.
    """
    corpus = frozenset(args.corpus or SEARCH_FIELDS)
    items = backend.search(SearchFilters(query=args.query, corpus=corpus, status=args.status))
    if args.limit is not None and args.limit > 0:
        items = items[: args.limit]
    return _serialize_items(items)
