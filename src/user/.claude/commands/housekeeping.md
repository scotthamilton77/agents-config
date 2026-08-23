---
description: Audit the repository for drift — residue of what moved out or was retired, docs that contradict the code, agent-instruction files that contradict each other or cite what no longer exists, wiring that builds nothing, a tracker that has stopped matching the branches — and write a dated recommendation list. Recommends only; changes nothing.
admission:
  provides: A recurring drift audit. Invoking it fans read-only subagents out over a fixed question set, re-checks every removal-driving claim before it is reported, and writes a dated recommendation list — what to remove, archive, or reconcile, each with the evidence that earned it — with repeat findings marked against the previous run. The repository is left exactly as it was found.
  cost: A fan-out of subagent runs whose reading scales with the repository rather than with this file, and a report left behind in the user's Claude directory.
  remove_when: Two consecutive runs return an empty recommendation set, or every question the command asks is answered by a gate that runs in CI.
---

# /housekeeping

A repository accretes faster than it cleans: every failure mints a rule, every
extraction leaves a copy behind, every plan outlives the decision it planned. This
command finds what should leave and says so, with evidence. It removes nothing —
each recommendation the user accepts becomes tracked work of its own.

`$ARGUMENTS` is optional: the directory to write the report into. Default
`~/.claude/housekeeping/<repository basename>/`.

**MUST NOT** edit, delete, move, stage, commit, or push anything in the repository,
run an installer or deploy step, or issue a tracker verb that writes. Every subagent
brief carries that prohibition verbatim. The run's only write is the report.

## 1 — Orient

Read the repository's own instruction files (every `AGENTS.md`, `CLAUDE.md` and
`CONTEXT.md` from the root down) and whatever names its CI target (`Makefile`,
`package.json`, `pyproject.toml`, a workflow file). Note what the sweeps need: what
the project says has moved out or been retired, and where to; which directory is
the shipped or deployed surface; how the tracker is addressed, if there is one; and
the newest earlier report in the report directory, if any.

## 2 — Sweep

Dispatch one read-only subagent per question, all at once, on the cheapest model
tier that can run the enumeration; questions 2 and 3 need judgment and get one
tier up. Each brief names the absolute repository root, one question, the
prohibition above, and its report path `<report dir>/<date>/q<n>.md`.

1. **Residue of departures.** For everything step 1 says has left: copies still in
   the tree, references still pointing at the old home, configuration still naming
   it — CI targets, registries, tracker vocabulary.
2. **Docs against code.** Every document whose subject is code: is the code there,
   does it do what the document says, does the document's own status line agree?
   Dated design records whose decisions are already in the code and cited nowhere.
3. **The instruction surface.** Every file an agent loads — instruction files at
   every level, rules, skills, commands, hooks: citations that do not resolve
   (where a gate already checks them, run it and carry its output); two files
   answering one question differently; content that belongs one level down; an
   artifact whose own stated removal condition has been met.
4. **Wiring.** Directories the CI target does not run, entry points nothing calls,
   scripts nothing invokes, jobs for things that have left.
5. **Tracker rot** — only where a tracker exists and the project says how to read it.
   If its CLI ships a hygiene report, run that and carry the output; otherwise look
   for in-flight items whose pull request has merged, items missing what the
   project's own rules require of them, deferrals with no stated revival condition,
   and orphans.
6. **What smells.** A free slot: anything that looks wrong and the questions above
   did not ask about.

Git clutter — branches and worktrees — is not swept here; `/clean-up-git` owns it.

Rules every brief carries:

- No `| head` cap on an enumeration. A capped list hides the site you missed.
- A negative claim — "nothing references X" — carries the command that produced it
  and its empty output. Absence reported from one probe is a guess.
- Tracker reads only, through the CLI the project's instructions name; that CLI's
  read verbs are the whole allowance.
- Report what was checked as well as what was found: a question that found nothing
  says what it enumerated.

## 3 — Grade the grader

Before a finding enters the report, re-run its decisive check yourself — the grep,
the diff, the file's existence, the status line. A finding whose check does not
reproduce is dropped, reason kept in the report's appendix. A subagent's "matches
verbatim" or "referenced nowhere" is a claim, not a result, and a claim that would
drive a deletion is never carried on trust.

## 4 — Write the report

`<report dir>/<date>/RECOMMENDATIONS.md`, one recommendation per heading, in the
order the reader should act: highest confidence and smallest blast radius first.
Each states what to do (remove, archive, relocate, reconcile), the evidence with
paths and line numbers, what to verify by hand before acting, and what it costs to
leave alone. Findings that looked wrong and survived re-checking go in a "cleared"
section so they are not re-litigated next run.

If an earlier report exists, close with a delta: recommendations repeated from it,
marked with their age — a repeat escalates rather than re-argues; recommendations
resolved since; and what is new.

## 5 — Stop

Present the report's headings and stop. Do not act on a recommendation; the user
names which ones become tracked work.
