# Acceptance-criteria lifecycle: one standard, one home, attacked before any claim

**Date:** 2026-09-16
**Status:** Draft. Design child `agents-config-9k9.405.1` of the spec container `agents-config-9k9.405`, under the harness-rework milestone. Refines charter D1 and D3 and states where D3's attack fires for work that never has a spec.
**Relates to:** `agents-config-9k9.226` (the spec-quality standard, which cites the criteria standard this spec places), `agents-config-9k9.397` (the behavioural-outcome lens, slice S2 here), `agents-config-9k9.404` (slicing caught at creation and claim, the same doctrine at a different property), `agents-config-9k9.206` (an upstream lens at criteria authoring).

## Problem statement

Acceptance criteria are the termination condition a review checks against. They are the only thing that makes an LLM reviewer stop, because taste is inexhaustible and a contract is not. Today they enter the system through six doors and no door has a bouncer:

1. The grilling interview and its docs-attached variant refuse to end until criteria are enumerated.
2. The spec synthesis skill writes a spec's Acceptance Criteria section.
3. The ticketing skill and `work create --acceptance` copy criteria onto tracker items with no spec behind them.
4. `work deliver --spec` expands a spec's Continuations manifest into children, one criteria citation each.
5. `work acceptance set --why` restates criteria after work has started and records a trail.
6. A review-panel round halted on a criteria-indicting finding sends someone back to rewrite them.

Specs are not always written. The tracker holds 239 items carrying acceptance text. One attack record exists on the default branch. `work claim` refuses containers, blocked, parked, deferred and closed items and nothing else, so empty criteria and unattacked criteria both walk through to implementation.

Quality has no single source. Charter D1, the grilling skill, the spec skill and the attack skill's proposal sketch each carry a private copy of "red-test-convertible plus the edge-case taxonomy". None of them requires a criterion to name a behaviour a reader observes. PR 748's four criteria (a contract sentence exists, a test names it, the prompt bytes agree, the gate is green) satisfied every copy and three review rounds, and the behaviour change shipped unverified. The subagent-briefing skill tells a brief-writer that criteria are "tests that pass", which steers agents toward that artifact shape. The review-time rewrite has no guidance at all.

Storage has three copies during a review: the spec's criteria section, the tracker item's acceptance field, and the criteria file the review-panel invoker types by hand for `--acs`. The verdict-rendering work under `agents-config-9k9.390` caught the tracker copy one wording tweak behind the panel's file.

Two structural facts block the fix. The attack record binds by filename to the attacked document and is committed beside it; a tracker item has no beside. And the attack skill's doctrine says the attack runs before the work, never alongside it, so a criterion amended mid-execution is unattackable by the skill's own contract.

## Solution

One criteria standard, stated once and cited from every door. One canonical home, the tracker item's acceptance field, from which every consumer renders rather than retypes. One survival record per criterion set, stored where the record's existing binding rule already works. One gate, at claim, that refuses empty or unattacked criteria. One rule for amendment: an amended set is not used until it has been re-attacked, and the record's own revision binding is what enforces it.

## User stories

- **The implementer** claims a leaf and knows the criteria on it were attacked, because the claim would have been refused otherwise. They render the criteria with one facade call and never retype them.
- **The spec author** writes criteria once, under one standard, and the children minted from the spec carry citations that render back to that text.
- **The ticket author** with no spec writes criteria on the item under the same standard, attacks them, and the item becomes claimable.
- **The reviewer after a halt** rewrites the criteria through `work acceptance set --why`, sees the survival record invalidate, and runs the attack again before the next round 1.
- **The brief writer** dispatching a subagent states criteria as observable outcomes and lists tests and gates as the evidence for them, not as the criteria.
- **The human** reading a posted verdict sees the criteria the round judged against, and they are the item's criteria, byte for byte.

## Decisions

**ACL-D1 — One criteria standard, one deployed home for it.** A shared skill, `acceptance-criteria`, is the single deployed statement of what a criterion is, and every door cites it instead of carrying a copy. The standard: a criterion is an observable outcome. It names who observes (a user, a seat, a downstream reader, a gate) and what they see differently once the work is done. It is false today and true when the work is done, so it converts to one failing test. A criterion set holds at least one behavioural criterion; a criterion that pins an artifact property (a sentence present, a constant set, a test naming a symbol, a byte pin) is admitted only beside a behavioural criterion it serves and says which. The edge-case taxonomy (inverse, empty and boundary, dependency failure, repeated and concurrent invocation, idempotency) is walked per criterion and each row resolved or ruled out with a reason. The skill is shared, not Claude-only, because five of the six doors deploy to every tool. It enters `src/` through the admission gate, and its admission argument is the four private copies it deletes. The spec-quality standard under `agents-config-9k9.226` cites this skill for the criteria clause rather than restating it.

