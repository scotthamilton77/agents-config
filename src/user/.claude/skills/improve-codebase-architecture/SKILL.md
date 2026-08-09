---
name: improve-codebase-architecture
description: Scan a codebase for deepening opportunities, present them as a visual HTML report, then grill through whichever one you pick.
disable-model-invocation: true
admission:
  provides: A bounded architectural survey that ends in a decision — at most five deepening candidates, each with a before/after visualisation and a recommendation strength, then a grilling loop over the one the user picks. Unprompted, the model reviews the code in front of it; this reads commit history for hot spots, applies the deletion test, and refuses to propose interfaces before the user has chosen a candidate.
  cost: On invoke it costs an HTML report and one subagent walk of the codebase.
  remove_when: A survey pass returns no candidate above Speculative in two consecutive runs, meaning the spec contract and the grilling path are catching architectural friction before it accumulates.
---

<!--
Source: skills/engineering/improve-codebase-architecture/
Upstream: https://github.com/mattpocock/skills @ e74f0061bb67222181640effa98c675bdb2fdaa7
Last sync: 2026-05-23
Drift policy: rewrite-and-divorce (project-extended fork)
Placement: Claude tree, because an invocation writes an HTML file and opens it in the user's viewer before the user is asked anything. Claude alone honours disable-model-invocation; where the projection strips it, that report lands on the user's screen unrequested. The procedure is otherwise portable, which is why it looks shareable and is not.
-->

# Improve Codebase Architecture

Surface architectural friction and propose **deepening opportunities** — refactors that turn shallow modules into deep ones. The aim is testability and AI-navigability.

This pass is _informed_ by the project's domain model and built on a shared design vocabulary:

- Run the `codebase-design` skill for the architecture vocabulary (**module**, **interface**, **depth**, **seam**, **adapter**, **leverage**, **locality**) and its principles (the deletion test, "the interface is the test surface", "one adapter = hypothetical seam, two = real"). Use these terms exactly in every suggestion — don't drift into "component," "service," "API," or "boundary."
- The domain language in `CONTEXT.md` gives names to good seams; ADRs record decisions this pass should not re-litigate.

## Process

### 1. Explore

**Scope before you scan — YAGNI.** Deepening a module pays off by making future changes to it easier, so put extra weight on the parts of the codebase that have recently changed. Decide *where* to look before you look:

- If the user named a direction — a module, a subsystem, a pain point — take it, and skip the inference below.
- Otherwise, walk back a good stretch of the commit history (`git log --oneline`) to find the codebase's hot spots — the files and areas that keep coming up — and let those paths pull your attention first. If the changes are scattered with no clear hot spot, widen the net.

Read the project's domain glossary (`CONTEXT.md`), if it has one, and any ADRs in the area you're touching first.

Then walk the codebase — delegate the walk to a subagent if your harness has them, since it keeps the raw file survey out of this context. Don't follow rigid heuristics; explore organically and note where you experience friction:

- Where does understanding one concept require bouncing between many small modules?
- Where are modules **shallow** — interface nearly as complex as the implementation?
- Where have pure functions been extracted just for testability, but the real bugs hide in how they're called (no **locality**)?
- Where do tightly-coupled modules leak across their seams?
- Which parts of the codebase are untested, or hard to test through their current interface?

Apply the **deletion test** to anything you suspect is shallow: would deleting it concentrate complexity, or just move it? A "yes, concentrates" is the signal you want.

### 2. Present candidates as an HTML report

**Take at most five candidates into the report.** More friction than that always exists, so an unbounded pass has no reason to stop and produces a list nobody acts on. Rank what you found by the deletion test and recommendation strength, carry the top five, and say in one line how many you set aside. If fewer than five clear the bar, report fewer — a short honest list beats a padded one.

Ask the helper where the file goes, so nothing lands in the repo and the platform's opener is not re-derived. Run it from this skill's `scripts` directory; the path it prints is absolute, so the report itself can be written from anywhere:

```bash
uv run report_target.py            # prints a fresh absolute path
# ... write the HTML there ...
uv run report_target.py --open <path>
```

If `uv` is not installed, run these with plain `python3` instead — the script has no
dependency beyond the standard library.

Tell the user the absolute path either way.

The report uses **Tailwind via CDN** for layout and styling, and **Mermaid via CDN** for diagrams where a graph/flow/sequence reliably communicates the structure. Mix Mermaid with hand-crafted CSS/SVG visuals — use Mermaid when relationships are graph-shaped (call graphs, dependencies, sequences), and hand-built divs/SVG when you want something more editorial (mass diagrams, cross-sections, collapse animations). Each candidate gets a **before/after visualisation**. Be visual.

For each candidate, render a card with:

- **Files** — which files/modules are involved
- **Problem** — why the current architecture is causing friction
- **Solution** — plain English description of what would change
- **Benefits** — explained in terms of locality and leverage, and how tests would improve
- **Before / After diagram** — side-by-side, custom-drawn, illustrating the shallowness and the deepening
- **Recommendation strength** — one of `Strong`, `Worth exploring`, `Speculative`, rendered as a badge

End the report with a **Top recommendation** section: which candidate you'd tackle first and why.

**Use CONTEXT.md vocabulary for the domain, and the `codebase-design` vocabulary for the architecture.** If `CONTEXT.md` defines "Order," talk about "the Order intake module" — not "the FooBarHandler," and not "the Order service."

**ADR conflicts**: if a candidate contradicts an existing ADR, only surface it when the friction is real enough to warrant revisiting the ADR. Mark it clearly in the card (e.g. a warning callout: _"contradicts ADR-0007 — but worth reopening because…"_). Don't list every theoretical refactor an ADR forbids.

See [HTML-REPORT.md](HTML-REPORT.md) for the full HTML scaffold, diagram patterns, and styling guidance.

Do NOT propose interfaces yet. After the file is written, ask the user: "Which of these would you like to explore?"

### 3. Grilling loop

Once the user picks a candidate, run the `grilling` skill to walk the decision tree with them — constraints, dependencies, the shape of the deepened module, what sits behind the seam, what tests survive.

Side effects happen inline as decisions crystallise — run the `domain-modeling` skill to keep the domain model current as you go:

- **Naming a deepened module after a concept not in `CONTEXT.md`?** Add the term to `CONTEXT.md`. Create the file lazily if it doesn't exist.
- **Sharpening a fuzzy term during the conversation?** Update `CONTEXT.md` right there.
- **User rejects the candidate with a load-bearing reason?** Offer an ADR, framed as: _"Want me to record this as an ADR so future architecture reviews don't re-suggest it?"_ Only offer when the reason would actually be needed by a future explorer to avoid re-suggesting the same thing — skip ephemeral reasons ("not worth it right now") and self-evident ones.
- **Want to explore alternative interfaces for the deepened module?** Run the `codebase-design` skill and use its design-it-twice parallel sub-agent pattern.
