---
name: research
description: Investigate a question against primary sources and leave the findings as a dated, cited note in the project's reference documentation. Use when a decision waits on an external fact — API behaviour, library semantics, specification details — that reading can settle and whose answer should outlive this session.
admission:
  provides: A cited note at a known path, traced to the documents that own each claim rather than to recall or a secondary write-up, which later sessions read instead of asking again.
  cost: Per invocation, a reading pass over primary sources and one committed file.
  remove_when: Fact-finding routes to a retrieval tool that cites primary sources and persists its answer, so a hand-written note adds nothing.
---

<!--
Source: skills/engineering/research/
Upstream: https://github.com/mattpocock/skills @ 84fdeffd12f2ee307994d1eb6feb48173b6e0502
Last sync: 2026-08-07
Drift policy: local-fork — output artifact given a stated home, citation and open-question discipline added; do not re-sync
-->

# Research

Answer the question from the sources that own it, and leave the answer behind in writing.

Hand this to a background agent if you have one — the point is that you keep working while it reads.

1. **Go to the primary source.** Official documentation, the library's own code, the specification, the first-party API. Not a blog post, not a summary, not memory. Follow every claim back to the artifact that defines it.
2. **Cite each claim** precisely enough that a reader can re-check it: a URL, or a file and the symbol inside it.
3. **Say what you could not settle.** A named open question is worth more than a confident guess, and it tells the next reader where to resume.
4. **Write one Markdown file**, dated — `docs/reference/<YYYY-MM-DD>-<slug>.md`, unless the project already keeps notes like this somewhere else, in which case match that. Dated because the finding is true of the sources as they stood on the day they were read, and sources move.

Report the answer in the conversation as well. The file is the durable copy, not the delivery.
