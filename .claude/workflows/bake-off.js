export const meta = {
  name: 'bake-off',
  description: 'Parameterized model×effort bake-off: reset worktrees, run contestant arms, audit+gate, sanitize, blind-judge, synthesize',
  whenToUse: 'Run a pinned task across contestant arms (Claude native or codex exec) and judge the outputs blind; a judge seat is {id, kind: claude|codex|openrouter, model|codexModel, effort?}, where effort defaults per session (audit high, score medium, rank high) and overrides as one level or {audit, score, rank}; an openrouter seat ({model, effort?, fallback: {kind, model|codexModel, effort?}}) needs openrouterLauncherPath (absolute run.js of the openrouter-claude-subagent skill). Args: {task, base, dir, briefPath (absolute; copied to <dir>/brief.md, which every arm and seat reads), rubricText, axisKeys (first = factual grounding), acIds (the brief\'s criterion ids), arms[], judges[], runnerPath (required for codex arms), pricingCheckPath (absolute; required — halts the run on an expired price; collect_usage.py beside it prices every arm into the result\'s usage field), reconcile?, reset?, maxAttempts?, watchdogSeconds?, rungTimeoutMs?, armsOnly? (end after Sanitize/Usage with no judging — the complement of judgeOnly)}. Judge-only re-judging of retained artifacts: {judgeOnly: true, dir, labels[], gateSummary (one "Arm <label>: ..." line per arm), rubricText, axisKeys, acIds, judges[], rankReads?, cachedSeats?, cachedChecker?}.',
  phases: [
    { title: 'Preflight', detail: 'place the pinned brief where arms and seats read it' },
    { title: 'Reset', detail: 'archive then reset each arm worktree to the pinned base' },
    { title: 'Arms', detail: 'contestants implement the pinned brief in isolated worktrees' },
    { title: 'Audit', detail: 'commit check, diff capture, gate run per arm' },
    { title: 'Sanitize', detail: 'strip environment tells from arm reports for blind judging' },
    { title: 'Usage', detail: 'wall time, exact tokens and priced cost per arm, from the harness transcripts' },
    { title: 'Judge', detail: 'per seat: audit and score one arm per session, then rank the seat\'s own table' },
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
const JUDGES = IN.judges && IN.judges.length ? IN.judges : [{ id: 'J1', kind: 'claude', model: 'sonnet' }]
// A seat's effort per session, by what the session does: the audit pins every
// criterion and catches false claims — the calibration-bearing work; the score reads
// a finished ledger; the rank is the one judgment over the whole field. A seat's
// `effort` overrides this as one level for all three or as {audit, score, rank};
// an openrouter model may not offer every level, so its caller checks the list.
const SESSION_EFFORT = { audit: 'high', score: 'medium', rank: 'high' }
const SESSIONS = Object.keys(SESSION_EFFORT)
const effortFor = (seat, session) => typeof seat.effort === 'string' ? seat.effort : { ...SESSION_EFFORT, ...(seat.effort || {}) }[session]
for (const s of JUDGES) {
  if (s.effort && typeof s.effort !== 'string' && Object.keys(s.effort).some(k => !SESSIONS.includes(k))) throw new Error(`bake-off: judge ${s.id} effort keys must be among ${SESSIONS.join('/')}`)
}
const GATE_CMD = IN.gateCmd || 'make ci'
// Size and cyclomatic complexity are evidence for a code deliverable's
// engineering-quality axis and meaningless for a prose one, where a longer
// document is not a worse one. Off drops the measurement from the audit, the
// audit schema, and the gate summary the judges read.
const MEASURE_CODE = IN.measureCode !== false
// Codex arms run through the versioned single-attempt runner script; every
// recovery decision (resume / fresh retry / stop) is made here in plain JS from
// the rung's state JSON — the wrapper agent is transport only. The runner's
// in-code watchdog stays strictly below the rung's Bash-call timeout, so the
// harness's background-on-timeout branch is unreachable inside a rung.
const RUNNER = IN.runnerPath || null
// An openrouter seat runs its sessions through the openrouter-claude-subagent
// launcher (its only supported entry point: a direct claude call against
// openrouter.ai returns empty with exit 0 and bills the tokens). The seat names
// a fallback seat, taken seat-wide when the launcher refuses (exit 78) or a
// session returns nothing parseable twice; the result records which seat ran.
const OR_LAUNCHER = IN.openrouterLauncherPath || null
for (const s of JUDGES.filter(j => j.kind === 'openrouter')) {
  if (!s.model) throw new Error(`bake-off: openrouter seat ${s.id} needs model (vendor/model-id)`)
  if (!s.fallback || !s.fallback.kind || s.fallback.kind === 'openrouter') throw new Error(`bake-off: openrouter seat ${s.id} needs a fallback seat of another kind ({kind, model|codexModel, effort})`)
  if (!OR_LAUNCHER || !OR_LAUNCHER.startsWith('/')) throw new Error('bake-off: openrouterLauncherPath (absolute path to the openrouter-claude-subagent run.js) is required when an openrouter seat is configured')
}
// The pinned brief is a file, not a string: codex arms are handed its path on the
// command line and every seat reads it for the criteria. Passing the text inline as
// well would give the run two sources of truth for its one pinned input, so it does
// not: preflight copies this into place and everything downstream reads that copy.
const BRIEF_PATH = IN.briefPath || null
// A published price with an end date is not a price after that date, and a cost
// computed from one is wrong in a way nothing downstream can detect. Preflight runs
// this check and the run stops on an expired entry, so a human re-verifies the table
// against the vendor rather than a later reader trusting a number nobody checked.
const PRICING_CHECK = IN.pricingCheckPath || null
// The usage collector lives beside the pricing check and reads the same table. Its
// output is the run's cost axis and goes only into the final result: price tracks
// model tier, so a seat holding it is partly unblinded.
const USAGE_COLLECTOR = PRICING_CHECK ? PRICING_CHECK.replace(/check_pricing\.py$/, 'collect_usage.py') : null
const MAX_ATTEMPTS = IN.maxAttempts || 4
const WATCHDOG_S = IN.watchdogSeconds || 1200
const RUNG_TIMEOUT_MS = IN.rungTimeoutMs || 1740000
// Exact JSON keys for the rubric's quality axes. When set, judge prompts name them
// and the judge schema pins them — without this, seats derive keys from the rubric's
// prose axis titles and drift (fit_and_scope vs fit_scope), splitting the axis means.
const AXES = IN.axisKeys && IN.axisKeys.length ? IN.axisKeys : null
if (!AXES || AXES.length < 2) throw new Error('bake-off: axisKeys is required — the first key is the factual-grounding axis the audit session scores; the rest are scored by the score session')
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
// Arms-only: the run ends after Sanitize and Usage, spawning no seat, checker or
// reconciler. It is judgeOnly's complement — a partial-cohort re-run whose judging
// belongs to a later full-cohort judgeOnly pass, which would otherwise burn a
// throwaway panel and leave a partial verdict artifact in the run dir.
const ARMS_ONLY = !!IN.armsOnly
if (ARMS_ONLY && JUDGE_ONLY) throw new Error('bake-off: armsOnly and judgeOnly are complements of one split run — pass one, not both')
// The brief's acceptance-criterion ids, pinned by the caller. A seat audits one arm
// at a time and must return one row per id; the script checks the set, so a sampled
// audit cannot read as complete.
const AC_IDS = IN.acIds || []
if (!AC_IDS.length) throw new Error('bake-off: acIds is required — the brief\'s acceptance-criterion ids (e.g. ["AC1", ..., "AC17"]); every seat must audit each one per arm')
// How many of a seat's own top-scored documents the rank session re-reads whole.
const RANK_READS = IN.rankReads || 3
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
if (!JUDGE_ONLY && (IN.arms || []).some(a => a.kind !== 'reference') && !BRIEF_PATH) {
  throw new Error('bake-off: briefPath is required when contestant arms run — it is the pinned brief every arm and seat reads')
}
if (BRIEF_PATH && !BRIEF_PATH.startsWith('/')) {
  throw new Error('bake-off: briefPath must be absolute — the preflight agent starts in the session root, not this checkout')
}
if (!PRICING_CHECK) {
  throw new Error('bake-off: pricingCheckPath is required — every run verifies its pricing table has not expired. Pass the absolute path to check_pricing.py.')
}
if (!PRICING_CHECK.startsWith('/')) {
  throw new Error('bake-off: pricingCheckPath must be absolute — the preflight agent starts in the session root, not this checkout')
}
const codexArms = JUDGE_ONLY ? [] : (IN.arms || []).filter(a => a.kind !== 'reference' && a.kind !== 'claude')
if (codexArms.length && !RUNNER) {
  throw new Error('bake-off: runnerPath (absolute path to run_codex_arm.py) is required when codex arms run')
}
if (RUNNER && !RUNNER.startsWith('/')) {
  throw new Error('bake-off: runnerPath must be absolute — rung agents start in the session root, not this checkout')
}
// The ladder's no-backgrounding guarantee IS this inequality: the runner's
// watchdog must expire with margin inside the rung's Bash-call timeout.
if (codexArms.length && WATCHDOG_S * 1000 > RUNG_TIMEOUT_MS - 60000) {
  throw new Error(`bake-off: watchdogSeconds (${WATCHDOG_S}s) must sit at least 60s inside rungTimeoutMs (${RUNG_TIMEOUT_MS}ms)`)
}
for (const a of codexArms) {
  if (!a.codexModel || !a.effort) throw new Error(`bake-off: codex arm ${a.label} needs codexModel and effort`)
}

// Prompts embed these values inside Bash commands without shell quoting; restrict
// them to shell-inert characters and fail fast, rather than quoting throughout the
// prose. gateCmd is exempt on purpose — it IS a shell command.
const SHELL_INERT = /^[A-Za-z0-9._/-]+$/
const embedded = [['dir', DIR], ['base', BASE], ['contextCheckout', IN.contextCheckout]]
if (TRAP_LEDGER) embedded.push(['trapLedgerPath', TRAP_LEDGER])
if (RUNNER) embedded.push(['runnerPath', RUNNER])
if (BRIEF_PATH) embedded.push(['briefPath', BRIEF_PATH])
embedded.push(['pricingCheckPath', PRICING_CHECK])
for (const a of IN.arms || []) {
  embedded.push([`arm ${a.label} label`, a.label], [`arm ${a.label} worktree`, a.worktree])
  if (a.codexModel) embedded.push([`arm ${a.label} codexModel`, a.codexModel], [`arm ${a.label} effort`, a.effort])
  if (a.runTag) embedded.push([`arm ${a.label} runTag`, a.runTag])
  if (a.reportPath) embedded.push([`arm ${a.label} reportPath`, a.reportPath])
}
for (const l of (JUDGE_ONLY ? IN.labels : [])) embedded.push([`label ${l}`, l])
for (const id of AC_IDS) embedded.push([`acId ${id}`, id])
for (const s of JUDGES) {
  embedded.push([`judge ${s.id} id`, s.id])
  if (s.codexModel) embedded.push([`judge ${s.id} codexModel`, s.codexModel])
  for (const k of SESSIONS) embedded.push([`judge ${s.id} ${k} effort`, effortFor(s, k)])
  if (s.kind === 'openrouter') {
    embedded.push([`judge ${s.id} model`, s.model], [`judge ${s.id} fallback model`, s.fallback.model || s.fallback.codexModel])
    for (const k of SESSIONS) embedded.push([`judge ${s.id} fallback ${k} effort`, effortFor(s.fallback, k)])
  }
}
for (const [name, value] of embedded) {
  if (!SHELL_INERT.test(String(value))) throw new Error(`bake-off: ${name} contains shell-active characters or spaces: ${JSON.stringify(value)}`)
}

const tag = arm => arm.runTag || '1'
const judgedPath = arm => `${DIR}/judged/report-${arm.label}.md`
const reportPath = arm => arm.reportPath || `${DIR}/reports/arm-${arm.label}.md`

// ---------- prompts ----------

function preflightPrompt() {
  return `You are a mechanical preflight checker for a bake-off run. Execute with Bash. Create the run directory and, if a source brief is named below, place the brief; change nothing else anywhere.

1. mkdir -p ${DIR}
${BRIEF_PATH ? `2. cp ${BRIEF_PATH} ${DIR}/brief.md — if this fails, do not retry and do not write the file by any other means; report the failure in notes.
` : '2. No source brief was named: the brief is expected to be in place already. Do not create it.\n'}3. test -s ${DIR}/brief.md && echo BRIEF_PRESENT || echo BRIEF_ABSENT
4. If present: shasum -a 256 ${DIR}/brief.md | cut -d' ' -f1 — and: wc -l < ${DIR}/brief.md
5. Check the pricing table has not expired, as one call: python3 ${PRICING_CHECK}; echo "PRICING_EXIT=$?" — read the verdict ONLY from that exit status (0 clean, 3 expired, 2 unusable), never from the JSON body, and copy the JSON's "message" field verbatim if there is one.

Return the structured result: exists per step 3, sha256 = the bare hash or "", lines = the count or 0, pricing_ok = true only when PRICING_EXIT was exactly 0, pricing_message = the JSON's "message" verbatim or its errors or "" when clean, notes = anything unexpected. Never write, edit, summarize or reconstruct the brief's contents — copying it is the only way it may arrive. Report only observed values; never invent one.`
}

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
  return `Dispatch preamble (run tag ${tag(arm)}): your working root is ${arm.worktree}. Your report path is ${reportPath(arm)}. Your brief is the file ${DIR}/brief.md — read it first with the Read tool, in full, and treat it as the whole of your instructions. Read nothing else under ${DIR}.`
}

// One rung = one runner-script invocation = one codex attempt. The script owns
// the mechanics (dispatch write + self-check guard, pidfile guard, in-code
// watchdog, state capture); the transport agent owns nothing but the call.
function rungCmd(arm, attempt, sessionId) {
  return `python3 ${RUNNER} --dir ${DIR} --worktree ${arm.worktree} --label ${arm.label} --model ${arm.codexModel} --effort ${arm.effort} --base ${BASE} --brief ${DIR}/brief.md --report-path ${reportPath(arm)} --run-tag ${tag(arm)} --attempt ${attempt} --watchdog-seconds ${WATCHDOG_S}${sessionId ? ` --resume-session ${sessionId}` : ''}`
}

function rungPrompt(arm, attempt, sessionId) {
  return `You are a mechanical transport runner (run tag ${tag(arm)}) for one attempt of bake-off arm ${arm.label}. Execute exactly ONE foreground Bash call, with timeout ${RUNG_TIMEOUT_MS}, running exactly this command and nothing else:

${rungCmd(arm, attempt, sessionId)}

The command supervises its own subprocess under an internal watchdog shorter than your timeout, so it always exits on its own — never use run_in_background, never re-run it, and never run any other codex command. Its final stdout line is a single JSON object: return that object as your structured result, every field copied verbatim. If the call printed no JSON line, return the required fields as codex_exit -1, session_id "", report_exists false, worktree_touched false, log_tail = the last lines you saw, and set rung_error to the exit code and what happened. Report only observed values; never invent one.`
}

// When a transport agent dies or returns garbage, the rung's true state is
// still on disk — a probe reconstructs it and the ladder continues.
function probePrompt(arm) {
  return `You are a mechanical state prober (run tag ${tag(arm)}) for bake-off arm ${arm.label}. A transport agent failed to deliver this arm's attempt state; the state lives on disk. Execute with Bash, changing nothing:

1. tail -c 2000 ${DIR}/${arm.label}.exec.log
2. the LAST CODEX_EXIT= value in that log (grep -oE 'CODEX_EXIT=-?[0-9]+' ${DIR}/${arm.label}.exec.log | tail -1)
3. grep -m1 -oE 'session id: [0-9a-f-]+' ${DIR}/${arm.label}.exec.log | cut -d' ' -f3
4. test -s ${reportPath(arm)} && echo REPORT_EXISTS || echo NO_REPORT
5. git -C ${arm.worktree} status --porcelain — and: git -C ${arm.worktree} log --oneline ${BASE}..HEAD
6. P=$(cat ${DIR}/${arm.label}.pid 2>/dev/null); [ -n "$P" ] && kill -0 $P 2>/dev/null && echo PID_ALIVE || echo NO_LIVE_PID

Return the structured result: codex_exit = the last CODEX_EXIT value, or -1 if none; watchdog_fired false; session_id = the bare uuid or ""; report_exists per step 4; worktree_touched = true if step 5 printed anything at all; tokens_used 0; wall_seconds -1; total_wall_seconds -1; log_tail = the step-1 tail; probe true; pid_alive per step 6. Report only observed values; never guess.`
}

function auditPrompt(arm) {
  return `You are a mechanical auditor (run tag ${tag(arm)}) for the git worktree ${arm.worktree} (base commit ${BASE}). Execute these steps with Bash; change no file contents; never push; never touch any other directory.

1. Run: git -C ${arm.worktree} status --porcelain — and read every line.
2. If it lists uncommitted paths: stage ONLY by explicit path — one git -C ${arm.worktree} add <path> per listed path — EXCLUDING any path at the tree root whose name contains REPORT or NOTES (leave those unstaged). Then: git -C ${arm.worktree} commit -m "arm output (audit-committed)". Record that the audit committed. If the tree is clean, record that the arm committed its own work.
3. Run: git -C ${arm.worktree} log --oneline ${BASE}..HEAD — capture it.
4. Run: mkdir -p ${DIR}/diffs && git -C ${arm.worktree} diff ${BASE} HEAD > ${DIR}/diffs/${arm.label}.diff
5. Count changed files: git -C ${arm.worktree} diff --name-only ${BASE} HEAD | wc -l
${MEASURE_CODE ? `5b. Mechanical size and complexity measures:
   - LOC: git -C ${arm.worktree} diff --numstat ${BASE} HEAD — sum column 1 as loc_added and column 2 as loc_removed across all rows.
   - Complexity: for each changed .py file (from step 5's list), run: uvx radon cc -s -a ${arm.worktree}/<file> — record the average-complexity line and the single highest-ranked block per file into complexity_summary (one line per file, e.g. "fold.py: avg A (3.2), worst C (12) _h_pr_closed"). If radon fails or no .py files changed, set complexity_summary to exactly what you observed (e.g. "radon unavailable: <error>" or "no .py changes").
` : ''}6. Gate, exactly this compound command with a 600000ms timeout, run as one Bash call:
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

const BLIND = `You do not know, and must not try to infer or state, who or what produced any arm. Redaction markers like "[environment detail removed for blind judging]" are the harness's blinding edits, not the arm's writing — draw no inference from their presence, placement, or any incoherence they introduce. Read nothing under ${DIR} beyond the files named here — other files there would unblind the comparison. For surrounding-code context read the repository checkout at ${IN.contextCheckout} (it sits at the same base commit); change nothing anywhere.`

// Session 1 of a seat's work on one arm: is the document true? Every criterion
// audited and the factual-grounding axis scored, against the tree. One arm per
// session is the point — a seat holding the whole field samples the audit and the
// schema cannot tell; a seat holding one arm returns the rows or is refused.
function auditPrompt_(seat, label, gateLine, runTags) {
  return `You are a blind judge (seat ${seat.id}, run tag ${runTags}) auditing ONE arm, ${label}, of a multi-arm comparison. Other arms exist; you will not see them and must not speculate about them. ${BLIND}

The task brief this arm received is at ${DIR}/brief.md — read it first, in full. Then read ${DIR}/diffs/${label}.diff and ${DIR}/judged/report-${label}.md.

The rubric (read it and follow it exactly; this session does Phase 0, Phase 1, and axis 1 of Phase 2 only):

${IN.rubricText}

Harness rules that apply regardless of the rubric text:
- Gate result, already measured mechanically (do not re-run anything): ${gateLine}
- An EMPTY diff is no-contest; a non-zero gate exit is disqualified. Either way set standing accordingly, give the reason, return an empty ac_audit and factual_grounding 0, and stop.
- Otherwise standing is "scored" and you audit EVERY one of these criteria, by id, in this order, one row each, no omissions and no extras: ${AC_IDS.join(', ')}. A row is {ac, class, verdict, evidence}; evidence quotes the document, report, or code line the verdict rests on, and for an unmet justification-class criterion states what the truth is.
- Verify the load-bearing claims yourself against the checkout before ruling — that is this session's whole job. Record every claim you found false in false_claims as {claim, truth, load_bearing}; an empty list means you checked and found none, not that you did not check.
- Score factual_grounding 0-5 per the rubric, applying its cap rule from your own false_claims.

Return the structured result; put the per-criterion reasoning in the rows, not in notes.`
}

// Session 2: is the document good? Axes 2-5, fed the audit ledger so axis 4 carries
// the verdicts across instead of re-verifying.
function scorePrompt(seat, label, audit, runTags) {
  const ledger = audit.false_claims && audit.false_claims.length
    ? audit.false_claims.map(c => `- ${c.load_bearing ? 'LOAD-BEARING: ' : ''}${c.claim} — truth: ${c.truth}`).join('\n')
    : '- none found'
  const unmet = audit.ac_audit.filter(r => r.verdict === 'unmet' || r.verdict === 'unpinned' || r.verdict === 'partially-pinned').map(r => `- ${r.ac} ${r.verdict}: ${r.evidence}`).join('\n') || '- none'
  return `You are a blind judge (seat ${seat.id}, run tag ${runTags}) scoring ONE arm, ${label}, of a multi-arm comparison. Other arms exist; you will not see them and must not speculate about them. ${BLIND}

The task brief this arm received is at ${DIR}/brief.md — read it first, in full. Then read ${DIR}/diffs/${label}.diff and ${DIR}/judged/report-${label}.md.

The rubric (read it and follow it exactly; this session scores axes 2, 3, 4 and 5 of Phase 2 only — axis 1 and the criterion audit are already done and their results are below):

${IN.rubricText}

Results of this arm's audit session (treat as settled; do not re-verify, and do not score the same finding twice):
Factual grounding: ${audit.factual_grounding}/5.
Claims found false:
${ledger}
Criteria not met or not pinned:
${unmet}

Score ${AXES.slice(1).join(', ')} as integers 0-5 per the rubric bands, each arm-independently — you are scoring this document against the bands, not against other arms. Return the structured result with the reasoning per axis in rationale.`
}

// Session 3, once per seat: which ships? The seat's own complete table plus a whole
// re-read of its leading documents.
function rankPrompt(seat, rows, runTags) {
  const table = rows.map(r => `Arm ${r.label}: standing ${r.standing}${r.standing !== 'scored' ? ` (${r.reason})` : ''}; ${AXES.map(k => `${k}=${r.scores ? r.scores[k] : '-'}`).join(', ')}; criteria met ${r.met}/${AC_IDS.length}; false claims ${r.false_claims}${r.load_bearing ? ' (load-bearing)' : ''}\n  audit: ${r.audit_rationale}\n  scoring: ${r.score_rationale}`).join('\n')
  const top = rows.filter(r => r.standing === 'scored').sort((a, b) => b.total - a.total).slice(0, RANK_READS).map(r => r.label)
  return `You are a blind judge (seat ${seat.id}, run tag ${runTags}) ranking a ${rows.length}-arm comparison. ${BLIND}

Every arm was audited and scored by this seat, one arm per session, against the rubric below. The rubric's Phase 3 is yours now; Phases 0-2 are done and their results are the table.

${IN.rubricText}

The seat's table:
${table}

Read ${DIR}/brief.md, then the documents of the leading arms in full — ${top.map(l => `${DIR}/diffs/${l}.diff and ${DIR}/judged/report-${l}.md`).join('; ')} — and any other arm's documents you need to settle a close call. Scores are this seat's own, produced without cross-arm comparison, so two arms at the same total may not be equivalent: the rubric's tie conditions govern. Return preference (exactly one arm label, or "tie" only under the rubric's tie conditions), ordering (every scored arm, best first), rationale citing the audit results, and notes.`
}

// The quarantined checker, per arm: it alone reads the trap ledger.
function checkerPrompt(label, runTags) {
  return `You are the trap-ledger checker (run tag ${runTags}) for ONE arm, ${label}, of a blind multi-arm comparison. Facts only — never score quality, never state a preference, never infer who produced any arm.

Read ${TRAP_LEDGER}, then ${DIR}/judged/report-${label}.md and ${DIR}/diffs/${label}.diff. Read nothing else under ${DIR}. You may consult the repository checkout at ${IN.contextCheckout} read-only to confirm a ledger fact; change nothing.

For each ledger probe: quote the exact report sentence(s) bearing on it (or write "silent"), and rule caught (the arm correctly states the fact), repeated (the arm asserts the false version), silent (no claim either way), or n/a. Every finding carries arm "${label}". Markers reading "[environment detail removed for blind judging]" are the harness's edits — draw no inference from them. Return the structured result.`
}

// A codex seat's session runs through codex exec under a haiku transport agent.
// The JSON shape is spelled out because codex returns prose unless told not to.
function codexSessionPrompt(seat, effort, fileTag, promptText, shapeText) {
  return `You are a mechanical harness runner for judge seat ${seat.id}, session ${fileTag}. Execute with Bash; do not improvise and do not judge anything yourself.

Step 1 — write the session prompt to ${DIR}/seat-${fileTag}.prompt.md using a quoted heredoc so nothing expands, then append this exact final instruction to the file: "Respond with ONLY a JSON object, no prose, shaped as ${shapeText.replace(/"/g, '\\"')}." The session prompt content is everything between BEGIN-PROMPT and END-PROMPT below.

Step 2 — run as ONE FOREGROUND Bash call with timeout 600000:
codex exec -C ${IN.contextCheckout} -m ${seat.codexModel} -c model_reasoning_effort=${effort} -s read-only --add-dir ${DIR} -o ${DIR}/seat-${fileTag}.out.md - < ${DIR}/seat-${fileTag}.prompt.md > ${DIR}/seat-${fileTag}.exec.log 2>&1; echo "CODEX_EXIT=$?" >> ${DIR}/seat-${fileTag}.exec.log

Step 2b — if the harness reports the command was moved to the background on timeout, WAIT for its completion notification; never start another codex process for this session while one may be running. Only after it has fully ended, if ${DIR}/seat-${fileTag}.out.md does NOT exist, extract the session UUID with: grep -m1 -oE 'session id: [0-9a-f-]+' ${DIR}/seat-${fileTag}.exec.log | cut -d' ' -f3 — and run as ONE FOREGROUND Bash call with timeout 600000: codex exec resume <that-uuid> -o ${DIR}/seat-${fileTag}.out.md - <<< "Continue where you left off and finish; your final message must be ONLY the JSON object exactly as specified." >> ${DIR}/seat-${fileTag}.exec.log 2>&1; echo "CODEX_EXIT=$?" >> ${DIR}/seat-${fileTag}.exec.log — at most 3 resumes, same session id.

Step 3 — read ${DIR}/seat-${fileTag}.out.md, extract the JSON object, and return it as the structured result with seat_exit set to the recorded CODEX_EXIT. If a key differs only in wording from the pinned keys, rename it and record the rename in notes — never alter a value. If the output is missing or not parseable JSON, return seat_exit -1 with the required fields empty and the raw tail in notes. Report only observed values.

BEGIN-PROMPT
${promptText}
END-PROMPT`
}

// An openrouter seat's session runs the launcher under a haiku transport agent:
// read-only tools, rooted at the context checkout, prompt on stdin, result as JSON.
function openrouterSessionPrompt(seat, effort, fileTag, promptText, shapeText) {
  return `You are a mechanical harness runner for judge seat ${seat.id}, session ${fileTag}. Execute with Bash; do not improvise and do not judge anything yourself.

Step 1 — write the session prompt to ${DIR}/seat-${fileTag}.prompt.md using a quoted heredoc so nothing expands, then append this exact final instruction to the file: "Respond with ONLY a JSON object, no prose, shaped as ${shapeText.replace(/"/g, '\\"')}." The session prompt content is everything between BEGIN-PROMPT and END-PROMPT below.

Step 2 — run as ONE FOREGROUND Bash call with timeout 1200000:
cd ${IN.contextCheckout} && node ${OR_LAUNCHER} --model ${seat.model} --effort ${effort} --permission-mode dontAsk --allowedTools Read Grep Glob "Bash(git status*)" "Bash(git diff *)" "Bash(git log *)" "Bash(git show *)" --add-dir ${DIR} --output-format json -p < ${DIR}/seat-${fileTag}.prompt.md > ${DIR}/seat-${fileTag}.out.json 2> ${DIR}/seat-${fileTag}.exec.log; echo "LAUNCH_EXIT=$?" >> ${DIR}/seat-${fileTag}.exec.log

Step 3 — if LAUNCH_EXIT is 78 the launcher refused to start (no key, or a refused model): return seat_exit 78 with the required fields empty and the exec log's last lines in notes. Otherwise read ${DIR}/seat-${fileTag}.out.json, take its "result" string, extract the JSON object from it, and return that object as the structured result with seat_exit set to LAUNCH_EXIT. If a key differs only in wording from the pinned keys, rename it and record the rename in notes — never alter a value. If the output is missing or holds no parseable JSON object, return seat_exit -1 with the required fields empty and the raw tail in notes. Report only observed values.

BEGIN-PROMPT
${promptText}
END-PROMPT`
}

// ---------- schemas ----------

function usagePrompt() {
  const armArgs = IN.arms.filter(a => a.kind !== 'reference')
    .map(a => `--arm ${a.label},${a.kind},${a.worktree}${a.codexModel ? `,${a.codexModel}` : ''}`).join(' ')
  return `You are a mechanical usage collector for a bake-off run. Execute with Bash exactly one command and change nothing: python3 ${USAGE_COLLECTOR} --dir ${DIR} ${armArgs} > ${DIR}/usage.json; echo "USAGE_EXIT=$?" — then cat ${DIR}/usage.json. Return the structured result: ok = (USAGE_EXIT was 0); report = the file's JSON text verbatim (the empty string if the command failed); notes = stderr or anything unexpected. Do not summarize, price, or compare anything yourself.`
}

const USAGE_SCHEMA = {
  type: 'object',
  properties: { ok: { type: 'boolean' }, report: { type: 'string' }, notes: { type: 'string' } },
  required: ['ok', 'report', 'notes'],
}

const PREFLIGHT_SCHEMA = {
  type: 'object',
  properties: {
    exists: { type: 'boolean' },
    sha256: { type: 'string' },
    lines: { type: 'integer' },
    pricing_ok: { type: 'boolean' },
    pricing_message: { type: 'string' },
    notes: { type: 'string' },
  },
  required: ['exists', 'sha256', 'lines', 'pricing_ok', 'pricing_message', 'notes'],
}

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

// State of one codex attempt, as the runner script prints it (a probe returns
// the same shape reconstructed from disk). rung_error marks transport failure.
const RUNG_SCHEMA = {
  type: 'object',
  properties: {
    label: { type: 'string' },
    attempt: { type: 'integer' },
    kind: { type: 'string' },
    codex_exit: { type: 'integer' },
    watchdog_fired: { type: 'boolean' },
    session_id: { type: 'string' },
    report_exists: { type: 'boolean' },
    report_copied: { type: 'boolean' },
    worktree_touched: { type: 'boolean' },
    wall_seconds: { type: 'integer' },
    total_wall_seconds: { type: 'integer' },
    log_tail: { type: 'string' },
    probe: { type: 'boolean' },
    pid_alive: { type: 'boolean' },
    rung_error: { type: 'string' },
    guard_exit: { type: 'integer' },
  },
  required: ['codex_exit', 'session_id', 'report_exists', 'worktree_touched', 'log_tail'],
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
  required: MEASURE_CODE
    ? ['uncommitted_found', 'committed_by_audit', 'commits', 'gate_exit', 'files_changed', 'loc_added', 'loc_removed', 'complexity_summary', 'notes']
    : ['uncommitted_found', 'committed_by_audit', 'commits', 'gate_exit', 'files_changed', 'notes'],
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
const AC_ROW = {
  type: 'object',
  properties: {
    ac: { type: 'string', enum: AC_IDS },
    class: { type: 'string', enum: ['test-expressible', 'justification'] },
    verdict: { type: 'string', enum: ['pinned', 'partially-pinned', 'unpinned', 'met', 'unmet'] },
    evidence: { type: 'string' },
  },
  required: ['ac', 'class', 'verdict', 'evidence'],
}
const AUDIT_SESSION_SCHEMA = {
  type: 'object',
  properties: {
    standing: { type: 'string', enum: ['scored', 'no-contest', 'disqualified'] },
    reason: { type: 'string' },
    ac_audit: { type: 'array', items: AC_ROW },
    false_claims: {
      type: 'array',
      items: {
        type: 'object',
        properties: { claim: { type: 'string' }, truth: { type: 'string' }, load_bearing: { type: 'boolean' } },
        required: ['claim', 'truth', 'load_bearing'],
      },
    },
    factual_grounding: { type: 'integer', minimum: 0, maximum: 5 },
    rationale: { type: 'string' },
    notes: { type: 'string' },
    seat_exit: { type: 'integer' },
  },
  required: ['standing', 'reason', 'ac_audit', 'false_claims', 'factual_grounding', 'rationale', 'notes'],
}
const SCORE_SESSION_SCHEMA = {
  type: 'object',
  properties: {
    ...Object.fromEntries(AXES.slice(1).map(k => [k, { type: 'integer', minimum: 0, maximum: 5 }])),
    rationale: { type: 'string' },
    notes: { type: 'string' },
    seat_exit: { type: 'integer' },
  },
  required: [...AXES.slice(1), 'rationale', 'notes'],
}
const rankSchema = labels => ({
  type: 'object',
  properties: {
    preference: { type: 'string', enum: [...labels, 'tie'] },
    ordering: { type: 'array', items: { type: 'string', enum: labels } },
    rationale: { type: 'string' },
    notes: { type: 'string' },
    seat_exit: { type: 'integer' },
  },
  required: ['preference', 'ordering', 'rationale', 'notes'],
})

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

// ---------- codex-arm ladder ----------

// The recovery ladder, in deterministic JS. Each iteration spawns one rung
// (one runner-script attempt); the decisions — done, resume, one fresh retry
// on a launch-level failure with a provably untouched worktree, or stop —
// happen here from the rung's state JSON. A dead transport agent costs a disk
// probe, not the arm. The full history is returned for observability and is
// deliberately kept out of gateSummary and every judge prompt: a retry count
// is both a bias vector and an unblinding hint.
async function runCodexLadder(arm) {
  const history = []
  let sessionId = ''
  let freshRetryUsed = false
  let outcome = 'attempts_exhausted'
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    const kind = sessionId ? 'resume' : (attempt === 1 ? 'initial' : 'retry')
    let state = await agent(rungPrompt(arm, attempt, sessionId), { label: `arm:${arm.label}:a${attempt}`, phase: 'Arms', model: 'haiku', effort: 'low', schema: RUNG_SCHEMA })
    // A guard exit is a deliberate stop the script already explained — probe
    // only when the transport itself failed to deliver a rung state.
    if (!state || (state.rung_error && !state.guard_exit)) {
      log(`ARM ${arm.label}: attempt ${attempt} transport ${state ? `error (${state.rung_error})` : 'lost'} — probing disk state`)
      state = await agent(probePrompt(arm), { label: `probe:${arm.label}:a${attempt}`, phase: 'Arms', model: 'haiku', effort: 'low', schema: RUNG_SCHEMA })
    }
    if (!state) { outcome = 'state_unrecoverable'; history.push({ attempt, kind, outcome }); break }
    // The runner's guard codes are all nonzero; the transport agent fills the
    // optional field with 0 on an ordinary rung, and that is not a guard stop.
    if (state.guard_exit) {
      log(`ARM ${arm.label}: runner guard stop (exit ${state.guard_exit}): ${state.rung_error}`)
      outcome = `guard_stop_${state.guard_exit}`
      history.push({ attempt, kind, guard_exit: state.guard_exit, outcome })
      break
    }
    history.push({ attempt, kind, codex_exit: state.codex_exit, watchdog_fired: !!state.watchdog_fired, wall_seconds: state.wall_seconds, report_exists: !!state.report_exists, probed: !!state.probe })
    sessionId = state.session_id || sessionId
    if (state.pid_alive) {
      log(`ARM ${arm.label}: a codex process for this arm is still alive after transport loss — stopping rather than racing it`)
      outcome = 'live_process_orphaned'
      break
    }
    if (state.codex_exit === 0 && state.report_exists) { outcome = 'completed'; break }
    if (sessionId) {
      log(`ARM ${arm.label}: attempt ${attempt} incomplete (exit ${state.codex_exit}${state.watchdog_fired ? ', watchdog' : ''}) — resuming session`)
      continue
    }
    if (!state.worktree_touched && !freshRetryUsed) {
      freshRetryUsed = true
      log(`ARM ${arm.label}: launch-level failure with untouched worktree — one fresh retry`)
      continue
    }
    log(`ARM ${arm.label}: attempt ${attempt} failed with no session to resume and ${state.worktree_touched ? 'a touched worktree' : 'the retry spent'} — stopping`)
    outcome = 'unrecoverable_failure'
    break
  }
  const resumed = history.filter(h => h.kind === 'resume').length
  if (outcome !== 'completed' || history.length > 1) log(`ARM ${arm.label}: ladder ${outcome} after ${history.length} attempt(s), ${resumed} resume(s)`)
  return { ladder: { outcome, attempts: history.length, resumed, history } }
}

// ---------- pipeline ----------

// Every codex arm is handed ${DIR}/brief.md on its command line, and every judge,
// checker and reconciler seat reads it for the criteria. Absent, a codex arm dies
// before it starts and a seat scores against criteria it never saw — a whole matrix
// spent on a missing file. This runs first, in judge-only mode too, and halts.
phase('Preflight')
const preflight = await agent(preflightPrompt(), { label: 'preflight:brief', phase: 'Preflight', model: 'haiku', effort: 'low', schema: PREFLIGHT_SCHEMA })
if (!preflight || !preflight.exists) {
  throw new Error(`bake-off: ${DIR}/brief.md is absent or empty — every codex arm reads the brief from that path and every seat reads it for the criteria. ${BRIEF_PATH ? `Copying it from ${BRIEF_PATH} did not produce it: ${preflight ? preflight.notes : 'the preflight agent returned nothing'}` : 'Pass briefPath so the run places it.'}`)
}
log(`Brief in place: ${DIR}/brief.md, ${preflight.lines} lines, sha256 ${preflight.sha256}`)
if (!preflight.pricing_ok) {
  throw new Error(`bake-off: the pricing table has an expired price and this run will not start. ${preflight.pricing_message || 'The preflight check reported no detail; run check_pricing.py by hand.'} A human must re-verify the affected rates against the vendor and update the table — there is no override.`)
}


// Per arm: (reset →) contestant → audit → sanitize, no cross-arm barrier until judging.
let arms = []
let usage = null
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
      : runCodexLadder(arm).then(r => ({ resetResult, contestant: r })),
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
const ladderSummary = arms.filter(a => a.contestant && a.contestant.ladder)
  .map(a => `${a.arm}=${a.contestant.ladder.outcome}:${a.contestant.ladder.attempts}att/${a.contestant.ladder.resumed}res`)
if (ladderSummary.length) log(`Codex ladders (outcome:attempts/resumes): ${ladderSummary.join(', ')}`)

// Collected once every arm has finished writing its transcript. Kept out of
// gateSummary and every seat prompt on purpose — see USAGE_COLLECTOR.
phase('Usage')
const usageRaw = await agent(usagePrompt(), { label: 'usage:collect', phase: 'Usage', model: 'haiku', effort: 'low', schema: USAGE_SCHEMA })
try {
  usage = usageRaw && usageRaw.ok ? JSON.parse(usageRaw.report) : { error: usageRaw ? usageRaw.notes : 'collector agent lost' }
} catch (e) {
  usage = { error: `collector output is not JSON: ${e.message}`, raw: usageRaw.report }
}
if (usage.arms) log(`Usage (wall s / USD): ${usage.arms.map(u => `${u.label}=${u.error ? 'ERR' : `${u.wall_seconds}s/$${u.cost && u.cost.usd != null ? u.cost.usd : '?'}`}`).join(', ')}`)
else log(`Usage collection failed: ${usage.error}`)
if (ARMS_ONLY) {
  log(`Arms-only: ending after Sanitize — no seat was spawned; judge these arms later with judgeOnly`)
  return { task: IN.task || null, base: BASE, arms_only: true, arms, usage }
}
} else {
  log(`Judge-only: judging retained artifacts in ${DIR} — ${IN.labels.length} arm(s), ${CACHED_SEATS.length} cached seat(s)${CACHED_CHECKER ? ', cached checker' : ''}`)
}

