"""VERBS registry and the capability gate (decision 11).

`VERBS` maps a verb name to its handler: `(Backend, Namespace) -> JsonValue`.
`REQUIRED_CAPABILITY` maps a verb name to the `Capabilities` attribute it
needs; a verb absent from this map has no gate (every v1 backend must
support it unconditionally). `cli.py`'s dispatch loop checks the gate before
ever calling the handler, so an unsupported capability never reaches verb
code at all.
"""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Callable

from workcli.backend import Backend, Capabilities
from workcli.envelope import JsonValue
from workcli.verbs.read import list_, ready, search, show
from workcli.verbs.relations import dep, label
from workcli.verbs.syncing import sync
from workcli.verbs.write import close, create_raw, note, reopen, update

VERBS: dict[str, Callable[[Backend, Namespace], JsonValue]] = {
    "show": show,
    "list": list_,
    "ready": ready,
    "search": search,
    "create": create_raw,
    "update": update,
    "note": note,
    "close": close,
    "reopen": reopen,
    "dep": dep,
    "label": label,
    "sync": sync,
}

REQUIRED_CAPABILITY: dict[str, str] = {
    "ready": "supports_ready",
    "sync": "supports_sync",
    "dep": "supports_dep_types",
}


def missing_capability(verb: str, capabilities: Capabilities) -> bool:
    """True when `verb` declares a required capability `capabilities` lacks."""
    attr = REQUIRED_CAPABILITY.get(verb)
    if attr is None:
        return False
    return not getattr(capabilities, attr)
