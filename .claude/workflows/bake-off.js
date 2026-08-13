export const meta = {
  name: 'bake-off',
  description: 'Parameterized model×effort bake-off: reset worktrees, run contestant arms, audit+gate, sanitize, blind-judge, synthesize',
  whenToUse: 'Run a pinned task across contestant arms (Claude native or codex exec) and judge the outputs blind. Args: {task, base, dir, briefText, rubricText, arms[], judges[], reconcile?, reset?}. Judge-only re-judging of retained artifacts: {judgeOnly: true, dir, labels[], gateSummary, rubricText, judges[], cachedSeats?, cachedChecker?}.',
  phases: [
    { title: 'Reset', detail: 'archive then reset each arm worktree to the pinned base' },
    { title: 'Arms', detail: 'contestants implement the pinned brief in isolated worktrees' },
    { title: 'Audit', detail: 'commit check, diff capture, gate run per arm' },
    { title: 'Sanitize', detail: 'strip environment tells from arm reports for blind judging' },
    { title: 'Judge', detail: 'blind rubric seats over all arms' },
    { title: 'Synthesize', detail: 'decision inventory across arms (optional)' },
  ],
}

// Workflow args arrive as a JSON string in some harness paths — parse defensively.
let IN
try {
  IN = typeof args === 'string' ? JSON.parse(args) : args
} catch (e) {
  throw new Error(`bake-off: args arrived as a string but is not valid JSON: ${e.message}`)
}

const DIR = IN.dir
const BASE = IN.base
const RESET = IN.reset !== false
const JUDGES = IN.judges && IN.judges.length ? IN.judges : [{ id: 'J1', kind: 'claude', model: 'sonnet', effort: 'high' }]
const GATE_CMD = IN.gateCmd || 'make ci'
// Exact JSON keys for the rubric's quality axes. When set, judge prompts name them
// and the judge schema pins them — without this, seats derive keys from the rubric's
// prose axis titles and drift (fit_and_scope vs fit_scope), splitting the axis means.
const AXES = IN.axisKeys && IN.axisKeys.length ? IN.axisKeys : null
// Per-task trap ledger, quarantined to a dedicated checker seat. Main judge seats
// never see it: a key in a judge's context becomes an attention map, and its floor
// becomes the panel's ceiling.
const TRAP_LEDGER = IN.trapLedgerPath || null
// Reconciliation symmetrizes the panel's factual findings across arms and rules on
// whether the majority preference survives the verified ledger. `divergence` is the
// v1 name for the same slot.
const RECONCILE = IN.reconcile !== undefined ? IN.reconcile : IN.divergence
// Optional split-panel escalation: {model, effort} spawns a claude-kind adjudicator
// over the disputed points when seat preferences are not unanimous.
const ESCALATION = IN.escalation || null
// Judge-only mode: judge a completed run's retained artifacts (brief.md, diffs/,
// judged/ under dir) without touching arms — the recovery path when a seat dies
// mid-verdict (resume caching is positional-prefix, so a resumed pipeline re-runs
// contestants instead of just the judge phase), and the cheap path for panel
// iteration over unchanged arm outputs. The caller supplies what the arms phase
// would have produced — labels, the mechanical gateSummary text, a runTags string —
// plus any surviving seat verdicts ({seat, kind, verdict}) and checker findings,
// which join the panel unchanged.
const JUDGE_ONLY = !!IN.judgeOnly
const CACHED_SEATS = IN.cachedSeats || []
const CACHED_CHECKER = IN.cachedChecker || null
if (JUDGE_ONLY && !(IN.labels && IN.labels.length && IN.gateSummary)) {
  throw new Error('bake-off: judgeOnly requires labels[] and gateSummary describing the retained arms')
}
// Cached panel inputs only make sense over unchanged artifacts: on a full run the
// arms are fresh, so a carried-over verdict or checker finding describes bytes that
// no longer exist — refuse rather than silently double-count or go stale.
if (!JUDGE_ONLY && (CACHED_SEATS.length || CACHED_CHECKER)) {
  throw new Error('bake-off: cachedSeats/cachedChecker are judge-only inputs — a full run re-judges everything')
}
// Prompts interpolate these unconditionally; absent, judges would read "undefined".
if (!IN.rubricText) throw new Error('bake-off: rubricText is required — judge prompts interpolate it')
if (!JUDGE_ONLY && (IN.arms || []).some(a => a.kind !== 'reference') && !IN.briefText) {
  throw new Error('bake-off: briefText is required when contestant arms run')
}

