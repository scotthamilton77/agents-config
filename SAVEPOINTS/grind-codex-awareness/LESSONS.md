# Grind lessons — codex awareness fixes (2026-07-19)

Running ledger. To be triaged into discovered work at shutdown. Nothing here is filed yet
unless a bead ID is named.

## From Scott

### L1 — ROOT stopped updating the bookkeeper; Scott had to ask why the dashboard was static
The dashboard was accurate; ROOT simply wasn't sending deltas. ROOT collected several lane
reports (bead started, TDD green, reviewer dispatched) and relayed none of them, so the
human's only view of the run went stale while work was actively progressing. Scott noticed
before ROOT did, which is exactly backwards — the dashboard exists so he doesn't have to ask.

Root cause: the skill tells ROOT to send `UPDATE:` / `ATTENTION:` deltas but never binds
that to a trigger. There is no rule saying *when*. ROOT treated it as an ambient duty and
it silently dropped under load while ROOT chased the gate defect.

Candidate fix: make the bookkeeper update a required leg of the same reflex that already
handles lane reports — i.e. "every time you relay to a lane, you also update the
bookkeeper." Bind it to an event, not to good intentions. Possibly: any state change worth
a lane message is by definition worth a dashboard delta.

### L2 — The grind should negotiate approval permission UP FRONT when in auto mode
ROOT built two PRs all the way through implementation, HEAVY gate, Codex review, thread
resolution, and the full merge floor before discovering the auto-mode classifier would deny
`approve_pr.py`. Both lanes then parked with nothing to do, the whole grind stalled, and
Scott had to be interrupted for a permission that was foreseeable at minute one.

The cost is asymmetric and entirely avoidable: asking at setup costs one question in a
message ROOT is already sending (the partition/roster confirmation). Discovering it at the
merge boundary costs a full stall of every lane plus an unplanned human interrupt.

Candidate fix: the grind skill's setup sequence (currently: partition -> propose roster ->
spawn bookkeeper -> spawn lanes) should include a pre-flight authorization check. When the
repo's resolved merge policy carries an `approver` (or any merge path needs a privileged
command), ROOT asks for that permission IN THE SAME MESSAGE as the partition confirmation,
naming the exact script. Generalizes beyond approvals: any command the run will certainly
need and the harness may deny should be surfaced before agents are spawned, not when the
first PR is ready to land.

## Found by ROOT during the run

### L3 — `agents_empty_result` is not self-interpreting, and a false clean is invisible
Filed as **`agents-config-wgclw.31`** (P0) and **`agents-config-wgclw.32`** (P0).
Two independent false-clean mechanisms in the HEAVY gate. Beyond the specific bugs, the
meta-lesson: the gate's returned payload looked IDENTICAL on a hollow run and a genuine one
(`exit=acceptance, clean-at-floor, openAtFloor=0`, and even the same "3 of 4 agents empty"
usage line). Distinguishing them required dispatching a subagent to read
`journal.jsonl`/`agent-*.jsonl` for evidence of actual diff engagement.

Standing practice ROOT adopted mid-run and which belongs in the skill: after every HEAVY
gate, audit the journal via an ad-hoc ephemeral subagent — confirm finders obtained a
non-empty diff at the intended `repo_root` and cited real code, and independently re-check
any finding the refuters eliminated. Two of three gate runs this session were defective.

### L4 — "Reviewed-clean" from a lane is not a mergeability claim
Filed as **`agents-config-abn9.44.10`** (P1). A lane passed its review skill's own terminal
Phase 9 check cleanly and reported reviewed-clean; the merge floor then returned EXIT 1 on
the identical thread. The two gates disagree on when a SKIP thread is "settled."

Standing rule ROOT issued to both lanes and which belongs in the grind skill: a lane must
run `check-merge-eligibility.sh` itself and report its EXIT CODE as the evidence, never
assert "reviewed-clean" off the review skill alone. Phase 9 clean means "my triage is done,"
not "this PR can merge."

### L5 — Lane partition can silently descope a bead's own DoD
Filed as **`agents-config-abn9.44.9`** (P1). abn9.44.2.9's DoD required BOTH caller sites
updated; ROOT's file-conflict partition put one caller in another lane's territory, so the
lane correctly refused to touch it — and would have closed the bead half-delivered had ROOT
not caught that the DoD explicitly covered it.

Candidate fix for the skill: when partitioning by file-conflict surface, check each bead's
acceptance criteria against the lane boundaries BEFORE spawning. Where a bead's DoD spans
two lanes, decide up front whether to split the bead, re-partition, or plan the in-scope
deferral — rather than discovering it at review time via the bot reviewer. Note the
descope was ROOT's to own, not the lane's.

### L6 — A lane's own background poll rings into the void (skill already knows; worth data)
`wait-for-pr-comments` starts a background poll and the lane then parks. A parked lane
cannot hear its own background task complete — that notification wakes ROOT. Observed on
both lanes. ROOT's independently-armed watchers were the actual delivery mechanism for both
review-ready signals, catching them at t=240s and t=300s.