**ACL-D2 — The tracker item's acceptance field is the canonical home.** The facade already names it as what a claim is checked against. It holds the criteria in full, citations by ID into the one spec the item names through `--spec`, or both in one field. A spec's criteria section is the authoring source for spec-born items and the manifest already copies citations onto children; nothing else copies text. Every consumer renders from the field through one facade verb, `work acceptance render ID`, which prints the item's description and criteria as Markdown, in field order, resolving each cited ID to the spec's full entry. The rendering is deterministic over description and criteria alone: the title is a label and is excluded, and a note on the item does not change the rendering, so repeated renders of unchanged data are byte-equal. Resolution rules: a line whose whole content matches the criterion-ID pattern is a citation, and any other line is text, whether or not the item names a spec; a citation resolves only against the spec the item names, never a global lookup; an ID that spec does not define, or defines more than once, is refused by that ID's name; a cited entry with no text renders as no criterion. The review-panel `--acs` file and the verdict poster's `--criteria` file are that verb's output, never a hand-typed file, and both refuse a file that is not byte-equal to a fresh rendering.

**ACL-D3 — Survival records for tracker-born criteria live in the repo under `.work/attacks/`.** The rendered document from ACL-D2 is written to `.work/attacks/<item-id>.md` and attacked as any document is; its record lands beside it as `.work/attacks/<item-id>-ac-attack.json`, so the attack checker's bind-by-name rule and its revision hashing work unchanged. Both files are committed on the implementation branch before the claim. Spec-born criteria keep the record beside the spec. Decided over a note on the item, which is append-only bloat and the shape of the 64KB event-snapshot wall `agents-config-9k9.390` hit, and over a facade field, which is cleanest but a schema change nothing else needs. The directory is tracked, like the facade's own config beside it.

**ACL-D4 — A claim is refused on empty or unattacked criteria, and the attestation binds to content, not to note order.** `work claim` refuses a leaf whose criteria render to nothing, naming `work acceptance set`: an empty or whitespace-only field, or one whose citations resolve to no text. It refuses a leaf whose rendering is refused, naming the unresolved or duplicated ID. It refuses a `feat` or `bugfix` leaf whose current rendering carries no attestation, naming the attack step. The attestation is one marker note, `[work] acceptance attacked <ISO-8601> <rendering-digest>`, written by a new verb `work acceptance attacked ID --record PATH`. That verb reads one field of the record, the revision it attacked, and refuses to write a marker when the path is missing, does not parse as an attack record, or names a revision other than the digest of the item's current rendering; a second attestation with the same record is a no-op. At claim, the facade renders the item, hashes the rendering, and looks for a marker carrying that digest; a marker whose timestamp or digest does not parse is not an attestation. Note order plays no part, so a restatement, a description edit, or a spec edit landing after the round and before the marker all leave the item unattested. The facade never judges whether the round closed; that is the CI gate's job (ACL-D6), and the attack skill invokes the attest verb only after the checker exits zero. An item created `--trivial` is exempt from the attestation and not from the criteria: the flag already carries the declaration that the work needs no design input, and a second flag for the same trust would drift from the first. Other nouns need criteria and no attestation, because their delivery is a note or a decision, not a PR.

**ACL-D5 — Amended criteria are not used until re-attacked, and the record enforces it.** `work acceptance set --why` on a started item changes the rendered document, so the committed record's revision no longer matches and the checker reports the round open. The CI gate (ACL-D6) goes red, and the item's current rendering carries no attestation, so a re-claim refuses too. The same holds for a description edit, since the description is part of what the attackers read, and for an edit to a spec criterion that items cite: the spec's own record stops closing, and every citing item's rendering changes digest. That a description edit forces a re-attack is intended and pinned, not an accident of the hashing. The agent runs a fresh attack round over the amended document, commits the new record over the old (git keeps the prior round), and attests again. The attack skill's doctrine sentence changes from "before the work, never alongside it" to "before the criteria are used, and again after any amendment"; its `--implementation-started` check is unchanged, since it already asks only that no round be open while work proceeds. A full round per amendment is the deliberate ceiling here; a delta-scoped attack is the upgrade if amendments turn out to be frequent.

