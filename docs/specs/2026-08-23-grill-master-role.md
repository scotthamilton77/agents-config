# The grill-master's role — a re-examination against the grilling-UI v1 spec

**Date:** 2026-08-23
**Status:** Ruling, with the spec amendment it implies. Amends
`docs/specs/2026-08-18-grilling-ui-v1.md`; changes no code by itself.

## 0. Ruling

**(a) — the spec is amended.** The prompt and code drift found here is real and is listed,
but it is not the whole defect. Two things the incident turned on are the spec's own
design, stated in so many words: the obligation a killing answer carries admits only an
`invalidate` per named id (GUI-D42: "one the turn only narrated is still on the frontier"),
and the agent on the map channel is briefed by its tier, not its role (GUI-D11: "The fast
tier facilitates discussion"). A spec that stands would have produced the same step 3, the
same step 4 and the same step 5 with a better-behaved model in the seat, because the prompt
gave the model nothing else to say and the checker would not have credited it if it had.
Ruling (b) fails its own test — it cannot show, per incident step, how the unchanged spec
would have produced a different outcome — so (b) is not taken.

What changes, in one line each: the grill-master is briefed as the map's author on either
tier; every map turn is a document with a closed shape, in which a ruling of *stands* is a
first-class, credited answer; the grill-master is given the one part of the house grilling
method the board does not already mechanise; the map channel's default tier is configured
apart from the threads' and defaults to the heavy tier; `puts_in_question` means what it
says — a prediction the grill-master rules on — everywhere it appears; and a thread agent
is told how to read a board that moved.

## 1. What the spec makes the grill-master for

Derived from the use cases and criteria, each with its source. Nothing here is asserted
from the vocabulary paragraph alone.

1. **The author of the map's evolution, and the only one.** Vocabulary ("owns the map and
   is the only agent that authors changes to it"); GUI-D25 (sole author; thread agents
   recommend); GUI-D19 (the update kinds are what it does: add-node, invalidate with
   rationale, revise, unsettle, settle, informational, elicit-alert); GUI-A37.
