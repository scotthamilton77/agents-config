---
name: readable-prose
description: The standard for prose a person reads first, such as a spec, a design note, a pull request description or a work-item description. Use before drafting one. Use when one that exists is dense, hard to follow, or has grown clause by clause through review rounds, and it has to become readable without changing anything it decides. Not for skills, rules or other instruction text an agent reads, and not for changing a design.
admission:
  prevents: A human owner spending a second read or a clarifying question on a spec whose substance was right, and a readability rewrite that narrows a criterion or strengthens a claim while it shortens the text. Both happened on one spec. It needed an editorial pass before its owner could read it, and that pass's meaning check found a widening its author had not noticed.
  cost: Revising an existing document spends a second full pass over it, a side-by-side read that grows with the document, and a fresh criteria attack when the earlier attack judged the old wording.
  remove_when: Three consecutive specs reach their owner readable on the first pass with this standard not loaded.
---

# Readable prose

A spec, a design note, a pull request description or a work-item description is read first by a person who has to approve it or act on it. That person was not in the conversation that produced it. The text is readable when each paragraph answers one clear question on a single read. The reader never has to untangle a sentence or follow a reference to find the main point.

The rules are the same whether you are drafting or revising. Drafting with them is the cheap path, because a draft has no earlier version to disagree with. Revising costs a rewrite and a meaning check. Load this standard before you write, and keep revision for text that already exists.

This standard does not cover instruction text an agent reads, such as a skill or a rules file. `writing-skills` covers that. It also never changes a design.

## The rules

1. **Open with the decision or the result.** The first sentence of a document, a section and a decision says what changes, who owns it, or what stays true. An opening that only names a topic makes the reader wait. Write "The export job retries three times, then parks the batch." Do not write "This section describes the retry behaviour." A decision's heading states the decision too.
2. **Give each sentence one main job.** Behaviour, reason, exception and consequence each get their own sentence. The sentences still read as a paragraph. When one sentence is the reason for another, keep the word that says so.
3. **Use paragraphs for reasoning and lists for parallel items.** A list suits things a reader counts or compares, such as flags, cases and steps. Reasoning broken into bullets loses the words that connect it. A document that has tripled in length has not become easier to read.
4. **Name the actor and use a direct verb.** "The launcher rejects the flag." "The caller chooses the value." "The lint checks the table."
5. **Use exact terms and familiar words.** Use the defined term, and define it where it first appears. Do not describe the term in its place: write "provider", not "the thing a run is launched through". Keep flags, field names, identifiers and error text exactly as they are. Never replace a precise behaviour with "handles", "supports" or "manages".
6. **Cut repetition and commentary about the document.** Keep a second explanation only when it makes a hard distinction easier.
7. **Give a substantial decision a fixed shape.** State these in order: the decision in one sentence; the behaviour and who owns it; each rejected alternative with the concrete reason it fails; the cost, and the condition for removing or reconsidering the decision. A reader comparing decisions then finds the same thing in the same place. A one-sentence correction needs none of this.
8. **State what is measured.** "Idle means no request was forwarded for M seconds" can be checked. "Idle detects a stranded process" claims more than anyone measured, and it reads better, which is why it creeps in. Keep an observed duration distinct from a guaranteed one.

## Revising text that exists

A revision changes how the text reads. It changes nothing the text commits anyone to. A shorter criterion that covers less is worse than the dense one it replaced.

1. Keep a copy of the original outside the file you edit. The meaning check needs it.
2. Rewrite the document whole. Patching one sentence at a time never reaches the shape rule 7 asks for.
3. Leave alone what other things depend on: identifiers, the line format of acceptance criteria, section numbers and headings that are cited elsewhere, and quoted flags and error text. A lint may parse a criterion line, and a renumbered section breaks every reference to it.
4. Correct a stale reference when the right target is certain. Where two passages conflict and the intent is unclear, keep both and report the conflict. Choosing between them is a design decision.
5. Run the meaning check.
6. Write the report.

### The meaning check

Take the original one decision and one criterion at a time, and find each in the rewrite. Compare these for each one:

- the owner;
- the required and prohibited behaviour;
- the scope, exceptions and conditions;
- the flags, exit codes, signals and recorded outputs;
- the timing, ordering and compatibility;
- the costs, removal conditions and rejected alternatives;
- the evidence, uncertainty and validation status.

For an acceptance criterion, compare the promised outcome and its check separately. The pass rule accepts and rejects exactly what it did before.

Classify every difference as one of four kinds: wording only, a narrowed or widened obligation, a strengthened claim, or a resolved conflict. Only a wording difference may stand. Restore the original meaning for the other three. If you believe the original was wrong, restore it anyway and report it.

The revision is not done until the check has covered every decision and every criterion.

### The report

- Three or four representative before-and-after pairs.
- How the meaning check was done, and each difference it found and restored.
- Every conflict or suspected error left unresolved.
- Whether the document's criteria had already been attacked. An attack judged the old wording, and the `acceptance-criteria` standard asks for a fresh one after an amendment. For that reason, revise before the criteria are attacked whenever you have the choice.

There is no word-count target. Shorter is not the goal.

## The last read

Before you hand over a draft or a revision, read it as someone who has not seen the work. Each paragraph answers a question you can name. Where you reread a sentence, or looked elsewhere for its main point, rewrite that sentence.