// Barrier: every seat's rank session needs all of that seat's arms.
phase('Judge')
const labels = JUDGE_ONLY ? IN.labels : arms.map(a => a.arm)
const runTags = JUDGE_ONLY ? (IN.runTags || 'judge-only') : IN.arms.map(a => `${a.label}${tag(a)}`).join('/')
const gateSummary = JUDGE_ONLY ? IN.gateSummary : arms.map(a =>
  `Arm ${a.arm}: gate exit ${a.audit ? a.audit.gate_exit : 'unknown'}, ${a.audit ? a.audit.files_changed : '?'} files changed${MEASURE_CODE ? ` (+${a.audit ? a.audit.loc_added : '?'}/-${a.audit ? a.audit.loc_removed : '?'} LOC), complexity: ${a.audit ? a.audit.complexity_summary : 'unknown'}` : ''}, committed by ${a.audit && a.audit.committed_by_audit ? 'the audit (arm left work uncommitted)' : 'the arm itself'}${a.kind === 'reference' ? ' [commit pre-existed this run; "committed by the arm" reflects the audit finding a clean tree, not authorship during this dispatch]' : ''}`
).join('\n')
const gateLines = Object.fromEntries(gateSummary.split('\n').map(line => [(line.match(/^Arm (\S+):/) || [])[1], line]).filter(([l]) => l))

