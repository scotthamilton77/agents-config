# Roadmap Phase 5b — Beadification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the C2 milestone-modeling decision to the bead data: create six top-level milestone/bucket features, cleave heterogeneous domain epics (7bk, acmh) along milestone lines, reparent strategic beads under their correct milestone, apply structural edge/label changes, and verify the new tree shape with bd queries.

**Architecture:** Pure bd CLI operations driven from `dangerouslyDisableSandbox: true` Bash. The fail-safe is `bd export -o issues.backup.jsonl` as Task 1 — every later task can be undone by `bd import` of the backup if anything goes wrong. Tasks are sequenced so that parents exist before children reference them, and heterogeneous epics' children are redistributed before the epic itself is rescoped.

**Tech Stack:** `bd` CLI (beads issue tracker); jq for single-line JSON fields (id, title, status, labels); `python3` for fields with embedded literal newlines that break jq parsing (notes, description, acceptance_criteria) per `src/plugins/beads/.claude/rules/beads.md` ("`bd show --json` emits literal newlines in `notes`/`description`/`acceptance_criteria`").

**Reference:** Roadmap doc at `docs/plans/2026-05-09-roadmap.md` Sections 6-8 (the spec); design at `docs/plans/2026-05-09-roadmap-analysis-design.md`; round-3 review history.

**Out of scope for this plan:** running M1-M4 work; brainstorming the new discovered-work beads (Vision-Gap-2, Vision-Gap-3, memory-governance, feedback-loop spike). Those go through the eventual M2 brainstorm-readiness gate.

---

## File Structure

This plan modifies bead state, not source files. The only artifact files are:

| Path | Producer | Purpose | Lifetime |
|---|---|---|---|
| `issues.backup.jsonl` | Task 1 | Pre-restructuring snapshot fail-safe | Permanent (committed) |
| `/tmp/phase5b-preflight-state.txt` | Task 2 | Captured pre-state of beads to be modified, for post-execution diffing | Session |
| `/tmp/phase5b-id-map.txt` | Tasks 3, 4, 5 | New bead-IDs assigned by `bd create` calls — used in subsequent reparent operations | Session |
| `/tmp/phase5b-audit.txt` | Task 16 | Audit-pass output (per-milestone tree dumps + invariant checks) | Session |

---

## Task 1: Snapshot fail-safe

**Files:**
- Create: `issues.backup.jsonl` (in repo root)

- [ ] **Step 1: Verify clean working tree before snapshot**

Run:
```bash
git status --short
```

Expected: empty output (no uncommitted changes). If output is non-empty, STOP — commit or stash first so the snapshot artifact is the only change introduced by this plan.

- [ ] **Step 2: Capture full bead state**

Run:
```bash
bd export -o issues.backup.jsonl
wc -l issues.backup.jsonl
```

Expected: file exists, line count ≥ 374 (the snapshot total at planning time; should be slightly higher if il69 spawned additional follow-up beads after planning). If line count <100, STOP — the export silently failed.

- [ ] **Step 3: Verify snapshot is valid JSONL and counts match**

Run:
```bash
python3 -c "
import json
with open('issues.backup.jsonl') as f:
    lines = f.readlines()
parsed = [json.loads(l) for l in lines if l.strip()]
print(f'JSONL lines: {len(parsed)}')
from collections import Counter
print(f'Status: {dict(Counter(b.get(\"status\",\"?\") for b in parsed))}')"
```

Expected: total ≥ 374; status distribution shows open + in_progress + closed.

- [ ] **Step 4: Commit the snapshot**

Run:
```bash
git add issues.backup.jsonl
git commit -m "chore(beads): snapshot before Phase 5b beadification"
```

The snapshot lives in repo history. Restoration path if rollback needed: `bd import issues.backup.jsonl`.

---

## Task 2: Pre-flight bead state capture

**Files:**
- Create: `/tmp/phase5b-preflight-state.txt`

- [ ] **Step 1: Capture pre-state of every bead this plan will modify**

Run:
```bash
{
  echo "=== Pre-flight state capture: $(date) ==="
  for id in agents-config-7bk agents-config-acmh agents-config-jyb \
            agents-config-7bk.4 agents-config-7bk.11 agents-config-7bk.12 \
            agents-config-7bk.13 agents-config-7bk.14 agents-config-7bk.15 \
            agents-config-7bk.16 agents-config-7bk.17 agents-config-7bk.19 \
            agents-config-7bk.20 agents-config-7bk.24 agents-config-7bk.25 \
            agents-config-acmh.2 agents-config-acmh.5 agents-config-acmh.9 \
            agents-config-acmh.10 \
            agents-config-owqa agents-config-4htl agents-config-sxfk \
            agents-config-76r agents-config-ffxh agents-config-d3s1 \
            agents-config-hft agents-config-jp9w agents-config-2yyb \
            agents-config-nbrd agents-config-19n9 agents-config-e2l \
            agents-config-clz agents-config-f298 agents-config-2gzy \
            agents-config-gmxo agents-config-3qz agents-config-xshc \
            agents-config-td39 agents-config-ukzs agents-config-z7a \
            agents-config-syod agents-config-l0v0 agents-config-zetc \
            agents-config-cx6 agents-config-717 agents-config-mptb \
            agents-config-7bk.19.9 agents-config-il69; do
    echo "--- $id ---"
    bd show "$id" --json 2>/dev/null | python3 -c "
import sys, json
try:
  d = json.load(sys.stdin)[0]
  print(f'  status={d.get(\"status\")}  type={d.get(\"issue_type\")}  parent={d.get(\"parent\",\"orphan\")}')
  print(f'  labels={d.get(\"labels\",[])}')
  print(f'  deps={[(x.get(\"id\") if isinstance(x,dict) else x) for x in d.get(\"dependencies\",[])]}')
except Exception as e:
  print(f'  (not found or unparseable: {e})')"
  done
} > /tmp/phase5b-preflight-state.txt
wc -l /tmp/phase5b-preflight-state.txt
head -30 /tmp/phase5b-preflight-state.txt
```

Expected: file written; ≥ 200 lines. If a bead is not found, that's noted and the plan continues (the bead may have been closed since planning).

- [ ] **Step 2: Capture pre-rescope text fields for 7bk and acmh**

Title, description, and acceptance fields will be rewritten in later tasks. Capture the originals for the rescope-rationale notes:

Run:
```bash
{
  echo "=== 7bk pre-rescope ==="
  bd show agents-config-7bk --json | python3 -c "
import sys, json
d = json.load(sys.stdin)[0]
print('TITLE:', d.get('title',''))
print('--- description ---')
print(d.get('description',''))
print('--- acceptance ---')
print(d.get('acceptance_criteria',''))"
  echo ""
  echo "=== acmh pre-rescope ==="
  bd show agents-config-acmh --json | python3 -c "
import sys, json
d = json.load(sys.stdin)[0]
print('TITLE:', d.get('title',''))
print('--- description ---')
print(d.get('description',''))
print('--- acceptance ---')
print(d.get('acceptance_criteria',''))"
} >> /tmp/phase5b-preflight-state.txt
```

---

## Task 3: Create six milestone/bucket feature beads + dependency chain

**Files:**
- Append: `/tmp/phase5b-id-map.txt`