This confirms the skill's existing "ROOT arms every watcher" rule with live evidence, and
suggests the lane briefing should say explicitly: *expect your own poll to ring into the
void; ROOT's watcher is what will reach you.* Both lanes were briefed this way and neither
got stuck, so the briefing text works — worth promoting into the skill rather than leaving
it to each ROOT to reinvent.

### L8 — Scope hidden in a bead's NOTES got shipped past two checkpoints
Filed as **`agents-config-abn9.44.11`** (P1). `abn9.44.2.9`'s title and description describe
only the per-identity dispatch work; a P1 scope broadening (two `poll-copilot-review.sh`
completion-detection defects, added in PR #336 round 3) lived in the bead's **NOTES** field.
The lane implemented the description, not the notes, and shipped a PR delivering roughly half
the DoD. It cleared the HEAVY gate, Codex review, and the merge floor — none of which know
what a bead's DoD is — and ROOT merged it.

Two failures, and the second is the load-bearing one:
1. The lane read ROOT's summarized brief and the bead description, not the full bead. It
   caught this itself while writing the close reason and self-flagged unprompted, which is
   the behavior that saved it.
2. **ROOT never verified the DoD against the bead before authorizing the merge** — even
   though ROOT's own initial brief had listed both items. The manager briefed the scope and
   then didn't check the scope was delivered. Every mechanical gate in the chain can pass
   while a bead is half-built, because none of them read the tracker.

Candidate fix for the skill: a lane must `bd show <id>` and read **notes/acceptance in full**
before starting — not work from the orchestrator's summary, which is lossy by construction.
And ROOT must check the delivered work against the bead's acceptance criteria as an explicit
step before the merge decision — the merge floor proves the PR is *safe to merge*, never that
the *work is complete*. Consider treating any bead whose notes carry scope beyond its
description as a re-brief trigger.

### L9 — Post-merge `git pull --ff-only` collided with an unpushed human commit
lane-polling's post-merge fast-forward failed: local `main` carried an unpushed commit of
Scott's (`docs(worktrees)…`, `7c17a19`) that had diverged from origin's two new merges. The
lane checked for conflicts, rebased cleanly (different file, no overlap), and **flagged that
it had rebased a commit it did not author** rather than doing it silently. Verified after the
fact: content intact, now `1054517`, original still reachable, `main` ahead 1, nothing lost.

Right outcome, but it happened by the lane's own judgment rather than by rule. The post-merge
leg says "fast-forward main" and is silent on what to do when ff fails because a human's
local work is in the way. Candidate fix: name this case explicitly — check for unpushed
non-agent commits before the ff, and either surface to ROOT or rebase-and-report, never
rewrite a human's commit silently. Note the grind ran in a repo with other live sessions, so
this is a normal condition, not an edge case.

### L10 — Two lanes raced to reconcile the SAME local `main`, with different strategies
Within about a minute of each other, both lanes ran their post-merge "fast-forward main"
step against the one shared local `main`: lane-polling **rebased** Scott's unpushed commit
onto `origin/main`; lane-eligibility then ran **`git merge --no-ff origin/main`**. Two
authors, one branch, two incompatible strategies.

It came out clean purely by ordering luck — the rebase landed first, so `origin/main` was
already an ancestor and the merge was a silent no-op. Had the order reversed, or had both
run concurrently, the result would have been a merge commit over a rewritten history with a
human's unpushed commit caught in the middle.

Compounding it: **lane-eligibility reported a merge commit that did not exist.** It described
what its command was supposed to do rather than what git produced (`git status -sb` read
`ahead 1`, linear, no merge commit). ROOT caught it only by verifying against the repo.

Two fixes, both adopted mid-run:
1. **No lane touches local `main`. Ever.** The post-merge leg drops "fast-forward main"
   entirely; ROOT reconciles main itself, once, from the main tree. Lanes branch new
   worktrees off **`origin/main`** explicitly, which removes the dependency on local main's
   state regardless of what any other lane is doing.
2. **Report what git shows, not what the command intended.** `git log --oneline -3` +
   `git status -sb` after any history operation — the same "report the floor's exit code,
   not your conclusion" discipline already established on the PR side.

The skill's post-merge leg currently assigns "fast-forward main" to *each lieutenant*, which
in a multi-lane grind is a shared mutable resource with no owner. That is the defect; it
should be ROOT's step, or explicitly single-owner.

### L11 — The gate's refuter stage has a 2-of-2 false-refutation rate
Second occurrence of **`agents-config-wgclw.32`**, recorded on that bead. Across the whole
grind the HEAVY gate raised a finding exactly twice (`rawTotal=1` on two separate runs), and
**both times both refuters fabricated a "this code does not exist" claim and destroyed a true
finding.** The refuter stage has not produced a single correct refutation in this sample.

Both destroyed findings happened to be minor (a `jq` fork; duplicated prose). That is luck of
the draw, not mitigation — the mechanism is severity-blind.

The operational consequence, adopted mid-run and worth promoting into the grind skill: **a
`clean-at-floor` verdict with `confirmedTotal=0` after a nonzero `rawTotal` must be presumed
to be a suppressed true finding until audited.** ROOT now audits every gate run via an
ephemeral subagent, and every audit so far has recovered a real finding the gate had thrown
away. The audit costs ~20 lines of ROOT context and has a 100% hit rate.

A testable hypothesis worth checking before designing a fix: refuters may inherit the
caller's cwd exactly as finders did in `wgclw.31`, in which case an unqualified `grep` would
genuinely return nothing and the refuter would *sincerely* conclude absence — making both
P0s one root cause with one fix. But that does not explain the refuters' *positive* claims
about what specific lines contain, which are assertions about content rather than absence.
Both need investigating.

### L12 — Never file a defect measured against a moving target
A worktree read as clean → 2 files modified (`+52/-9`, uncommitted) → clean across three
consecutive reads. During that window `gate_triage` reported `files=0, tier SERIAL` on a
`src/**` change that must floor HEAVY. The tempting move was to file a gate-routing defect
immediately.

ROOT instead wrote **"UNRESOLVED — do not file, re-measure on a stable tree"** into the
handoff, ordered the lane to commit, and re-measured. The stable measurement produced a
*different and correct* defect: `gate_triage` counts only COMMITTED changes (uncommitted →
`files=0`/SERIAL; identical content committed → `files=2, loc=62`/HEAVY). Filed as
**`agents-config-wgclw.33`** (P1).

Had the unstable reading been filed, the bead would have described the wrong mechanism and
sent whoever picked it up chasing a phantom. The discipline generalizes: **a measurement
taken while the thing measured is changing is not evidence.** Stabilize, re-measure, then
file. It also cost nothing — the flap had to be resolved anyway.

Corollary that fell out of the same investigation, recorded so nobody re-files it:
`gate_triage` handles a behind-base branch CORRECTLY. A naive `git diff origin/main` in a
worktree 2 commits behind showed 10 files / −317 lines (the real change PLUS the inverse of
an intervening merged PR); `gate_triage` correctly reported the branch's own 2 files. Always
diff against the **merge-base**, never the moved base.

### L13 — When a count does not match what was added, that discrepancy IS the bug report
A lane reported adding 4 new tests; the suite went 227 → 230. Three, not four. Both the lane
and ROOT read that report and neither noticed.

A reviewer did, and traced it to a **BLOCKING** defect: the new tests were inserted between a
`run_script` call and the assertion belonging to it, and each reassigned `out`/`rc`. The
pre-existing assertion silently began checking the *new* test's exit code. It still passed —
purely because both scenarios yield `rc=1` — while the behavior it was written to verify
became completely unverified. A green suite, one assertion quietly pointed at the wrong thing.

Two rules out of it:
1. **Reconcile test-count arithmetic explicitly.** Report "added N assertions, count went
   X → Y, Y − X = N ✓". A mismatch is not bookkeeping noise; it is the symptom of a test
   silently pointed at the wrong run.
2. **Keep an assertion adjacent to the run it describes.** The absence of that adjacency is
   what made the hijack possible, and it is invisible in a diff that only shows insertions.

### L7 — The merge gate was blind to CI on every PR it cleared tonight
`check-merge-eligibility.sh` reported `ci_state="none"` on BOTH PRs while CI had genuinely
passed — the exact defect `abn9.44.3` fixes, now merged. Worth recording because ROOT came
within one decision of merging a security-gate change on a CI fact it knew to be blind. ROOT
verified CI independently (`gh api .../check-runs`) before both merges.

Once the fix propagates (installer run), re-verify that `ci_state` reads correctly — the
merged fix is in `src/`, and the *installed* copy the guard actually executes is still the
old one until `scripts/install.sh` runs. Until then, keep verifying CI by hand before any
merge.

## L14 — The HEAVY gate's journal makes its verdicts unauditable

The gate's `journal.jsonl` records only `{type:started}` / `{type:result}` envelopes.
No cwd, no repo_root, no tool invocations, no command output. So when a finder
returns `{"findings":[]}`, there is NO WAY to distinguish:

  - "I diffed the target and it is genuinely clean"  from
  - "I never found the target and returned empty"

These are opposite verdicts with identical journal representations.

Discovered auditing run `wf_a0e6f00b-ac5` (bead abn9.44.4): 4 agents, 0 errors,
3 empty results, verdict "clean-at-floor". The diff was independently confirmed
REAL at the target worktree (2 files, +52/-9, tree clean at 744640e) — so the
empty findings were not explained by an absent change. But nothing in the journal
could establish whether the finders reached it.

NOTE THE TRAP I ALMOST FELL INTO: the audit subagent reported "FALSE CLEAN" and
read "no evidence they reached the diff" as "evidence they did not." Those are
different claims. A finder that genuinely reviewed 61 clean lines ALSO returns
`[]`. I relayed the weaker, true claim — unauditable — not the stronger, unproven
one. This is the same discipline as L12 (never file a defect measured against a
moving target): do not let an auditor's overreach become my finding.

The mitigation I injected for wgclw.31 — mandatory GATE-HARNESS-ERROR finding on
an empty diff — did NOT fire here and produced no signal either way. A fallback
that is invisible when it fails is not a fallback.

RULE: a HEAVY gate verdict of "clean" with empty finder results is NOT acceptable
evidence. Either the gate must log cwd + the diff stat each finder actually saw,
or every clean-with-empty-results verdict must be replaced by a directed reviewer
dispatched with an explicit worktree-absolute repo_root and a mandatory
first-action diff whose output it must quote. The directed-reviewer play worked
on 44.14 and on 44.4's re-review; the gate did not.

This UPGRADES wgclw.31: that bead is filed as "gate ignores repo_root." The
deeper defect is that the gate cannot be checked at all, so the repo_root bug was
only ever detectable by luck (the one run where a true finding was destroyed).

## L15 — "Address the review findings" silently invalidates the review

lane-polling was relayed a clean review with three sub-floor items. It took all
three — correctly, as instructed — and one of them was a REFACTOR (extract a
shared fetch_head_sha() used by two call sites). loc_changed went 61 -> 116.

The reviewed artifact was no longer the shipping artifact. The change nearly
doubled, and the new material landed in exactly the freshness logic the review
had been about. "Gate obligation satisfied" was true when I said it and false
twenty minutes later, and nothing in the workflow flagged the transition.

The sharper edge was on a second item. The lane removed a dead `|| current_head=""`
fallback, justified as "the helper internally already returns 0 on every path."
That was established against the PRE-refactor helper — and the same commit
restructured that helper. The premise and the code moved together, so the premise
needed re-proving against what actually shipped. A justification inherited across
a restructuring of the thing it describes is not a justification.

Note the asymmetry that makes this dangerous: 76/76 tests still passed after the
refactor. Tests are strong evidence that the HAPPY path held and weak evidence
about FAILURE paths — which are the least covered and, in a fail-closed security
gate, the only ones that matter. A green suite after a refactor of error handling
is close to no signal at all.

Contrast lane-eligibility on the same day: it committed, then deliberately refused
to rebase partly BECAUSE a reviewer was mid-examination of its tree. Same session,
opposite instinct, and it ended up in the defensible position.

RULE: a review clears a COMMIT, not a branch and not an intention. If any code
changes after the review — including changes made to satisfy that review's own
findings — the clearance is void for the delta. Either re-review the delta or
state explicitly why the delta needs none. Applying review findings is the single
most likely moment for this to happen, and the least likely to feel like it needs
re-review, because it feels like compliance rather than change.

COROLLARY for ROOT: when relaying sub-floor findings, distinguish items that are
textual (a comment, a rename) from items that RESTRUCTURE control flow or error
handling. The first can be applied and shipped; the second buys a second review
round. I relayed all three undifferentiated and created this problem myself.

## L16 — Reported artifact content must be quoted, not recalled

lane-polling reported that PR #360's body named a shared helper extraction with
`head_committer_equilibrium_epoch`. That function does not exist:

  git grep -n "head_committer.*epoch\s*()"  -> poll-copilot-review.sh:260: head_committer_epoch() {
  git grep -n "equilibrium"                 -> (no match anywhere in the tree)

The PR body itself was CORRECT — it says `head_committer_epoch`. Only the REPORT
to ROOT invented the token, by paraphrasing the body from memory instead of
reading it back.

Outcome: nothing wrong with the artifact. Recording it anyway, for two reasons.

FIRST, the verification was still correct to run. This is the third report-vs-world
discrepancy in this run. The prior two were both real: an off-by-one test count
that turned out to be the first visible symptom of a BLOCKING test-hijack, and a
"clean" gate verdict whose empty finder results made it unauditable. Two for three
is a high enough base rate that the two grep calls are obviously worth it. A
verification that comes back clean is not a wasted verification — it is the price
of the ones that don't.

SECOND, and this is the transferable part: ROOT merges on the strength of lane
REPORTS. An invented token in a report is indistinguishable from an invented token
in the code until somebody checks. The lane paraphrased a PR body; it could as
easily have paraphrased a test result or a floor exit code. The failure mode isn't
dishonesty, it's recall — and recall degrades exactly as a lane's context fills,
which is precisely when its reports carry the most accumulated weight.

RULE for lanes: when reporting the CONTENT of an artifact (PR body, commit
message, file, command output), quote it or read it back. Do not recall it.
RULE for ROOT: a symbol in a report that appears nowhere in prior reports is a
cheap, high-yield thing to grep. Do it before it becomes load-bearing, and tell
the lane the check came back clean — a lane that only hears from you when it is
wrong learns to report less.

## L17 — Grind state belongs at {project}/.grind/{worktree_slug}/

USER-DIRECTED, 2026-07-19.

Grind working state — ORCHESTRATION-STATE.md, LESSONS.md, state.json,
dashboard.html, watchers/ — must live at:

    {project}/.grind/{worktree_slug}/

This run put it at `.claude/worktrees/../.claude/grind-codex-awareness/`, i.e.
under `.claude/` and slugged by TOPIC ("codex-awareness") rather than by
WORKTREE. Both parts are wrong:

- `.claude/` is Claude Code's own config/worktree home. Grind state is run
  artifact, not tool config, and burying it there conflates the two — it also
  makes the state Claude-specific when the discipline is meant to be portable
  across tools.
- Slugging by topic breaks the mapping from a worktree to the state that
  describes it. A worktree slug is unambiguous and mechanically derivable; a
  topic name is chosen prose that a successor cannot compute from context.

For THIS run the state stays where it is — the bookkeeper writes state.json and
dashboard.html at the current paths and the armed watchers reference them, so
moving mid-run would break live paths for no benefit. The move belongs in
shutdown, or in the orchestrated-grind skill itself.

FOLLOW-UP: the `orchestrated-grind` skill should specify this path convention
explicitly in its setup sequence. It currently does not say where grind state
goes, which is why this run invented a location. File as discovered work at
shutdown against the skill, not against this run.

## L18 — The directed review found what the HEAVY gate certified clean

Decisive evidence for the superseding rule in L14, on the SAME commit (744640e):

  HEAVY gate wf_a0e6f00b-ac5  -> "clean-at-floor", 0 findings, 3 of 4 finders empty
  Directed opus reviewer       -> one MAJOR, two MINOR, plus a proven-vacuous-test finding

The MAJOR: widening the trigger-comment exemption to a FIRST-LINE match means
`"@codex review\n<any content>"` is exempt. A human typing the trigger phrase and
then adding real feedback below has that feedback silently dropped from
untriaged_feedback — in a security gate whose whole purpose is fail-closed.

WHY THE DIRECTED REVIEW WON, and it is not "a better model":

1. It was told the EXACT risk shape to enumerate — every body form that could NOW
   wrongly earn the exemption (leading blank line, whitespace, CRLF, BOM, unicode
   look-alikes, trigger-line-plus-hostile-tail). It worked a checklist, not a vibe.
2. It was told WHERE to look, with a worktree-absolute repo_root and a mandatory
   first-action diff it had to quote.
3. It PROVED claims by mutation instead of reasoning about them: it reverted the
   predicate to the pre-fix version, re-ran the suite, and observed which tests
   actually failed. That is how it established tests (11) and (12) are vacuous —
   they pass both before AND after the change, so they validate nothing about it.
   No amount of reading would have produced that with the same confidence.
4. It was forbidden from asserting absence without quoted grep output, which is
   what destroyed two true findings earlier in this run.

THE VACUOUS-TEST FINDING IS THE SLEEPER. A test that passes before and after the
change it supposedly covers is worse than no test: it consumes a slot in the count,
survives review, and reads as coverage forever. Mutation testing is the only cheap
way to catch it. ADD THIS to the standard directed-review brief: "verify the new
tests would actually FAIL against the pre-change code; demonstrate concretely
rather than reasoning about it."

CAVEAT WORTH KEEPING: the reviewer mutated a LIVE lane worktree to run those
experiments. It restored correctly and I verified independently (HEAD 744640e,
`git status --short` empty, predicate intact) — but a reviewer with write access
mutating a lane's tree is a real hazard, and it got verified only because I
happened to check. Future directed reviews that need mutation should either work
on a throwaway copy or be verified by ROOT afterwards as a matter of course, not
as a matter of luck.

## L15-AMENDMENT — the mechanism was wrong; the principle held

Correcting L15 rather than leaving it to mislead a successor.

L15 says lane-polling "applied a REFACTOR after its review cleared the code," implying an
already-reviewed commit followed by a second commit. That is NOT the shape. The delta
reviewer established it:

  git grep -n 'fetch_head_sha' dbe20f1^ -- .../wait-for-pr-comments/
  -> (no hits in parent)

dbe20f1 is a SINGLE squashed commit containing both the freshness filter and the extraction.
There was never a pre-refactor commit. The reviewed content existed only as an uncommitted
working tree, so there was no pre-refactor tree to diff against — which is also why the
reviewer had to review the post-state against the semantics the brief ATTRIBUTED to the
pre-refactor code rather than against an actual artifact.

WHAT SURVIVES, and it is the whole point: the shipping artifact still differed from the
reviewed one. Re-reviewing was still correct, and the re-review had to be framed
semantically rather than as a diff. So the RULE in L15 stands unchanged — a review clears
what was actually examined, and applying that review's own findings is the most likely moment
to void it.

WHAT DOES NOT SURVIVE: my description of the mechanism, and the implication to the lane that
it had committed things out of order. It hadn't. I told the lane so explicitly rather than
letting a wrong premise sit in its context — a lane that accepts a false correction will
"fix" a process that was never broken.

META-LESSON: I inferred a two-commit history from a lane's prose report and never checked
`git log`. One `git grep` against the parent commit would have settled it before I briefed a
reviewer on a false premise. This is L16's rule (quote artifacts, don't recall them) applying
to ROOT, not just to lanes — and it cost a reviewer a paragraph of working around my error.

ALSO WORTH KEEPING: the delta reviewer stated the premise correction FIRST, before its
findings, rather than silently reviewing something other than what it was asked to. That is
exactly right, and the opposite of the refuters earlier in this run that invented facts to fit
the brief they were given.

## L19 — ROOT ordered a skill violation; the lane caught it

I instructed lane-polling to "cite the bead ID" in its SKIP-disposition reply on PR #360.
That directly violates a hard rule in `reply-and-resolve-pr-threads`, whose Red Flags table
forbids it verbatim: never include bd/bead IDs, ESCALATE, inventory, phase, or other internal
tool names in PR replies. The lane had correctly followed that rule on four prior dispositions
this run (44.9, 44.12, 44.13, 44.14) and my order would have broken the streak.

The lane HELD and FLAGGED rather than complying, and offered a compliant draft alongside the
question. That is the behavior to reinforce: a lane that silently resolves a conflict between
an order and its skill leaves ROOT believing a rule holds when it doesn't, and the divergence
surfaces later as an inconsistency nobody can explain. Eating a correction is cheap.

On the merits I was simply wrong — a bead ID is internal vocabulary, meaningless to Codex, and
leaks tooling into a public thread for no reviewer benefit. Our audit trail is the inventory
and the grind state files, not the PR.

SECOND-ORDER CATCH, which nearly shipped: the lane's draft had gone STALE while it held for my
ruling. It gave two reasons for deferring, the first being "this PR already carries an
unreviewed refactor that needs its own pass first" — and the delta review had come back CLEAR
in the interim. Posting it would have put a false statement in a public thread and handed the
reviewer a reason it could fairly challenge. Dropped it; the second reason (the gap pre-exists
on all three completion paths, so it deserves one coherent fix) is stronger and stands alone.

RULE: when a lane holds a draft pending a ruling, re-validate the draft's FACTUAL CLAIMS
before authorizing the post, not just the point in dispute. A hold is a window during which
the world moves — and the longer ROOT takes to rule, the staler the draft it is ruling on.
Both the lane and I were focused on the bead-ID question; neither of us was looking at the
clause that had quietly expired.

## L20 — A reversal that arrives after the act is not a reversal

Sequel to L19. The lane held its draft, flagged my bead-ID instruction as a skill violation,
and asked for a ruling. I ruled in its favour — post the no-ID version, and also drop a clause
that had gone stale. My ruling arrived AFTER it had already posted.

Published text therefore carried both defects: the internal bead ID its skill forbids, and
"this PR already carries a refactor that needed its own review pass first" — false by then,
since the delta review had come back clear.

ROOT fixed it directly (PATCH on the review comment, then read the body back to verify) rather
than routing the cleanup back to a lane that had done nothing wrong. Own your own errors at
the point of failure; making a lane clean up after ROOT wastes a round trip and misattributes
the mistake in the record.

THE STRUCTURAL LESSON: "hold and flag" only protects anything if the ruling beats the act.
The lane did everything right — it flagged, it drafted a compliant alternative, it asked. But
it said "holding for your call, then posting" and then, reasonably, proceeded. A lane that
asks a question is not obliged to block forever, and ROOT's latency is unbounded.

RULE: when a lane flags a conflict and offers to proceed, ROOT's reply must be the very next
thing it does — before state files, before lessons, before bookkeeper deltas. I spent that
window writing a lesson about how well the lane had handled it. The irony is the point: the
housekeeping that documents good judgment is exactly what delayed acting on it.

COROLLARY: a lane holding for a ruling should say what it will do if no ruling arrives, and
ROOT should treat any such message as a deadline rather than a question. If the default action
on silence is "post anyway," that is not a hold — it is a notification with a grace period,
and it must be answered at that speed.

## L21 — ROOT reached into a lane's artifact and caused a write race

Immediate sequel to L20. Having discovered my reversal arrived too late, I fixed the posted PR
reply myself (PATCH on comment 3611060574). The lane, on receiving that same correction,
independently fixed it too. Two writers, one artifact, no ownership declared.

Outcome verified and benign: the lane's write landed last, both versions were substantively
identical (no bead ID, no stale clause), thread still resolved, grep for the leaked strings
returns zero hits. Pure luck. If either version had been wrong, or if the order had differed,
one write would have silently clobbered the other with no trace.

This is precisely the mid-air collision the grind's own branch-ownership discipline exists to
prevent — "one author per branch at any moment," and ROOT issues an explicit OWNERSHIP CHANGE
before touching anything a lane might also touch. I applied that rule to branches and never
extended it to PR-public text, which is just as much a shared mutable artifact.

Compounding factor: L20's rule ("answer a holding lane immediately") pushed me to act fast,
and acting fast is exactly what made me skip the ownership handshake. The two lessons pull
against each other, and the resolution is not "be slower" — it is that SPEED APPLIES TO THE
REPLY, NOT TO THE REACH-IN. Sending the lane a correction is fast and safe; editing the lane's
artifact myself is neither.

RULE: PR-public text (comments, replies, thread bodies, PR descriptions) belongs to the lane
that owns the PR, exactly as its branch does. ROOT sends the change; ROOT does not reach in.
Exception: the lane is terminated or unreachable — and then ROOT says so explicitly in the
same message as the edit, so the record shows why ownership moved.

GENERALIZATION WORTH KEEPING: every time this run has had two actors on one mutable thing
without a declared owner, it has come out fine ONLY by ordering luck — twice on local `main`
(L10), once here. Three for three on "no harm," which is exactly the base rate that makes a
team stop bothering with the handshake right up until the one time it matters.

## L22 — Killing a mutating reviewer nearly stranded a live worktree

lane-eligibility committed 2749572 while a directed review of 882d2b6 was in flight. The
review was now examining superseded code including a test file that had since changed, so I
killed it (L12: never adjudicate against a moving target).

Its final output line was: "Backups made. Mutation (b) — drift the producer's marker literal:"

It was killed MID-MUTATION, in a live worktree another agent owns, after taking backups it
never got to restore from. I verified immediately: `git status --porcelain` empty, HEAD at
2749572, no stray .bak/.orig files, both marker literals identical and undrifted. Clean —
by timing luck, not by design. Had the kill landed a second later, the lane's worktree would
have carried a silently drifted marker literal, and the NEXT thing to run there would have
been a test suite that passes or fails for reasons unrelated to the code under review.

TWO RULES OUT OF THIS:

1. Before killing an agent, consider whether it MUTATES. A read-only reviewer is free to kill;
   a mutating one has a restore obligation that a kill cancels. If it must die mid-flight,
   verify the worktree immediately and treat the tree as suspect until proven clean.
2. Brief mutating reviewers to restore IMMEDIATELY after each experiment rather than batching
   restores at the end, and to end their run by reporting `git status --porcelain` and
   `git log --oneline -1`. A reviewer that batches restores has a long window where a kill,
   a crash, or an API timeout strands the tree. I added both requirements to the re-dispatched
   brief.

ROOT CAUSE, and it is mine: I dispatched a review and then let a lane keep working on the same
tree. The lane was not at fault — my "stay parked" message crossed its in-flight work, the
same crossing that has now happened four times in this run. The durable fix is not more
messages; it is to dispatch the review only AFTER the lane has confirmed it is parked, or to
review a COMMIT-PINNED copy rather than the live worktree. A review that reads a live tree an
active lane owns is racing by construction.

## L23 — ROOT was talking into a window nobody reads (USER-DIRECTED)

Scott, 2026-07-19: "you are too chatty/verbose. I'm not watching this window, so you're
screaming into the void unless you escalate to me thru the dashboard or I come looking."

The ROOT transcript is not a human-facing surface during a grind. The DASHBOARD is. Every
paragraph ROOT writes to the transcript is unread by default, costs ROOT's scarcest resource
(context), and creates a false sense that the human has been informed.

RULES:
- Default to SHORT in the ROOT transcript. It is a log, not a report.
- Anything the human must actually know goes to the BOOKKEEPER, to appear on the dashboard.
  "I told the user" is only true if it reached the dashboard.
- Escalations are a dashboard action, not a paragraph.
- Long-form prose belongs in the handoff doc (durable, re-readable) or the dashboard (watched),
  never in a transcript scroll.

Filed agents-config-abn9.44.16 (P2) for the related gap Scott identified: the grind event log
has no channel for human questions and ROOT's answers, so an exchange in the ROOT session is
invisible on the dashboard and lost across compaction.

ALSO FLAGGED FOR THE END-OF-RUN RETROSPECTIVE: Scott observed ROOT doing many file edits and
asked whether that means ROOT is doing work the agents should have done, or correcting work
that escaped their quality controls. Preliminary honest answer, to be verified properly at
retro rather than asserted now: nearly all ROOT edits this run were to ROOT's OWN state
artifacts — ORCHESTRATION-STATE.md and this LESSONS.md — plus one PR-comment PATCH (ROOT's own
error, and itself a mistake per L21) and rendering a watcher script. ROOT has not implemented
or corrected lane code. But the volume is real and the question deserves a measured answer:
count the edits by target at retro and report the split, rather than defending the position.

## L24 — ROOT used a grep COUNT as evidence and was wrong

I told lane-polling its duplication collapse was incomplete, citing:

    poll-copilot-review.sh          liveness=2 soundness=3
    poll-copilot-rereview-start.sh  liveness=1 soundness=2
    poll-copilot-review_test.sh     liveness=2 soundness=2
    SKILL.md                        liveness=0 soundness=0

The lane disputed it. It was right. Reading the CONTEXT of each hit rather than counting:
three of the hits (poll-copilot-review.sh:497, _test.sh:336, _test.sh:419) are about the
CLEAN-SIGNAL REACTION bound — a different comparison entirely, pre-existing, not the lane's
work. The genuine hits were the two-line pointer I had asked for and the canonical block.

MY FAILURE: I grepped for term COUNTS and treated the number as a fact about meaning. A count
tells you a token appears; it tells you nothing about what the line says. This is the same
recall-instead-of-quote error (L16) I had been correcting in lanes all run, applied to my own
evidence — and worse, because I presented it AS evidence, with a formatted table, which made
it look verified.

The lane's own fix for the real gap was better than what I asked for: SKILL.md scoring 0/0 was
not cosmetic — a reader following either pointer would land on the canonical text and fail to
recognize the concept they were sent to find, because the vocabulary did not match. It added
the framing terms to existing sentences without lengthening them.

RULE: when citing grep as evidence, quote the matching LINES, never the count. If the output
is too long to quote, that is a signal to narrow the query, not to summarize it as a number.
A formatted table of counts reads as rigor and can be pure noise.

SECOND RULE: a lane that pushes back on ROOT's evidence is doing the job. This is the third
time this run a lane has been right against me (the bead-ID skill rule, the premise about
dbe20f1's commit shape, and now this). Concede fast and in writing — a lane that wins an
argument and gets no acknowledgement stops arguing, and ROOT's error rate is not low enough
to afford that.

## L25 — four patch attempts is a design signal ROOT missed

`abn9.44.4` burned four review cycles (`2589dbe`, `882d2b6`, `2749572`, `00fd5c4`) on
the same losing move: matching the *shape* of an attacker-controlled comment body.
Each attempt constrained more lines; each was defeated by leaving some region free.
Attempt 4's closing sentinel relocated the gap from the tail to the middle.

The reviewer caught every one, so quality held — but ROOT let the lane keep patching
after attempt 2 made the pattern visible. The manager's job on a third identical
rejection is to halt coding and demand a design decision, not to relay the finding
and let another jq patch fly. Cost: two avoidable review cycles.

Rule: when N>=3 attempts fail by the *same mechanism*, ROOT stops the lane and
requires a written design choice before the next diff.

## L26 — a dispatched review can outlive the agent that ordered it

lane-polling dispatched a directed reviewer, then halted before it returned. The
verdict arrived at ROOT — worker completions notify ROOT, never the dispatching
lieutenant — by which time the lane was stopped and could not fold it in. Its
handoff recorded "verdict unknown / never returned," which was true from where it
sat and false in fact. ROOT corrected the file after the lane was down.

ROOT's authorization to fix the one MAJOR the reviewer found did land in time — the
lane applied it as `5b974ad` and corrected its own handoff. But ROOT had already
written both the state file and the handoff as though it hadn't, and reported that
to Scott. The recovery was luck of timing, not design.

Second-order lesson, and the sharper one: ROOT twice wrote a confident negative
("verdict never returned", "the fix was never applied") about a teammate it had
ordered to stop but had not confirmed stopped. A halt order is not a stop event.
Confirm termination before recording anything as final — or write the uncertainty
instead of the guess. Both statements were the same failure mode L16 already names
(quote, don't recall), wearing a different hat: ROOT asserted a fact about the world
from its own expectation rather than from an observation.

Rule: before ordering a halt, ROOT checks for in-flight workers it will outlive.
Either wait for them, or accept that ROOT itself owns folding the result into the
stopped lane's handoff — and say so in the halt order so the lane does not write a
confident negative about a verdict ROOT is about to receive.

## L27 — ROOT filed a duplicate by doing the lane's job without telling it

ROOT ordered lane-eligibility to file the 44.4 residual bead during wind-down. The
lane reported a clean stop without mentioning it; ROOT checked `bd`, saw nothing,
concluded the lane had missed it, and filed `abn9.44.18` itself. The lane was in
fact filing it at that moment, as `abn9.44.17`. Two beads, same content.

The lane caught the collision, closed `.17` as a duplicate of `.18`, and verified no
close-walk cascade — which ROOT then re-verified independently (`.17` closed, `.18`
open, parent epic and `44.4` both still `in_progress`). Clean recovery, but only
because the lane noticed.

The error was not "checking." Verifying against `bd` instead of trusting the report
was correct and is what caught the earlier real gap. The error was going straight
from *absence of evidence* to *taking the action myself*, on a teammate that had not
yet confirmed termination — the same not-confirmed-stopped mistake as L26, one turn
later, in a form that mutated shared state instead of just a file.

Rule: when ROOT finds a teammate's ordered task apparently undone, ROOT asks or
confirms the teammate is stopped BEFORE doing it. Tracker writes are shared state;
two agents filing into it concurrently is the same hazard as two agents committing
to one branch.