// Prompts embed these values inside Bash commands without shell quoting; restrict
// them to shell-inert characters and fail fast, rather than quoting throughout the
// prose. gateCmd is exempt on purpose — it IS a shell command.
const SHELL_INERT = /^[A-Za-z0-9._/-]+$/
const embedded = [['dir', DIR], ['base', BASE], ['contextCheckout', IN.contextCheckout]]
if (TRAP_LEDGER) embedded.push(['trapLedgerPath', TRAP_LEDGER])
for (const a of IN.arms || []) {
  embedded.push([`arm ${a.label} label`, a.label], [`arm ${a.label} worktree`, a.worktree])
  if (a.runTag) embedded.push([`arm ${a.label} runTag`, a.runTag])
  if (a.reportPath) embedded.push([`arm ${a.label} reportPath`, a.reportPath])
}
for (const l of (JUDGE_ONLY ? IN.labels : [])) embedded.push([`label ${l}`, l])
for (const s of JUDGES) {
  embedded.push([`judge ${s.id} id`, s.id])
  if (s.codexModel) embedded.push([`judge ${s.id} codexModel`, s.codexModel])
}
for (const [name, value] of embedded) {
  if (!SHELL_INERT.test(String(value))) throw new Error(`bake-off: ${name} contains shell-active characters or spaces: ${JSON.stringify(value)}`)
}

const tag = arm => arm.runTag || '1'
const judgedPath = arm => `${DIR}/judged/report-${arm.label}.md`
const reportPath = arm => arm.reportPath || `${DIR}/reports/arm-${arm.label}.md`

// ---------- prompts ----------

function resetPrompt(arm) {
  return `You are a mechanical worktree resetter (run tag ${tag(arm)}) for the bake-off experiment worktree ${arm.worktree} (pinned base ${BASE}). This worktree and its branch exist only for this experiment; resetting them to base is the authorized design. Never run any of this against any other path. Execute with Bash:

1. Run: git -C ${arm.worktree} status --porcelain — and: git -C ${arm.worktree} log --oneline ${BASE}..HEAD
2. If BOTH are empty, verify HEAD: git -C ${arm.worktree} rev-parse HEAD — report and stop; nothing to do.
3. Otherwise archive what is there first: mkdir -p ${DIR}/pre-reset && git -C ${arm.worktree} diff ${BASE} HEAD > ${DIR}/pre-reset/${arm.label}-${tag(arm)}.tracked.diff && git -C ${arm.worktree} status --porcelain > ${DIR}/pre-reset/${arm.label}-${tag(arm)}.porcelain.txt && git -C ${arm.worktree} ls-files --others --exclude-standard | tar -C ${arm.worktree} -czf ${DIR}/pre-reset/${arm.label}-${tag(arm)}.untracked.tgz -T - 2>/dev/null; true
4. Then reset, scoped strictly to this worktree: git -C ${arm.worktree} reset --hard ${BASE} && git -C ${arm.worktree} clean -fd
5. Verify: git -C ${arm.worktree} status --porcelain is empty and git -C ${arm.worktree} rev-parse HEAD starts with ${BASE}. If verification fails, say so in notes — do not retry destructive commands.

Return the structured result; report only observed values.`
}

function claudeArmPrompt(arm) {
  return `Dispatch preamble (run tag ${tag(arm)}): your working root is ${arm.worktree}. Your report path is ${reportPath(arm)}. The brief follows.\n\n${IN.briefText}`
}

