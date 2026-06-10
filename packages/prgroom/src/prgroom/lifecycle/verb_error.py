"""Verb-error policy — tier → control-flow disposition + mandated mutation (§3.3).

``handle_verb_error`` maps a tier-tagged :class:`~prgroom.errors.PrgroomError` to a
:class:`VerbDisposition` (CONTINUE: the cycle proceeds; PROPAGATE: the run-loop
re-raises to ``run``, which applies ``exit_code_for_tier``) and applies the per-tier
state mutation. It mutates the passed ``state`` in place; the run-loop owns the
``store.write`` afterward (this module is gh/git/store-free).

``VerbDisposition`` is named distinctly from the §2 ``Disposition`` value-object —
this one is control flow, that one is a review item's outcome.

Tier policy (§3.6):

- ``RUNTIME_TRANSIENT`` → PROPAGATE, set ``last_error``, no phase change (scheduler retries).
- ``RUNTIME_TERMINAL_USER`` / ``STATE_CORRUPT`` / ``STATE_SCHEMA_UNKNOWN`` → PROPAGATE,
  gate ``human-gated``, set ``last_error``, re-arm ``lifecycle_escalation_filed=False``.
- ``CONTRACT_AUDIT_FAILED`` → CONTINUE, no ``last_error`` (the verb already flipped the
  affected item to ``FAILED`` with a rationale; the resolver gates phase at priority 2).
- ``RUNTIME_CANCELLED`` → PROPAGATE, no mutation (state stays exactly as last written
  so ``status`` reports the true last phase; the run-loop maps it to 130/143).
- Any other tier → PROPAGATE without mutation (crash-loud safety: never silently
  persist undefined state; a unit test enumerating every Tier recovers exhaustiveness).
"""

from __future__ import annotations

from enum import StrEnum

from prgroom.errors import PrgroomError, Tier
from prgroom.prsession.enums import PRPhase
from prgroom.prsession.state import PRGroomingState


class VerbDisposition(StrEnum):
    """Control-flow outcome of a verb error (§3.3). Distinct from §2 ``Disposition``."""

    CONTINUE = "continue"
    PROPAGATE = "propagate"


def handle_verb_error(err: PrgroomError, state: PRGroomingState) -> VerbDisposition:
    """Apply the §3.3 verb-error policy to ``state``; return the control disposition.

    Mutates ``state`` in place per the tier (the run-loop persists). See the module
    docstring for the full tier table.
    """
    match err.tier:
        case Tier.RUNTIME_TRANSIENT:
            state.last_error = err.code.value
            return VerbDisposition.PROPAGATE
        case Tier.RUNTIME_TERMINAL_USER | Tier.STATE_CORRUPT | Tier.STATE_SCHEMA_UNKNOWN:
            state.phase = PRPhase.HUMAN_GATED
            state.last_error = err.code.value
            state.lifecycle_escalation_filed = False
            return VerbDisposition.PROPAGATE
        case Tier.CONTRACT_AUDIT_FAILED:
            # The verb already flipped the affected item(s) to FAILED with a
            # rationale; the resolver promotes phase at priority 2. No last_error.
            return VerbDisposition.CONTINUE
        case Tier.RUNTIME_CANCELLED:
            # Non-retryable lifecycle exit; leave state untouched so `status` reports
            # the last known phase accurately. run maps this to 128 + signum.
            return VerbDisposition.PROPAGATE
        case _:
            # Tiers that do not reach this policy in normal flow (precondition tiers,
            # lifecycle-cap) get a defined, mutation-free answer rather than undefined
            # behavior. Crash-loud-safe: never silently store-write undefined state.
            return VerbDisposition.PROPAGATE
