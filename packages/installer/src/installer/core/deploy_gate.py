"""The deploy-time admission gate.

One pass over the finalized staging plans, run in ``cli._run`` after the plan
is assembled and before any write. It:

1. **partitions** every gated artifact (rules/skills/commands/agents) by its
   admission record — dropping the record-less (the zero-base mechanism),
   collecting the malformed as violations, keeping the complete;
2. **sanitizes** each admitted artifact — the ``admission``/``claims`` front
   matter and any provenance comment are deploy-time inputs, so they are
   stripped from the bytes that ship (see ``sanitize``);
3. measures the **surface budget** over the *sanitized admitted* content — the
   always-on surface per tool and each admitted skill body. Measuring after
   sanitization is the point: the budget weighs what a reader actually loads,
   not the governance metadata that enforces the budget;
4. runs the **conflict audit** over the admitted artifacts' claims.

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

from installer.core.admission import (
    DIR_RECORD_FILE,
    AdmissionOutcome,
    classify,
    is_gated,
    record_source_text,
)
from installer.core.conflict_audit import conflict_violations
from installer.core.frontmatter import split_frontmatter
from installer.core.sanitize import sanitize_text
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


def _skill_body(text: str) -> str:
    """The admitted skill's on-invoke body: its entry file minus front matter."""
    _mapping, body = split_frontmatter(text)
    return body


def _entry_text(item: StagedItem, overrides: dict[Path, bytes]) -> str | None:
    """The gated item's front-matter-bearing text, as it will deploy.

    A directory item's entry file may have been patched into ``dir_overrides``
    by a plugin extension; those bytes win over the file under ``source_path``,
    because they are the ones that reach disk.
    """
    if item.content is None:
        patched = overrides.get(Path(DIR_RECORD_FILE))
        if patched is not None:
            return patched.decode("utf-8", errors="replace")
    return record_source_text(item)


def run_admission_gate(plans: dict[Tool, StagingPlan]) -> GateResult:
    """Partition, budget, and conflict-audit ``plans`` in one pass."""
    filtered: dict[Tool, StagingPlan] = {}
    skipped: list[str] = []
    violations: list[str] = []
    claims_by_artifact: list[tuple[str, dict[str, str]]] = []
    skill_bodies: list[tuple[str, str]] = []

    for tool, plan in plans.items():
        kept: dict[Path, StagedItem] = {}
        # Sanitized entry-file bytes per admitted directory item, overlaid onto
        # that dir's surviving overrides once the partition is known.
        sanitized_entries: dict[Path, bytes] = {}
        for dest, item in plan.items.items():
            if not is_gated(item):
                kept[dest] = item
                continue
            label = f"{tool.value}:{dest}"
            overrides = plan.dir_overrides.get(dest, {})
            text = _entry_text(item, overrides)
            verdict = classify(item, text=text)
            if verdict.outcome is AdmissionOutcome.NO_RECORD:
                skipped.append(label)
                continue
            if verdict.outcome is AdmissionOutcome.MALFORMED:
                violations.append(f"{label}: incomplete admission record — {verdict.detail}")
                continue

            # Admitted: ship the artifact without its deploy-time governance
            # metadata. A file item carries its own bytes; a directory item is
            # opaque, so the rewritten entry file rides the dir_overrides side
            # channel the sync already overlays on top of the source tree.
            sanitized = sanitize_text(text) if text is not None else None
            if sanitized is not None:
                if item.content is not None:
                    item = replace(item, content=sanitized.encode("utf-8"))
                else:
                    sanitized_entries[dest] = sanitized.encode("utf-8")
            kept[dest] = item

            claims_by_artifact.append((label, verdict.claims))
            if item.namespace == "skills":
                skill_bodies.append((label, _skill_body(sanitized or "")))

        # Drop override bytes for any item the gate removed, then lay each
        # admitted dir's sanitized entry file over what survives.
        kept_overrides = {d: dict(ov) for d, ov in plan.dir_overrides.items() if d in kept}
        for dest, entry in sanitized_entries.items():
            kept_overrides.setdefault(dest, {})[Path(DIR_RECORD_FILE)] = entry
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