function codexArmPrompt(arm) {
  return `You are a mechanical harness runner (run tag ${tag(arm)}). Execute exactly the steps below with the Bash tool. Do not improvise, do not edit any file, do not interpret the task the runner executes — your job is transport and capture only.

Step 0 — write the dispatch file: mkdir -p ${DIR}/reports && printf '%s\\n\\n' "Dispatch preamble (run tag ${tag(arm)}): your working root is ${arm.worktree}. Your report path is ${reportPath(arm)}. The brief follows." > ${DIR}/dispatch-${arm.label}.md — then append the brief, which is already on disk at ${DIR}/brief.md: cat ${DIR}/brief.md >> ${DIR}/dispatch-${arm.label}.md

Step 1 — run the runner as ONE FOREGROUND Bash call with timeout 600000 (do NOT use run_in_background — the runner must finish inside this one call):

date +%s > ${DIR}/${arm.label}.start; codex exec -C ${arm.worktree} -m ${arm.codexModel} -c model_reasoning_effort=${arm.effort} -s workspace-write --add-dir ${DIR}/reports -o ${DIR}/reports/arm-${arm.label}.last.md - < ${DIR}/dispatch-${arm.label}.md > ${DIR}/${arm.label}.exec.log 2>&1; echo "CODEX_EXIT=$?" >> ${DIR}/${arm.label}.exec.log; date +%s > ${DIR}/${arm.label}.end

Step 1b — completion ladder (a high-effort runner can outlast one call):
(a) If the harness reports the Step 1 command was moved to the background on timeout, WAIT for its completion notification — never start another codex process while one may still be running for this arm.
(b) Only after the command has fully ended, check the tail of ${DIR}/${arm.label}.exec.log. If NO CODEX_EXIT line was recorded, the runner was killed mid-flight: extract the bare session UUID with: grep -m1 -oE 'session id: [0-9a-f-]+' ${DIR}/${arm.label}.exec.log | cut -d' ' -f3 — then run as ONE FOREGROUND Bash call with timeout 600000: codex exec resume <that-uuid> -o ${DIR}/reports/arm-${arm.label}.last.md - <<< "Continue where you left off and finish the original dispatch; your working root, report path, and constraints are unchanged." >> ${DIR}/${arm.label}.exec.log 2>&1; echo "CODEX_EXIT=$?" >> ${DIR}/${arm.label}.exec.log; date +%s > ${DIR}/${arm.label}.end
Apply rules (a) and (b) to each resume call too, resuming the SAME session id, at most 3 resumes total. If no session id is found in the log, record what happened for log_tail and continue.

Step 2 — retry rule, applied at most once: if the recorded CODEX_EXIT is non-zero AND \`git -C ${arm.worktree} status --porcelain\` is empty AND \`git -C ${arm.worktree} log --oneline ${BASE}..HEAD\` is empty (a transport-class failure that produced no work — e.g. an HTTP 5xx in the log), run the Step 1 command once more. If the worktree has changes or commits, never re-run — capture what is there.

Step 3 — capture with plain foreground reads:
- CODEX_EXIT from the last lines of ${DIR}/${arm.label}.exec.log
- the "tokens used" figure printed near the end of that log (0 if absent)
- wall seconds = the number in ${DIR}/${arm.label}.end minus the number in ${DIR}/${arm.label}.start
- whether ${reportPath(arm)} exists; if it does NOT exist but ${DIR}/reports/arm-${arm.label}.last.md does, copy the .last.md file to ${reportPath(arm)} (the runner's final message is its report)
- the last 25 lines of ${DIR}/${arm.label}.exec.log

Then return the structured result. Report ONLY observed values — if a value was never observed (timeout, launch failure), use -1 for it and say exactly what happened in log_tail. Never invent a number.`
}

function auditPrompt(arm) {
  return `You are a mechanical auditor (run tag ${tag(arm)}) for the git worktree ${arm.worktree} (base commit ${BASE}). Execute these steps with Bash; change no file contents; never push; never touch any other directory.

1. Run: git -C ${arm.worktree} status --porcelain — and read every line.
2. If it lists uncommitted paths: stage ONLY by explicit path — one git -C ${arm.worktree} add <path> per listed path — EXCLUDING any path at the tree root whose name contains REPORT or NOTES (leave those unstaged). Then: git -C ${arm.worktree} commit -m "arm output (audit-committed)". Record that the audit committed. If the tree is clean, record that the arm committed its own work.
3. Run: git -C ${arm.worktree} log --oneline ${BASE}..HEAD — capture it.
4. Run: mkdir -p ${DIR}/diffs && git -C ${arm.worktree} diff ${BASE} HEAD > ${DIR}/diffs/${arm.label}.diff
5. Count changed files: git -C ${arm.worktree} diff --name-only ${BASE} HEAD | wc -l
5b. Mechanical size and complexity measures:
   - LOC: git -C ${arm.worktree} diff --numstat ${BASE} HEAD — sum column 1 as loc_added and column 2 as loc_removed across all rows.
   - Complexity: for each changed .py file (from step 5's list), run: uvx radon cc -s -a ${arm.worktree}/<file> — record the average-complexity line and the single highest-ranked block per file into complexity_summary (one line per file, e.g. "fold.py: avg A (3.2), worst C (12) _h_pr_closed"). If radon fails or no .py files changed, set complexity_summary to exactly what you observed (e.g. "radon unavailable: <error>" or "no .py changes").
6. Gate, exactly this compound command with a 600000ms timeout, run as one Bash call:
   cd ${arm.worktree} && ${GATE_CMD} > ${DIR}/gate-${arm.label}.log 2>&1; echo "GATE_EXIT=$?"
   Read the gate result ONLY from the GATE_EXIT number that command prints — it is the gate's own exit status. Never infer the gate from log contents, and never pipe the gate into another command.
7. Return the structured result. Put anything unexpected (excluded files, commit failures, timeout) in notes. Report only observed values.`
}

