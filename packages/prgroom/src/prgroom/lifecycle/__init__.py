"""Lifecycle spine — the pure, gh/git-free core of the grooming loop (§3, §4).

This package holds the deterministic decision logic the `run` aggregate threads:
terminal-phase predicates, the §3.4 round/reviewer predicates, the §4.1
quiescence predicate, the §3.2 end-of-cycle phase resolver, and the §3.3
verb-error policy. None of it touches the clock, RNG, or the network directly —
time and randomness arrive via the injected :class:`~prgroom.deps.Deps` seams and
every gh/git effect lives behind the verb internals (a later bead).

The terminal sets distinguish the two notions of "done" (§3.1):

- **terminal-for-CLI** — the CLI takes no further autonomous action; re-entry
  needs an external trigger (operator push, ``resolve-escalated``, ``--max-rounds``
  raise). ``quiesced``, ``human-gated``, ``merged``.
- **graph-terminal** — truly absorbing; no path out. ``merged`` only.
"""

from __future__ import annotations

from prgroom.prsession.enums import PRPhase

TERMINAL_FOR_CLI_PHASES: frozenset[PRPhase] = frozenset(
    {PRPhase.QUIESCED, PRPhase.HUMAN_GATED, PRPhase.MERGED}
)
GRAPH_TERMINAL_PHASES: frozenset[PRPhase] = frozenset({PRPhase.MERGED})


def is_terminal_for_cli(phase: PRPhase) -> bool:
    """True iff the CLI rests at ``phase`` and awaits an external trigger (§3.1)."""
    return phase in TERMINAL_FOR_CLI_PHASES


def is_graph_terminal(phase: PRPhase) -> bool:
    """True iff ``phase`` is absorbing — ``merged`` only (§3.1)."""
    return phase in GRAPH_TERMINAL_PHASES
