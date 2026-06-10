"""Prompt-template loader (§5 prompt templates).

Each contract's prompt lives in ``agent/prompts/<contract>.tmpl`` as a template
file with ``{placeholder}`` fields, rendered against a flat ``str -> str`` map
(the contract-specific data, flattened by the dispatcher). A power user may
override a shipped template by dropping a same-named file in ``PRGROOM_PROMPTS_DIR``
— that override wins per-filename and falls through to the shipped template when
the override dir lacks it. Override is for experimentation, not the default path.

Rendering is stdlib ``str.format_map`` over a strict mapping that raises on a
missing key, so an unresolved ``{placeholder}`` is a loud
:class:`UnresolvedPlaceholderError` rather than a silent hole shipped to the
agent. ``{{``/``}}`` escape to literal braces (the format-spec native rule), so a
template can embed literal JSON.

This is a deliberately minimal loader, not a templating engine: §5 names a single
shared engine "the same one used for reply rendering", but that reply renderer
does not exist in the foundation yet (the ``reply`` verb is still a skeleton).
Rather than invent a heavyweight dependency or a Protocol the foundation does not
own, this ships the smallest honest mechanism; when the reply renderer lands, its
bead may lift this into a shared module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Final

PROMPTS_DIR_ENV: Final = "PRGROOM_PROMPTS_DIR"
_TEMPLATE_SUFFIX: Final = ".tmpl"
_PROMPTS_PACKAGE: Final = "prgroom.agent.prompts"


class UnresolvedPlaceholderError(KeyError):
    """A template referenced a ``{placeholder}`` the render data did not supply.

    Subclasses :class:`KeyError` because that is what ``str.format_map`` raises on
    a missing key; the dispatcher catches this distinct type to fail the dispatch
    loudly rather than send a half-filled prompt to the agent.
    """


class _StrictMapping(dict[str, str]):
    """A ``format_map`` backing dict that turns a missing key into a clear error."""

    def __missing__(self, key: str) -> str:
        msg = f"prompt placeholder {{{key}}} has no value in the render data"
        raise UnresolvedPlaceholderError(msg)


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """A loaded prompt template. ``render`` substitutes a flat ``str -> str`` map."""

    name: str
    text: str

    def render(self, data: dict[str, str]) -> str:
        """Substitute ``{placeholder}`` fields from ``data`` (strict on missing keys).

        ``{{``/``}}`` collapse to literal braces. A placeholder with no matching
        ``data`` key raises :class:`UnresolvedPlaceholderError` — never a silent
        ``{hole}`` in the prompt handed to the agent.
        """
        return self.text.format_map(_StrictMapping(data))


def _override_path(name: str) -> Path | None:
    """The ``PRGROOM_PROMPTS_DIR/<name>.tmpl`` override path if it exists, else ``None``.

    A blank env value is treated as unset (POSIX convention, mirroring the Store's
    ``XDG_STATE_HOME`` handling). A dir that exists but lacks ``<name>.tmpl`` falls
    through to the shipped template — the override is per-filename, not all-or-nothing.
    """
    raw = os.environ.get(PROMPTS_DIR_ENV)
    if not raw:
        return None
    candidate = Path(raw) / f"{name}{_TEMPLATE_SUFFIX}"
    return candidate if candidate.is_file() else None


def load_prompt(name: str) -> PromptTemplate:
    """Load the ``<name>`` contract template (override dir wins, else shipped).

    ``name`` is the contract stem (``cluster`` / ``fix``). The override dir
    (``PRGROOM_PROMPTS_DIR``) is consulted first per-filename; otherwise the
    template ships inside the ``prgroom.agent.prompts`` package and is read via
    :mod:`importlib.resources` so it resolves from an installed wheel, not just a
    source checkout.
    """
    override = _override_path(name)
    if override is not None:
        return PromptTemplate(name=name, text=override.read_text(encoding="utf-8"))
    resource = resources.files(_PROMPTS_PACKAGE).joinpath(f"{name}{_TEMPLATE_SUFFIX}")
    return PromptTemplate(name=name, text=resource.read_text(encoding="utf-8"))
