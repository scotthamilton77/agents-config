# V3 — Beads Export Verification Report

**Date:** 2026-07-21 (executed 2026-07-21→22)
**Scope:** `docs/specs/2026-07-21-harness-rework-way-forward.md` §3 S1 open verification
**V3 charge:** "confirm bd export/import + dolt archive mechanics preserve close notes
and dependency edges in the frozen reference."

**Overall verdict: PASS** — all four ACs pass with evidence below. One
significant operational discovery surfaced mid-task (orphaned live dolt
server invisible to `bd dolt status`); it delayed but did not block AC-V3.3,
and is flagged for separate follow-up.

---

## AC-V3.1 — Export command identified, contains ALL issues incl. deferred

**Verdict: PASS**

Command identified: `bd export --all -o <file>`. `bd export` (no `--all`)
excludes 8 pre-promotion "wisp" scratch records (all closed, all
brainstorm-process artifacts); `--all` is the maximal, lossless form and is
what was used for the final reference. There are no stored memories
(`bd memories` → "No memories stored"), so `--all` and
`--all --include-memories` are identical (verified: both produce 2359 lines).

Live totals, three independent sources, all agree:

```
$ bd count
Total: 2359

$ bd count --by-status
Total: 2359
closed: 1965
deferred: 189
in_progress: 10
open: 195

$ bd export --all -o /tmp/.../all.jsonl
Exported 2359 issues to /tmp/.../all.jsonl
$ wc -l /tmp/.../all.jsonl
2359
```

Note: `bd stats` (as named in the task prompt) does not exist as a command;
`bd status` and `bd count` are the equivalents. `bd status`'s human summary
undercounts (2351) because it's the same set as the default (non-`--all`)
export — i.e. it silently drops the 8 wisp records. `bd count` is the
authoritative total and matches `--all` exactly.

Deferred-status breakdown confirmed present and large (189 / 2359 ≈ 8%),
matching the AGENTS.md note that a large share of the backlog is `deferred`.
Status distribution inside the export file itself:

```
$ jq -r '.status' all.jsonl | sort | uniq -c
   1965 closed
    189 deferred
     10 in_progress
    195 open
```

All four required states (open, in_progress, closed, deferred) present and
counts reconcile exactly against `bd count --by-status`.

---

## AC-V3.2 — Round-trip fidelity (scratch DB, 3 probes)

**Verdict: PASS**

Imported `all.jsonl` (2359 records) into a fresh scratch DB at
`/tmp/beads-v3-scratch` (prefix `scratch`, never touching the live DB):

```
$ bd import -i all.jsonl --json --dry-run | jq '{created:(.created|length),updated:(.updated|length),skipped}'
{ "created": 2359, "updated": 0, "skipped": 0 }
$ bd count --by-status   # in scratch DB after real import
Total: 2359
closed: 1965
deferred: 189
in_progress: 10
open: 195
```

