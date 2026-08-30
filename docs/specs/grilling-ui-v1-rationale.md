# Grilling UI v1 — how the contract was arrived at

**Date:** 2026-08-18
**Companion to:** `docs/specs/2026-08-18-grilling-ui-v1.md`, which states the contract. This
record holds the evidence behind it and nothing normative. Where the two disagree, the spec
wins.

## Provenance

Every requirement in the spec was ratified by the owner across five prototype rounds. The
reaction ledger, the wire findings and the measured spike evidence live in
`docs/prototypes/grilling-ui/REACTIONS.md`, `LIVE-SESSION-REPORT.md` and
`spike5/SPIKE5-REPORT.md`. The binding copies are committed on branch
`prototype/grilling-ui` — rounds 1–3 at `04a88809`, round 4 at `c8146beb`, spike 5 at
`661fc5f0`. None of those paths exist on the default branch; they resolve only at the named
commits. The two files the spec binds implementation to — `grilling-ui-prototype-r5.html`
and `REACTIONS.md` — have been promoted to this branch, and the spec cites them by repo
path with no SHA, because they are now maintained artifacts rather than snapshots.

`spike5/backend.py` at `661fc5f0` is prior art for the protocol semantics — a reference
implementation, not a design to copy verbatim.

The spec supersedes the prototype transport, `BRIDGE.md` on branch `prototype/grilling-ui`,
wherever the two disagree. `BRIDGE.md`'s poll-every-few-hundred-milliseconds advice and its
`ok`/`accepted` acknowledgement are both explicitly reversed.

## The five rounds

1. **Rounds 1–3** (`04a88809`) — surface design against a canned agent living in the page
   on a timer. Three variants (map, queue, document) went to the owner; the verdict was a
   hybrid: the map canvas beside one blended column of answerable and settled decisions,
   bidirectional focus sync, threads as per-decision slide-outs, and a notifications list as
   the attention surface. Rounds 2 and 3 were fix rounds over that hybrid — auto-apply
   taxonomy, pending-update target locks, bubble overlays, and the scroll discipline.
2. **Round 4** (`c8146beb`) — the page over a mail-slot bridge, driven by a real harness
   subagent. This is where the transport failures were found, and where the page still owned
   the board.
3. **Spike 5** (`661fc5f0`) — a server-authoritative backend owning the log on disk and
   minting its own agents, with the page reduced to a renderer. This is where the
   architecture in §1 of the spec was measured rather than argued.

## Which decision came from which observation

| Spec requirement | The observation behind it |
|---|---|
| GUI-D1 (server authority) | Round 4's worst trap: the page re-emitted a hello mid-session carrying the board's *initial* definition, byte-indistinguishable from a genuine reset, and the live agent discarded correct state. |
| GUI-D2 (epoch and sequence) | Round 4's envelope seq and body seq diverged on page reload; the live agent had to guess which one `basedOnSeq` meant. |
| GUI-D3 (two images) | Round 4 gave the agent only deltas after hello, so it reconstructed board state itself and got it wrong. |
| GUI-D4 (image 2 crosses whole) | The spike's first projector trimmed settled decisions out of a dispatch to save tokens, and a dispatched agent lost a decision the human had settled minutes earlier. The loss was undetectable downstream, which is why v1 has no elision path at all. |
| GUI-D6, GUI-D7 (handoff inversion) | Round 4's page-owned board could not survive the browser leaving; spike 5 inverted it and `spike5/HANDOFF.md` is the shape the spec's handoff schema normalises. |
| GUI-D11, GUI-D12 (tiers and escalation) | Round 4's live session ran on a single heavy agent and the owner's reaction was that responder latency is partly model choice. The spike then measured both tiers, and observed a fast model asked to judge its own competence answering anyway — on a question the human had explicitly said they could not resolve. |
| GUI-D13 (mechanical status lane) | The live session's top-priority ask was a thinking indicator; the spike measured the status lane at 0–1 ms against 1 s and 12–34 s agent turns. |
| GUI-D16 (uniform receipts) | Round 4's bridge returned `ok`/`accepted` over a silent no-op, which let the agent tell the human something was on the board when it was not. |
| GUI-D19 (update kinds) | The live agent's own priority list: thinking indicator, real add-node with payload echo, rationale text on invalidate, a state read, and a rejection receipt. |
| GUI-D20 (thread shapes) | The round-4 backend was written against one of the page's two thread shapes; a scripted check passed while the real UI path was rejected. |
| GUI-D21 (atomic fold) | The live session rated the fold the best part of the protocol. The prototype also rewrote an agent-supplied basis sequence at fold time without saying so — hence the receipt clause. |
| GUI-D22 (no agent polling) | The spike's latency anatomy: ~80% of a 20–90 s reaction was composing the structured update, and a reaction cost a minimum of three round-trips. Sub-second polling advice is unusable for anything paying per poll. |
| GUI-U1–GUI-U10 (UI mandates) | The round-4 owner reactions, item for item: waiting visibility, timestamps, concision, floating thread chrome, labelled options with notes, hover-hide-on-click, one main window, the three-signal connection indicator, Discuss on informationals, mark-all-read. |