**ACL-D6 — The attack checker is a CI gate over every record in the repository.** A `make` target runs the checker with `--implementation-started` over every attack record the tree holds, the ones beside specs and the ones under `.work/attacks/` alike, and joins the whole-repo gate. A record that does not close, or whose document has moved from the revision it attacked, is red and named. A record that does not parse is red and named, never skipped. A tree holding no records is green. What the gate cannot see is stated rather than hidden: a marker naming a digest for which no record was ever committed, or whose files were later deleted, passes the claim and this gate both. The attestation is exactly as strong as the PR number `work deliver --pr` records and the evidence ledger's `observed:` row: not unforgeable, but callable in, and visible in the branch's diff. Nothing retroactive: the 48 open items carrying criteria today are attacked when next claimed, not by a backfill.

**ACL-D7 — The review-time doors cite the standard and the home.** The review-panel skill says the criteria file is `work acceptance render` output, its emitter refuses a criteria file that is not byte-equal to a fresh rendering at round emission, and a criteria-indicting halt resolves through `work acceptance set --why` and a re-attack. The verdict poster refuses a criteria file that differs from a fresh rendering at posting time, so a criteria amendment between judgment and post refuses the post rather than posting text the round never judged. The subagent-briefing skill's criteria clause says criteria are observable outcomes per the standard, and tests, gates and artifacts are the evidence a report cites per criterion. `work discover` gains nothing: discovered items get criteria through `acceptance set` before claim, because the gate is at claim, not at creation.

**ACL-D8 — A stale facade is refused by name.** The attack skill's tracker-item path and the review-panel's render step each check, before invoking a verb this spec introduces, that the installed facade reports a version at or past the one shipping it, and refuse naming that version otherwise. This is the same failure class the stale verdict poster had, and the same fix.

## Implementation decisions

- The rendering verb, the attestation verb and the claim refusals are facade changes in the `scotthamilton77/workcli` repository. Each slice here that needs one names the facade version that ships it and closes when the installed `work` reports that version.
- The attack skill gains no new storage code. The tracker-item path is documentation: render, attack the rendered file, commit both, attest.
- The behavioural-outcome lens is `agents-config-9k9.397` unchanged in scope; it becomes S2 of this spec and cites the standard rather than restating it.
- The CI target lives beside `spec-lint` and `doc-lint` in the root `Makefile`, invoking the deployed checker by its source path under `src/`.

## Testing decisions

Facade behaviour is tested in the workcli repository against its fake backend. The CI gate is tested by a fixture record under a temp directory. The standard's adoption is tested by the trigger evals the skill ships and by the attack lens of S2. Behavioural criteria below are discharged by tests where a test can observe the outcome and by an attributed observation where only a human at the surface can.

## Acceptance criteria

