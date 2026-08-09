---
name: wait-what
description: Stop. That last message did not land — re-pitch it.
disable-model-invocation: true
admission:
  prevents: A re-explanation delivered in the register that just failed — same jargon, no orienting context, terms that are not the project's. The default response to "I don't follow" is to restate it at greater length, which fails the same way and costs another round-trip.
  cost: Context footprint only, bounded by the caps content-lint enforces.
  remove_when: Re-explanations land unprompted — the user stops needing a second turn after saying they are lost.
---

<!--
Source: skills/productivity/wait-what/
Upstream: https://github.com/mattpocock/skills @ 84fdeffd12f2ee307994d1eb6feb48173b6e0502
Last sync: 2026-08-07
Drift policy: accept-periodic-resync
Placement: Claude tree, because the body is the user's own line and only the user is entitled to say it. Claude alone honours disable-model-invocation; where the projection strips it, the model can invoke this and answer a complaint nobody made.
-->

Wait — I don't understand where you've got to here. Re-pitch that: give me a little bit of context, talk in ASD-STE100 Simplified Technical English, and use the ubiquitous language from `CONTEXT.md`.