function sanitizePrompt(arm) {
  return `You prepare a contestant's report for blind judging (run tag ${tag(arm)}). Input: ${reportPath(arm)}. Output: write ${judgedPath(arm)} (mkdir -p ${DIR}/judged first).

Copy the report verbatim EXCEPT: remove any sentence or fragment that describes the execution environment rather than the work itself — tool, product, model or vendor names; sandbox or permission failures; git locking or commit-environment errors; tracker or database access failures; paths outside the working root. Replace each removed sentence with "[environment detail removed for blind judging]". Additionally, where a model or vendor name is embedded inside an identifier the report quotes — a branch name, commit message, or path — replace only the name portion with [redacted], keeping the rest of the identifier intact. Model names include at least: claude, sonnet, opus, haiku, fable, gpt, codex, luna, terra, sol, gemini — treat any of these inside an identifier as a name to redact, however unfamiliar. Never alter, summarize, reword, or reorder anything about the code, the tests, the decision, or the evidence — the judge must see those bytes as written.

If the input report does not exist, write ${judgedPath(arm)} containing exactly: NO REPORT DELIVERED

If the Write tool refuses the output path, write it with Bash instead (a quoted heredoc: cat > ${judgedPath(arm)} <<'SANITIZED_EOF' ... SANITIZED_EOF); note that you did.

Return the structured result.`
}

function judgeHarnessPrompt(gateSummary, armLabels, runTags) {
  return `You are a blind judge (run tag ${runTags}) for a ${armLabels.length}-arm comparison. Independent implementations of the same task exist as diffs against the same base commit. You do not know, and must not try to infer or state, who or what produced any arm.

The task brief every arm received is at ${DIR}/brief.md — read it first.

The rubric (read it and follow it exactly):

${IN.rubricText}

Harness rules that apply regardless of the rubric text:
- An arm whose diff is EMPTY is no-contest: do not score it — omit it from scores entirely — and name it in disqualified.
- An arm whose gate exited non-zero is disqualified: name it in disqualified instead of scoring it.
- Redaction markers like "[environment detail removed for blind judging]" are the harness's blinding edits, not the arm's writing — draw no inference against an arm from their presence, placement, or any apparent incoherence they introduce.

Gate, size and complexity results, already measured mechanically (gate exits feed the disqualification rules; LOC and complexity are evidence for the engineering-quality axis, never targets; do not re-run anything):
${gateSummary}

Read ONLY these files, with the Read tool:
- ${DIR}/brief.md
${armLabels.map(l => `- ${DIR}/diffs/${l}.diff and ${DIR}/judged/report-${l}.md`).join('\n')}

Do not read anything else under ${DIR} — other files there would unblind the comparison. For surrounding-code context you may read the repository checkout at ${IN.contextCheckout} (it sits at the same base commit); change nothing anywhere.

Score each arm on every rubric axis independently before comparing, then give the pairwise preference (with more than two arms: name the single arm you would ship). ${AXES ? `Use EXACTLY these JSON keys for the axes, one integer 0-5 per axis per scored arm: ${AXES.join(', ')}. ` : ''}Set preference to exactly one arm label, or "tie" only under the rubric's tie conditions (or when no arm is scorable — explain in notes). Return the rubric's Phase 1 audit as ac_audit: one entry per acceptance criterion per arm ({ac, arm, class, verdict, evidence} — evidence quotes the test, code, or report line the verdict rests on). Return the structured result; put scoring reasoning per axis in rationale and any caveats in notes.`
}

function codexJudgePrompt(seat, judgeText, labels) {
  const axesShape = AXES ? AXES.map(k => `\\"${k}\\": int 0-5`).join(', ') : '<axis>: int 0-5, ...'
  const prefShape = labels.map(l => `\\"${l}\\"`).join('|') + '|\\"tie\\"'
  return `You are a mechanical harness runner for judge seat ${seat.id}. Execute with Bash; do not improvise and do not judge anything yourself.

Step 1 — write the judge prompt to ${DIR}/judge-${seat.id}.prompt.md using a quoted heredoc so nothing expands, then append this exact final instruction to the file: "Respond with ONLY a JSON object, no prose, shaped as {\\"scores\\": {<label>: {${axesShape}}, ...}, \\"ac_audit\\": [{\\"ac\\": string, \\"arm\\": <label>, \\"class\\": \\"test-expressible\\"|\\"justification\\", \\"verdict\\": \\"pinned\\"|\\"partially-pinned\\"|\\"unpinned\\"|\\"met\\"|\\"unmet\\", \\"evidence\\": string}, ...], \\"preference\\": ${prefShape}, \\"rationale\\": string, \\"disqualified\\": [labels], \\"notes\\": string}. Use those axis keys EXACTLY." The judge prompt content is everything between BEGIN-PROMPT and END-PROMPT below.

Step 2 — run as ONE FOREGROUND Bash call with timeout 600000:
codex exec -C ${IN.contextCheckout} -m ${seat.codexModel} -c model_reasoning_effort=${seat.effort} -s read-only --add-dir ${DIR} -o ${DIR}/judge-${seat.id}.out.md - < ${DIR}/judge-${seat.id}.prompt.md > ${DIR}/judge-${seat.id}.exec.log 2>&1; echo "CODEX_EXIT=$?" >> ${DIR}/judge-${seat.id}.exec.log

Step 2b — completion ladder (a large comparison can outlast one call):
(a) If the harness reports the Step 2 command was moved to the background on timeout, WAIT for its completion notification — never start another codex process while one may still be running for this seat.
(b) Only after the command has fully ended, check whether ${DIR}/judge-${seat.id}.out.md exists. If it does NOT, the runner was killed mid-flight: extract the bare session UUID with: grep -m1 -oE 'session id: [0-9a-f-]+' ${DIR}/judge-${seat.id}.exec.log | cut -d' ' -f3 — then run as ONE FOREGROUND Bash call with timeout 600000: codex exec resume <that-uuid> -o ${DIR}/judge-${seat.id}.out.md - <<< "Continue where you left off and finish the judging task; your final message must be ONLY the JSON object exactly as specified." >> ${DIR}/judge-${seat.id}.exec.log 2>&1; echo "CODEX_EXIT=$?" >> ${DIR}/judge-${seat.id}.exec.log
Apply rules (a) and (b) to each resume call too, resuming the SAME session id, at most 3 resumes total. If no session id is found in the log, note it and go to Step 3.

Step 3 — read ${DIR}/judge-${seat.id}.out.md, extract the JSON object, and return it as the structured result with seat_exit set to the recorded CODEX_EXIT. If an axis key in the judge's JSON differs only in wording from the pinned keys, rename it to the pinned key and record the rename in notes — never alter a score. If the output is missing or not parseable JSON, return seat_exit -1, empty scores, preference "tie", and put the raw tail in notes. Report only observed values.

BEGIN-PROMPT
${judgeText}
END-PROMPT`
}