## Measurement circumstances

- **Every heavy-tier cost and latency figure in the spec was measured at Sonnet weight**, deliberately,
  to keep the bill honest during the spike. They are a floor for a heavier default, which is
  why the spec's open question about the heavy tier's default model exists at all.
- The heavy-tier figures — $0.576 cold, $0.054 resumed, 6.5 s standalone, 12–34 s under load
  — come from spike 5's own runs, on one machine, over loopback. The 10× cost drop and 2.7×
  speedup on resumed turns are the same measurement, which is what makes the cache TTL an
  architectural input rather than a tuning detail.
- The fast-tier figures (~1 s, $0.0002–$0.0008 per turn) are OpenRouter-hosted non-Claude
  models measured in the same spike.
- The status-lane figure (0–1 ms) is measured from the log's own timestamps, not wall clock
  around the call.

## Decisions the owner reversed after the first draft

The spec carries the current position; these are the reversals, so nobody re-derives the
superseded one from the prototype record.

- **Per-side-thread agents moved from deferred to in scope.** Each thread is its own channel
  with its own agent context, defaulting to the first rung's seat for that channel
  (GUI-D46).
- **Human-initiated escalation moved from deferred to in scope**, as the transfer-to-expert
  control. The agent recommends; the human decides.
- **The clean decision-log projection moved from deferred to in scope**, as the core of the
  capture skill.
- **Image 2's token budget was dropped entirely.** The first draft carried a budget with an
  elision-marker escape; v1 carries a completeness contract with no elision path, and the
  machinery is deferred behind a real session hitting a context limit.
- **Autonomous escalation left v1 entirely.** The restructure briefly kept an
  agent-initiated upgrade path beside the human-gated control; the same criteria drove
  both with no discriminator, and the owner resolved it human-gated only, with autonomous
  escalation deferred behind sessions where the human accepts essentially every
  recommendation — superseded by GUI-D35, under which the escalation policy is session
  configuration taking `gated` or `autonomous`, defaulting to `gated`.
- **The thread-agent context became a named projection.** Image-2-whole for every dispatch
  contradicted thread isolation; the owner resolved it as a per-thread projection — own
  thread in full, other non-parked threads as stubs carrying decision id, title, status
  and the folded conclusion, parked threads absent — with the completeness contract
  binding settled decisions in every dispatch of any kind.

## Retired identifiers

Requirement and criterion ids are never renumbered or reused; deleted items leave gaps.

- **GUI-A4** — the elision-marker criterion. Retired with the budget language it checked.
- **GUI-A15** — the test-suite self-count criterion. Retired as a property of the harness
  rather than of this system.
