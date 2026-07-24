"""The deploy-time admission gate.

One pass over the finalized staging plans, run in ``cli._run`` after the plan
is assembled and before any write. It:

1. **partitions** every gated artifact (rules/skills/commands/agents) by its
   admission record — dropping the record-less (the zero-base mechanism),
   collecting the malformed as violations, keeping the complete;
2. measures the **surface budget** over the *admitted* content — the
   always-on surface per tool and each admitted skill body;
3. runs the **conflict audit** over the admitted artifacts' claims.

Any violation makes ``GateResult.ok`` false; the caller reports each and aborts
with a non-zero exit *before* the write block, so a breach never half-deploys.
The returned ``plans`` are the admission-filtered plans the caller installs —
content the gate dropped is no longer desired, so the existing prune removes
any previously-deployed copy (this is what reproduces the empty zero-base dirs).

The gate runs on the user-home deploy only; the ``--project`` surface is not
gated (the always-on budget is a user-home concept).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from installer.core.admission import AdmissionOutcome, classify, is_gated, record_source_text
from installer.core.conflict_audit import conflict_violations
from installer.core.frontmatter import split_frontmatter
from installer.core.surface_budget import always_on_violations, skill_body_violations

if TYPE_CHECKING:
    from installer.core.model import StagedItem, StagingPlan, Tool

# The always-on instruction file each tool deploys (Claude/Codex/OpenCode emit
# AGENTS.md; Gemini emits GEMINI.md). Used to weigh the surface budget.
_INSTRUCTION_DESTS = (Path("AGENTS.md"), Path("GEMINI.md"))


@dataclass(frozen=True, slots=True)
class GateResult:
    """Outcome of the admission gate.

    ``plans`` are the admission-filtered plans to install. ``skipped`` labels
    the record-less artifacts dropped (reported, not fatal). ``violations`` are
    the fatal breaches (malformed records, budget over-cap, claim conflicts);
    non-empty means the deploy must abort.
    """

    plans: dict[Tool, StagingPlan]
    skipped: list[str]
    violations: list[str]

    @property
    def ok(self) -> bool:
        return not self.violations


def _instruction_bytes(plan: StagingPlan) -> bytes | None:
    for dest in _INSTRUCTION_DESTS:
        item = plan.items.get(dest)
        if item is not None and item.content is not None:
            return item.content
    return None


def _skill_body(item: StagedItem) -> str:
    """The admitted skill's on-invoke body: SKILL.md with front matter stripped."""
    text = record_source_text(item)
    if text is None:
        return ""
    _mapping, body = split_frontmatter(text)
    return body


def run_admission_gate(plans: dict[Tool, StagingPlan]) -> GateResult:
    """Partition, budget, and conflict-audit ``plans`` in one pass."""
    filtered: dict[Tool, StagingPlan] = {}
    skipped: list[str] = []
    violations: list[str] = []
    claims_by_artifact: list[tuple[str, dict[str, str]]] = []
    skill_bodies: list[tuple[str, str]] = []

    for tool, plan in plans.items():
        kept: dict[Path, StagedItem] = {}
        for dest, item in plan.items.items():
            if not is_gated(item):
                kept[dest] = item
                continue
            label = f"{tool.value}:{dest}"
            verdict = classify(item)
            if verdict.outcome is AdmissionOutcome.NO_RECORD:
                skipped.append(label)
                continue
            if verdict.outcome is AdmissionOutcome.MALFORMED:
                violations.append(f"{label}: incomplete admission record — {verdict.detail}")
                continue
            kept[dest] = item
            claims_by_artifact.append((label, verdict.claims))
            if item.namespace == "skills":
                skill_bodies.append((label, _skill_body(item)))
        # Drop override bytes for any dir item the gate removed.
        kept_overrides = {d: ov for d, ov in plan.dir_overrides.items() if d in kept}
        filtered[tool] = replace(plan, items=kept, dir_overrides=kept_overrides)

    for tool, plan in filtered.items():
        rule_bytes = [
            it.content
            for it in plan.items.values()
            if it.namespace == "rules" and it.content is not None
        ]
        violations += always_on_violations(
            tool=tool.value, instruction=_instruction_bytes(plan), rules=rule_bytes
        )
    violations += skill_body_violations(skill_bodies)
    violations += conflict_violations(claims_by_artifact)

    return GateResult(plans=filtered, skipped=skipped, violations=violations)
