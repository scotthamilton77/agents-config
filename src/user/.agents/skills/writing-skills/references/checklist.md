# Skill Creation Checklist (TDD-Adapted)

Work this in order. Do not skip the RED phase — an untested skill is an
untested change to how every future agent behaves.

## RED Phase — Watch It Fail

- [ ] Create test scenarios appropriate to the skill type (pressure for
      discipline, application for technique, retrieval for reference).
- [ ] Run scenarios WITHOUT the skill (or with the OLD version). Document
      baseline behavior verbatim.
- [ ] Identify patterns in rationalizations, fumbles, or triggering misses.
- [ ] Draft 16-20 trigger-eval queries (8-10 should-trigger + 8-10
      should-not-trigger near-misses).

## GREEN Phase — Write Minimal Skill

- [ ] Name uses only letters, numbers, hyphens. Matches folder name.
- [ ] YAML frontmatter, max 1024 chars, both required fields present.
- [ ] Description: trigger-dense, pushy, **no workflow summary**, third person.
- [ ] Keywords throughout body for search (errors, symptoms, tools).
- [ ] Clear overview with core principle.
- [ ] Body addresses the specific baseline failures from RED.
- [ ] Code inline OR linked to a bundled file (heavy reference → `references/`,
      executable → `scripts/`, output material → `assets/`).
- [ ] One excellent example, not multi-language.
- [ ] Run scenarios WITH the skill — verify compliance / capability / triggering.

## REFACTOR Phase — Close Loopholes

- [ ] Identify new rationalizations or near-miss query failures from testing.
- [ ] Add explicit counters (rationalization table, red flags list — for
      discipline skills).
- [ ] Re-test until bulletproof.
- [ ] Verify total word count is in budget (`wc -w SKILL.md`).

## Quality Checks

- [ ] Register matches skill type (no MUSTs in technique skills, no soft
      reframing in discipline skills).
- [ ] Small flowchart only where the decision is non-obvious.
- [ ] Quick reference table where it helps.
- [ ] Common mistakes section.
- [ ] No narrative storytelling.
- [ ] Supporting files only for tools or heavy reference.

## STOP Before Moving to the Next Skill

After writing ANY skill, you MUST STOP and complete this checklist before
moving on. Do not batch multiple skills without testing each. Deploying
untested skills is deploying untested code.
