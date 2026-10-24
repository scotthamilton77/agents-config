---
name: ac-attack
description: Attack a document's acceptance criteria with a panel of adversarial lenses, then check that the resulting record closes the round. Use when criteria have been drafted or revised and work is about to be claimed against them.
admission:
  prevents: Criteria that read complete and are not, because the failure modes nobody named stay unnamed until the code exists — and by then a review can only audit coverage of the cases the criteria already list, so the missing case ships.
  cost: A document's criteria cannot go to implementation until an attacker has run per lens over the whole document and every objection they return carries a written disposition committed beside it.
  remove_when: Attack rounds stop producing accepted objections across a run of documents, or the criteria-drafting step starts producing criteria that survive an attack unchanged.
---

Criteria that read complete rarely are. This skill attacks them: a panel of adversarial lenses
reads the document, each objecting to what its criteria let through on a named ground, and every
objection comes back adjudicated on the record. An accepted one is answered by a criterion the
author writes, since the author holds the context an attacker lacks.

Running before the work starts is the point: once code exists, a review can check the tests cover
the failure cases the criteria name, but cannot invent the ones nobody thought of. Attack before
use, and again after amendment: an attack on one version of the criteria says nothing about the next.

The scripts below run via `uv run`. If `uv` is not installed, run them with plain `python3`
instead; `check_record.py` and `assemble_record.py` need `jsonschema` installed first.

## Attack lenses

The lenses are the directories under `lenses/`, and each script reads that registry live. Each
lens owns `lenses/<lens>/prompt.md`: its body is the lens's instructions, and its front matter
gives its `tier`, its `transport`, its pin (the `effort` and the `tools` it is dispatched with),
and the `acceptance-criteria` rule IDs it `enforces`. Its prompt carries exactly those rules, read
live from that skill installed beside this one, and every objection cites one of them. A lens
marked `workings: required` also returns an inventory, judged by the `workings.schema.json` beside
its prompt, and each gap the inventory shows is owed an objection.

A rule's owner is the lens whose unit its question needs; two lenses may share ground when one
asks about a criterion and the other about the set.

| Lens | Reads | What it attacks |
| --- | --- | --- |
| `behavioural-outcome` | One criterion, on its own shape | An artifact checked where an outcome is promised, bundled obligations, or no way to decide the result. |
| `obligation-reduction` | The set against the document's promises | Obligations no criterion discharges, and criteria that discharge none, read off an inventory. |
| `set-consistency` | The set against itself | Criteria that cannot hold together, and wording that admits different outcomes. |
| `what-if` | One criterion, asked what it leaves untested | The standard's what-if questions, naming cases no criterion tests. |

A lens's `tier` is the capability it needs, `transport` its route: an `openrouter` lens through
the `openrouter-claude-subagent` skill, a `codex` lens as the Codex delegation skill's read-only
run. Its model is the model routing table's cell for its provider (`codex` is the table's
`openai`) at its tier. Its effort and tool grant are the pin its `round.json` entry carries:
`read-only-sandbox` is the Codex runtime's read-only sandbox, and an empty list is no tools, since
the prompt holds the whole document. Ingest usable output, fix a refusal, rerun unusable output as
`unusable-output`, and stop a run you signalled.

A run its provider did not serve is `transport-error`, a dead route: dispatch the lens on its
failover seat, the other transport at the same tier, and say so in your report. A run that ended
inside the model's reasoning, or that your watchdog ended for silence, is a dead run and climbs a
ladder, one step per dead run: the same model and tools at the next lower effort the routing
table lists for it; then the failover seat, when the table lists nothing below the effort that
died or the step down also died. The failover pin is held here, not per lens: a lens arriving on
Codex runs the read-only sandbox at `medium`, one arriving on OpenRouter runs no tools at `low`.
A dead run on the failover seat ends the ladder: the lens has no report, the round does not close,
and the lens runs again later. One attacker runs per lens, alone: asked for everything, one
attacker satisfices, returning two holes where a panel returns seven.

## Emitting the prompts

The attacked artifact is the whole document, never an extracted list of criteria: criteria mean
what the document's definitions and scope say they mean. Run from this directory:

```bash
uv run emit_prompts.py --spec /path/to/document.md --out-dir /tmp/attack-document
```

One `<lens>.md` prompt lands per lens, plus `round.json` recording the document, the revision
attacked, and each lens with its tier, transport, effort and tool grant. `--lens <name>` emits
that lens alone; its round file names only that lens, so a record built from it stays incomplete.
Dispatch the lenses `round.json` names, not the files the directory holds; a round refuses an
out-dir holding a Markdown file it does not write.

Stdout is `{"emitted": true, "prompts": […], "round": …}`, the lens prompts then the round file,
which is metadata and not one of them. A refusal is
`{"emitted": false, "errors": [{"code", "message"}]}`, exit 2, every code in `errors.md`. Both
`--spec` and `--out-dir` are required. Everything written is owner-only, since a prompt carries
the whole document.

Objections and the record are described in `record.md`: the shape an attacker returns, the `id` a
disposition names, and the record committed beside the document as `<document>-ac-attack.json`
(`ledger.md` gets `ledger-ac-attack.json`); the check holds the record to that name, so a record
copied onto a second document closes nothing. Its machine-readable form is
`attack-record.schema.json`.

## Assembling the record

```bash
uv run assemble_record.py union --round <dir>/round.json --report <lens>=<raw-output> …
uv run assemble_record.py assemble --union <dir>/union.json --dispositions <file> --spec <document>
```

Between the two, fill in the skeleton the union writes and make every accepted edit. Disclose the
repairs and drops stdout lists. `record.md` describes both steps.

## Checking the round

```bash
uv run check_record.py /path/to/document-ac-attack.json [--spec <path>] [--implementation-started]
```

Stdout is
`{"clean": …, "complete": …, "errors": [{"code", "id"?, "message"}], "document"?, "revision"?}`,
keys and errors sorted. `complete` says the round is closed: every lens reported, every objection
adjudicated, and every acceptance carried into a revision the document still hashes to — or, in a
round that accepted nothing, the revision attacked. The edits an acceptance drives never
invalidate the round that drove them; an unrelated later edit does, having faced no attacker. `clean`
adds that no lens objected. `document` and `revision` name the file the verdict was decided
against and what it hashes to. Exit 0 complete, 1 not, 2 on unusable input. Every code is in
`errors.md`.

`--implementation-started` declares what the invoker observed: the first work item that changes the
system this document describes has been claimed. Revising the document is not that. The checker
reads the record, the document, that declaration, and its own lens registry, read live, so a
record is judged against the lens set in force now: adding a lens reopens rounds that never faced
it, while retiring one leaves the rounds it ran in closed. It consults no tracker and writes
nothing, and over one tree it answers the same way every time.

The record **attests** that the round happened as written; the checker does not verify that it did.
It can see the document is at the revision an acceptance names, never that the criterion is in it,
since a hash names content without describing it, so an edit carrying none of the accepted
objections closes the round as well as one carrying all of them, and a lens entry claims a report
nothing shows was made. The emitter's refusals, made before a round exists, are where an
unattackable document is stopped. What is
enforced is that the account is internally whole and that the document in front of the checker is
the one the record accounts for. The result names the file it read, so a round closed against a
copy handed to `--spec` is visible as one: a `complete` round over the wrong file evidences nothing.