// ---------- schemas ----------

const RESET_SCHEMA = {
  type: 'object',
  properties: {
    was_dirty: { type: 'boolean' },
    archived: { type: 'boolean' },
    head_ok: { type: 'boolean' },
    notes: { type: 'string' },
  },
  required: ['was_dirty', 'archived', 'head_ok', 'notes'],
}

const WRAPPER_SCHEMA = {
  type: 'object',
  properties: {
    codex_exit: { type: 'integer' },
    tokens_used: { type: 'integer' },
    wall_seconds: { type: 'integer' },
    report_exists: { type: 'boolean' },
    log_tail: { type: 'string' },
  },
  required: ['codex_exit', 'tokens_used', 'wall_seconds', 'report_exists', 'log_tail'],
}

const AUDIT_SCHEMA = {
  type: 'object',
  properties: {
    uncommitted_found: { type: 'boolean' },
    committed_by_audit: { type: 'boolean' },
    commits: { type: 'string' },
    gate_exit: { type: 'integer' },
    files_changed: { type: 'integer' },
    loc_added: { type: 'integer' },
    loc_removed: { type: 'integer' },
    complexity_summary: { type: 'string' },
    notes: { type: 'string' },
  },
  required: ['uncommitted_found', 'committed_by_audit', 'commits', 'gate_exit', 'files_changed', 'loc_added', 'loc_removed', 'complexity_summary', 'notes'],
}

const SANITIZE_SCHEMA = {
  type: 'object',
  properties: {
    existed: { type: 'boolean' },
    removed_count: { type: 'integer' },
    notes: { type: 'string' },
  },
  required: ['existed', 'removed_count', 'notes'],
}

// Built per run: labels pin the preference enum; AXES (when set) pin the score keys.
// A disqualified or no-contest arm is simply omitted from scores, so no label is required.
function judgeSchema(labels) {
  const axesSchema = AXES
    ? {
        type: 'object',
        properties: Object.fromEntries(AXES.map(k => [k, { type: 'integer', minimum: 0, maximum: 5 }])),
        required: AXES,
        additionalProperties: false,
      }
    : { type: 'object' }
  return {
    type: 'object',
    properties: {
      scores: {
        type: 'object',
        properties: Object.fromEntries(labels.map(l => [l, axesSchema])),
        additionalProperties: false,
      },
      ac_audit: {
        type: 'array',
        items: {
          type: 'object',
          properties: {
            ac: { type: 'string' },
            arm: { type: 'string', enum: labels },
            class: { type: 'string', enum: ['test-expressible', 'justification'] },
            verdict: { type: 'string', enum: ['pinned', 'partially-pinned', 'unpinned', 'met', 'unmet'] },
            evidence: { type: 'string' },
          },
          required: ['ac', 'arm', 'class', 'verdict', 'evidence'],
        },
      },
      preference: { type: 'string', enum: [...labels, 'tie'] },
      rationale: { type: 'string' },
      disqualified: { type: 'array', items: { type: 'string' } },
      notes: { type: 'string' },
      seat_exit: { type: 'integer' },
    },
    required: ['scores', 'ac_audit', 'preference', 'rationale', 'disqualified', 'notes'],
  }
}

