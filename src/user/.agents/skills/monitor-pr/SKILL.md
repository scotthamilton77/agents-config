---
name: monitor-pr
description: >
  Supervises a pull request through the prgroom CLI's deterministic grooming
  loop. Use after a PR is created or pushed, or when an open PR has Copilot or
  human review feedback to resolve. Drives `prgroom run` (poll, fix, push,
  reply, resolve), reads the `status --json` merge-gate envelope, reports the
  terminal outcome, and acts on human-judgment kickbacks: when prgroom gates a
  PR to human-gated, it surfaces each escalation and hands over the
  `prgroom resolve-escalated` recipe so a human can reclassify. Use when the
  user mentions a PR, review, Copilot, feedback, grooming, escalations, or the
  merge gate. Do NOT use to merge a PR — merge authorization is governed by
  the repo's merge-authorization policy, enforced by the merge-guard skill
  (default: explicit human instruction).
model: sonnet[1m]
effort: medium
---

# monitor-pr

A thin, contract-aware supervisor over the `prgroom` CLI. prgroom owns the
mechanics — polling Copilot, clustering, fixing, pushing, replying, resolving.
This skill selects the run mode, interprets prgroom's exit code plus its
`status --json` envelope, reports the outcome, and drives the human loop when
prgroom kicks work back. It supervises; it does not reimplement the loop.

## 1. Select the mode from the trigger

| Trigger | Mode | Flag |
|---|---|---|
| Chat — a person asked | interactive | `--interactive` |
| cron / `/loop` / CI (e.g. GitHub Actions) | autonomous | `--autonomous` (the default) |

Interactive returns at `awaiting-review`/`idle` so you own the wait and can talk
to the user; autonomous blocks through the wait until the PR quiesces or caps.

## 2. Run the loop

Resolve the PR ref as `<owner>/<repo>#<n>` (or a full PR URL), then:

```
prgroom run <owner>/<repo>#<n> --interactive    # or --autonomous
prgroom status <owner>/<repo>#<n> --json         # read the outcome envelope
```

From the envelope read `phase`, `last_error`, `items_summary` (disposition
counts), `merge_gates`, and `auto_merge_eligible`. The **phase**, not the exit
code alone, decides terminal handling — a hard-cap terminal exits 0 yet lands in
`human-gated`.

## 3. Act on the result

| prgroom result | Interactive | Autonomous |
|---|---|---|
| exit 0, `phase ∈ {quiesced, merged}` | Report the success summary from `status --json` (dispositions, `auto_merge_eligible`) | Exit 0; sink stays silent |
| `phase = human-gated` (escalated/failed items, or `last_error = LIFECYCLE_HARD_CAP_EXCEEDED`) | Surface each escalation; hand over the resolve recipe (§4); re-invoke after the human decides | prgroom already routed escalations to its sink; the supervisor itself exits non-zero on `human-gated` — even when prgroom exited 0 (hard-cap rides on exit 0) — so the scheduler sees the gate |
| exit 77 — `RUNTIME_TERMINAL_USER` (gh auth expired, push rejected) | Surface the infra problem from stderr; stop (retry is futile until it is fixed) | Sink; exit non-zero |
| exit 75 — `RUNTIME_TRANSIENT` (gh/git 5xx, lock held) | Re-invoke, bounded (a couple of attempts) | Let the scheduler retry on its next cadence |
| exit 130 / 143 — `RUNTIME_CANCELLED` (SIGINT / SIGTERM) | Report the cancellation; stop | Exit per the signal; a scheduler must NOT treat 143 as retryable |
| any other non-zero (exit 2 precondition, 65 contract, 78 state) | Surface the what/why/how from stderr; stop — these are invocation/corruption faults, not retries | Sink; exit non-zero |

## 4. Human-gated: surface, then route by disposition

prgroom emits one escalation line per blocked item, and **two dispositions
block** — they need different handling:

```
prgroom escalation [block] <owner>/<repo>#<n>: item <gh_id> dispositioned escalated
prgroom escalation [block] <owner>/<repo>#<n>: item <gh_id> dispositioned failed
```

(a lifecycle cap instead reads `lifecycle gate: LIFECYCLE_HARD_CAP_EXCEEDED`).
Surface each item's rationale to the human, then route by its disposition:

- **`escalated`** — the human reclassifies it. On their decision, run:

  ```
  prgroom resolve-escalated <owner>/<repo>#<n> <gh_id> \
    --as {fixed|skipped|deferred|wont_fix} [--rationale "..."] [--commits sha1,sha2]
  ```

  `--commits` is required for `--as fixed`. If a bare `<gh_id>` is ambiguous
  (the same id across thread/summary/comment kinds), disambiguate as
  `<kind>:<gh_id>`. `resolve-escalated` accepts ONLY `escalated` items — it
  rejects anything else with a precondition error.

- **`failed`** — the fix agent could not converge or an audit rejected its work.
  This is NOT a reclassification: address the underlying problem (or let the fix
  loop re-attempt on the next `run`), not `resolve-escalated`, which rejects it.

- **`LIFECYCLE_HARD_CAP_EXCEEDED`** — raise the cap and re-run:
  `prgroom run <owner>/<repo>#<n> --max-rounds <n>` (a bare re-run stays `human-gated`).

After the blockers clear, re-invoke `prgroom run <owner>/<repo>#<n> --interactive`.
The loop releases `human-gated` back to `fixes-pending` only once no `escalated`
and no `failed` items remain and `last_error` is clear, then finishes.

## Red flags

- **Do not merge on `auto_merge_eligible: true`.** That rollup is never
  consumed — merge-guard recomputes its own atomic gates live. Merge
  authorization is governed by the repo's merge-authorization policy via the
  merge-guard skill (default: explicit human instruction).
- **Do not re-invoke on exit 77 / 2 / 65 / 78.** Those are terminal faults (auth,
  bad ref, contract, corrupt state); retrying without fixing the cause just loops.
- **Do not hand-parse the tracker or post replies yourself.** prgroom owns reply,
  resolve, and state. Reaching around it risks double-posting.
- **Read the phase, not just the exit code.** `human-gated` can ride on exit 0.