// Every audit row must be present exactly once. A short or padded audit is refused
// here, in code, and the session re-run once; a second failure fails the seat-arm.
function auditComplete(a) {
  if (!a) return false
  if (a.standing !== 'scored') return true
  const seen = a.ac_audit.map(r => r.ac)
  return seen.length === AC_IDS.length && AC_IDS.every(id => seen.filter(x => x === id).length === 1)
}

const auditShape = `{"standing": "scored"|"no-contest"|"disqualified", "reason": string, "ac_audit": [{"ac": ${AC_IDS.map(i => `"${i}"`).join('|')}, "class": "test-expressible"|"justification", "verdict": "pinned"|"partially-pinned"|"unpinned"|"met"|"unmet", "evidence": string}, ... one per criterion], "false_claims": [{"claim": string, "truth": string, "load_bearing": bool}], "factual_grounding": int 0-5, "rationale": string, "notes": string}`
const scoreShape = `{${AXES.slice(1).map(k => `"${k}": int 0-5`).join(', ')}, "rationale": string, "notes": string}`
const rankShape = `{"preference": ${labels.map(l => `"${l}"`).join('|')}|"tie", "ordering": [labels best first], "rationale": string, "notes": string}`

const persist = (seat, file) => `\n\nDelivery hardening (seat ${seat.id}): FIRST write your complete result as a single JSON object to ${DIR}/audits/${file} with the Write tool (mkdir -p ${DIR}/audits first if needed) — the same object you will return. THEN return exactly that object as your structured result.`

