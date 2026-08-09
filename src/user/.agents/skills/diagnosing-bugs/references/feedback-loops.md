# Constructing and tightening a feedback loop

Phase 1 material. Read this when you do not yet have a command that goes red on
the bug, or when the one you have is slow, flaky, or vague.

## Ways to construct one — try them in roughly this order

1. **Failing test** at whatever seam reaches the bug — unit, integration, e2e.
2. **Curl / HTTP script** against a running dev server.
3. **CLI invocation** with a fixture input, diffing stdout against a known-good snapshot.
4. **Headless browser script** (Playwright / Puppeteer) — drives the UI, asserts on DOM/console/network.
5. **Replay a captured trace.** Save a real network request / payload / event log to disk; replay it through the code path in isolation.
6. **Throwaway harness.** Spin up a minimal subset of the system (one service, mocked deps) that exercises the bug code path with a single function call.
7. **Property / fuzz loop.** If the bug is "sometimes wrong output", run 1000 random inputs and look for the failure mode.
8. **Bisection harness.** If the bug appeared between two known states (commit, dataset, version), automate "boot at state X, check, repeat" so you can `git bisect run` it.
9. **Differential loop.** Run the same input through old-version vs new-version (or two configs) and diff outputs.
10. **Human-in-the-loop script.** Last resort — see below.

## Tighten the loop

Treat the loop as a product. Once you have _a_ loop, **tighten** it:

- Can I make it faster? (Cache setup, skip unrelated init, narrow the test scope.)
- Can I make the signal sharper? (Assert on the specific symptom, not "didn't crash".)
- Can I make it more deterministic? (Pin time, seed RNG, isolate filesystem, freeze network.)

A 30-second flaky loop is barely better than no loop; a 2-second deterministic one is tight — a debugging superpower.

## Non-deterministic bugs

The goal is not a clean repro but a **higher reproduction rate**. Loop the trigger 100×, parallelise, add stress, narrow timing windows, inject sleeps. A 50%-flake bug is debuggable; 1% is not — keep raising the rate until it is debuggable.

## When you genuinely cannot build one

Stop and say so explicitly, and list what you tried — the list is what lets the
user judge which of these to give you. Ask for one of:

- **access** to whatever environment reproduces it;
- **a redacted captured artifact** — HAR file, log dump, core dump, or a screen
  recording with timestamps;
- **permission** to add temporary instrumentation to production.

Do not proceed to hypothesise without a loop. An unfalsifiable fix shipped
against a bug you could not reproduce cannot be told from no fix at all.

## Human-in-the-loop script

Only when a human must physically click something. Driving them from a script keeps the loop structured and keeps the captured output in a form you can read back. Save this, edit the steps, and run it:

```bash
#!/usr/bin/env bash
# The agent runs the script; the user follows prompts in their terminal.
#   step "<instruction>"       → show instruction, wait for Enter
#   capture VAR "<question>"   → show question, read response into VAR
# `capture` prints its value back to the terminal, where the agent reads it — so
# capture observations, and leave signing in to the user as a `step`.
set -euo pipefail

step() {
  printf '\n>>> %s\n' "$1"
  read -r -p "    [Enter when done] " _
}

capture() {
  local var="$1" question="$2" answer
  printf '\n>>> %s\n' "$question"
  read -r -p "    > " answer
  printf -v "$var" '%s' "$answer"
}

# --- edit below ---------------------------------------------------------
step "Open the app at http://localhost:3000 and sign in."
capture ERRORED "Click the 'Export' button. Did it throw an error? (y/n)"
capture ERROR_MSG "Paste the error message (or 'none'):"
# --- edit above ---------------------------------------------------------

printf '\n--- Captured ---\n'
printf 'ERRORED=%s\n' "$ERRORED"
printf 'ERROR_MSG=%s\n' "$ERROR_MSG"
```
