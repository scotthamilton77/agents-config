---
description: Map the code in view to the layer above it — the relevant modules, their callers, and the project's own vocabulary for them. For when you do not know this part of the codebase.
admission:
  provides: A fixed request for the layer above the code in view. Invoking it produces a map of the relevant modules and their callers, named in the project's glossary vocabulary rather than in whatever terms the model reaches for first — so the altitude and the vocabulary are both settled by typing the command instead of being renegotiated in prose each time.
  cost: One Claude-scoped command. Nothing is always-on — the two-line body is paid only when someone types it, and the exploration behind the map is paid then too.
  remove_when: Asking about an unfamiliar area of code in plain words, with no command typed, already returns a module-and-caller map in the project's glossary vocabulary on two consecutive occasions.
---

<!--
Source: skills/engineering/zoom-out/
Upstream: https://github.com/mattpocock/skills @ e74f0061bb67222181640effa98c675bdb2fdaa7
Last sync: 2026-08-07
Drift policy: rewrite-and-divorce — upstream deleted this skill after the pinned commit, so there is nothing left to resync against. The pin is a historical origin for the utterance, which is verbatim upstream; the asset type (Claude command, not skill) and the record are ours.
-->

# /zoom-out

`$ARGUMENTS` optionally names the area to map; empty means the code already in view.

I don't know this area of code well. Go up a layer of abstraction. Give me a map of all the relevant modules and callers, using the project's domain glossary vocabulary.