const CHECKER_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          probe: { type: 'string' },
          arm: { type: 'string' },
          verdict: { type: 'string', enum: ['caught', 'repeated', 'silent', 'n/a'] },
          quote: { type: 'string' },
        },
        required: ['probe', 'arm', 'verdict', 'quote'],
      },
    },
    notes: { type: 'string' },
  },
  required: ['findings', 'notes'],
}

const RECONCILE_SCHEMA = {
  type: 'object',
  properties: {
    choices: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          choice: { type: 'string' },
          arms: { type: 'array', items: { type: 'string' } },
          unique: { type: 'boolean' },
          classification: { type: 'string', enum: ['advantage', 'neutral', 'defect', 'unverified'] },
          justification: { type: 'string' },
        },
        required: ['choice', 'arms', 'unique', 'classification', 'justification'],
      },
    },
    preference_consistency: { type: 'string', enum: ['consistent', 'contradicted'] },
    consistency_reason: { type: 'string' },
    notes: { type: 'string' },
  },
  required: ['choices', 'preference_consistency', 'consistency_reason', 'notes'],
}

const ESCALATION_SCHEMA_BASE = labels => ({
  type: 'object',
  properties: {
    ruling: { type: 'string' },
    own_arm_preference: { type: 'string', enum: [...labels, 'tie'] },
    notes: { type: 'string' },
  },
  required: ['ruling', 'own_arm_preference', 'notes'],
})

// ---------- pipeline ----------

// Per arm: (reset →) contestant → audit → sanitize, no cross-arm barrier until judging.
let arms = []
if (!JUDGE_ONLY) {
phase('Arms')
log(`Dispatching ${IN.arms.length} arm(s); reset=${RESET}`)
const armResults = await pipeline(
  IN.arms,
  // A 'reference' arm is a pre-existing change (its worktree already sits at the
  // commit under audit): never reset it, never run a contestant for it.
  // A null stage result drops the item from the pipeline entirely — every skip
  // path must resolve to a truthy sentinel, never null.
  arm => RESET && arm.kind !== 'reference'
    ? agent(resetPrompt(arm), { label: `reset:${arm.label}`, phase: 'Reset', model: 'haiku', effort: 'low', schema: RESET_SCHEMA })
    : Promise.resolve({ skipped: true }),
  (resetResult, arm) => arm.kind === 'reference'
    ? Promise.resolve({ resetResult, contestant: 'reference arm: pre-existing change under audit; no contestant was run' })
    : arm.kind === 'claude'
      ? agent(claudeArmPrompt(arm), { label: `arm:${arm.label}`, phase: 'Arms', model: arm.model, effort: arm.effort })
          .then(r => ({ resetResult, contestant: r }))
      : agent(codexArmPrompt(arm), { label: `arm:${arm.label}`, phase: 'Arms', model: 'haiku', effort: 'low', schema: WRAPPER_SCHEMA })
          .then(r => ({ resetResult, contestant: r })),
  (prev, arm) => agent(auditPrompt(arm), { label: `audit:${arm.label}`, phase: 'Audit', model: 'haiku', effort: 'low', schema: AUDIT_SCHEMA })
    .then(audit => ({ ...prev, audit })),
  (prev, arm) => agent(sanitizePrompt(arm), { label: `sanitize:${arm.label}`, phase: 'Sanitize', model: 'sonnet', effort: 'low', schema: SANITIZE_SCHEMA })
    .then(sanitize => {
      // Surface a no-deliverable arm the moment the sanitizer detects it, not
      // when a judge scores its justification criteria zero an hour later.
      const report_missing = !sanitize || !sanitize.existed
      if (report_missing) log(`ARM ${arm.label}: no report delivered — it will be judged on its diff alone, and justification-class criteria will fail`)
      return { arm: arm.label, kind: arm.kind, report_missing, ...prev, sanitize }
    }),
)

arms = armResults.filter(Boolean)
log(`Arms complete: ${arms.length}/${IN.arms.length}. Gates: ${arms.map(a => `${a.arm}=${a.audit ? a.audit.gate_exit : '?'}`).join(', ')}`)
} else {
  log(`Judge-only: judging retained artifacts in ${DIR} — ${IN.labels.length} arm(s), ${CACHED_SEATS.length} cached seat(s)${CACHED_CHECKER ? ', cached checker' : ''}`)
}