2. **A responder to human board gestures, never an initiator.** GUI-D14 ("Only a human
   turn is owed a reply"); GUI-D22 ("The orchestrator decides when any agent gets a
   turn"); the lane's answerable kinds are `answer`, the thread kinds and `thread-fold`.
   Its turns are: an answer (GUI-D38/D42 — "the turn the answer bought"), a fold
   (GUI-D25, GUI-A99), a withdrawal conflict (GUI-D26, GUI-A39), the doctor (GUI-U12).
3. **The judge of what a gesture costs the rest of the board.** What an answer moots
   (GUI-D38); what an applied invalidate strands, where *revise* is a legal way out because
   "a decision resting on one that died may well survive the loss" (GUI-D38 ¶2, GUI-D43);
   what a thread conclusion costs — "fold it in as updates, or take it as context and say
   so" (GUI-D25, GUI-A37).
4. **The keeper of the queue.** Every dispatch carries the pending queue; it supersedes its
   own and reconciles a withdrawal the human got in front of (GUI-D26).
5. **The predictor of downstream cost when it authors.** It writes `puts_in_question` on
   the nodes it adds or revises (GUI-D37).
6. **The judge of completion.** `stop_when` is "the condition under which the grill-master
   should treat the grilling as complete" (Vocabulary, GUI-D7); it says so and does not
   end the session (GUI-D10).
7. **The adversary.** "An agent adversarially questions it, decision by decision, until
   every decision is either settled or explicitly parked with a named blocker" (§0);
   `posture` is "how adversarially to grill" (Vocabulary, GUI-D7).
8. **A raiser of loose ends.** A parked thread is one "the grill-master may raise again"
   (GUI-D29).
9. **A writer of notices, not a conversationalist.** Its prose is bounded to two or three
   plain sentences (GUI-U3, GUI-U26), lands as an informational with a Discuss control
   (GUI-U9), and framing about a decision renders on that decision (GUI-U15). In code the
   map reply's `text` is recorded as an `informational` — a queue item — and no event kind
   lets the human type on the map channel; the map thread (GUI-D40) is a thread with its
   own agent.
10. **An agent whose reply is measured in code.** GUI-D42: the mootness reply "is measured
    against the same list in code".

**Where the spec pulls in different directions.**

- *"The driving agent"* (Vocabulary) against items 2 and 4 of this list, GUI-D40 (the
  human steers the map through a thread agent) and the Vocabulary's own "backend
  (equivalently, the orchestrator)". The grill-master drives nothing: the board's
  frontier drives, computed in code (GUI-D43). "Driving" can only mean "authoring".
- *The mandate is the tier's* (GUI-D11: "The fast tier facilitates discussion ... stops
  short of deciding") against items 1, 3 and 10, which put a decision on whichever tier
  takes the map turn. GUI-A88 presumes a "grill-master's standing brief, on the fast tier
  and on the heavy one" that the spec never states. On the fast tier, the map's author is
  told to stop short of deciding on the one turn whose whole work is a ruling.
- *"Put in question"* (GUI-D37, GUI-U25: "would put this in question") against *"a killing
  answer"* (GUI-D42) and *"moots"* (GUI-D38), bound together by GUI-D42's first sentence.
  The name says doubt; the obligation says death. The plan in evidence uses the name both
  ways: d1.a names d2 while its own `pcr` says it "weakens the case for a shared checker
  engine" (a shift, not a kill); d2.c names d3 and "subsumes the scope-and-exemption
  question" (a kill).
- *"A channel is one conversational lane ... one for the map"* with GUI-U3's sentence cap
  against item 9: the map channel has no human composer, so the grill-master's prose is
  addressed to nobody who can answer on that channel. Discuss opens a different agent's
  thread (GUI-U9), which is step 6 of the incident.

**Where the spec agrees with itself**, and the amendment leaves alone: the sole-author
rule is restated by GUI-D25, D31, D34, D39, D40, D41 and D42 identically; the human
applies every withdrawal (GUI-D26, D37, D38, D42); ending is the human's (GUI-D10, U17).

## 2. The evidence, read

The session is `portable-prose-gates` (tracker `9k9.284`), five decisions d1–d5; d2's
`prereqs` are `[d1]`, d3's `[d2]`, d4's `[d1, d3]`, d5's `[d1, d2]`. Option d1.a carries
`puts_in_question: ["d2"]`. Log sequence numbers are the session log's.

### 2.1 The grill-master's dispatch (recorded at seq 4, answering the answer at seq 2)

**What it received.** The system prompt opens "You facilitate the discussion. Answer from
the context you were given, quickly, and keep the human moving. The moment a question
crosses into reasoning, decisioning or implied design, stop short of deciding it" — the
fast tier's prompt; no sentence names it the grill-master. Then the no-manufacture rule,
the three-sentence cap, the dialogue rule, the one-turn rule, the mutation format ("reply
with a JSON object carrying `text` ... and `updates` ... Reply with plain prose when you
are proposing nothing"), the standing mootness rule, the basis rule, the supersede rule and
the register rule. The user prompt carries `## Briefing` (statement, impetus, context,
constraints, posture, stop_when), `## The board, whole` (the dispatch context as JSON: d1
settled on option a with the human's note; d2–d5 open; frontier `[d2]`; pending `[]`;
history d1 answered at seq 2; no threads; `mootness` with target d1, the answer text, ids
`[d2]`, cause `answer`), `## This channel (map), in order` (one line: the human's note),
and `## What the answer you are replying to puts in question`: "The human answered d1 with
'(a) plus the results ...'. That option names d2, and the board is still offering it.
Propose an `invalidate` for each decision named above, in this turn, carrying that answer
as its `why`. The human's own answer is what killed them ... Saying they are dead is not
proposing it."

**What it could not have known from that.** That the mark on d1.a was written as a
prediction that d2's balance shifts — the `pcr` line that says so is inside the board's
bytes, but the obligation section overrides it with "killed". That a prose "d2 stands"
would not be credited: it would cost an expert turn and a notice telling the human
something was left undone. That it is the map's author at all, or that a ruling is what
the turn is for. That invalidating d2 frees d3 and d5 onto the frontier on a footing that
has gone (GUI-D43 is nowhere in its prompt).

**What it did with it.** In 1.1 s it returned a fold (seq 5): an informational — "Option
(a) commits us to a coverage-carrying evidence schema, which turns d2 into the central
question of whether we ship vocabulary, a shared engine, or a declarative artifact
schema." — and `invalidate d2`, basis 4, `why`: "Answered d1 with option (a) plus results;
d2 must now be answered to determine what the portable artifact actually is under that
evidence contract." It obeyed every rule it was given: one invalidate per named id, the
answer as the why, basis carried, under three sentences. Its content dissents from its own
form — a rationale that says a decision must now be answered is a `stands` ruling wearing
an `invalidate`. The log attributes the turn to the fast tier, 5 923 prompt tokens.

### 2.2 The side thread (dispatches at seq 10, 15 and 20)

For a reader who has not seen them: a thread agent's prompt is the thread-agent mandate
("You are a side-thread agent ... You recommend and never author changes to the map ... If
the human asks you to change the map ... say plainly that you cannot"), then the same
fast-tier prompt the grill-master got — facilitation first — then the convergence rule and
the register rule. Its user prompt is the briefing, the board as a thread projection, its
own thread's turns, and "Answer the last thing the human said". Nothing in any of it says
what `puts_in_question`, `pending`, `history` or `rationale` are.

**Dispatch at seq 10.** Received: the board after the invalidate was applied — d1 settled;
d2 `invalidated`, `rationale` verbatim "Answered d1 with option (a) plus results; d2 must
now be answered ..."; frontier `[d3, d5]`; pending one `informational` with a null target
(the grill-master's notice, the one this thread was opened from); history for d2: an
`invalidate` at seq 7, actor `human`; the thread itself, kind `notice`, `decision: null`,
one turn quoting the notice. Also, inside the JSON, 7 313 characters of `help_reference` —
"Driving the board ... You are not grilling their plan and you do not touch the board" —
handed to it because the code gives the board's help material to any thread with a null
anchor that is not the map thread. Could not have known: why the grill-master proposed the
invalidate (the obligation is a map-channel field; the thread projection carries none);
that the pending notice is the text it was opened about; that an `actor: human`
invalidate is the human applying an agent's proposal (the proposing entry at seq 5 is not
in the image). Did: answered the notice as a design point, two sentences, no question.
Sound on its own terms.

**Dispatch at seq 15.** Received: the same board plus two turns; the human now asks "isn't
defining what the coverage record contains a discussion about vocabulary, the engine, or
artifact kind schema?" — which is d2's title, asked by a human noticing d2 is alive. Did:
"It is precisely that discussion" — affirming that d2's question is live, against a board
in its own context that says d2 is invalidated with a rationale saying it must be answered.
The contradiction was in front of it and it did not name it. Could not have known: nothing
new; what it lacked was any instruction that the board's record of *why* is what a "why"
question is answered from.

**Dispatch at seq 20.** Received: the same plus two turns; the human: "I don't understand
why T2 was kicked out of the flow." Could have known, from the bytes it held: d2 is
`invalidated`; its `rationale`, verbatim; history: invalidate at seq 7 by the human;
d2's `prereqs` are `[d1]`; d1.a carries `puts_in_question: ["d2"]`. Could not have known:
what the mark means; that the backend obliged the invalidate; that the human's "kicked
out" is the apply gesture they made themselves. Did: "T2 was invalidated because decision
d2 depends on the outcome of decision d1, and d1 was settled with an option that altered
the premise of d2. You must now settle d2 to determine whether ..." The first clause is
supported — d1 is in d2's prereqs. "Altered the premise" is in no record it held; the
rationale it held says the opposite. "You must now settle d2" tells the human to answer a
decision its own board says is invalidated and off the frontier. It quoted nothing. The
no-manufacture rule it carried was not enough to make it read the record for the answer.

## 3. The hypotheses, each with a verdict

Classification: **drift** is code, prompt or skill disagreeing with the spec; **gap** is
the spec itself being silent or self-contradicting.

1. **Three meanings ride on `puts_in_question`.** Confirmed. The schema's `Option`
   docstring says "display data and nothing else" — stale against GUI-D42 ("Taking it is
   what makes it more than display data"): drift. The skill says "Where an option would
   reopen another decision": drift, and a third meaning again (reopen is what `unsettle`
   does). The obligation reads the list as killed: that is GUI-D38/D42, the spec. Under it
   sits a **gap**: a field named for doubt carrying a semantics of death, which the plan
   author in evidence used in the plain sense (§1, third bullet).
2. **The obligation admits a verdict, not a choice.** Confirmed, and it is the spec's
   design: `DISCHARGING` credits an answer's list only with `invalidate`; `outstanding()`
   reads the pending queue and nothing else; `_press_mootness` treats a prose "it stands"
   exactly as silence. GUI-D42 says so. **Gap.**
3. **The grill-master inherits the tier's "facilitate" line though its inputs are events
   and its outputs mutations.** Confirmed: `system_prompt(tier, agent)` joins
   `SYSTEM_PROMPTS[tier]` to the role's rules, and the grill-master mandate is a member of
   the heavy prompt only. Checked for all four pairs: the fast grill-master carries the
   facilitation mandate and no grill-master line; the heavy thread agent carries "You are
   the grill-master ... the only agent that authors changes to the map" beside "You
   recommend and never author changes". The tests pin it
   (`test_the_fast_prompt_carries_the_facilitation_mandate_and_stops_short_of_deciding`,
   `test_the_heavy_prompt_leaves_ending_the_grilling_to_the_human`). **Gap** — GUI-D11
   hangs the mandate on the tier and no decision states the grill-master's brief — **and
   drift**: a heavy thread agent told it is the sole author contradicts GUI-D25 and the
   spirit of GUI-A89, which passes because it checks for the refusal text and not against
   its contradiction.
4. **The output contract is soft.** Confirmed: the mutation-format rule ends "Reply with
   plain prose when you are proposing nothing"; `declared_updates` returns anything not
   shaped `{text, updates|supersedes|proposed_answer}` as prose, so a document with a
   misspelt key is shown to the human as raw JSON; the fast request carries no structured
   output request. **Gap**: §8 fixes the thread agent's `proposed_answer` (§8.9) and says
   nothing about the grill-master's reply document.
5. **No method; nobody drives.** Confirmed. The fast grill-master receives no role at all;
   the heavy one receives an aim ("interrogate the plan decision by decision ... Push on
   the axis the posture names") and no procedure for a turn. "Nobody drives" is by design
   and stays so — GUI-D14/D22 make every agent a responder and the frontier is code. What
   is missing is what a responder does with an answer. **Gap.**
6. **The map's sole author runs on the lightest model with thinking off.** Confirmed:
   `DEFAULT_FAST_MODEL` names a lite-tier model; `request_body` sends no reasoning
   parameter; `tier_for` puts every channel on the fast tier until a transfer. GUI-D11
   and D24 default the fast tier per channel, and §10 leaves the heavy default open;
   nothing weighs the map's author separately from a thread's. **Gap.**
7. **Thread agents reason blind about board changes, and a notice thread has no anchor.**
   Confirmed (§2.2). The anchor is null because `record_reply` records the map `text` as an
   untargeted informational and the page anchors a Discuss thread on the notice's target.
   Two drifts beside the gap: `help_reference` reaches `notice` threads (the test for
   GUI-A95 checks the map thread only), and the `notice` kind the page emits is absent
   from §8.5's list. **Gap and drift.**
8. **The spec is ambivalent — owner of the map, yet one conversational lane under the
   three-sentence register.** Confirmed as written (§1, fourth bullet). **Gap.**

## 4. The seven questions, ranked by how much of the defect each carries

**1 — Q4 and Q2 together: strict JSON, always; the enumerated set with a reason.** Yes.
The map channel is not a chat: its prose is recorded as a queue notice (`record_reply`),
the human cannot type on it, and the soft contract's fallback shows a mistyped document to
the human as prose. Q2 dissolves into Q4: the enumerated set already exists — the update
kinds of GUI-D19 — and what is missing is the null action with a reason. A ruling
vocabulary of `invalidate | revise | stands`, each with a `why`, inside one document shape,
is the whole of Q2 and most of the incident (§5.2).

**2 — Q3 and Q7 together: the role.** It did see itself as a discussion agent, because the
first sentence it read told it to, and the spec states no grill-master brief for the tier
prompt to defer to. The human did not misunderstand the purpose; one word collides with
the spec's vocabulary — *orchestrate* is the backend's, and the spec's own word for the
grill-master is *author*. "Orchestrates the evolution of the map" is exactly item 1 of §1.

**3 — Q5: the method.** Give it the one step of the house method the board does not
already do. The `grilling` skill, read at `/Users/scott/.claude/skills/grilling/SKILL.md`
(its body is byte-identical to `src/user/.agents/skills/grilling/SKILL.md`; the source
copy differs only by its admission front matter and provenance comment), instructs: map
the plan as a design tree; work it in rounds; the question frontier is every decision whose
prerequisites are settled; ask the whole frontier with a numbered marker and a recommended
answer; "Each round of answers reshapes the tree — settled decisions push the question
frontier outward"; finding facts is the agent's job, never the user's; the exit criterion
is an empty frontier plus acceptance criteria with stable IDs, each red-test convertible,
each run through an edge-case taxonomy. Of that, the backend mechanises the
tree (the map), the frontier (GUI-D43, in code), the round (the board is always the
current round), the numbered marker (decision ids) and the recommendation (`options[0]`).
Fact-finding is structurally unavailable: a turn is one call with no tools, and the
handoff's `context` plus the no-manufacture rule stand in for it. The exit criterion does
not apply: a UI session ends on `stop_when` (GUI-D7/D10), and the skill's AC enumeration is
a different session's contract. What is left is the reshape step, and that is what the
grill-master is not told: on an answer, say what it settled, what it puts in question and
how each of those is ruled, what it implies that the map lacks, and whether the stop
condition is met. That is §5.3, and it is three sentences, not the skill.

**4 — Q6 and Q1 together: its own model and effort.** Yes, per agent, not per tier. Q1
dissolves into Q6: the evidence does not show under-weighting as the cause — the fast
agent did exactly what a prompt with no other legal answer asked, in one second. Three
observations on the fast tier on the map channel stand beside it (GUI-D42's two-sentence
reply to eight moots, GUI-D12's generous self-judgement, this one), and none separates
weight from prompt. Weight becomes testable once `stands` exists: replay the recorded
dispatches through both tiers and compare rulings. Until then the map's author defaults to
the heavy tier (§5.4), and the fast tier gains an effort setting for the turns it keeps.

## 5. The amendment

Each item below is wording for the v1 spec; the decision ids continue its numbering.

### 5.1 The role

**GUI-D44 — The grill-master is briefed as the map's author, on either tier.** A standing
brief has two parts and they vary independently: the tier's part says how a turn is taken
— answer from the context given, assert nothing it does not support, write for one reading,
take one turn and stop — and the role's part says what the turn is for. The grill-master's
role part, stated to it first and on both tiers: *You are the grill-master: the author of
the map and the only agent that changes it. The human answers decisions; you rule on what
each answer does to the rest of the plan and keep the map honest after every gesture. Push
on the axis the posture names. You speak to the human only in notices; when you judge the
stop condition met, say so, and leave ending the session to them.* A thread agent's role
part is GUI-D24's and GUI-D39's, on both tiers, and carries no sentence of the grill-master's.
Keying the role to the tier is refused: it puts the map's author under "stop short of
deciding" on the turn whose work is a ruling, and hands the sole-author line to a thread
agent the moment the human transfers its thread.

### 5.2 The output contract

**GUI-D45 — Every grill-master turn is a document of one shape, and a ruling is a
first-class answer.** The shape is §8.10. There is no prose mode: `text` is the notice the
human reads (GUI-U3 bounds it; it may be empty when the board already says everything,
GUI-U15), `updates` are the map mutations, `supersedes` the withdrawals, `rulings` the
turn's judgement on decisions a gesture put in question, and `stop` whether the stop
condition is met. A reply that does not validate is refused and retried once
on the same tier with the refusal quoted, then handed to the expert once, then recorded as
a backend `informational` naming the failure; it is never shown to the human as prose. The fast
transport asks the provider for the shape where it can, and both drivers validate what
comes back. A ruling names a decision, one of `invalidate`, `revise` or `stands`, and a
`why`. An `invalidate` or `revise` ruling is credited only when the same document carries
that update targeting that decision; a `stands` ruling is credited by its `why`, which the
driver records as an `informational` targeted at that decision, so it renders on the
decision (GUI-U15) and a Discuss from it anchors there. Rulings may name decisions the
dispatch did not; the check is only that every decision the dispatch named is ruled.

**§8.10 — The grill-master reply document.** One object, every map turn, under §8's rule
that an unknown key is a rejection:

- `text` — string; may be empty. The notice to the human, bounded by GUI-U3.
- `updates` — array; may be empty. Each entry is one GUI-D19 update: `kind`, `target`
  where the kind has one, `basis` (the board's `seq` as dispatched) and `why` where the
  kind carries a rationale — `invalidate` always does.
- `supersedes` — array of pending ids; may be empty.
- `rulings` — array; may be empty on a dispatch naming nothing. Each entry: `decision`
  (string, a decision on the board), `ruling` (`invalidate`, `revise` or `stands`) and
  `why` (string, one line, non-empty). Every id the dispatch's obligation section names
  must appear once; ids it does not name may.
- `stop` — object: `met` (boolean) and `why` (string, empty while `met` is false).

The driver records `rulings` and `stop` as keys on the turn's own log entry, the way a
thread turn carries `proposed_answer` (GUI-D31), and mints one `informational` targeted at
each `stands` ruling's decision inside the same entry.

The incident's case — the grill-master judging that d2, named by d1.a's mark, stands:

```json
{
  "text": "Option (a) fixes what a gate must report; d2 is now the central question.",
  "updates": [],
  "supersedes": [],
  "rulings": [
    {
      "decision": "d2",
      "ruling": "stands",
      "why": "(a) fixes the evidence contract, not what ships it; d2 asks what is portable."
    }
  ],
  "stop": {"met": false, "why": ""}
}
```

The same gesture where the mark was a kill — d2 answered with option c, whose mark names
d3, which c subsumes:

```json
{
  "text": "A declarative kind schema owns scope, so d3 has no separate answer left.",
  "updates": [
    {
      "kind": "invalidate",
      "target": "d3",
      "basis": 12,
      "why": "d2 answered with (c): the kind declaration owns scope, which is all of d3."
    }
  ],
  "supersedes": [],
  "rulings": [
    {"decision": "d3", "ruling": "invalidate", "why": "subsumed by the kind declaration"}
  ],
  "stop": {"met": false, "why": ""}
}
```

What the driver records for the first document, as the turn's log entry — a fold carrying
the notice, the targeted informational minted from the ruling, and the ruling itself:

```json
{
  "kind": "fold",
  "actor": "grill-master",
  "channel": "map",
  "payload": {
    "updates": [
      {"kind": "informational",
       "text": "Option (a) fixes what a gate must report; d2 is now the central question."},
      {"kind": "informational", "target": "d2",
       "text": "d2 stands: (a) fixes the evidence contract; d2 asks what is portable."}
    ],
    "rulings": [
      {"decision": "d2", "ruling": "stands",
       "why": "(a) fixes the evidence contract, not what ships it; d2 asks what is portable."}
    ],
    "stop": {"met": false, "why": ""},
    "tier": "heavy"
  }
}
```

**GUI-D42 is amended** to read its check off the rulings: the dispatch still names the ids
and quotes the answer, and now states the three rulings; a reply leaving any named id
unruled hands the turn up once, narrowed to what is unruled; a second reply that rules on
nothing raises the notice, which now says the decisions were *not ruled on*, not that no
invalidate was proposed. An answer's list and an applied invalidate's list take the same
three rulings — `stands` is the way out GUI-D38 ¶2 describes for a dependent that keeps
the dead prereq and survives, and `revise` stays the way out for one that drops it.

**GUI-D38 is amended** to oblige a ruling per decision the answer puts in question, with
`invalidate` where it is moot; narrating a decision as dead without ruling it remains
refused, and so does ruling it dead while saying it must be answered: the `why` of an
`invalidate` is shown on the decision and has to justify a death.

### 5.3 The method

The grill-master's brief carries the reshape step, on both tiers, as the procedure for
every turn: *An answer settles its decision; say what else it did. Rule on every decision
the dispatch names and on any other the answer undermines — dead, changed, or standing,
each with one line of why. Where the answer implies a decision the map lacks, add it with
its prerequisites and what its options would put in question. Say whether the stop
condition is met.* Nothing else of the `grilling` skill crosses: the tree, the
frontier, the round and the recommendation are the board's, fact-finding is impossible in
one call, and the acceptance-criteria exit is not this session's.

### 5.4 Per-agent model and effort

**GUI-D46 — Which tier takes a channel's first turn is configured per agent, and the map's
author defaults to the heavy tier.** Beside the two model ids, the heavy effort and the
escalation policy sit two more settings: the map channel's default tier, `heavy` unless
set, and the thread channels' default tier, `fast` unless set. A fast-tier effort setting
is passed to the provider where the model takes one, unset by default. The transfer
control already reads the channel's mode (GUI-U22), so a map that starts on the heavy tier
offers *Return to fast agent* from its first paint and the human can take it there. The
grill-master's heavy turns use the configured heavy model and effort; a separate effort
for the map is not added until a session shows the shared one wrong in one direction —
a human naming the map's latency as why they stopped answering, or a ruling at lower
effort that a replay at higher effort reverses. Cost, stated so the default can be
re-made: a resumed heavy map turn runs about $0.054 and 12–34 seconds per human gesture,
against roughly $0.0005 and a second on the fast tier; a five-decision board pays under a
dollar, and the waiting clock is what the human sees while it thinks. The observation
that reverts the default:
over the recorded dispatches of three sessions, the fast tier's rulings replayed against
the heavy tier's agree on every decision named.

### 5.5 What thread agents are told about board changes

**GUI-D47 — A thread agent is told how to read a board that moved.** Its brief carries a
board legend, on both tiers: a decision's `status`, `rationale` and `history` are the
record of what happened to it and why, and a question about why the board moved is
answered by quoting them or by saying the record does not say — never by inferring a
cause; `prereqs` is what a decision waits on, and `puts_in_question` on an option is the
plan author's prediction that taking the option puts those decisions in question, which
the grill-master rules on — a mark, not a dependency; `pending` is what the human has not
dealt with, including a notice this thread may have been opened from; a map change in
`history` carries `proposed_by` — the agent whose queued update the human's apply landed —
and, where a ruling produced it, that `verdict` and its why (§8.6's entry gains both
fields), so who proposed a move and what was ruled is quoted, never inferred. A thread opened
from a notice is kinded `notice` and anchors to the decision the notice targeted, null
where the notice targeted none; §8.5's kind list gains `notice`. `help_reference` crosses
to the `help` kind and to no other — not to a `notice` thread anchoring nothing.

### 5.6 The handoff field

§8.2's `puts_in_question` reads: *optional array of decision ids that taking this option
puts in question — decisions that may die, change or turn on something else once it is
taken. The page pre-marks them while the option is in hand (GUI-U25); the grill-master
rules on each when the human takes the option (GUI-D45); an id resolving to no node is
ignored.* The skill's sentence becomes: *Where taking an option would put another decision
in question — kill it, change what it asks, or shift what it turns on — name that decision
in `puts_in_question`: the board pre-marks it while the human holds the option, and the
grill-master rules on it when they take it.* The example in the skill is unchanged and
still valid; the field in the plan in evidence, read under this wording:

```json
{
  "id": "a",
  "text": "Coverage-carrying evidence: the gate reports what it read; the panel refuses the rest.",
  "pcr": [
    "Vacuity becomes mechanically detectable rather than a matter of reviewer alertness.",
    "Every gate must be taught to emit its coverage set, and 'read' needs a definition.",
    "Demotes the capability name to a label, which weakens the case for a shared checker engine."
  ],
  "puts_in_question": ["d2"]
}
```

The schema docstring on `Option` says the same thing as §8.2, which it does not today.

## 6. The incident, replayed under the ruling

1. **The handoff marks d1.a with `puts_in_question: ["d2"]`.** Nothing changes in the
   handoff: the mark was right under §5.6 — (a) shifts what d2 turns on. The skill's
   sentence now tells the author what the mark obliges, so the intent and the mechanism
   agree. Acceptable as is.
2. **The human answers d1 = a with a note.** Nothing changes; the gesture is the same.
3. **The backend computes the obligation and briefs the grill-master.** The dispatch goes
   to the heavy tier by default (GUI-D46); its system prompt opens with the role and the
   reshape step (GUI-D44, §5.3); the obligation section names d2, quotes the answer and
   states the three rulings (GUI-D42 as amended). The section can no longer say "killed".
4. **The agent replies.** The reply is a document (GUI-D45) and must rule on d2. The agent
   that wrote "d2 must now be answered" has `stands` and is credited for it; if it still
   rules `invalidate`, the `why` is shown on d2 and has to say why d2 is dead.
5. **The human applies it.** Under `stands` there is nothing to apply: d2 stays on the
   frontier, and its targeted notice says why, on d2. Under a still-wrong `invalidate`
   nothing stops the human applying it — the queue is their gate (GUI-D26) — which is
   acceptable: the rationale they apply is now one that argues for a death, and the
   applied invalidate obliges the next map turn to rule on d3 and d5 (GUI-D38 ¶2), where
   `stands` is again available.
6. **The human opens a thread from the notice and asks why d2 was removed.** Opened from
   the ruling's notice, the thread anchors on d2 (GUI-D47); opened from the untargeted
   `text`, it anchors on nothing, as today. Either way its agent carries the board legend,
   receives no help material, and answers "why" from d2's `rationale` and `history` —
   quoting the grill-master's own why — or says the record does not say. "Because d2
   depends on d1" is an inference the legend forbids. The human can also read the why on
   d2 itself and never open the thread.

## 7. The declined patches

1. **Accept `revise` or a "stands" as a discharge.** A consequence of the ruling, in a
   different coat: discharge is by a ruling in the document (§5.2), checked against the
   document's `rulings` and the queued update, never by a prose phrase or by any
   informational that happens to target the id — that last would credit "d2 is dead" as a
   ruling, which is the narration GUI-D38 refuses.
2. **Reword the skill's `puts_in_question` line.** A consequence: the wording is §5.6, and
   it is the same sentence §8.2 and the `Option` docstring now carry.
3. **Add a fast-tier reasoning knob.** Independent of the ruling's core and a consequence
   of GUI-D46 only: under the heavy default the map's author does not use it, and the
   thread agents that keep the fast tier may. It does not address the incident on its own.

## 8. The criteria, dispositioned

Every decision and criterion the document touches. *Stands* needs no change; *changes*
carries the replacement; *suspect* names what would settle it.

- **Vocabulary (grill-master).** Changes: "The *grill-master* is the map's author: it
  rules on what every human gesture does to the rest of the plan and is the only agent
  that authors changes to the map." "Driving" is dropped. The channel sentence changes:
  "A *channel* is one lane between the page and an agent: the map's, on which the human
  makes gestures and the grill-master returns documents, and one conversational lane per
  thread."
- **GUI-D4.** Stands.
- **GUI-D7.** Stands.
- **GUI-D10.** Changes: "An agent that judges `stop_when` satisfied says so to the human —
  the grill-master as the `stop` field of its document (§8.10), which the page raises as a
  notice — and does not end the session itself."
- **GUI-D11.** Changes: the first sentence becomes "The fast tier answers from the context
  it was given, fast, and never manufactures information." The facilitation mandate —
  "stop short of deciding" — moves to the thread agent's role part (GUI-D44) and is no
  longer a property of the tier. The rest of GUI-D11 stands.
- **GUI-D12, GUI-D14, GUI-D15, GUI-D19, GUI-D22, GUI-D24, GUI-D26, GUI-D29, GUI-D30,
  GUI-D39, GUI-D40, GUI-D41, GUI-D43.** Stand.
- **GUI-D25.** Stands, and GUI-D44 restates it as the role.
- **GUI-D37.** Changes: "an array of decision ids the grill-master expects that option, if
  taken, to put in question downstream" and "Taking it is what obliges a ruling on each,
  and what that obliges is GUI-D45's". The display-data paragraph stands.
- **GUI-D38.** Changes as §5.2 states.
- **GUI-D42.** Changes as §5.2 states; the carriage and the expert hand-up stand.
- **GUI-U3.** Changes: "this is a constraint on the `text` of the grill-master's document
  and on the thread agents' turns alike" — the cap is on the notice, not on a ruling's
  `why`, which renders on its decision.
- **GUI-U9, GUI-U12, GUI-U15, GUI-U16, GUI-U26, GUI-U29.** Stand. GUI-U15 is what a
  `stands` ruling's targeted notice relies on.
- **§8.1 `help_reference`.** Stands; the code drifts from it (GUI-D47 restates).
- **§8.2 `puts_in_question`.** Changes as §5.6.
- **§8.5 thread `kind`.** Changes: `notice` is added — "for a thread opened from an
  agent's notice, anchored to the decision the notice targeted or to none".
- **§8.10 (new).** The grill-master reply document, §5.2.
- **GUI-A37, GUI-A38, GUI-A39, GUI-A40, GUI-A57, GUI-A64, GUI-A70, GUI-A79–A82,
  GUI-A93, GUI-A94, GUI-A102, GUI-A106, GUI-A107, GUI-A108.** Stand.
- **GUI-A43.** Changes: "a scripted turn under it returns a `text` of at most three
  sentences absent an explicit request for detail".
- **GUI-A83.** Stands.
- **GUI-A88.** Changes: "The grill-master's standing brief, on the fast tier and on the
  heavy one, obliges a ruling per decision the human's answer puts in question —
  `invalidate` where it moots the decision, carrying that answer as its rationale — and
  refuses narrating a decision as dead in place of ruling it. A thread agent's brief
  carries no such obligation and no sentence of the grill-master's role."
- **GUI-A89.** Changes: append "and carries no line naming it the map's author, on either
  tier".
- **GUI-A95.** Changes: append "and a `notice` thread's carries none".
- **GUI-A100.** Changes: "names each decision the answer put in question, quotes that
  answer, and states the three rulings".
- **GUI-A101.** Changes: "a fast tier that rules on neither decision is followed by an
  expert turn on the same gesture whose recorded dispatch names both ... and a fast tier
  that rules `stands` on both, each with a why, is followed by no expert turn".
- **GUI-A103.** Changes: "a reply ruling on each named id — an `invalidate` queued for one
  and `stands` with a why for the other — leaves the expert untouched, the human unsaid
  to, the invalidate in the queue and the standing decision on the frontier under a notice
  targeted at it".
- **GUI-A109.** Changes: "the expert proposes nothing and rules nothing" in place of
  "proposes nothing either".
- **GUI-D46's default (map on the heavy tier).** Suspect, by design: settled by the replay
  named in §5.4, which is the observation that reverts it.
- **GUI-D11's cost and latency figures.** Suspect for the map's author under GUI-D46: they
  were measured at a lighter weight; a session on the heavy default reports its own.

## Acceptance criteria

Each is checkable against the package's composed prompts, its drivers, its lane or the
skill's text, and each names what a red test would assert.

- **GMR-A1** For all four tier-agent pairs, the composed system prompt opens with that
  agent's role part: the grill-master's names it the map's author and carries the reshape
  step on both tiers; the thread agent's carries the facilitation mandate and no sentence
  of the grill-master's on both tiers. Mutation-tested: keying either role to a tier turns
  the suite red naming the pair.
- **GMR-A2** A grill-master reply validates against §8.10 or is refused: a prose reply, a
  document missing `text` or `rulings`, and a ruling outside the three kinds each surface
  as the lane's error phase naming the tier, and none reaches the log as a notice.
- **GMR-A3** A dispatch carrying an obligation names the ids, quotes the gesture and states
  the three rulings; a reply ruling `stands` with a why on each named id presses no expert,
  raises no unmet notice, records one informational targeted at each decision carrying
  that why, and leaves each on the frontier; a reply ruling nothing on a named id hands the
  turn up once, narrowed to the unruled ids, and a second such reply raises one notice
  saying those decisions were not ruled on.
- **GMR-A4** An `invalidate` or `revise` ruling whose document carries no matching update
  targeting that decision is not credited, and the turn is handed up as unruled;
  mutation-tested by crediting the ruling alone.
- **GMR-A5** With no tier configuration set, the first map turn is composed by the heavy
  tier and the first thread turn by the fast tier, the lane names each, and the map's
  transfer control reads *Return to fast agent* at first paint; setting the map's default
  to `fast` makes its first turn fast with the control reading *Transfer to expert*. A
  fast-tier effort, where set, appears in the request body and in the turn's attribution.
- **GMR-A6** Every composed thread-agent prompt carries the board legend, on both tiers; a
  scripted turn asked why a decision was invalidated, over a board whose `rationale` and
  `history` state it, replies quoting that rationale and asserts no cause outside it.
- **GMR-A7** A thread created from a notice targeting a decision anchors to that decision
  and is kinded `notice`; a `notice` thread's recorded dispatch carries no
  `help_reference` and the help thread's still does; the page-derived kind check admits
  `notice`.
- **GMR-A8** §8.2's `puts_in_question` text, the `Option` docstring and the skill's
  sentence state the same semantics — a prediction the grill-master rules on — asserted by
  the phrase "rules on" being present in all three.

## 9. The changes, in order

No tracker items are minted here. Each change names its target and the observation that
would show it was wrong to make.

1. **Spec text** — `docs/specs/2026-08-18-grilling-ui-v1.md`: the Vocabulary, GUI-D10,
   D11, D37, D38, D42 and U3 as §8 states; new GUI-D44–D47; §8.2, §8.5 and the new §8.10;
   the criteria of §8 and GMR-A1–A8 into the table and the evidence ledger. Wrong if: a
   reader of the amended spec can still find a sentence briefing an agent by its tier.
2. **Prompt** — `packages/grillui/src/grillui/tiers.py`: `system_prompt` joins a role part
   to a tier part; the grill-master's role part carries §5.1 and §5.3; the thread agent's
   carries the facilitation mandate and the legend of §5.5; the obligation sections state
   the three rulings; the mutation-format rule becomes the document rule. Wrong if: a
   replay of the recorded incident dispatch through the amended prompt on either tier
   still returns an `invalidate` whose why says the decision must be answered.
3. **Code** — `packages/grillui/src/grillui/schemas.py` (the reply document and ruling
   types; the `Option` docstring; `notice` in the thread-kind note),
   `packages/grillui/src/grillui/drivers.py` (validate the document; ask the fast
   provider for the shape; mint the targeted informational per `stands`; carry `rulings`
   and `stop` on the entry), `packages/grillui/src/grillui/escalation.py`
   (`outstanding` credits a ruling with its update, or `stands`),
   `packages/grillui/src/grillui/lane.py` (press on unruled ids; the notice wording),
   `packages/grillui/src/grillui/dispatch.py` (`help_reference` on the `help` kind only),
   and `tiers.py`'s configuration (per-channel default tier, fast effort). The page needs
   no change: it already anchors a Discuss thread on the notice's target. Wrong if: a
   session's log shows a grill-master turn refused for shape more than once in ten, which
   says the fast provider's structured output is not holding and the soft parser must
   return as a fallback.
4. **Skill** — `src/user/.agents/skills/grill-with-ui/SKILL.md`, the `puts_in_question`
   sentence (§5.6); `src/user/.agents/skills/grill-with-ui/references/help.md` gains one
   line saying a pre-marked decision is one the grill-master will rule on when the option
   is taken. Wrong if: a handoff written under the new sentence still marks a decision the
   author meant only as "related", which says the sentence needs an example of a mark
   that is not warranted.
5. **Tests** — `packages/grillui/tests/unit/test_tiers.py` and `test_lane.py`: the two
   tier-keyed prompt tests become role-keyed; the obligation tests take the three rulings.
   Wrong if: a test has to assert a tier to pass, which says the role part leaked back
   into the tier part.