Exact match to live. Original issue IDs preserved verbatim on import (no
prefix remapping despite the scratch DB's different default prefix).

**Probe (a) — closed bead with a close note: `agents-config-abn9.11`**
(3 comments, including a detailed close/review note). `bd show` on live vs.
scratch, diffed:

```
$ diff probeA-live.txt probeA-scratch.txt
73a74,75
>
> 💡 Tip: Install the beads plugin for automatic workflow context...
```

Only difference is a cosmetic plugin-detection footer (present in the scratch
DB, absent live, unrelated to data). All fields — description, type,
priority, timestamps, all 3 comments verbatim (including the detailed
`ralf-review` cycle-by-cycle close note) — are byte-identical.

**Probe (b) — milestone blocks-chain `agents-config-wgclw` → `agents-config-abn9`**

```
LIVE    BLOCKS: wgclw → abn9, wgclw → abn9.23.3
SCRATCH BLOCKS: wgclw → abn9, wgclw → abn9.23.3
LIVE    abn9 dep list: wgclw (blocks) — SCRATCH: identical
```

Byte-identical on both sides.

**Probe (c) — deep parent-child subtree `agents-config-abn9.8`**
(includes a 3-level-deep nested example: `abn9.8.23` → `abn9.8.23.1/.2/.3`,
and `abn9.8.13` → `abn9.8.13.1`):

```
$ diff probeC-live.txt probeC-scratch.txt
(no output — 84/84 lines identical)
```

Full tree structure, statuses, types, priorities all preserved exactly.

**Conclusion:** close notes, dependency edges (blocks + parent-child),
labels, types, priorities, and timestamps all survive the export→import
round-trip without loss, across three independently-chosen, structurally
different probes.

---

## AC-V3.3 — Dolt directory cold-copyable

**Verdict: PASS** (after resolving a live-server discovery mid-task — see below)

### Discovery: `bd dolt status`/`bd dolt stop` gave false negatives

Initial attempt: `bd dolt status` reported "not running" for this project.
Trusting that, `.beads/` was copied via `cp -a`. Cross-check via `ps`/`lsof`
then revealed this was **wrong** — a real dolt sql-server process (PID
22838, alive since Jul 9) was bound to port 48128 (this project's configured
port per `.beads/config.yaml`), with its process `cwd` rooted at
`.beads/dolt` and an open handle on the noms `LOCK` file — i.e. it was
genuinely serving this exact live database the whole time. `bd`'s own
status/stop bookkeeping (a port-tracking file) had gone stale, making the
server invisible to bd's own commands while still fully live and lock-held.

This is a real bug in bd's server-lifecycle tracking, separate from the
documented "no such file /opt/homebrew/bin/git" stale-git-path gotcha. I
did not attempt to signal-kill the process myself (blocked by the session's
permission classifier on anything containing "kill", including `--help`);
Scott ran `bd dolt killall` directly. Confirmed clean afterward:

```
$ ps aux | grep -i "dolt sql-server" | grep -v grep
(no output)
$ bd dolt status
Dolt server: not running
  Expected port: 48128
```

### Redone cleanly against a verified-stopped server

```
$ ps aux | grep dolt   # confirmed: zero dolt processes
$ cp -a .beads /tmp/beads-v3-coldcopy/
$ du -sh /tmp/beads-v3-coldcopy/.beads
1.0G
$ bd dolt status   # live project, immediately after copy — still not running
Dolt server: not running
```

Reopened the copy read-only, ran queries:

```
$ cd /tmp/beads-v3-coldcopy/.beads
$ bd --readonly info
Issue Count: 2359
$ bd --readonly count
2359
$ bd --readonly count --by-status
closed: 1965 / deferred: 189 / in_progress: 10 / open: 195
$ bd --readonly show agents-config-abn9.11   # spot-check probe (a) again
[full close-note comment reproduced verbatim]
```

Matches live and matches the export exactly. The cold-copy's own dolt
server was stopped afterward (`bd dolt stop` → "Dolt server stopped."); the
live project's server state was unaffected throughout (confirmed
"not running" before, during, and after the copy).

**Note for follow-up (not in V3 scope):** the stale server-tracking bug
means `bd dolt status`/`bd dolt stop` cannot be trusted alone to confirm a
server is down before any future cold-copy/backup operation on this or
other bd-managed repos — always corroborate with `ps`/`lsof` on the expected
port, or use `bd dolt killall` unconditionally first.

---

## AC-V3.4 — Final dated artifacts

**Verdict: PASS**

- Export: `SAVEPOINTS/2026-07-21-beads-final-export.jsonl`
  (2359 lines, `bd export --all`, sha256
  `22ee6407f3934964a47a2da571da5a5162b79de9adf367adfaee290889f86fd9`).
  Byte-identical (`diff` clean) to the copy already validated through the
  round-trip (AC-V3.2) and cold-copy (AC-V3.3) tests above — no live writes
  occurred between validation and final export (read-only session
  throughout).
- Report: `SAVEPOINTS/2026-07-21-beads-export-v3-report.md` (this file).

---

## Summary table

| AC | Verdict | Key evidence |
|----|---------|--------------|
| AC-V3.1 | PASS | `bd export --all` = 2359 = `bd count`; status breakdown reconciles exactly |
| AC-V3.2 | PASS | 3 probes (close-note, blocks-chain, deep subtree) byte-identical live vs. scratch-import |
| AC-V3.3 | PASS | Cold copy against verified-stopped server reopens read-only, reproduces exact counts + probe |
| AC-V3.4 | PASS | Both artifacts present at specified paths |

**Recommendation for S1:** the export mechanics are lossless. Proceed with
S1's tracker reset (archive this DB, open the new empty DB) using
`SAVEPOINTS/2026-07-21-beads-final-export.jsonl` as the frozen reference.
Separately file the `bd dolt status`/`stop` stale-tracking bug — it's a
genuine correctness gap in bd's own server lifecycle management, worth a
bead of its own before it bites an unattended overnight run.
