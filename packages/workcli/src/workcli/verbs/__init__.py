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


def _raw_incompatible_flags(args: Namespace) -> list[str]:
    """Noun/lifecycle-only inputs that `create_raw` never consumes.

    `create_raw` reads only title/description/type/priority/parent/labels; the
    positional noun and the lifecycle flags below (`--orphan`/`--spec`/
    `--trivial`/`--acceptance`) are silently ignored under `--raw`. `--orphan`
    in particular changes placement intent yet never records the orphan marker,
    so an ignored combination is a surprising no-op rather than a harmless one.
    """
    offenders: list[str] = []
    if args.noun is not None:
        offenders.append(f"noun {args.noun!r}")
    if args.orphan:
        offenders.append("--orphan")
    if args.spec is not None:
        offenders.append("--spec")
    if args.trivial:
        offenders.append("--trivial")
    if args.acceptance is not None:
        offenders.append("--acceptance")
    return offenders


def _create(backend: Backend, args: Namespace) -> JsonValue:
    """Dispatch `work create`: `--raw` (transport primitive) or a NOUN;
    absent both, refuse naming the two valid modes (spec §2, plan L9/CLI surface).

    `--raw` is transport-only: combining it with a noun or a lifecycle flag it
    cannot honor is rejected as `E_USAGE` rather than proceeding with a
    silently-ignored flag.
    """
    if args.raw:
        offenders = _raw_incompatible_flags(args)
        if offenders:
            raise WorkError(
                ErrorCode.USAGE,
                "create --raw is transport-only and cannot honor "
                f"{', '.join(offenders)}; drop it, or use `work create <noun>` "
                "for noun/lifecycle creation",
            )
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