function transportSession(seat, session, fileTag, promptText, shapeText, schema, opts) {
  const effort = effortFor(seat, session)
  if (seat.kind === 'codex') return agent(codexSessionPrompt(seat, effort, fileTag, promptText, shapeText), { ...opts, model: 'haiku', effort: 'low', schema })
  if (seat.kind === 'openrouter') return agent(openrouterSessionPrompt(seat, effort, fileTag, promptText, shapeText), { ...opts, model: 'haiku', effort: 'low', schema })
  return agent(promptText + persist(seat, `seat-${fileTag}.json`), { ...opts, model: seat.model, effort, schema })
}

// `st` is the seat's runtime state: the declared seat plus `active`, the seat its
// sessions currently run on. An openrouter seat falls back seat-wide — every later
// session, and this one re-run — when the launcher refuses or two sessions return
// nothing parseable; sessions already in flight on the old transport re-run on the
// new one when they come back. The seat id stays; `ran` records what produced it.
async function runSession(st, fileTag, promptText, shapeText, schema, phaseName) {
  const opts = { label: `${phaseName}:${st.id}:${fileTag.split('-').pop()}`, phase: 'Judge' }
  const ran = st.active
  const r = await transportSession(ran, phaseName, fileTag, promptText, shapeText, schema, opts)
  if (ran.kind !== 'openrouter') return r
  const refused = !!r && r.seat_exit === 78
  const unparsed = !r || r.seat_exit === -1
  if (unparsed) st.no_parse++
  if (st.active === ran && (refused || st.no_parse >= 2)) {
    st.fell_back = refused ? 'launcher refused (exit 78)' : 'no parseable result twice'
    st.active = { ...ran.fallback, id: st.id }
    log(`Seat ${st.id}: ${st.fell_back} — falling back seat-wide to ${st.active.kind}/${st.active.model || st.active.codexModel}`)
  }
  if (st.active !== ran && (refused || unparsed)) return runSession(st, fileTag.replace(/^([^-]+)-/, '$1-fb-'), promptText, shapeText, schema, phaseName)
  return r
}