// Barrier: every judge seat needs all arms.
phase('Judge')
const labels = JUDGE_ONLY ? IN.labels : arms.map(a => a.arm)
const runTags = JUDGE_ONLY ? (IN.runTags || 'judge-only') : IN.arms.map(a => `${a.label}${tag(a)}`).join('/')
const gateSummary = JUDGE_ONLY ? IN.gateSummary : arms.map(a =>
  `Arm ${a.arm}: gate exit ${a.audit ? a.audit.gate_exit : 'unknown'}, ${a.audit ? a.audit.files_changed : '?'} files changed (+${a.audit ? a.audit.loc_added : '?'}/-${a.audit ? a.audit.loc_removed : '?'} LOC), complexity: ${a.audit ? a.audit.complexity_summary : 'unknown'}, committed by ${a.audit && a.audit.committed_by_audit ? 'the audit (arm left work uncommitted)' : 'the arm itself'}${a.kind === 'reference' ? ' [commit pre-existed this run; "committed by the arm" reflects the audit finding a clean tree, not authorship during this dispatch]' : ''}`
).join('\n')
const judgeText = judgeHarnessPrompt(gateSummary, labels, runTags)
const JUDGE_SCHEMA = judgeSchema(labels)

// Claude seats persist the verdict to disk before returning it: a connection drop
// mid-structured-response otherwise loses a completed judgment with no artifact.
const claudeSeatSuffix = seat => `\n\nDelivery hardening for this seat (${seat.id}): FIRST write your complete verdict as a single JSON object to ${DIR}/audits/seat-${seat.id}.json with the Write tool — the same object you will return: {scores, ac_audit, preference, rationale, disqualified, notes}. THEN return exactly that object as your structured result. The scores object must carry every scored arm label, each with exactly the five pinned axis keys, integer 0-5 — no other keys anywhere in scores.`
const seatThunks = JUDGES.map(seat => () =>
  seat.kind === 'codex'
    ? agent(codexJudgePrompt(seat, judgeText, labels), { label: `judge:${seat.id}`, phase: 'Judge', model: 'haiku', effort: 'low', schema: JUDGE_SCHEMA })
        .then(v => ({ seat: seat.id, kind: seat.kind, verdict: v }))
    : agent(judgeText + claudeSeatSuffix(seat), { label: `judge:${seat.id}`, phase: 'Judge', model: seat.model, effort: seat.effort, schema: JUDGE_SCHEMA })
        .then(v => ({ seat: seat.id, kind: seat.kind, verdict: v }))
)
// The checker seat is quarantined: it alone reads the trap ledger, and its output
// never enters a main judge's context. A cached checker result suppresses a re-run.
if (TRAP_LEDGER && !CACHED_CHECKER) seatThunks.push(() =>
  agent(`You are the trap-ledger checker (run tag ${runTags}) for a blind ${labels.length}-arm comparison. Facts only — never score quality, never state a preference, never infer who produced any arm.

Read ${TRAP_LEDGER}, then for each arm label (${labels.join(', ')}): ${DIR}/judged/report-<label>.md and ${DIR}/diffs/<label>.diff. Read nothing else under ${DIR}. You may consult the repository checkout at ${IN.contextCheckout} read-only to confirm a ledger fact; change nothing.

For each ledger probe crossed with each arm: quote the exact report sentence(s) bearing on the probe (or write "silent"), and rule caught (the arm correctly states the fact), repeated (the arm asserts the false version), silent (no claim either way), or n/a. Markers reading "[environment detail removed for blind judging]" are the harness's edits — draw no inference from them. Return the structured result.`,
    { label: 'checker', phase: 'Judge', model: 'haiku', effort: 'low', schema: CHECKER_SCHEMA })
    .then(v => ({ checkerResult: v })))
const seatResults = (await parallel(seatThunks)).filter(Boolean)
// A seat whose agent died terminally resolves with verdict: null — drop it from the
// panel and report it, rather than letting a null verdict poison later stages.
// Cached seat verdicts join the panel unchanged and count in every later stage.
const judges = [...seatResults.filter(r => !r.checkerResult && r.verdict), ...CACHED_SEATS.filter(s => s && s.verdict)]
const judges_failed = seatResults.filter(r => !r.checkerResult && !r.verdict).map(r => r.seat)
if (judges_failed.length) log(`Seat(s) returned no verdict (agent died): ${judges_failed.join(', ')} — panel proceeds with ${judges.length} seat(s)`)
const checker = (seatResults.find(r => r.checkerResult) || {}).checkerResult || CACHED_CHECKER

// Aggregate in plain code: per-axis means and preference tally across seats.
const totals = {}
const prefs = {}
for (const j of judges) {
  const v = j.verdict || {}
  if (v.preference) prefs[v.preference] = (prefs[v.preference] || 0) + 1
  for (const [armLabel, axesScores] of Object.entries(v.scores || {})) {
    totals[armLabel] = totals[armLabel] || {}
    for (const [axis, score] of Object.entries(axesScores || {})) {
      totals[armLabel][axis] = totals[armLabel][axis] || []
      if (typeof score === 'number') totals[armLabel][axis].push(score)
    }
  }
}
const aggregate = {}
for (const [armLabel, axesScores] of Object.entries(totals)) {
  aggregate[armLabel] = {}
  let sum = 0
  for (const [axis, scores] of Object.entries(axesScores)) {
    const mean = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null
    aggregate[armLabel][axis] = mean
    if (mean !== null) sum += mean
  }
  aggregate[armLabel].total = sum
}
// Majority preference: the label with the most seat votes; null on a tie.
const sortedPrefs = Object.entries(prefs).sort((a, b) => b[1] - a[1])
const majority = sortedPrefs.length && (sortedPrefs.length === 1 || sortedPrefs[0][1] > sortedPrefs[1][1])
  ? sortedPrefs[0][0] : null