bd create returns the new bead's id. Each step captures it for later use. New beads created here will be ORPHAN at creation time (no `--parent`); they're top-level features.

- [ ] **Step 1: Create M1 feature**

Run:
```bash
M1_ID=$(bd create \
  --title "Milestone M1 — Stabilize, finish in-flight, ship immediate accelerators" \
  --type feature \
  --priority 1 \
  --description "Top-level milestone-anchor for the M1 scope per the 2026-05-09 roadmap. Children include domain epics (jyb, acmh, il69) and orphan beads addressing the stability bar (hft, d3s1), in-flight non-MVP-critical work (jp9w, 2yyb), and the immediate-accelerator set (nbrd, 19n9, e2l, clz, f298, 2gzy). Reference: docs/plans/2026-05-09-roadmap.md Section 4 / M1." \
  --acceptance "agents-config-hft closed (notes-overwrite bug fixed). agents-config-d3s1 closed (persona vs orchestration reconciled). agents-config-il69 fully wrapped — all Tier 1 audit findings closed and Tier 2/Tier 3 follow-ups (acmh.* set) closed or moved to their proper milestones. All currently-in-progress non-MVP-critical beads closed (jp9w, jyb's children, 2yyb). All immediate-accelerator beads closed (nbrd, 19n9, e2l, clz, f298, 2gzy)." \
  --json | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['id'] if isinstance(d, dict) else d[0]['id'])")
echo "M1_ID=$M1_ID" | tee -a /tmp/phase5b-id-map.txt
```

Expected: `M1_ID=agents-config-<8-char-hex>` printed and appended.

- [ ] **Step 2: Create M2 feature**

Run:
```bash
M2_ID=$(bd create \
  --title "Milestone M2 — Brainstorm-readiness gate" \
  --type feature \
  --priority 1 \
  --description "Top-level milestone-anchor for M2: makes commitment 2 ('make AI good at saying no, not ready') mechanical via a verify-brainstorm gate that fires when the implementation-ready label is being added (bd label add <id> implementation-ready), plus AC classification + auto-merge knob capture at brainstorm time, plus spec post-mortem feedback loop. Reference: docs/plans/2026-05-09-roadmap.md Section 4 / M2." \
  --acceptance "verify-brainstorm skill exists and rejects under-specified beads when bd label add <id> implementation-ready is invoked on them. brainstorm-bead formula captures AC classification + auto-merge knobs + review depth. bead-spec agent + bead-assess + bead-write-spec skills exist. spec post-mortem skill (4htl) ships and is invoked on bug-fix and feature-completion paths. grill-me skill (sxfk) integrated into brainstorm-bead workflow." \
  --json | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['id'] if isinstance(d, dict) else d[0]['id'])")
echo "M2_ID=$M2_ID" | tee -a /tmp/phase5b-id-map.txt
```

- [ ] **Step 3: Create M3 feature**

Run:
```bash
M3_ID=$(bd create \
  --title "Milestone M3 — Worker fleet through PR autonomy" \
  --type feature \
  --priority 1 \
  --description "Top-level milestone-anchor for M3: a feature bead from bd ready runs through worker-fleet implementation, completion gate, and PR creation autonomously, with HEP escalation pausing for human input only at genuine decision points. Includes the 7bk-fleet rescoped epic, gmxo (merge-gate redesign moved to MVP), 3qz, and 76r (single-context mode implemented per Q3). Reference: docs/plans/2026-05-09-roadmap.md Section 4 / M3." \
  --acceptance "agents-config-7bk.19 closed. agents-config-7bk.13 + 7bk.20 closed (HEP rollout + lifecycle). agents-config-7bk.14 + 7bk.15 closed (per-step model/effort + cost rightsizing). agents-config-gmxo closed. agents-config-3qz closed. agents-config-76r closed (single-context mode shipped). End-to-end smoke test from fresh feature bead at bd ready to a PR opened against main passes on Claude Code." \
  --json | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['id'] if isinstance(d, dict) else d[0]['id'])")
echo "M3_ID=$M3_ID" | tee -a /tmp/phase5b-id-map.txt
```

- [ ] **Step 4: Create M4 feature**

Run:
```bash
M4_ID=$(bd create \
  --title "Milestone M4 — Overnight autonomy" \
  --type feature \
  --priority 1 \
  --description "Top-level milestone-anchor for M4: a production shell driver runs unattended overnight, pulling beads from bd ready through the M3 pipeline, opening PRs, addressing Copilot review, and surfacing escalations as human-labeled beads. Includes 7bk.11 (production driver, lands LAST in MVP), xshc (instrumentation), the new memory/context-compaction governance bead (Vision-Gap-3), and acmh.9 (run-queue replacement, coordinated with 7bk.11). Reference: docs/plans/2026-05-09-roadmap.md Section 4 / M4." \
  --acceptance "agents-config-7bk.11 closed (production shell driver runs unattended ≥4h processing ≥3 brainstorm-readied feature beads end-to-end). Memory/compaction-governance bead closed (synthetic compaction event recoverable mid-run). agents-config-xshc closed (85/5/10 instrumentation produces per-overnight-run summary)." \
  --json | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['id'] if isinstance(d, dict) else d[0]['id'])")
echo "M4_ID=$M4_ID" | tee -a /tmp/phase5b-id-map.txt
```

- [ ] **Step 5: Create Post-MVP feature**

Run:
```bash
POSTMVP_ID=$(bd create \
  --title "Post-MVP capabilities" \
  --type feature \
  --priority 2 \
  --description "Bucket for capabilities deferred until after M1-M4 MVP ships. Includes td39 (risk-tiered auto-merge — needs M3-MVP dogfooding to inform tier classification), ukzs (wall-clock pipelining of external waits), z7a (RALF foreign-eyes hard-fail), 7bk.16 (A/B testing per-stage allocations), syod (bd native gates research), and the Vision-Gap-2 PR-classification-policy bead. Reference: docs/plans/2026-05-09-roadmap.md Section 6." \
  --acceptance "Each child bead has a verifiable AC of its own. Bucket closes when all children close." \
  --json | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['id'] if isinstance(d, dict) else d[0]['id'])")
echo "POSTMVP_ID=$POSTMVP_ID" | tee -a /tmp/phase5b-id-map.txt
```

- [ ] **Step 6: Create Research-spikes feature**

Run:
```bash
SPIKES_ID=$(bd create \
  --title "Research spikes (retire-or-rescope)" \
  --type feature \
  --priority 3 \
  --description "Bucket for research-spike beads whose outcome is retire (won't-do) OR rescope (produce concrete adoption beads). Runs opportunistically — no milestone dep. Includes 7bk.24 (karpathy-guidelines), l0v0 (mattpocock skills), zetc (Codex 5.5 confidence-loop), cx6 (fork superpowers), 717 (residual lu3 risk-closer review), feedback-loop spike (new), acmh.2 (skillize tech-lead), acmh.5 (formulas-as-skills review). Reference: docs/plans/2026-05-09-roadmap.md Section 6." \
  --acceptance "Each spike's outcome documented (retire OR concrete adoption beads filed). Bucket closes when all child spikes have a verdict applied." \
  --json | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['id'] if isinstance(d, dict) else d[0]['id'])")
echo "SPIKES_ID=$SPIKES_ID" | tee -a /tmp/phase5b-id-map.txt
```

