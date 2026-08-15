---
name: orchestrating-teammates
description: Use when running named teammate subagents and deciding what their silence means — a teammate's idle notification arrived but no FINAL REPORT message did, a report's delivery status is unclear, a stop-noncompliance marker or report-gate state directory needs reading, or you are about to ping, re-spawn, or give up on a quiet teammate. This skill owns diagnosing the silence, including the idle-without-report case instructing-subagents also lists; that skill governs only writing or rewriting the dispatch brief.
admission:
  prevents: An orchestrator mishandling a silent named teammate — repeated pings that return only further idle notifications, prose deliverables lost although composed verbatim in the teammate's own transcript, and delivery decisions blocked on a report that was never going to arrive.
  cost: Accurate only while the teammate-report-gate hook ships in the deployed settings — edit or retire the two together.
  remove_when: The harness delivers a teammate's report with its idle notification (or otherwise guarantees message-content delivery), or the teammate-report-gate hook is retired.
---

# Orchestrating Teammates

Two mechanical facts govern everything here:

- A named teammate transmits content **only by an explicit SendMessage tool call**.
  Text it composes as a plain final message is never delivered anywhere. The
  automatic idle notification is a separate event that carries no content and says
  nothing about whether a report was sent — a teammate can believe it reported and
  be wrong.
- Delivery therefore leaves observable traces, and silence is investigated through
  them — not by asking the teammate.

## Dispatch

Write the brief per `instructing-subagents`. The reporting contract MUST command
delivery as a SendMessage call carrying the markers — progress messages beginning
`UPDATE <n>:`, the deliverable beginning `FINAL REPORT:` — plus the written report
file. The `teammate-report-gate` hook enforces exactly this protocol when wired in
settings (`TaskCompleted`, `TeammateIdle`, `PostToolUse` on SendMessage): a task
completion is refused until an UPDATE is sent, idle is refused until the FINAL
REPORT is sent, and after three refused idles the teammate is released and a
noncompliance marker is dropped for you to find.

## When an idle notification arrives

If the FINAL REPORT already reached you, the trailing idle notification warrants no
reply. Otherwise investigate before touching the teammate, in this order:

1. **Gate state**: `/tmp/claude/teammate-report-gate/<project-dir-slug>/<session-id>/`
   (slug = cwd with every non-alphanumeric character replaced by `-`). Read
   `<name>.json` — `final_delivered` settles whether a report was ever sent — and
   `<name>.stop-noncompliance.marker`, which means the gate gave up and points at
   the transcript.
2. **The mandated report file** from the brief.
3. **The teammate's own transcript**:
   `~/.claude/projects/<project-dir-slug>/<parent-session-id>/subagents/agent-*.jsonl`.
   A stranded report is usually composed there verbatim in the final assistant
   turns — lift it; never re-spawn an agent to regenerate a report that already
   exists on disk.
4. **The tree itself**, for code work: `git status`, the diff, and the gate's own
   exit status outrank any self-report.

Ping at most once, and only for judgment the transcript cannot answer — choices it
made, coverage it dropped deliberately. Command the reply as a SendMessage call
beginning `FINAL REPORT:`; a ping recovers content only when the teammate replies
through the tool. A second silent idle means stop pinging — `TaskStop` it and
proceed on what the traces gave you.

## Prose-only deliverables

A review or critique teammate's only deliverable IS the report — there is no tree
to fall back on. Never let a delivery decision wait on that report arriving:
mandate the report file at dispatch, treat the SendMessage as confirmation, and
when it goes quiet start at the transcript, where the judgment usually survives.
