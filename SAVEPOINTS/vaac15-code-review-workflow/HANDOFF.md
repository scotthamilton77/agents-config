# Handoff — vaac.15: code-review workflow + slimmed quality-gate

**Date:** 2026-07-19 · **Session:** 79d2bd47-72ae-44c7-bd8d-1c8db05bbcfa
**Bead:** `agents-config-vaac.15` (claimed `in_progress` — release or deliver, never abandon)
**Worktree:** `.claude/worktrees/vaac15-code-review-workflow`
**Feature branch:** `worktree-vaac15-code-review-workflow` — **pushed to origin @ `1430954`. No PR yet (deliberate).**
**Scratch branch:** `vaac15-fixture` (local only; planted-bug fixture + iteration history; delete after Task 4 wraps)

## What this is

Implements `docs/specs/2026-07-19-code-review-workflow-and-slim-quality-gate-design.md`
via `docs/plans/2026-07-19-code-review-workflow-quality-gate.md` (both on the branch):

1. **New** `src/user/.claude/workflows/code-review.js` — standalone port of the upstream
   Anthropic code-review command (steps 2–6): Haiku change-summary → parallel role lanes
   (compliance, diff-only bug-scan, history, prior-PRs, comment-fidelity, Codex
   cross-model; `profile:"gate"` adds security + simplify) → per-finding Haiku scorer,
   ≥80 filter, scorer-adjudicated severity/fixClass. Targets PR / ref / bare branch.
   Returns findings; never posts.
2. **Rewritten** `src/user/.claude/workflows/quality-gate.js` — refuter panels DELETED
   (pre-removal code preserved at main `5395c13`, a full-tree snapshot; the commit that
   last touched the file is `ffc8bab` — see finding #3 below). Single pass:
   `workflow('code-review', {profile:'gate'})` child → mechanical-fix wave → scored
   re-check of fixer-touched files → dual-signal synthesis. Exit precedence:
   all-lanes-dead > lane-quorum > budget > recheck-regression > residual.
3. **Rule edit** `src/user/.agents/rules/completion-gate.md` — HEAVY `all-lanes-dead`
   (or thrown Workflow call) → fall back to SERIAL.

## Plan progress (5 tasks)

- Tasks 1–3 (both workflows + rule clause): **done, committed, pushed.**
- Task 4 (planted-bug fixture): **in progress, paused by Scott after run 3.**
- Task 5 (gate dogfood on this branch → PR → review loop): **not started.**

## Fixture runs so far (Task 4, on `vaac15-fixture`)

- **Run 1** — died: Haiku summarizer hallucinated calling StructuredOutput; discovered
  `agent({schema})` **throws** (doesn't return null) on that. → Hardening now in both
  files: summary degrades, lane throw = attributed death, scorer throw = kept-unscored,
  `withRepair` catches throws.
- **Run 2** — mechanics green (all 6 lanes incl. Codex), but scorer rated the planted
  off-by-one 25: fixture comments confessed (`# planted:`), and my "breaks on 1-item
  list" claim was wrong (negative indexing). Fixture rewritten innocent; prompts pinned
  to cwd (summarizer had wandered to the main checkout).
- **Run 3** — 9 raw → 5 survived ≥80. Bug-scan FOUND the off-by-one; scorer killed it at
  25 by reading the `"de-incriminate fixture"` **commit message**. To pass the planted-bug
  assertion honestly, the fixture needs an innocent commit message too.

## Run-3 findings on OUR code — dispositions proposed, NOT yet applied

1. **`/tmp/codex-review-prompt.md` fixed path (major, 85)** — real; fix: `mktemp` in the
   Codex-lane prompt. APPLY.
2. Fixture-ships-if-merged (major, 92) — artifact of reviewing the scratch branch; fixture
   branch gets deleted. NO ACTION.
3. **Preservation SHA (minor, 85)** — `5395c13` works (full snapshot) but cite `ffc8bab`
   (last commit touching quality-gate.js) in: quality-gate.js header, spec (2 places),
   bead `wgclw.36` text. APPLY.
4. **Plan doc's `node --check` claim (“blocking”, 100)** — stale text; actual check used:
   wrap body in `async function (…) {}` + strip `export` (top-level return/await are
   harness idioms). Fix plan text. APPLY.
5. **Spec cost line (minor, 80)** — reality is 8 Sonnet lane agents + 1 external Codex
   call. One-line spec fix. APPLY.
- **Near-misses at 75, worth applying anyway:** (a) validate `target.pr` (int) /
  `target.ref` (safe charset) before prompt interpolation; (b) cross-lane fingerprint
  dedup before scoring (dupe mechanical findings → second fixer fails → false residual).

## Gotchas the next session must know

- **Workflow name registry serves `~/.claude/workflows/` (installed, still OLD quality-gate).**
  Test via `scriptPath:` (absolute path into this worktree). The gate's child call
  `workflow('code-review')` resolves BY NAME → for the Task 4 gate test, temporarily copy
  `code-review.js` to `~/.claude/workflows/` (new file), delete after. NEVER run the installer.
- **Syntax gate:** `{ echo 'async function _wf(args, budget, agent, parallel, pipeline, workflow, log, phase) {'; sed 's/^export const meta/const meta/' FILE; echo '}'; } | node --input-type=module --check`
- **Scorer rubric text is duplicated** in both workflow files (harness: no imports);
  source of truth = code-review.js. Keep in sync.
- The PostToolUse hook `~/.claude/hooks/ruff-postedit.py` is missing → every Edit logs a
  hook error. Harmless; Scott was told.
- Related beads filed this session: `wgclw.35` (remove dead scale_hint.refuters — P3),
  `wgclw.36` (optional refuter skill restoration — P3). Both open, provenance-linked.

## Resume checklist (in order)

1. Get Scott's green light on the disposition list above; apply fixes on the feature
   branch (items 1, 3, 4, 5 + the two 75s).
2. Optional: redo fixture with innocent commit message → assert off-by-one survives ≥80;
   else accept two-of-three assertion evidence and record it.
3. Task 4 step 3: gate run on fixture (needs the ~/.claude copy; remove after).
4. Teardown: delete `vaac15-fixture` branch (src changes already consolidated @ 1430954).
5. Task 5: gate-triage → HEAVY dogfood on this branch → `finishing-a-development-branch`
   (PR) → `wait-for-pr-comments` loop → pause at merge (merge-guard policy; Scott's
   standing grant applies only if the gate fully clears).
6. Close out `vaac.15` (deliver) and update bead notes with fixture evidence.