async function auditArm(seat, label) {
  let a = await runSession(seat, `${seat.id}-audit-${label}`, auditPrompt_(seat, label, gateLines[label] || 'unknown', runTags), auditShape, AUDIT_SESSION_SCHEMA, 'audit')
  if (!auditComplete(a)) {
    log(`Seat ${seat.id} arm ${label}: audit incomplete (${a ? a.ac_audit.length : 'no'} rows of ${AC_IDS.length}) — re-running once`)
    a = await runSession(seat, `${seat.id}-audit2-${label}`, auditPrompt_(seat, label, gateLines[label] || 'unknown', runTags) + `\n\nA previous attempt returned ${a ? a.ac_audit.length : 'no'} rows; this comparison requires exactly one row per criterion listed above.`, auditShape, AUDIT_SESSION_SCHEMA, 'audit')
  }
  if (!auditComplete(a)) { log(`Seat ${seat.id} arm ${label}: audit incomplete twice — this seat-arm is dropped`); return null }
  return a
}

// Seat work: for each seat, every arm through audit → score (pipeline, no barrier
// between arms), then one rank session over the seat's own complete table.
async function runSeat(seat) {
  const st = { ...seat, active: seat, no_parse: 0, fell_back: null }
  const ranOf = () => ({ kind: st.active.kind, model: st.active.model || st.active.codexModel || null, effort: Object.fromEntries(SESSIONS.map(k => [k, effortFor(st.active, k)])), fell_back: st.fell_back })
  const rows = (await pipeline(
    labels,
    label => auditArm(st, label),
    async (audit, label) => {
      if (!audit) return null
      if (audit.standing !== 'scored') return { label, audit, score: null }
      const score = await runSession(st, `${seat.id}-score-${label}`, scorePrompt(seat, label, audit, runTags), scoreShape, SCORE_SESSION_SCHEMA, 'score')
      return { label, audit, score }
    },
  )).filter(Boolean)
  const table = rows.map(r => {
    const scores = r.score ? { [AXES[0]]: r.audit.factual_grounding, ...Object.fromEntries(AXES.slice(1).map(k => [k, r.score[k]])) } : null
    return {
      label: r.label, standing: r.audit.standing, reason: r.audit.reason, scores,
      total: scores ? Object.values(scores).reduce((x, y) => x + y, 0) : -1,
      met: r.audit.ac_audit.filter(x => x.verdict === 'met' || x.verdict === 'pinned').length,
      false_claims: r.audit.false_claims.length, load_bearing: r.audit.false_claims.some(c => c.load_bearing),
      audit_rationale: r.audit.rationale, score_rationale: r.score ? r.score.rationale : '',
    }
  })
  const scoredLabels = table.filter(r => r.standing === 'scored').map(r => r.label)
  const rank = scoredLabels.length
    ? await runSession(st, `${seat.id}-rank`, rankPrompt(seat, table, runTags), rankShape, rankSchema(scoredLabels), 'rank')
    : { preference: 'tie', ordering: [], rationale: 'no scorable arm', notes: '' }
  if (!rank) { log(`Seat ${seat.id}: rank session returned nothing — seat dropped`); return { seat: seat.id, kind: seat.kind, ran: ranOf(), verdict: null } }
  // Assemble the seat's verdict in the panel shape aggregation, reconcile and
  // escalation already consume.
  const verdict = {
    scores: Object.fromEntries(table.filter(r => r.scores).map(r => [r.label, r.scores])),
    ac_audit: rows.flatMap(r => r.audit.ac_audit.map(x => ({ ...x, arm: r.label }))),
    false_claims: Object.fromEntries(rows.map(r => [r.label, r.audit.false_claims])),
    preference: rank.preference,
    ordering: rank.ordering,
    rationale: rank.rationale,
    disqualified: table.filter(r => r.standing !== 'scored').map(r => `${r.label}: ${r.standing} — ${r.reason}`),
    notes: [rank.notes, ...rows.map(r => r.audit.notes ? `${r.label} audit: ${r.audit.notes}` : ''), ...rows.map(r => r.score && r.score.notes ? `${r.label} score: ${r.score.notes}` : '')].filter(Boolean).join('\n'),
    arms_dropped: labels.filter(l => !rows.some(r => r.label === l)),
  }
  return { seat: seat.id, kind: seat.kind, ran: ranOf(), verdict }
}