- **ACL-A1** An agent claiming a `feat` or `bugfix` leaf whose current rendering carries no attestation is refused, and the refusal names the attack step; the same claim succeeds after the attack closes and attests; a `--trivial` leaf, and a `chore` leaf with criteria, claim without attestation. An attestation written before a restatement, a description edit, or an edit to a cited spec criterion no longer covers the item, whatever the note order. A claim whose markers cannot be read is refused naming that failure, never granted.
- **ACL-A2** An agent claiming any leaf whose criteria render to nothing is refused naming `work acceptance set`, whether the field is empty, whitespace-only, or a citation to an entry with no text; a claim whose rendering is refused names the unresolved or duplicated ID.
- **ACL-A3** An implementer who amends criteria on a started item sees the whole-repo gate go red on the unchanged record, naming it, and green again after a fresh round closes over the amended document; no other file changes between the two runs. The same gate is red and names the file for a spec-born record whose spec moved, for a committed record whose round never closed over an unchanged document, and for a record that does not parse; it is red naming the checker when the checker is absent from the tree; a tree with no records is green.
- **ACL-A4** A reader of a posted verdict sees the criteria the round judged against byte-equal to the item's rendered criteria; a criteria file that differs from a fresh rendering is refused at round emission by the panel and at posting time by the poster, so an amendment between judgment and post refuses the post; a poster that cannot obtain the rendering refuses naming the cause, never posting the file unverified.
- **ACL-A5** A tracker item citing spec IDs renders to the spec's full criterion text; a field mixing text and citations renders both in order; a citation to an ID the named spec does not define, or defines twice, is refused by that ID's name, even when another spec defines it; a named spec file missing from the tree is refused by its path; a citation-shaped line on an item with no spec, and a text line on an item with one, render as text.
- **ACL-A6** A criterion set handed to the attack comes back with a finding naming each of: a set with no behavioural criterion; an artifact criterion that names no behavioural criterion it serves; a behavioural criterion that names no observer or no outcome that observer can distinguish; a criterion not observably false before the work. A set whose behavioural criterion is present and whose artifact criteria each name it draws none of these. The record cannot close until each such finding is dispositioned.
- **ACL-A7** An agent at any of the six doors, on any supported tool, asked how to write a criterion reaches one statement of the standard; a listing of every tool's deployed configuration finds the criteria definition and the edge-case taxonomy each stated in exactly one asset, a citation of it in every door, and none of the retired private phrasings in any door. This artifact criterion serves ACL-A6 and ACL-A8.
- **ACL-A8** A subagent brief produced under the briefing skill for work with several criteria and several tests states each criterion as an outcome a reader observes, lists every test and gate under evidence mapped to the criterion it supports, and introduces no test-passing or artifact-presence criterion; observed on a real dispatch after the skill change.
- **ACL-A9** A rendering of an item is unchanged by a note appended to that item or by a title change, so a record attacked before either still closes after it; two renders of unchanged data are byte-equal.
- **ACL-A10** An agent invoking the tracker-item attack path or the panel's render step against a facade older than the one shipping the render and attest verbs is refused naming the required version, not by an unknown-command error; the version read is the binary on PATH, never a checkout.
- **ACL-A11** An agent attesting an item against a record whose attacked revision is not the digest of the item's current rendering, or against a missing or unparseable record, is refused and no marker is written; attesting twice with the same record changes nothing.
- **ACL-A12** A spec author who edits a criterion in a merged spec sees every child `work deliver --spec` minted from it render the new text with no edit to the child, because the child carries a citation and not a copy.
- **ACL-A13** An agent reading the deployed attack skill finds the tracker-item path (render, attack the rendered file, commit both under `.work/attacks/`, attest) and the doctrine that the attack runs before the criteria are used and again after any amendment, with no sentence saying it never runs alongside the work; an agent reading the deployed review-panel skill finds that the criteria file is render output, never hand-typed, and that a criteria-indicting halt resolves through `work acceptance set --why` and a re-attack. This artifact criterion serves ACL-A3 and ACL-A4.

### Edge-case taxonomy

| Criterion | Inverse | Empty or boundary | Dependency failure | Repeated or concurrent | Idempotent |
| --- | --- | --- | --- | --- | --- |
| ACL-A1 | attested item claims | a marker whose digest matches counts, whatever its position; a malformed marker does not | facade cannot render (spec missing at the named path): refuse the claim, name the path | a restatement racing the claim: the claim renders at its own moment, so the later of the two wins and a stale marker never passes | a second claim on the same in-progress item is the existing no-op |
| ACL-A2 | non-empty rendering claims | whitespace-only is empty; a citation to an empty entry is empty | ruled out: the field is local | same as A1 | same as A1 |
| ACL-A3 | unamended record stays green | amendment that changes nothing writes nothing and stays green; no records is green | checker missing from the tree is red, not skipped | two amendments before one re-attack need one round over the latest | re-running the gate on a closed record stays green |
| ACL-A4 | matching file posts | empty rendering refuses the post | facade unreachable: the poster refuses, never posts the stale file | an amendment between judgment and post: the post is refused | posting the same verdict twice is the poster's existing rule |
| ACL-A5 | full-text criteria render verbatim | mixed fields resolve in order | spec file missing at the named path is refused by path | ruled out | rendering is a read |
| ACL-A6 | a set with one attributed behavioural criterion passes this lens | a one-criterion set that is artifact-only is a finding | lens transport down: the round is open, as today | ruled out | a second round over the same revision reproduces the finding |
| ACL-A7 | ruled out: a count of one has no inverse | zero statements is red | ruled out | ruled out | the search is a read |
| ACL-A8 | ruled out by observation | a brief with no criteria is refused by the skill's existing rule | ruled out | ruled out | ruled out |
| ACL-A9 | a criteria or description change does change the rendering | an item with no description renders criteria alone | ruled out | ruled out | two renders are byte-equal |
| ACL-A10 | a current facade proceeds | ruled out | facade absent from PATH is refused the same way | ruled out | the check is a read |
| ACL-A11 | a matching record attests | a record with no revision field is unparseable | record path unreadable is refused | two attestations race: both no-ops after the first | second attest with the same record is a no-op |
| ACL-A12 | a child with full text does not follow the spec | a spec with the cited entry removed makes the child's rendering refuse by ID | spec file missing: refused by path, as A5 | ruled out | rendering is a read |
| ACL-A13 | ruled out: a text is present or it is not | ruled out | ruled out | ruled out | the read is a read |

