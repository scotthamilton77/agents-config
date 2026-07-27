---
name: ac-attack
description: Attack a document's acceptance criteria with a panel of adversarial lenses, then check that the resulting record closes the round. Use when criteria have been drafted or revised and work is about to be claimed against them.
admission:
  prevents: Criteria that read complete and are not, because the failure modes nobody named stay unnamed until the code exists — and by then a review can only audit coverage of the cases the criteria already list, so the missing case ships.
  cost: A document's criteria cannot go to implementation until an attacker has run per lens over the whole document and every proposal they return carries a written disposition committed beside it.
  remove_when: Attack rounds stop producing accepted proposals across a run of documents, or the criteria-drafting step starts producing criteria that survive an attack unchanged.
---

Criteria that read complete rarely are. This skill attacks them: a panel of adversarial lenses
reads the document, each naming behaviours its criteria let through, and every proposal comes back
adjudicated into the criteria or rejected on the record.

Running before the work starts is the point: once code exists, a review can check the tests cover
the failure cases the criteria name, but cannot invent the ones nobody thought of. Those get
invented here.

## Attack lenses

| Lens | What it attacks |
| --- | --- |
| `criteria-holes` | Behaviours that satisfy every stated criterion and are still wrong. |
| `edge-cases` | The taxonomy walk — inverse, empty and boundary, dependency failure, repeated and concurrent invocation, idempotency — naming cases no criterion tests. |
| `absent-requirements` | Obligations the document takes on that no criterion covers. |

Mandates are data in `lenses.json`, each lens's `tier` naming the model capability it needs and
`transport` the route its prompt goes out on: an `openrouter` lens through the
`openrouter-claude-subagent` skill, a `codex` lens through the codex command-line tool. When one
transport is down, run its lenses over the other — the panel has then lost its vendor diversity,
and blind spots correlate within a vendor. No field records that substitution and the checker
cannot see it, so state it wherever the round's verdict is reported or it is lost. One attacker runs per lens, alone, exhaustive within
it and silent outside: asked for everything, one attacker satisfices, returning two holes where a
panel returns seven.

## Emitting the prompts

The attacked artifact is the whole document, never an extracted list of criteria: criteria mean
what the document's definitions and scope say they mean, and an attacker handed the bare list has
nothing to judge them against. Run from this directory, naming
the document and the output by paths that resolve from here:

```bash
uv run emit_prompts.py --spec /path/to/document.md --out-dir /tmp/attack-document
```

One `<lens>.md` prompt lands per lens, plus `round.json` recording the document, the revision
attacked, and each lens with its tier and transport.

Stdout is `{"emitted": true, "prompts": […], "round": …}` — the lens prompts, then the round
file, which is metadata and not one of them. A refusal is
`{"emitted": false, "errors": [{"code", "message"}]}`, exit 2, every code in `errors.md`. `--spec`
and `--out-dir` are both required — the output names are fixed, so a round with nowhere named would
truncate whatever wears them in the directory it ran from. A directory the round creates is
owner-only and it creates no parent along the way; one already there keeps the permissions its
owner gave it. Every file written is owner-only, since a prompt carries the whole document.

Proposals and the record they are written into are described in `record.md`: the shape an attacker
returns, the `id` a disposition names, and the record committed beside the document as
`<document>-ac-attack.json`, the document's name without its extension — `ledger.md` gets
`ledger-ac-attack.json`. Its machine-readable form is `attack-record.schema.json`.

## Checking the round

```bash
uv run check_record.py /path/to/document-ac-attack.json [--spec <path>] [--implementation-started]
```

Stdout is
`{"clean": …, "complete": …, "errors": [{"code", "id"?, "message"}], "document"?, "revision"?}`,
keys and errors sorted. `complete` says the round is closed: every lens reported, every proposal
adjudicated, and every acceptance carried into a revision the document still hashes to — or, in a
round that accepted nothing, the revision attacked. The edits an acceptance drives never
invalidate the round that drove them; an unrelated later edit does, having faced no attacker. `clean`
adds that nothing was proposed. `document` and `revision` name the file the verdict was decided
against and what it hashes to. Exit 0 complete, 1 not, 2 on unusable input. Every code the check
can return, and what each one means, is in `errors.md`.

`--implementation-started` declares what the invoker observed: the first work item that changes the
system this document describes has been claimed. Revising the document is not that. The checker
reads the record, the document, that declaration, and its own lens registry — read live, so a
record is judged against the lens set in force now and adding a lens reopens rounds that never
faced it. It consults no tracker, writes nothing, and answers the same way every time.

The record **attests** that the round happened as written; the checker does not verify that it did.
It can see the document is at the revision an acceptance names, never that the criterion is in it —
a hash names content without describing it — so an edit carrying none of the accepted proposals
closes the round as well as one carrying all of them, and a lens entry claims a report nothing
shows was made. What is enforced is that the account is internally whole and that the document in
front of the checker is the one the record accounts for. The result names the file it read, so a
round closed against a copy handed to `--spec` is visible as one: read that pair as part of the
verdict, because a `complete` round over the wrong file evidences nothing.
