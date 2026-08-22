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

**The projection drops the key** for every tool whose loader does not define
it. For ``disable-model-invocation`` on Codex the drop is half of a
translation: Codex expresses the same declaration through a sidecar file
beside the skill's entry file — ``agents/openai.yaml`` carrying
``policy.allow_implicit_invocation: false`` — which the Codex adapter
generates at deploy time for every skill carrying the key. The key itself is
still not a Codex front-matter key, so it still does not ship. Everywhere
else the drop is the whole projection: Gemini and OpenCode expose no
per-artifact invocation control, and no tool but Claude defines a
per-artifact tool allowlist or an argument hint, so there is no target to
translate onto and inventing one would assert a capability that is not there.
Keeping a key inert is no better, on the sanitizer's own reasoning — bytes
with no runtime purpose downstream load into the reader's context for
nothing, and a loader that validates its front matter strictly would reject
the artifact rather than ignore the key. The same conclusion is already
reached one namespace over, where the Gemini adapter strips Claude-only keys
from agent front matter.

Support is declared per key rather than per tool. A tool acquiring one of these
capabilities is then a one-name edit, and a key nothing supports is visible as
an empty set rather than as an absence from four lists.

``disable-model-invocation`` carries two consequences beyond projection, and
they read the front matter at different points (see ``surface_budget``).

Which cap measures the artifact's **body** is read from the **source**
declaration, so it is the same on every target. The cap prices the shape its
author committed to — a body reached only when a user names it may be longer
than one the model may pull in mid-task — and a tool whose loader cannot
express that declaration has not been handed a different artifact. Pricing the
projection instead would charge the author the strict cap for a claim they did
make, on the grounds that the weakest loader in the set cannot read it.

Whether the artifact's **catalog entry** is charged to the always-on budget is
read from the **projected** front matter, so it is a fact about the target. A
shared skill declaring itself user-invoked is still published to the model on
Gemini and OpenCode, where the projection strips the key and nothing replaces
it: there the description genuinely does load into every session, and not
charging it would understate what a reader cannot decline. Codex strips the key
too, but the generated sidecar keeps the skill out of implicit invocation; its
description is charged from the projected reading all the same, an over-charge
in the safe direction rather than an under-charge.

Reading the projection makes one artifact's catalog number depend on which tool
is being staged. That is the intent: the number prices the target, and the
targets differ. The *verdict* stays uniform, because the repo-side content lint
stages every known tool unconditionally on every run — so an artifact is judged
against every target it can reach, and a per-machine deploy can only be looser
than the gate the repository has already passed.
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