## Ordered slice list

- **S1 — The standard and its citations** (ACL-D1, ACL-D7; ACL-A7, ACL-A8). Author the `acceptance-criteria` shared skill through the admission gate; replace the four private copies in the grilling, docs-attached grilling, spec and ticketing skills with citations; rewrite the briefing skill's criteria clause; the attack skill's proposal sketch cites the same standard.
- **S2 — The behavioural-outcome lens** (ACL-D1; ACL-A6). `agents-config-9k9.397` as filed: the first-ranked lens in the attack skill, and the checker requires it ran.
- **S3 — Render and attest verbs** (ACL-D2, ACL-D4; ACL-A5, ACL-A9, ACL-A11, ACL-A12). Facade work: `work acceptance render ID` and `work acceptance attacked ID --record PATH`; closes on the installed version that ships them.
- **S4 — The tracker-item attack path and its records** (ACL-D3, ACL-D8; ACL-A9, ACL-A10, ACL-A13). The attack skill documents render, attack, commit, attest, behind a facade-version check; the `.work/attacks/` convention is stated in this repository's delivery contract.
- **S5 — The claim gate** (ACL-D4; ACL-A1, ACL-A2). Facade work: the refusals on an empty, refused, or unattested rendering; closes on the installed version that ships them.
- **S6 — The CI gate and the amendment rule** (ACL-D5, ACL-D6; ACL-A3, ACL-A13). The `make` target over every record in the tree, joined to the whole-repo gate; the attack skill's doctrine sentence changes.
- **S7 — Review-time consumers render, never retype** (ACL-D2, ACL-D7, ACL-D8; ACL-A4, ACL-A10, ACL-A13). The review-panel emitter and the verdict poster take the rendering and refuse a differing file, behind a facade-version check.

## Continuations

- feat: acceptance-criteria standard as one shared skill, four private copies become citations — AC: ACL-A7, ACL-A8; make ci exits 0.
- feat: ac-attack behavioural-outcome lens, first-ranked, checker requires it ran (agents-config-9k9.397, already filed) — AC: ACL-A6; make ci exits 0.
- chore: workcli render and attest verbs land and the installed facade reports the shipping version — AC: ACL-A5, ACL-A9, ACL-A11, ACL-A12.
- feat: ac-attack documents the tracker-item path behind a facade-version check, and the delivery contract names the .work/attacks convention — AC: ACL-A9, ACL-A10, ACL-A13; doc-lint exits 0.
- chore: workcli claim refusals on an empty, refused, or unattested rendering land and the installed facade reports the shipping version — AC: ACL-A1, ACL-A2.
- feat: attack-record CI gate over every record in the tree and the before-use doctrine — AC: ACL-A3, ACL-A13; make ci exits 0.
- feat: review-panel and prgroom take the rendered criteria and refuse a differing file, behind a facade-version check — AC: ACL-A4, ACL-A10, ACL-A13; make ci exits 0.

## Out of scope

- A delta-scoped re-attack after amendment; the full round is the ceiling, stated at ACL-D5.
- A facade field holding the attack record or its digest beyond the marker note.
- The facade verifying that a record's round closed, or that its files are committed; the CI gate owns closure and the branch diff shows the files.
- The facade's own help text for criteria-bearing verbs; it states no definition today and the standard is cited from the skills that write criteria.
- Backfilling attacks over the open items that carry criteria today.
- Criteria on `work discover`; the gate is at claim.
- Generating criteria from recorded behavioural observations, which is the removal condition of the container and of the lens.
- The spec-quality standard's other clauses (traceability, per-slice sections, out-of-scope discipline), which stay with `agents-config-9k9.226`.

## Further notes

The gate sits at claim rather than at creation because creation has six doors and claim has one. A door can stay wide, and an item can hold rough criteria while it waits, so long as nothing executes against them until they survive an attack. That is also why `--trivial` is the one exemption: it is the flag that already says this work will not be designed, and the claim gate reads the flag rather than minting a second one.

## Evidence

How each criterion above is discharged. States: `open`; `test: <file>::<test_fn>`; `probe: <file>::<name>`; `observed: #<PR> <YYYY-MM-DD> <name>`.

- ACL-A1 | open
- ACL-A2 | open
- ACL-A3 | open
- ACL-A4 | open
- ACL-A5 | open
- ACL-A6 | open
- ACL-A7 | open
- ACL-A8 | open
- ACL-A9 | open
- ACL-A10 | open
- ACL-A11 | open
- ACL-A12 | open
- ACL-A13 | open