log(`Judging complete: ${judges.length} seat(s). Preferences: ${JSON.stringify(prefs)}; majority: ${majority}`)

// Optional split-panel escalation: an adjudicator rules on the disputed points.
// Recorded alongside the panel result; never replaces it silently.
let escalation = null
const prefValues = judges.map(j => j.verdict && j.verdict.preference).filter(Boolean)
const unanimous = prefValues.length > 0 && prefValues.every(p => p === prefValues[0])
if (ESCALATION && !unanimous) {
  phase('Synthesize')
  const seatSummaries = judges.map(j =>
    `Seat ${j.seat} preferred ${j.verdict.preference}. Rationale: ${j.verdict.rationale}\nNotes: ${j.verdict.notes}`).join('\n\n---\n\n')
  escalation = await agent(
    `You adjudicate a split blind panel (run tag ${runTags}). Seats disagreed on which of ${labels.length} independent implementations of the same task to ship. Do not tally votes — rule on the points of factual disagreement by your own reading of the primary materials, treating every seat claim as a hypothesis to verify with quoted evidence.

Read ${DIR}/brief.md, then for each arm label (${labels.join(', ')}): ${DIR}/diffs/<label>.diff and ${DIR}/judged/report-<label>.md. Read nothing else under ${DIR}. For ground truth read the repository checkout at ${IN.contextCheckout}; change nothing anywhere. Redaction markers in reports are the harness's edits — draw no inference from them.

The seat verdicts under dispute:

${seatSummaries}

Return: ruling (each factual disagreement resolved with quotes), own_arm_preference (the arm you would ship from your own analysis), notes.`,
    { label: 'escalation', phase: 'Synthesize', model: ESCALATION.model, effort: ESCALATION.effort, schema: ESCALATION_SCHEMA_BASE(labels) },
  )
}

// Reconciliation: symmetrize the panel's factual findings across arms, then rule on
// whether the majority preference survives the verified ledger. Findings never mutate
// seat scores; a contradiction raises a flag for human review, never a silent flip.
let reconciliation = null
if (RECONCILE) {
  phase('Synthesize')
  const seatFindings = judges.map(j =>
    `Seat ${j.seat} (preferred ${j.verdict.preference}): ${j.verdict.rationale}\nNotes: ${j.verdict.notes}`).join('\n\n---\n\n')
  reconciliation = await agent(
    `You reconcile a blind ${labels.length}-arm comparison (run tag ${runTags}). The panel's majority preference is ${majority || 'none (tie)'}.

Read ${DIR}/brief.md, then for each arm label (${labels.join(', ')}): ${DIR}/diffs/<label>.diff and ${DIR}/judged/report-<label>.md. Read nothing else under ${DIR}. For ground truth read the repository checkout at ${IN.contextCheckout}; change nothing anywhere. Redaction markers in reports are the harness's edits — draw no inference from them.

The panel's findings (treat every claim as a hypothesis — verify against the code before crediting):

${seatFindings}

${checker ? `The trap-ledger checker's factual findings (same rule — verify before use):\n${JSON.stringify(checker.findings)}\n` : ''}
Build the symmetrized inventory: every distinct factual finding or design choice claimed by any seat or checker, plus any you discover yourself — verify each against the code, then apply it to EVERY arm uniformly (does each arm have this property? quote the code). Classify each: advantage, neutral, defect — grounded in the brief's acceptance criteria — or unverified if you could not confirm it (unverified findings are excluded from the consistency ruling). Then rule preference_consistency: consistent, or contradicted — contradicted means the verified ledger shows a defect in the majority-preferred arm, material to the brief's objective, that the evidence shows the other arm(s) lack. Your ledger never alters seat scores. Return the structured result.`,
    { label: 'reconcile', phase: 'Synthesize', model: 'opus', effort: 'high', schema: RECONCILE_SCHEMA },
  )
}
const inversion_flag = !!(reconciliation && reconciliation.preference_consistency === 'contradicted')
if (inversion_flag) log(`INVERSION FLAG: majority preference ${majority} is contradicted by the verified ledger — human review required`)

return {
  task: IN.task || null,
  base: BASE,
  arms,
  judges,
  judges_failed,
  checker,
  preferences: prefs,
  majority,
  aggregate,
  escalation,
  reconciliation,
  inversion_flag,
}
