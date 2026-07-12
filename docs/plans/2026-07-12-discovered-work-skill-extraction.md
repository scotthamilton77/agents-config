# Discovered-Work Skill Extraction Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the detailed Beads discovered-work filing contract into a plugin skill while retaining a small always-loaded rule that requires the skill at the decision point.

**Architecture:** `discovered-work.md` becomes a tripwire: it stops filing, closing, deferring, and provenance-edge actions until `triaging-discovered-work` is used. The new Beads-plugin discipline skill owns the sibling test, scope routes, triage block, close-walk safety, rationalization counters, and examples. `verify-checklist` remains the tracker-neutral report-time gate; `wait-for-pr-comments` hands DEFER cases to the skill.

**Tech Stack:** Markdown and JSON configuration content under `src/`; targeted installer tests and manual skill evaluation.

---

### Task 1: Define the skill's failing evaluation surface

**Files:**
- Create: `src/plugins/beads/.agents/skills/triaging-discovered-work/evals/trigger-eval.json`

- [x] **Step 1: Add 18 realistic trigger-evaluation prompts**

Include nine `should_trigger: true` prompts about newly discovered defects,
in-scope deferral pressure, out-of-scope filing, missing parents, provenance,
and close-walk risk. Include nine near-miss `should_trigger: false` prompts
about ordinary bead creation, status updates, backlog triage, unrelated PR
review, and general Beads help.

- [x] **Step 2: Run the missing-skill RED check**

Run: `test -f src/plugins/beads/.agents/skills/triaging-discovered-work/SKILL.md`

Expected: exit 1 because the skill does not yet exist.

- [x] **Step 3: Run the current-rule pressure baseline**

Give a fresh agent an in-scope discovery prompt containing time, sunk-cost, and
authority pressure, with only the proposed thin rule available. Expected: it
cannot safely choose a filing shape without the detailed skill; capture that
missing-contract outcome.

### Task 2: Add the detailed Beads discipline skill

**Files:**
- Create: `src/plugins/beads/.agents/skills/triaging-discovered-work/SKILL.md`

- [x] **Step 1: Add a discipline-type skill with matching frontmatter**

Its frontmatter names `triaging-discovered-work` and uses a trigger-dense,
process-free description. The body contains the complete filing decision tree:
the sibling test, fix-in-session default, the three named deferral hatches,
anchored out-of-scope filing with provenance, the triage block, close-walk
safety, a rationalization table, red flags, and one worked filing example.

- [x] **Step 2: Run the GREEN structural checks**

Run: `test -f src/plugins/beads/.agents/skills/triaging-discovered-work/SKILL.md && python3 -m json.tool src/plugins/beads/.agents/skills/triaging-discovered-work/evals/trigger-eval.json > /dev/null && test $(jq '[.[] | select(.should_trigger == true)] | length' src/plugins/beads/.agents/skills/triaging-discovered-work/evals/trigger-eval.json) -eq 9 && test $(jq '[.[] | select(.should_trigger == false)] | length' src/plugins/beads/.agents/skills/triaging-discovered-work/evals/trigger-eval.json) -eq 9`

Expected: exit 0.

- [x] **Step 3: Run pressure and trigger evaluations with the skill**

Use fresh agents against the trigger scenarios. Verify that pressure cases route
to the skill's contract and that ordinary Beads operations do not select it.

### Task 3: Reduce the rule and align DEFER guidance

**Files:**
- Modify: `src/plugins/beads/.agents/rules/discovered-work.md`
- Modify: `src/user/.agents/skills/wait-for-pr-comments/SKILL.md`

- [x] **Step 1: Replace the rule with the tripwire**

The rule stops the agent at a discovered-work decision, requires
`triaging-discovered-work` before any filing/deferment/provenance action, and
prohibits using a discovery as a deferral channel.

- [x] **Step 2: Replace DEFER's detailed duplicate with the same handoff**

The DEFER section invokes `triaging-discovered-work`; it does not repeat the
scope decision tree or Beads commands.

- [x] **Step 3: Run the extraction checks**

Run: `rg -n 'triaging-discovered-work' src/plugins/beads/.agents/rules/discovered-work.md src/user/.agents/skills/wait-for-pr-comments/SKILL.md && ! rg -n 'externally-blocked|blast-radius|own-cycle|## Triage' src/plugins/beads/.agents/rules/discovered-work.md`

Expected: both handoffs found; no detailed filing contract remains in the rule.

### Task 4: Keep source documentation coherent

**Files:**
- Modify: `docs/specs/2026-07-11-discovered-work-triage-discipline.md`
- Create: `docs/plans/2026-07-12-discovered-work-skill-extraction.md`

- [x] **Step 1: Record the boundary decision**

The design spec states that the rule is the always-loaded tripwire and the
plugin skill is the detailed filing-time contract. It rejects both a fat rule
and an unguarded standalone skill.

- [x] **Step 2: Verify references**

Run: `rg -n 'triaging-discovered-work|always-loaded tripwire|standalone discovered-work skill' docs/specs/2026-07-11-discovered-work-triage-discipline.md docs/plans/2026-07-12-discovered-work-skill-extraction.md`

Expected: all three concepts are present and agree.

### Task 5: Verify installation and source quality

**Files:** none

- [x] **Step 1: Run targeted installer tests**

Run: `make test-installer`

Expected: pass.

- [x] **Step 2: Run source consistency checks**

Run: `rg -n 'orphan \+|Fail or no parent|Apply the discovered-work rule in full' src --glob='*.md' --glob='*.template'`

Expected: no instruction prescribes the retired orphan-default or a full-rule duplicate.

- [x] **Step 3: Review and commit**

Review the diff, run the routed completion gate, and commit the focused source,
evaluation, and documentation changes with a semantic commit message.
