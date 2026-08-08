---
name: wait-what
description: Stop. That last message did not land — re-pitch it.
disable-model-invocation: true
admission:
  prevents: A re-explanation delivered in the register that just failed — same jargon, no orienting context, terms that are not the project's. The default response to "I don't follow" is to restate it at greater length, which fails the same way and costs another round-trip.
  cost: A catalog entry of 16 always-on tokens on Codex and OpenCode, which strip the user-invoked declaration and publish the description regardless — zero on Claude, which honours it, and unmeasured on Gemini. The body is 51 tokens, measured, paid only on invocation.
  remove_when: Re-explanations land unprompted — the user stops needing a second turn after saying they are lost.
---

<!--
Source: skills/productivity/wait-what/
Upstream: https://github.com/mattpocock/skills @ 84fdeffd12f2ee307994d1eb6feb48173b6e0502
Last sync: 2026-08-07
Drift policy: accept-periodic-resync
-->

Wait — I don't understand where you've got to here. Re-pitch that: give me a little bit of context, talk in ASD-STE100 Simplified Technical English, and use the ubiquitous language from `CONTEXT.md`.