- [ ] **Step 7: Create dependency chain among milestone features**

Run:
```bash
source <(grep -E "^(M1|M2|M3|M4|POSTMVP)_ID=" /tmp/phase5b-id-map.txt)
bd dep add "$M2_ID" "$M1_ID"
bd dep add "$M3_ID" "$M2_ID"
bd dep add "$M4_ID" "$M3_ID"
bd dep add "$POSTMVP_ID" "$M4_ID"
echo "Dependency chain wired: M1 → M2 → M3 → M4 → Post-MVP"
```

Expected: each `bd dep add` succeeds silently. SPIKES_ID is intentionally NOT in the chain (research spikes run opportunistically per Scott's directive).

- [ ] **Step 8: Verify the milestone-feature beads**

Run:
```bash
for var in M1_ID M2_ID M3_ID M4_ID POSTMVP_ID SPIKES_ID; do
  source <(grep "^${var}=" /tmp/phase5b-id-map.txt)
  id="${!var}"
  echo "=== $var = $id ==="
  bd show "$id" --json | python3 -c "
import sys, json
d = json.load(sys.stdin)[0]
print(f'  type={d.get(\"issue_type\")} status={d.get(\"status\")} parent={d.get(\"parent\",\"orphan\")}')
print(f'  title={d.get(\"title\")[:80]}')
print(f'  deps_in={[x.get(\"id\") if isinstance(x,dict) else x for x in d.get(\"dependencies\",[])]}')"
done
```

Expected: all six features exist as orphans of type=feature. M2-M4 + Post-MVP have one dep each (the prior milestone). M1 and Research-spikes have no incoming deps.

---

## Task 4: Create the brainstorm-readiness epic under M2

**Files:**
- Append: `/tmp/phase5b-id-map.txt`

- [ ] **Step 1: Create brainstorm-readiness epic with M2 as parent**

Run:
```bash
source <(grep "^M2_ID=" /tmp/phase5b-id-map.txt)
BRAINSTORM_ID=$(bd create \
  --title "Brainstorm-readiness gate (epic)" \
  --type epic \
  --parent "$M2_ID" \
  --no-inherit-labels \
  --priority 1 \
  --description "Domain epic anchoring the brainstorm-readiness gate, AC classification + policy-knob capture at brainstorm time, the bead-spec agent, the spec post-mortem feedback loop, and grill-me adversarial questioning. Children: owqa (verify-brainstorm gate), 7bk.12 (expand brainstorm-bead — reparented out of 7bk), 7bk.25 (Phase 3 bead-spec agent — reparented out of 7bk), 4htl (spec post-mortem), sxfk (grill-me integration). Per round-2 review redirect c4." \
  --acceptance "All children closed: owqa, 7bk.12, 7bk.25, 4htl, sxfk. The brainstorm-readiness gate is mechanical (verifiable per parent feature M2's AC)." \
  --json | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['id'] if isinstance(d, dict) else d[0]['id'])")
echo "BRAINSTORM_ID=$BRAINSTORM_ID" | tee -a /tmp/phase5b-id-map.txt
```

Note: per memory `bd-create-parent-inherits-labels`, parented creates inherit parent labels by default. The `--no-inherit-labels` flag added above prevents that explicitly. The audit step below stays as a defensive double-check (cheap, surfaces version-skew bugs early).

- [ ] **Step 2: Verify no inherited labels (defensive)**

Run:
```bash
source <(grep "^BRAINSTORM_ID=" /tmp/phase5b-id-map.txt)
bd label list "$BRAINSTORM_ID"
```

Expected: empty (no labels). With `--no-inherit-labels` in Step 1 this should always be the case; if labels appear, the bd CLI version may have changed semantics — investigate before proceeding.

---

## Task 5: Create three discovered-work beads

**Files:**
- Append: `/tmp/phase5b-id-map.txt`

- [ ] **Step 1: Create Vision-Gap-2 bead (PR classification policy) under Post-MVP**

Run:
```bash
source <(grep "^POSTMVP_ID=" /tmp/phase5b-id-map.txt)
GAP2_ID=$(bd create \
  --title "Define PR classification policy for RALF-only vs human-required review" \
  --type feature \
  --parent "$POSTMVP_ID" \
  --no-inherit-labels \
  --priority 2 \
  --description "Vision-Gap-2 from the 2026-05-09 roadmap. RALF substitutes cross-model review for human review (commitment 3), but no open bead defines the decision rule for which PR classes get RALF-only vs human-required review. This is the prerequisite for agents-config-td39 (risk-tiered auto-merge): without a classification policy, the tiering has nothing to tier against. Output: a documented PR-classification policy keyed off blast radius, file types touched, and security surface — specific enough that a script can read a PR diff and emit a tier verdict." \
  --acceptance "A docs artifact (in this repo) defines PR classification rules with concrete examples per tier. A script (or specification) exists that maps a PR diff to a tier verdict (RALF-only / RALF + human / human-required). agents-config-td39 references this policy as its blocker dep." \
  --json | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['id'] if isinstance(d, dict) else d[0]['id'])")
echo "GAP2_ID=$GAP2_ID" | tee -a /tmp/phase5b-id-map.txt
```

- [ ] **Step 2: Create Vision-Gap-3 bead (memory/compaction governance) under M4**

Run:
```bash
source <(grep "^M4_ID=" /tmp/phase5b-id-map.txt)
GAP3_ID=$(bd create \
  --title "Memory/context compaction governance for overnight runs" \
  --type feature \
  --parent "$M4_ID" \
  --no-inherit-labels \
  --priority 1 \
  --description "Vision-Gap-3 from the 2026-05-09 roadmap. Beads persist work; formulas persist process. But agent memory (MEMORY.md, mempalace) is not governed during overnight runs — what gets written, what gets pruned, what survives a compaction event. This silently undermines commitment 5's 'work survives overnight runs' promise. This bead must pass through the M2 brainstorm-readiness gate before implementation begins (self-referential: the M2 gate informs how this work gets specced)." \
  --acceptance "Memory governance rules documented for overnight runs (write-policy, prune-policy, compaction-survival contract). A synthetic compaction event mid-run is recoverable: bead state, memory artifacts, and molecule progress can all be reconstructed post-compaction. Verified by running an overnight smoke that triggers a synthetic compaction." \
  --json | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['id'] if isinstance(d, dict) else d[0]['id'])")
echo "GAP3_ID=$GAP3_ID" | tee -a /tmp/phase5b-id-map.txt
```

- [ ] **Step 3: Create feedback-loop research spike under Research-spikes**

Run:
```bash
source <(grep "^SPIKES_ID=" /tmp/phase5b-id-map.txt)
FEEDBACK_ID=$(bd create \
  --title "Spike: feedback loops at points of greatest realization + processing/improvement mechanism" \
  --type task \
  --parent "$SPIKES_ID" \
  --no-inherit-labels \
  --priority 2 \
  --description "Research spike per Scott's round-2 ask. Beyond agents-config-4htl (spec post-mortem), the roadmap currently has no built-in feedback hooks at strategic 'points of greatest realization' — moments in the bead workflow where lessons surface and could be captured. Examples: PR review (Copilot finds an anti-pattern → did our tests catch this?), HEP escalation (worker hit a decision point → was the spec under-specified?), overnight-run completion (what unexpected outcomes emerged?), bead closure (did the AC accurately predict success criteria?). Spike investigates: (1) what 'points of greatest realization' map to in the actual bead workflow; (2) what mechanisms could capture lessons at those points (hooks, audit beads, memory writes); (3) how to process and act on captures (likely overlaps with Vision-Gap-3 memory governance). Outcome: produce concrete adoption beads per identified hook, OR close as deferred if cost/benefit doesn't pencil." \
  --acceptance "Spike outcome documented: (a) list of identified feedback points; (b) per-point capture mechanism proposal; (c) processing/improvement mechanism proposal; (d) per-point verdict — file concrete adoption bead, or close as deferred. Spike itself closes when all verdicts are applied." \
  --json | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['id'] if isinstance(d, dict) else d[0]['id'])")
echo "FEEDBACK_ID=$FEEDBACK_ID" | tee -a /tmp/phase5b-id-map.txt
```

- [ ] **Step 4: Verify the three new beads**

Run:
```bash
for var in GAP2_ID GAP3_ID FEEDBACK_ID; do
  source <(grep "^${var}=" /tmp/phase5b-id-map.txt)
  id="${!var}"
  echo "=== $var = $id ==="
  bd show "$id" --json | python3 -c "
import sys, json
d = json.load(sys.stdin)[0]
print(f'  type={d.get(\"issue_type\")} parent={d.get(\"parent\")} priority={d.get(\"priority\")}')"
done
```

Expected: GAP2 under POSTMVP_ID; GAP3 under M4_ID; FEEDBACK under SPIKES_ID.

---

## Task 6: Cleave 7bk — reparent OUT, then rescope to M3-fleet only

**Strategy:** redistribute heterogeneous children FIRST, THEN rescope 7bk's title/description/AC to reflect the M3-only residual scope. AFTER rescope, reparent 7bk under M3 itself (Task 12).

- [ ] **Step 1: Reparent 7bk.4 (AGENTS.md File Formats schema) to M1**

Run:
```bash
source <(grep "^M1_ID=" /tmp/phase5b-id-map.txt)
bd update agents-config-7bk.4 --parent "$M1_ID"
bd show agents-config-7bk.4 --json | python3 -c "
import sys, json
d = json.load(sys.stdin)[0]; print(f'  parent={d.get(\"parent\")}')"
```

Expected: parent = $M1_ID.

- [ ] **Step 2: Reparent 7bk.17 (project-config.toml key naming) to M1**

Run:
```bash
source <(grep "^M1_ID=" /tmp/phase5b-id-map.txt)
bd update agents-config-7bk.17 --parent "$M1_ID"
bd show agents-config-7bk.17 --json | python3 -c "import sys, json; print('  parent=', json.load(sys.stdin)[0].get('parent'))"
```

- [ ] **Step 3: Reparent 7bk.11 (production shell driver) to M4**

Run:
```bash
source <(grep "^M4_ID=" /tmp/phase5b-id-map.txt)
bd update agents-config-7bk.11 --parent "$M4_ID"
bd show agents-config-7bk.11 --json | python3 -c "import sys, json; print('  parent=', json.load(sys.stdin)[0].get('parent'))"
```

- [ ] **Step 4: Reparent 7bk.16 (A/B testing per-stage allocations) to Post-MVP**

Run:
```bash
source <(grep "^POSTMVP_ID=" /tmp/phase5b-id-map.txt)
bd update agents-config-7bk.16 --parent "$POSTMVP_ID"
bd show agents-config-7bk.16 --json | python3 -c "import sys, json; print('  parent=', json.load(sys.stdin)[0].get('parent'))"
```

- [ ] **Step 5: Reparent 7bk.24 (karpathy-guidelines spike) to Research-spikes**

Run:
```bash
source <(grep "^SPIKES_ID=" /tmp/phase5b-id-map.txt)
bd update agents-config-7bk.24 --parent "$SPIKES_ID"
bd show agents-config-7bk.24 --json | python3 -c "import sys, json; print('  parent=', json.load(sys.stdin)[0].get('parent'))"
```

- [ ] **Step 6: Reparent 7bk.12 to brainstorm-readiness epic**

Run:
```bash
source <(grep "^BRAINSTORM_ID=" /tmp/phase5b-id-map.txt)
bd update agents-config-7bk.12 --parent "$BRAINSTORM_ID"
bd show agents-config-7bk.12 --json | python3 -c "import sys, json; print('  parent=', json.load(sys.stdin)[0].get('parent'))"
```

- [ ] **Step 7: Reparent 7bk.25 to brainstorm-readiness epic**

Run:
```bash
source <(grep "^BRAINSTORM_ID=" /tmp/phase5b-id-map.txt)
bd update agents-config-7bk.25 --parent "$BRAINSTORM_ID"
bd show agents-config-7bk.25 --json | python3 -c "import sys, json; print('  parent=', json.load(sys.stdin)[0].get('parent'))"
```

- [ ] **Step 8: Verify 7bk's residual children are M3-only**

Run:
```bash
bd list --parent agents-config-7bk --json | python3 -c "
import sys, json
beads = json.load(sys.stdin)
print(f'7bk residual children ({len(beads)}):')
for b in beads:
    print(f'  {b[\"id\"]} [{b.get(\"status\",\"?\")}] {b.get(\"title\",\"\")[:80]}')"
```

Expected residual children of 7bk: 7bk.13, 7bk.14, 7bk.15, 7bk.19, 7bk.20 (and possibly 7bk.5, .6, .7, .8, .9, .10, .18, .19.X, .21, .22, .23, .27 if they're still open — most are closed). Any open child not in M3 scope is an audit-pass concern (Task 16).

- [ ] **Step 9: Rescope 7bk title, description, acceptance to M3-fleet only**

Run:
```bash
bd update agents-config-7bk \
  --title "Specialized agent fleet (M3 worker fleet)" \
  --description "Rescoped 2026-05-10 during Phase 5b beadification — was 'Specialized agent fleet for the bead pipeline' covering all per-stage subagent + cost-rightsizing + brainstorm-bead-rewiring + production-driver work; now M3-fleet-only after children spanning M1 hygiene, M2 brainstorm-readiness, M4 production-driver, post-MVP, and research-spike were redistributed.

Scope: redesign and ship the worker fleet that runs the bead pipeline end-to-end from feature-bead implementation through PR creation, including per-stage right-sized worker dispatch (worker-report-v1 schema, tdd-red-team / tdd-green-team / bug-diagnoser / bead-implementor-replacement) and cost-rightsizing controls (per-step Model:/Effort: directives in formula TOMLs; F-04 default table). Excludes: brainstorm-readiness work (now under brainstorm-readiness epic under M2), production shell driver work (now under M4), A/B testing and post-MVP multipliers (now under Post-MVP), and standalone hygiene/spike beads (now under M1 / Research-spikes)." \
  --acceptance "All M3-scope children closed: 7bk.13 (HEP rollout), 7bk.14 (per-step Model:/Effort: directives), 7bk.15 (cost rightsizing), 7bk.19 (worker layer redesign), 7bk.20 (HEP lifecycle). worker-report-v1 schema in use across stages. End-to-end smoke from bd ready to PR-opened passes."
bd update agents-config-7bk --append-notes "Rescoped during Phase 5b. Pre-rescope title/description/AC captured at /tmp/phase5b-preflight-state.txt. Children redistributed: 7bk.4 → M1, 7bk.17 → M1, 7bk.11 → M4, 7bk.16 → Post-MVP, 7bk.24 → Research-spikes, 7bk.12 → brainstorm-readiness, 7bk.25 → brainstorm-readiness."
```

Expected: bd update returns success.

---

## Task 7: Cleave acmh — reparent OUT, then rescope to M1-cleanups only

- [ ] **Step 1: Reparent acmh.9 (replace run-queue skill) to M4**

Note: acmh.9 has a coordination relationship with the Vision-Gap-3 memory governance bead and with the future 7bk.11 (production shell driver). Neither is yet a parent — acmh.9 just lives alongside under M4.

Run:
```bash
source <(grep "^M4_ID=" /tmp/phase5b-id-map.txt)
bd update agents-config-acmh.9 --parent "$M4_ID"
bd show agents-config-acmh.9 --json | python3 -c "import sys, json; print('  parent=', json.load(sys.stdin)[0].get('parent'))"
```

- [ ] **Step 2: Reparent acmh.10 (human-label semantics) to 7bk**

acmh.10 touches HEP semantics, which lives under 7bk-fleet (M3). Parent = agents-config-7bk (already rescoped to M3-fleet in Task 6 Step 9).

Run:
```bash
bd update agents-config-acmh.10 --parent agents-config-7bk
bd show agents-config-acmh.10 --json | python3 -c "import sys, json; print('  parent=', json.load(sys.stdin)[0].get('parent'))"
```

- [ ] **Step 3: Reparent acmh.2 (skillize tech-lead spike) to Research-spikes**

Run:
```bash
source <(grep "^SPIKES_ID=" /tmp/phase5b-id-map.txt)
bd update agents-config-acmh.2 --parent "$SPIKES_ID"
bd show agents-config-acmh.2 --json | python3 -c "import sys, json; print('  parent=', json.load(sys.stdin)[0].get('parent'))"
```

- [ ] **Step 4: Reparent acmh.5 (formulas-as-skills review) to Research-spikes**

Run:
```bash
source <(grep "^SPIKES_ID=" /tmp/phase5b-id-map.txt)
bd update agents-config-acmh.5 --parent "$SPIKES_ID"
bd show agents-config-acmh.5 --json | python3 -c "import sys, json; print('  parent=', json.load(sys.stdin)[0].get('parent'))"
```

- [ ] **Step 5: Verify acmh's residual children are M1-cleanups only**

Run:
```bash
bd list --parent agents-config-acmh --json | python3 -c "
import sys, json
beads = json.load(sys.stdin)
print(f'acmh residual children ({len(beads)}):')
for b in beads:
    print(f'  {b[\"id\"]} [{b.get(\"status\",\"?\")}] {b.get(\"title\",\"\")[:80]}')"
```

Expected residual children: acmh.1, acmh.3, acmh.4, acmh.6, acmh.7, acmh.8, acmh.11, acmh.12.

- [ ] **Step 6: Rescope acmh title, description, acceptance to M1-cleanups only**

Run:
```bash
bd update agents-config-acmh \
  --title "Audit-driven M1 cleanups across agents/, commands/, formulas/, rules/, scripts/, skills/, templates/" \
  --description "Rescoped 2026-05-10 during Phase 5b — was 'Audit skills, agents, commands, rules for best practices & coherence' (broad audit produced by il69); now M1-cleanups-only after the Tier 2/Tier 3 child beads spanning research spikes (acmh.2, acmh.5), M3 HEP semantics (acmh.10), and M4 run-queue replacement (acmh.9) were redistributed.

Scope: per-directory cleanup work derived from the il69 audit findings. Children: acmh.1 (agents/), acmh.3 (commands/), acmh.4 (formulas/), acmh.6 (rules/), acmh.7 (scripts/), acmh.8 (skills/), acmh.11 (templates/), acmh.12 (Tier 3 bd-sequence helper-script extractions). Excludes: structural / cross-cutting changes (now under their respective destinations)." \
  --acceptance "All residual children closed: acmh.1, acmh.3, acmh.4, acmh.6, acmh.7, acmh.8, acmh.11, acmh.12. Each child's specific F-N findings addressed per its own AC."
bd update agents-config-acmh --append-notes "Rescoped during Phase 5b. Pre-rescope title/description/AC captured at /tmp/phase5b-preflight-state.txt. Children redistributed: acmh.2 → Research-spikes, acmh.5 → Research-spikes, acmh.9 → M4, acmh.10 → 7bk (under M3)."
```

---

## Task 8: Reparent jyb under M1

- [ ] **Step 1: Reparent jyb to M1**

Run:
```bash
source <(grep "^M1_ID=" /tmp/phase5b-id-map.txt)
bd update agents-config-jyb --parent "$M1_ID"
bd show agents-config-jyb --json | python3 -c "import sys, json; print('  parent=', json.load(sys.stdin)[0].get('parent'))"
```

- [ ] **Step 2: Verify jyb children are all M1-relevant**

Run:
```bash
bd list --parent agents-config-jyb --json | python3 -c "
import sys, json
beads = json.load(sys.stdin)
print(f'jyb children ({len(beads)}):')
for b in beads:
    print(f'  {b[\"id\"]} [{b.get(\"status\",\"?\")}] {b.get(\"title\",\"\")[:80]}')"
```

Expected: jyb.2 (in_progress), jyb.3, jyb.4. All universal-flattening work; all M1 in-flight or hygiene-class. No reparent needed within jyb's subtree.

---

## Task 9: Reparent residual orphan strategic beads under their milestones

These beads currently have no parent. Reparent each one under its milestone feature.

- [ ] **Step 1: Reparent M1 orphans**

Run:
```bash
source <(grep "^M1_ID=" /tmp/phase5b-id-map.txt)
for id in agents-config-hft agents-config-d3s1 agents-config-jp9w \
          agents-config-2yyb agents-config-nbrd agents-config-19n9 \
          agents-config-e2l agents-config-clz agents-config-f298 \
          agents-config-2gzy agents-config-il69; do
  bd update "$id" --parent "$M1_ID"
done
bd list --parent "$M1_ID" --json | python3 -c "
import sys, json
print(f'M1 children: {len(json.load(sys.stdin))}')"
```

Expected: M1 active children (open + in_progress) count = 13: acmh, 7bk.4, 7bk.17, hft, d3s1, jp9w, 2yyb, nbrd, 19n9, e2l, clz, f298, 2gzy. Plus closed-but-parented historical beads: jyb, il69. Total visible with `--status closed`: 15.

- [ ] **Step 2: Reparent M3 orphans**

Run:
```bash
source <(grep "^M3_ID=" /tmp/phase5b-id-map.txt)
for id in agents-config-gmxo agents-config-3qz; do
  bd update "$id" --parent "$M3_ID"
done
bd list --parent "$M3_ID" --json | python3 -c "
import sys, json
print(f'M3 children pre-7bk-reparent: {len(json.load(sys.stdin))}')"
```

Expected: M3 children = gmxo, 3qz (7bk gets reparented under M3 in Task 12).

- [ ] **Step 3: Reparent M4 orphans**

Run:
```bash
source <(grep "^M4_ID=" /tmp/phase5b-id-map.txt)
bd update agents-config-xshc --parent "$M4_ID"
bd list --parent "$M4_ID" --json | python3 -c "
import sys, json
print(f'M4 children: {len(json.load(sys.stdin))}')"
```

Expected: M4 children = 7bk.11 (from Task 6), GAP3_ID (memory governance, from Task 5), acmh.9 (from Task 7), xshc = 4 children.

- [ ] **Step 4: Reparent Post-MVP orphans**

Run:
```bash
source <(grep "^POSTMVP_ID=" /tmp/phase5b-id-map.txt)
for id in agents-config-td39 agents-config-ukzs agents-config-z7a \
          agents-config-syod; do
  bd update "$id" --parent "$POSTMVP_ID"
done
bd list --parent "$POSTMVP_ID" --json | python3 -c "
import sys, json
print(f'Post-MVP children: {len(json.load(sys.stdin))}')"
```

Expected: Post-MVP children = 7bk.16 (from Task 6), GAP2_ID (PR classification, from Task 5), td39, ukzs, z7a, syod = 6 children.

- [ ] **Step 5: Reparent Research-spike orphans**

Run:
```bash
source <(grep "^SPIKES_ID=" /tmp/phase5b-id-map.txt)
for id in agents-config-l0v0 agents-config-zetc agents-config-cx6 \
          agents-config-717; do
  bd update "$id" --parent "$SPIKES_ID"
done
bd list --parent "$SPIKES_ID" --json | python3 -c "
import sys, json
print(f'Research-spikes children: {len(json.load(sys.stdin))}')"
```

Expected: Research-spikes children = 7bk.24 (from Task 6), acmh.2 (from Task 7), acmh.5 (from Task 7), FEEDBACK_ID (from Task 5), l0v0, zetc, cx6, 717 = 8 children.

---

## Task 10: Reparent under brainstorm-readiness epic

- [ ] **Step 1: Reparent owqa, 4htl, sxfk under brainstorm-readiness**

Run:
```bash
source <(grep "^BRAINSTORM_ID=" /tmp/phase5b-id-map.txt)
for id in agents-config-owqa agents-config-4htl agents-config-sxfk; do
  bd update "$id" --parent "$BRAINSTORM_ID"
done
bd list --parent "$BRAINSTORM_ID" --json | python3 -c "
import sys, json
beads = json.load(sys.stdin)
print(f'brainstorm-readiness children ({len(beads)}):')
for b in beads:
    print(f'  {b[\"id\"]} [{b.get(\"status\",\"?\")}] {b.get(\"title\",\"\")[:80]}')"
```

Expected: 5 children — owqa, 4htl, sxfk, 7bk.12 (already moved in Task 6), 7bk.25 (already moved in Task 6).

---

## Task 11: Reparent 76r and ffxh

- [ ] **Step 1: Reparent 76r under 7bk**

Run:
```bash
bd update agents-config-76r --parent agents-config-7bk
bd show agents-config-76r --json | python3 -c "import sys, json; print('  parent=', json.load(sys.stdin)[0].get('parent'))"
```

- [ ] **Step 2: Reparent ffxh under 7bk.13**

Run:
```bash
bd update agents-config-ffxh --parent agents-config-7bk.13
bd show agents-config-ffxh --json | python3 -c "import sys, json; print('  parent=', json.load(sys.stdin)[0].get('parent'))"
```

---

## Task 12: Reparent 7bk under M3

This MUST happen AFTER Tasks 6, 11 — otherwise 7bk's child redistribution would happen mid-flight while 7bk is already under M3.

- [ ] **Step 1: Reparent 7bk under M3**

Run:
```bash
source <(grep "^M3_ID=" /tmp/phase5b-id-map.txt)
bd update agents-config-7bk --parent "$M3_ID"
bd show agents-config-7bk --json | python3 -c "import sys, json; print('  parent=', json.load(sys.stdin)[0].get('parent'))"
```

- [ ] **Step 2: Verify M3 has expected children**

Run:
```bash
source <(grep "^M3_ID=" /tmp/phase5b-id-map.txt)
bd list --parent "$M3_ID" --json | python3 -c "
import sys, json
beads = json.load(sys.stdin)
print(f'M3 children ({len(beads)}):')
for b in beads:
    print(f'  {b[\"id\"]} [{b.get(\"issue_type\",\"?\")}] {b.get(\"title\",\"\")[:80]}')"
```

Expected: 3 children — 7bk (epic), gmxo, 3qz.

---

## Task 13: Apply structural edge changes

- [ ] **Step 1: ADD edges (3 total)**

Run:
```bash
bd dep add agents-config-4htl agents-config-owqa
bd dep add agents-config-7bk.12 agents-config-owqa
bd dep add agents-config-xshc agents-config-7bk
echo "3 ADD edges applied"
```

Note: `bd dep add <issue> <depends-on>` means `<issue>` depends on `<depends-on>` (i.e., `<depends-on>` blocks `<issue>`). So `bd dep add 4htl owqa` means 4htl depends on owqa shipping first — which matches the rationale: 4htl audits against owqa's standard.

- [ ] **Step 2: REMOVE edges (3 total)**

Run:
```bash
bd dep remove agents-config-mptb agents-config-gmxo 2>&1 || echo "edge already absent"
bd dep remove agents-config-76r agents-config-7bk.9 2>&1 || echo "edge already absent"
bd dep remove agents-config-7bk.19.9 agents-config-7bk.19.5 2>&1 || echo "edge already absent (ghost id)"
echo "REMOVE edges processed"
```

Note: the third edge references a ghost id (`7bk.19.5` without the `agents-config-` prefix) per Fork-B — `bd dep remove` may fail because the edge form is malformed. If failure persists, manually inspect 7bk.19.9's deps and remove the malformed entry via the bd CLI's available primitives.

- [ ] **Step 3: Verify edges**

Run:
```bash
echo "=== 4htl deps (should include owqa) ==="
bd show agents-config-4htl --json | python3 -c "
import sys, json
d = json.load(sys.stdin)[0]
print('  deps:', [x.get('id') if isinstance(x,dict) else x for x in d.get('dependencies',[])])"
echo "=== 7bk.12 deps (should include owqa) ==="
bd show agents-config-7bk.12 --json | python3 -c "
import sys, json
d = json.load(sys.stdin)[0]
print('  deps:', [x.get('id') if isinstance(x,dict) else x for x in d.get('dependencies',[])])"
echo "=== xshc deps (should include 7bk) ==="
bd show agents-config-xshc --json | python3 -c "
import sys, json
d = json.load(sys.stdin)[0]
print('  deps:', [x.get('id') if isinstance(x,dict) else x for x in d.get('dependencies',[])])"
echo "=== mptb deps (should NOT include gmxo) ==="
bd show agents-config-mptb --json | python3 -c "
import sys, json
d = json.load(sys.stdin)[0]
print('  deps:', [x.get('id') if isinstance(x,dict) else x for x in d.get('dependencies',[])])"
```

Expected: 4htl deps include owqa; 7bk.12 deps include owqa; xshc deps include 7bk; mptb deps do NOT include gmxo.

---

## Task 14: Apply vision-85-5-10 label additions

- [ ] **Step 1: Add vision-85-5-10 to 5 beads**

Run:
```bash
for id in agents-config-7bk.13 agents-config-7bk.20 agents-config-7bk.25 \
          agents-config-7bk.12 agents-config-7bk.11; do
  bd label add "$id" vision-85-5-10
done
echo "5 vision-85-5-10 labels applied"
```

- [ ] **Step 2: Verify the label set**

Run:
```bash
bd ready --label vision-85-5-10 --json 2>/dev/null | python3 -c "
import sys, json
beads = json.load(sys.stdin)
print(f'Beads with vision-85-5-10 label (currently ready): {len(beads)}')"
echo "---"
echo "Full vision-85-5-10 set (ready or not):"
for id in agents-config-owqa agents-config-d3s1 agents-config-td39 \
          agents-config-4htl agents-config-xshc agents-config-ukzs \
          agents-config-7bk.13 agents-config-7bk.20 agents-config-7bk.25 \
          agents-config-7bk.12 agents-config-7bk.11; do
  labels=$(bd label list "$id" 2>/dev/null | grep -c vision-85-5-10 || echo 0)
  echo "  $id  vision-label-count=$labels"
done
```

Expected: each of the 11 beads has the vision-85-5-10 label (6 pre-existing KEEPs + 5 ADDs).

---

## Task 15: Cleanup suspect open molecules

- [ ] **Step 1: Verify mol-dxvo and mol-miv9h status**

Run:
```bash
for id in agents-config-mol-dxvo agents-config-mol-miv9h; do
  echo "=== $id ==="
  bd show "$id" --json 2>/dev/null | python3 -c "
import sys, json
try:
  d = json.load(sys.stdin)[0]
  print(f'  status={d.get(\"status\")}  for-bead-label={[l for l in d.get(\"labels\",[]) if l.startswith(\"for-bead-\")]}')
except:
  print('  (not found)')"
done
```

- [ ] **Step 2: Close stale molecules with rationale**

Run:
```bash
for id in agents-config-mol-dxvo agents-config-mol-miv9h; do
  status=$(bd show "$id" --json 2>/dev/null | python3 -c "import sys, json; print(json.load(sys.stdin)[0].get('status','?'))" 2>/dev/null)
  if [ "$status" != "closed" ] && [ -n "$status" ] && [ "$status" != "?" ]; then
    bd close "$id" --reason "Stale molecule for already-closed parent bead — Phase 5b cleanup per roadmap Section 8."
    echo "  closed: $id"
  else
    echo "  already closed or not found: $id"
  fi
done
```

Note: per memory `bd-mol-ready-gated-discovers-molecules-whose-gate`, open molecules whose gate beads have closed normally pick up via `bd mol ready --gated`. These two specifically were flagged by Fork-B as stale despite their parent beads being closed — manual close is the cleanup.

---

## Task 16: Audit pass — verify the new tree shape

**Files:**
- Create: `/tmp/phase5b-audit.txt`

- [ ] **Step 1: Per-milestone tree dump**

Run:
```bash
{
  echo "=== Phase 5b audit: $(date) ==="
  for var in M1_ID M2_ID M3_ID M4_ID POSTMVP_ID SPIKES_ID; do
    source <(grep "^${var}=" /tmp/phase5b-id-map.txt)
    id="${!var}"
    echo ""
    echo "=== $var = $id ==="
    bd show "$id" --json | python3 -c "
import sys, json
d = json.load(sys.stdin)[0]
print(f'  TITLE: {d.get(\"title\")}')
print(f'  STATUS: {d.get(\"status\")}  TYPE: {d.get(\"issue_type\")}')"
    echo "  DIRECT CHILDREN:"
    bd list --parent "$id" --json | python3 -c "
import sys, json
for b in json.load(sys.stdin):
  print(f'    {b[\"id\"]} [{b.get(\"status\",\"?\")}] [{b.get(\"issue_type\",\"?\")}] {b.get(\"title\",\"\")[:80]}')"
  done
} > /tmp/phase5b-audit.txt
cat /tmp/phase5b-audit.txt
```

- [ ] **Step 2: Invariant — every M1-M4-tagged strategic bead has a milestone-feature ancestor**

Run:
```bash
python3 << 'EOF'
import subprocess, json
# Walk every open + in_progress bead's parent chain; verify each strategic bead's chain terminates at one of the milestone features (M1/M2/M3/M4/POSTMVP/SPIKES)
ids_file = open('/tmp/phase5b-id-map.txt').read()
milestones = {}
for line in ids_file.splitlines():
    if '=' in line and line.startswith(('M1_', 'M2_', 'M3_', 'M4_', 'POSTMVP_', 'SPIKES_', 'BRAINSTORM_', 'GAP2_', 'GAP3_', 'FEEDBACK_')):
        k, v = line.split('=', 1)
        milestones[k.strip()] = v.strip()
all_strategic = subprocess.run(['bd','list','--status','open','--limit','0','--json'], capture_output=True, text=True).stdout
all_strategic += subprocess.run(['bd','list','--status','in_progress','--limit','0','--json'], capture_output=True, text=True).stdout
# resilient parse
import json
decoder = json.JSONDecoder()
beads, idx = [], 0
while idx < len(all_strategic):
    s = all_strategic[idx:].lstrip()
    if not s: break
    chunk, end = decoder.raw_decode(s)
    items = chunk if isinstance(chunk, list) else [chunk]
    beads.extend(items)
    idx = idx + (len(all_strategic[idx:]) - len(s)) + end

milestone_ids = set([milestones.get(k) for k in ('M1_ID','M2_ID','M3_ID','M4_ID','POSTMVP_ID','SPIKES_ID')])
strategic = [b for b in beads if b.get('issue_type') not in ('molecule',) and not b['id'].startswith('agents-config-mol-')]
orphaned_strategic = []
for b in strategic:
    if b['id'] in milestone_ids: continue
    parent = b.get('parent')
    visited = set()
    while parent and parent not in milestone_ids and parent not in visited:
        visited.add(parent)
        # walk up
        p = subprocess.run(['bd','show',parent,'--json'], capture_output=True, text=True).stdout
        try:
            pd = json.loads(p)[0]
            parent = pd.get('parent')
        except:
            parent = None
    if parent not in milestone_ids:
        orphaned_strategic.append(b)
print(f'Strategic beads NOT under any milestone feature: {len(orphaned_strategic)}')
for b in orphaned_strategic[:20]:
    print(f'  {b["id"]} [{b.get("status","?")}] {b.get("title","")[:80]}')
EOF
```

Expected: zero orphaned strategic beads (every strategic bead is reachable from a milestone feature). If any appear, investigate — they may be intentional (e.g., closed beads not requiring milestone parent) or a missed reparent.

- [ ] **Step 3: Invariant — depends-on chain on milestone features is intact**

Run:
```bash
for var in M2_ID M3_ID M4_ID POSTMVP_ID; do
  source <(grep "^${var}=" /tmp/phase5b-id-map.txt)
  id="${!var}"
  echo "=== $var deps ==="
  bd show "$id" --json | python3 -c "
import sys, json
d = json.load(sys.stdin)[0]
print(f'  deps: {[x.get(\"id\") if isinstance(x,dict) else x for x in d.get(\"dependencies\",[])]}')"
done
```

Expected: M2 → M1; M3 → M2; M4 → M3; Post-MVP → M4. Research-spikes has no incoming deps (no dependency chain).

- [ ] **Step 4: Invariant — bd ready reflects milestone gating**

Run:
```bash
echo "=== Currently ready ==="
bd ready --json | python3 -c "
import sys, json
beads = json.load(sys.stdin)
print(f'  total ready: {len(beads)}')
for b in beads[:20]:
    print(f'    {b[\"id\"]} {b.get(\"title\",\"\")[:80]}')"
echo ""
echo "=== M1 ready children ==="
source <(grep "^M1_ID=" /tmp/phase5b-id-map.txt)
bd ready --parent "$M1_ID" --json 2>/dev/null | python3 -c "
import sys, json
print('  M1 ready children:', len(json.load(sys.stdin)))"
```

Expected: the M2, M3, M4, and Post-MVP milestone-feature beads should NOT be in `bd ready` output (blocked by their dep on the prior milestone). The M1 milestone-feature bead and Research-spikes bucket bead can appear (no incoming dep).

- [ ] **Step 5: Confirm 7bk and acmh title rescopes are visible**

Run:
```bash
echo "=== 7bk current title ==="
bd show agents-config-7bk --json | python3 -c "import sys, json; print(json.load(sys.stdin)[0].get('title'))"
echo "=== acmh current title ==="
bd show agents-config-acmh --json | python3 -c "import sys, json; print(json.load(sys.stdin)[0].get('title'))"
```

Expected: 7bk title contains "M3 worker fleet"; acmh title contains "M1 cleanups".

---

## Task 17: Handoff

- [ ] **Step 1: Compose summary**

Use this template:

```markdown
Phase 5b beadification complete.

**Snapshot:** `issues.backup.jsonl` committed at the start. Restore via `bd import issues.backup.jsonl` if rollback is needed.

**Beads created (10):** M1, M2, M3, M4, Post-MVP, Research-spikes (6 milestone/bucket features); brainstorm-readiness (epic under M2); Vision-Gap-2 PR-classification policy (under Post-MVP); Vision-Gap-3 memory/compaction governance (under M4); feedback-loop research spike (under Research-spikes).

**Cleavages:**
- 7bk: rescoped to M3-fleet only. Children redistributed: 7bk.4 + 7bk.17 → M1; 7bk.11 → M4; 7bk.16 → Post-MVP; 7bk.24 → Research-spikes; 7bk.12 + 7bk.25 → brainstorm-readiness.
- acmh: rescoped to M1-cleanups only. Children redistributed: acmh.9 → M4; acmh.10 → 7bk; acmh.2 + acmh.5 → Research-spikes.
- jyb: reparented intact under M1.

**Edges:** 3 ADD (4htl→owqa, 7bk.12→owqa, xshc→7bk); 3 REMOVE (mptb→gmxo, 76r→7bk.9 closed, 7bk.19.9→ghost-7bk.19.5).

**Labels:** 5 vision-85-5-10 ADDs (7bk.11, 7bk.12, 7bk.13, 7bk.20, 7bk.25). All 6 pre-existing labels confirmed correct (KEEP).

**Stale molecules closed:** mol-dxvo, mol-miv9h.

**Audit artifacts:** `/tmp/phase5b-audit.txt` shows the new tree; `/tmp/phase5b-id-map.txt` records the new bead IDs.

**Next steps (your call):**
- Optional Phase 5a: ralf-review on the roadmap doc itself for adversarial pressure-test on milestone definitions, DoD verifiability, business-outcome coherence, vision-gap honesty, cut-rationale strength, risk realism.
- Begin M1 work: `bd ready --parent <M1_ID>` shows M1 children that are ready to start.
```

- [ ] **Step 2: Send handoff and PAUSE**

This is the terminal step of Phase 5b. Do NOT begin Phase 5a (ralf-review) without Scott's explicit go.

- [ ] **Step 3: Memory update (housekeeping)**

After Scott confirms the beadification is acceptable, capture any non-obvious lessons via `bd remember`. Examples worth saving:
- Cleavage workflow that worked: capture preflight state → reparent OUT first → rescope title/desc/AC → reparent epic itself → audit invariants.
- bd CLI quirks discovered during execution (parent-inheritance of labels on bd create, ghost-id dep handling, etc.).

DO NOT save bead lists or transient state.

---

## Self-Review

**Spec coverage check (against roadmap doc Sections 6-8):**
- Section 6 research spikes routed: zetc, l0v0, 7bk.24, cx6, 717, feedback-loop, acmh.2, acmh.5 → all under SPIKES_ID via Tasks 5, 6, 7, 9.
- Section 6 deferrals: syod → POSTMVP_ID via Task 9 Step 4.
- Section 7 vision gaps filed: Gap-1 (absorbed into owqa scope, no new bead); Gap-2 → GAP2_ID via Task 5 Step 1; Gap-3 → GAP3_ID via Task 5 Step 2.
- Section 8 edges: all 3 ADD + 3 REMOVE handled in Task 13.
- Section 8 parent assignments: all reparents handled across Tasks 4-12. CREATE EPIC for brainstorm-readiness in Task 4. CREATE FEATURE × 6 in Task 3. CREATE for Gap-2/Gap-3/feedback-loop in Task 5. Cleavages in Tasks 6, 7. Reparents in Tasks 8, 9, 10, 11, 12.
- Section 8 labels: 5 vision-85-5-10 ADDs in Task 14.
- Section 8 suspect molecules: closed in Task 15.
- Section 8 new-beads inventory (10 entries): M1-M4 + Post-MVP + Spikes + brainstorm-readiness + Gap-2 + Gap-3 + feedback-loop = 10 ✓.

**Placeholder scan:** all bd commands have concrete bead IDs or shell variable resolutions; all expected outputs named. No "TBD" / "implement later" patterns.

**Type/name consistency:**
- Variable names: M1_ID, M2_ID, M3_ID, M4_ID, POSTMVP_ID, SPIKES_ID, BRAINSTORM_ID, GAP2_ID, GAP3_ID, FEEDBACK_ID — used consistently across tasks.
- Artifact paths: `/tmp/phase5b-preflight-state.txt`, `/tmp/phase5b-id-map.txt`, `/tmp/phase5b-audit.txt`, `issues.backup.jsonl` — used consistently.
- bd subcommands: create, update, show, list, label add/remove/list, dep add/remove, close — all spelled per `bd` CLI.

**Gaps fixed inline:** none found.

---

## Execution notes

- **Run with `dangerouslyDisableSandbox: true`** for all bd commands per project rules.
- **Idempotency:** `bd dep add` is idempotent (no-op if edge exists); `bd update --parent` is idempotent (no-op if parent already matches); `bd label add` is additive but harmless if applied twice. Re-running tasks is safe.
- **Variable scope:** the `source <(grep ... /tmp/phase5b-id-map.txt)` pattern re-loads the variables in each step's subshell. Using a single long-running shell session is also fine; the file pattern is for resilience across sessions.
- **NO bd dolt push** during this plan — that's a session-completion concern, decided after Scott reviews the audit output.
- **Rollback:** if something goes wrong, `bd import issues.backup.jsonl` restores the pre-Phase-5b state. The snapshot was committed in Task 1, so it survives any local file loss.
