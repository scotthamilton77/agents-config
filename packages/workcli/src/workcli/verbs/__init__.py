"""VERBS registry and the capability gate (decision 11).

`VERBS` maps a verb name to its handler: `(Backend, Namespace) -> JsonValue`.
`REQUIRED_CAPABILITY` maps a verb name to a predicate function over
`Capabilities` that must return true for the verb to run; a verb absent
from this map has no gate (every v1 backend must
support it unconditionally). `cli.py`'s dispatch loop checks the gate before
ever calling the handler, so an unsupported capability never reaches verb
code at all.
"""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Callable

from workcli.backend import Backend, Capabilities
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.lifecycle.create import create_noun
from workcli.lifecycle.deliver import deliver
from workcli.lifecycle.reconcile import reconcile
from workcli.lifecycle.transitions import claim, plan, promote, release
from workcli.verbs.read import list_, ready, search, show
from workcli.verbs.relations import dep, label
from workcli.verbs.syncing import sync
from workcli.verbs.write import close, create_raw, note, reopen, update


def _create(backend: Backend, args: Namespace) -> JsonValue:
    """Dispatch `work create`: `--raw` (transport primitive) wins over a NOUN;
    absent both, refuse naming the two valid modes (spec §2, plan L9/CLI surface).
    """
    if args.raw:
        return create_raw(backend, args)
    if args.noun is not None:
        return create_noun(backend, args)
    raise WorkError(
        ErrorCode.USAGE,
        "create requires --raw (transport primitive) or a noun "
        "(spike|chore|decision|feat|bugfix|spec|epic)",
    )


VERBS: dict[str, Callable[[Backend, Namespace], JsonValue]] = {
    "show": show,
    "list": list_,
    "ready": ready,
    "search": search,
    "create": _create,
    "update": update,
    "note": note,
    "close": close,
    "reopen": reopen,
    "claim": claim,
    "release": release,
    "plan": plan,
    "promote": promote,
    "deliver": deliver,
    "reconcile": reconcile,
    "dep": dep,
    "label": label,
    "sync": sync,
}

REQUIRED_CAPABILITY: dict[str, Callable[[Capabilities], bool]] = {
    "ready": lambda c: c.supports_ready,
    "sync": lambda c: c.supports_sync,
    "dep": lambda c: c.supports_dep_types,
}


def missing_capability(verb: str, capabilities: Capabilities) -> bool:
    """True when `verb` declares a required capability `capabilities` lacks."""
    check = REQUIRED_CAPABILITY.get(verb)
    if check is None:
        return False
    return not check(capabilities)