const seatThunks = JUDGES.map(seat => () => runSeat(seat))
// The checker seat is quarantined: it alone reads the trap ledger, and its output
// never enters a main judge's context. A cached checker result suppresses a re-run.
if (TRAP_LEDGER && !CACHED_CHECKER) seatThunks.push(() =>
  parallel(labels.map(label => () =>
    agent(checkerPrompt(label, runTags), { label: `checker:${label}`, phase: 'Judge', model: 'haiku', effort: 'low', schema: CHECKER_SCHEMA })))
    .then(parts => ({ checkerResult: {
      findings: parts.filter(Boolean).flatMap(p => p.findings),
      notes: parts.map((p, i) => p ? p.notes : `arm ${labels[i]}: checker returned nothing`).filter(Boolean).join('\n'),
    } })))
const seatResults = (await parallel(seatThunks)).filter(Boolean)
// A seat whose sessions died resolves with verdict: null — drop it from the panel
// and report it, rather than letting a null verdict poison later stages.
// Cached seat verdicts join the panel unchanged and count in every later stage.
const judges = [...seatResults.filter(r => !r.checkerResult && r.verdict), ...CACHED_SEATS.filter(s => s && s.verdict)]
const judges_failed = seatResults.filter(r => !r.checkerResult && !r.verdict).map(r => r.seat)
if (judges_failed.length) log(`Seat(s) returned no verdict: ${judges_failed.join(', ')} — panel proceeds with ${judges.length} seat(s)`)
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
  usage,
}
