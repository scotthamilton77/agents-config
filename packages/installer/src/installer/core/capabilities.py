"""Capability front matter: which tool's loader defines which key.

Some front-matter keys describe the artifact (``name``, ``description``) and
mean the same thing everywhere. Others name a capability of the *runtime that
loads it*: Claude Code reads ``disable-model-invocation`` to keep a skill out
of the model's catalog, ``allowed-tools`` to bound what an invoked artifact may
call, and ``argument-hint`` to describe its ``/name`` invocation. No other
supported tool defines any of the three.

Shared content stages into every tool, so without a projection step an author
faces a false choice: carry the key and ship inert lines into Codex, Gemini and
OpenCode, or drop it and lose the capability on the one tool that has it. The
projection removes the choice — the shared tree carries the key, and each tool
receives what is correct for it.

**The projection is to drop the key**, for every tool that does not define it.
Not to translate it: none of Codex, Gemini or OpenCode exposes a per-artifact
invocation control, a per-artifact tool allowlist, or an argument hint, so
there is no target to translate onto and inventing one would assert a
capability that is not there. Not to keep it inert either, on the sanitizer's
own reasoning — bytes with no runtime purpose downstream load into the reader's
context for nothing, and a loader that validates its front matter strictly
would reject the artifact rather than ignore the key. The same conclusion is
already reached one namespace over, where the Gemini adapter strips Claude-only
keys from agent front matter.

Support is declared per key rather than per tool. A tool acquiring one of these
capabilities is then a one-name edit, and a key nothing supports is visible as
an empty set rather than as an absence from four lists.

``disable-model-invocation`` carries two consequences beyond projection, and
both are read from the **projected** front matter rather than from the source:
it decides which cap measures the artifact's body, and whether the artifact's
catalog entry is charged to the always-on budget (see ``surface_budget``).
Reading the source would price a claim the author made instead of a fact about
the target — a shared skill declaring itself user-invoked is fully
model-invocable on every tool this projection strips the key for, so its
description does load and its body arrives on the model's own judgement.

Reading after projection makes one artifact's numbers depend on which tool is
being staged. That is the intent: the number prices the target, and the targets
differ. The *verdict* stays uniform, because the repo-side content lint stages
every known tool unconditionally on every run — so an artifact is judged against
every target it can reach, and a per-machine deploy can only be looser than the
gate the repository has already passed.

Codex is where the projected reading and the vendor's mechanism will eventually
diverge: Codex honours a user-invoked declaration through a generated sidecar
file beside the skill rather than through ``SKILL.md`` front matter, and this
installer emits no such sidecar. So today every deployed skill is in Codex's
catalog, which is exactly what the projected reading reports, because the key
is stripped for Codex. The change that emits the sidecar is the change that
must also make this module say so; nothing should be added for it beforehand.
"""

from __future__ import annotations

from installer.core.frontmatter import split_frontmatter

#: The key by which an artifact declares itself user-invoked only: the runtime
#: keeps it out of the model's catalog, so it is reached only when the user
#: names it.
USER_INVOKED_KEY = "disable-model-invocation"

#: Capability key → the tool names whose loader defines it. A key absent from a
#: tool's set is removed from that tool's deployed bytes. Tools are named by
#: ``Tool.value``, the same string the adapters carry as ``name``; a name here
#: that is not a known tool is a defect a test catches, because a typo would
#: silently strip the key from the tool that does support it.
CAPABILITY_SUPPORT: dict[str, frozenset[str]] = {
    USER_INVOKED_KEY: frozenset({"claude"}),
    "allowed-tools": frozenset({"claude"}),
    "argument-hint": frozenset({"claude"}),
}


#: Tools whose skill loading this project deliberately does not model, and which
#: therefore contribute to neither skill measurement — no catalog charge, no body
#: cap. Gemini is the only member: its CLI is deprecated, no vendor documentation
#: establishes whether it reads a deployed skill at all, and a number invented for
#: it would be a guess wearing a measurement's clothes. Silence is the honest
#: report, because a guess is the thing a reader would act on.
#:
#: An entry leaves the day that tool's skill loading is established. The default
#: is the safe direction: a tool absent from this set is modelled, so a newly
#: registered tool is charged and capped rather than silently exempt.
UNMODELLED_SKILL_LOADERS: frozenset[str] = frozenset({"gemini"})


def models_skill_loading(tool: str) -> bool:
    """True when this project models how ``tool``'s runtime loads a deployed skill.

    False means neither the catalog charge nor the body cap is computed for that
    tool — see ``UNMODELLED_SKILL_LOADERS``.
    """
    return tool not in UNMODELLED_SKILL_LOADERS


def unsupported_keys(tool: str) -> frozenset[str]:
    """The capability keys ``tool``'s loader does not define.

    An unknown tool name yields every key, which is the safe direction: a tool
    added to the registry without an entry here ships no inert capability keys,
    where the opposite default would ship all of them.
    """
    return frozenset(key for key, tools in CAPABILITY_SUPPORT.items() if tool not in tools)


def is_user_invoked(text: str) -> bool:
    """True when ``text``'s front matter sets ``disable-model-invocation: true``.

    Compared against ``True`` rather than truthiness, so an explicit ``false``
    and a stray string both read as model-invoked — the stricter cap is the one
    to fall back to.
    """
    mapping, _body = split_frontmatter(text)
    return mapping is not None and mapping.get(USER_INVOKED_KEY) is True
