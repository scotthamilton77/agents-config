"""Install / prune summary renderer.

``cli.main`` merges the per-target ``Counters`` from the three pipelines
(``install_pipeline`` tools, ``install_plugin_routes`` plugins,
``prune_pipeline`` orphans-by-tool) and hands them here with the active tool /
plugin lists, the ALL_* universes, and the verbose flag. The renderer decides
*what* to print and routes every line through the injected ``IOPort`` — it owns
no terminal, so it is unit-testable through ``ScriptedIO``.

Two shapes, branching on ``verbose``:

- **verbose**: a '-- Summary --' header, then one '-- <target> --' block per
  report target listing the six fields in fixed order (Installed / Updated /
  Merged / Backed up / Pruned / Skipped), then a DIM '(not detected, skipped)'
  footer for every ALL_* target absent from the report set;
- **quiet**: one line per target with non-zero *changes* (installed + updated +
  merged + pruned; a pure skip is not a change), or the single 'All files up to
  date — no changes made.' line when nothing changed anywhere.

The report-target set: active tools, then active plugins, then any ALL_* plugin
that pruned outside the active set (AC#19) — keyed off the report set so such a
plugin gets a real block, not a skipped footer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from installer.core.model import Counters

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from installer.core.io_port import IOPort

# Field rows in the verbose block: (label, Counters attribute). 'Installed' maps
# to the model's ``created`` (the rename lives here in the renderer, not the model).
_FIELDS: tuple[tuple[str, str], ...] = (
    ("Installed", "created"),
    ("Updated", "updated"),
    ("Merged", "merged"),
    ("Backed up", "backed_up"),
    ("Pruned", "pruned"),
    ("Skipped", "skipped"),
)

# Column at which each field's value is printed; computed so a label rename
# keeps alignment.
_VALUE_COLUMN = max(len(label) for label, _ in _FIELDS) + len(":  ")

# Quiet-line parts: (Counters attribute, suffix). A part is shown only when its
# value is non-zero.
_QUIET_PARTS: tuple[tuple[str, str], ...] = (
    ("created", "installed"),
    ("updated", "updated"),
    ("merged", "merged"),
    ("backed_up", "backed up"),
    ("pruned", "pruned"),
)


def _is_changed(counters: Counters) -> bool:
    """Whether a target counts as *changed* for the quiet summary.

    A pure skip is not a change — only installed/updated/merged/pruned count.
    ``backed_up`` rides along a change but never
    constitutes one on its own (a backup only happens alongside an overwrite or a
    prune), so it is intentionally excluded from this predicate.
    """
    return bool(counters.created or counters.updated or counters.merged or counters.pruned)


def _report_targets(
    counters: Mapping[str, Counters],
    *,
    tools: Sequence[str],
    plugins: Sequence[str],
    all_plugins: Sequence[str],
    clis: Sequence[str] = (),
) -> list[str]:
    """Ordered report-target set.

    Active tools, then active plugins, then any ALL_* plugin that is not already
    a report target but accumulated prune activity — so a plugin pruned outside
    the active set (AC#19) is reported once, as a real block. ``clis`` (the
    cli:<name> deploy/prune targets) are appended last, unconditionally — they
    have no ALL_* universe of their own.
    """
    targets = [*tools, *plugins, *clis]
    seen = set(targets)
    for plugin in all_plugins:
        if plugin in seen:
            continue
        c = counters.get(plugin)
        if c is not None and (c.pruned or c.backed_up):
            targets.append(plugin)
    return targets


def render_summary(
    counters: Mapping[str, Counters],
    *,
    tools: Sequence[str],
    plugins: Sequence[str],
    all_tools: Sequence[str],
    all_plugins: Sequence[str],
    clis: Sequence[str] = (),
    verbose: bool,
    io: IOPort,
) -> None:
    """Render the install / prune summary through ``io``.

    ``counters`` is the merged per-target tally (a target absent from the map is
    treated as all-zero). ``tools`` / ``plugins`` are the active sets in report
    order; ``all_tools`` / ``all_plugins`` are the ALL_* universes used to emit
    the '(not detected, skipped)' footers. ``clis`` is the active cli:<name>
    deploy/prune target set. ``verbose`` selects the per-tool block form over
    the one-line quiet form.
    """
    targets = _report_targets(
        counters, tools=tools, plugins=plugins, all_plugins=all_plugins, clis=clis
    )
    if verbose:
        _render_verbose(counters, targets, all_tools=all_tools, all_plugins=all_plugins, io=io)
    else:
        _render_quiet(counters, targets, io=io)


def _render_verbose(
    counters: Mapping[str, Counters],
    targets: Sequence[str],
    *,
    all_tools: Sequence[str],
    all_plugins: Sequence[str],
    io: IOPort,
) -> None:
    """Per-target block form.

    Each block header is ``\\n-- <name> --\\n``: a leading blank line, then the
    name wrapped in ``-- ... --``. The renderer produces this explicitly (a blank
    ``io.info("")`` then the wrapped name) rather than relying on
    ``IOPort.header``, whose contract prints the message verbatim with no
    wrapping and no leading newline (and is shared with non-Summary callers that
    pass already-formed text). A trailing blank line precedes ``Done.``.
    """
    io.info("")
    io.header("-- Summary --")
    for target in targets:
        c = counters.get(target, Counters())
        io.info("")
        io.header(f"-- {target} --")
        for label, attr in _FIELDS:
            value = getattr(c, attr)
            pad = " " * (_VALUE_COLUMN - len(label) - len(":"))
            io.info(f"  {label}:{pad}{value}")
    reported = set(targets)
    for absent in [*all_tools, *all_plugins]:
        if absent not in reported:
            io.info("")
            io.info(f"-- {absent} (not detected, skipped) --")
    io.info("")
    io.ok("Done.")


def _render_quiet(
    counters: Mapping[str, Counters],
    targets: Sequence[str],
    *,
    io: IOPort,
) -> None:
    """One-line-per-changed-target form."""
    lines: list[str] = []
    for target in targets:
        c = counters.get(target, Counters())
        if not _is_changed(c):
            continue
        parts = [
            f"{getattr(c, attr)} {suffix}" for attr, suffix in _QUIET_PARTS if getattr(c, attr)
        ]
        lines.append(f"{target}: {', '.join(parts)}")
    # One blank line before the up-to-date / Done branch, regardless of which fires.
    io.info("")
    if not lines:
        io.ok("All files up to date — no changes made.")
        return
    io.ok("Done.")
    for line in lines:
        io.info(f"   {line}")
