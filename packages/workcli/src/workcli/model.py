"""Shapes shared across the verb layer and every Backend adapter.

Normalized, backend-agnostic dataclasses: `Item`/`DepEdge` are what an
adapter's parser produces from the backend's raw payload, and what the verb
layer serializes into envelope `data` via `dataclasses.asdict`.
"""

from __future__ import annotations

from dataclasses import dataclass

# The three fields describing an item's place in the tree. Not every backend
# read reports all three -- see `Item.unknown_relations`.
RELATIONSHIP_FIELDS = ("parent", "deps", "children")


@dataclass(frozen=True)
class DepEdge:
    id: str
    # An open `str`, deliberately, and NOT the closed set `dep add` enforces
    # (`verbs/relations.py::DEP_TYPES`). A backend need not validate the type
    # it is handed -- bd stores whatever it is given -- so edges carrying an
    # unsanctioned type already exist; a read that could not express one would
    # misreport the very edges the write-side check now exists to stop being
    # made. Closed on write, open on read.
    type: str
    status: str  # status of the item at the other end


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
    created: str | None  # ISO strings as the backend emits them; no datetime parsing in v1
    updated: str | None
    # The criteria a claim on this item is checked against. `None` is the
    # backend's own answer -- this item carries none -- and is why the field
    # takes no default: an item built without one would report "no criteria"
    # for an item nobody asked about, which is the silence this field exists
    # to end. Optional rather than `str` because "none" is a real state here,
    # unlike `description`/`notes`, where the empty string says the same thing.
    acceptance: str | None
    # Which of `RELATIONSHIP_FIELDS` the source read could not express. The
    # fields themselves hold their empty value when named here, and the verb
    # layer drops them from the envelope rather than publishing an empty
    # stand-in for an answer the backend never gave: `[]` is indistinguishable
    # from a true "no children", so a verb that cannot see children must say
    # so rather than imply there are none.
    unknown_relations: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DepListing:
    # Named for the relationship, never for a backend's own direction words:
    # "up" and "down" invert depending on who is speaking, and a field named
    # after one would re-encode that ambiguity into every caller. bd is the
    # case that established it -- its `dep list --direction` default ("down")
    # lists what this item depends on, while "up" lists what depends on this
    # item (verified against golden fixtures in
    # adapters/bd/backend.py::BdBackend.dep_list).
    depends_on: list[DepEdge]
    dependents: list[DepEdge]


@dataclass(frozen=True)
class SyncResult:
    synced: bool
    # "push" | "pull" | "noop" -- "noop" is reserved for server-authoritative
    # backends that declare themselves a no-op; the bd adapter never emits it.
    mode: str


@dataclass(frozen=True)
class CreateFields:
    title: str
    description: str | None = None
    type: str | None = None
    priority: str | None = None
    parent: str | None = None
    labels: tuple[str, ...] = ()
    acceptance: str | None = None  # the criteria to stamp at creation
    blocked_by: str | None = None  # one bare blocks-edge, applied atomically at creation


@dataclass(frozen=True)
class UpdateFields:  # replace-semantics fields ONLY; notes never appear here
    title: str | None = None
    priority: str | None = None
    description: str | None = None
    # The parent is single-valued, so a move belongs here with the other
    # replace-semantics fields rather than on `dep add`, which only ever adds.
    # Reparenting through the seam replaces the old parent-child edge outright
    # (verified against bd's atomic `update --parent`), so one call moves the
    # item with no window in which it has two parents.
    parent: str | None = None


@dataclass(frozen=True)
class QueryFilters:
    status: str | None = None
    label: str | None = None
    parent: str | None = None
    type: str | None = None
    limit: int | None = None


# The `Item` fields a search may read, in the order a result set reports them
# -- a title match ranks above a description match, which ranks above a note.
# Ordering is contract, not incidental: it is what a caller's `--limit` keeps.
SEARCH_FIELDS = ("title", "description", "notes")


@dataclass(frozen=True)
class SearchFilters:
    query: str
    # Every field by default. The three narrowings this verb used to apply
    # silently -- corpus, status, bound -- are each askable now, and each
    # defaults to the wide answer: a narrowing nobody chose returns an empty
    # result a caller cannot tell from a true "nothing like this exists".
    corpus: frozenset[str] = frozenset(SEARCH_FIELDS)
    status: str | None = None  # None = every status, closed included
    # No limit here on purpose. A search spans several fields, and a bound
    # pushed down per field would truncate each one before they are merged
    # and undercount the union; the verb layer applies it to the merged set
    # instead (same ordering `list --track` already enforces).
