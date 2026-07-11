# Theme reference — class vocabulary

Inline `assets/theme.css` and `assets/quiz.js` verbatim into the explainer.
Then compose the page from the classes below — do not invent parallel styles,
and do not hardcode hex colors in the HTML. Everything reads from CSS variables,
so light/dark both work for free. To rebrand later, edit only the variable blocks
at the top of `theme.css`.

## Layout
- `.wrap` — page container (centered, max-width). Wrap all body content in one.
- `.toc` — table-of-contents card. Put a `<ol>` of `<a href="#id">` inside.
- Section `<h2 id="...">` — auto-gets a top rule; match ids to the TOC anchors.

## Callouts
`<div class="callout TYPE"><span class="label">Label</span> body…</div>`

| Type   | Use for                          |
|--------|----------------------------------|
| `note` | asides, tips, context            |
| `key`  | the one thing to remember        |
| `warn` | risks, edge cases, gotchas       |
| `def`  | definitions of a term            |

## Collapsible deep background
`<details><summary>New to X? Expand.</summary> … </details>`

## Code + syntax
- Blocks: `<pre> … </pre>` (newlines preserved). Add `class="wrap-lines"` to soft-wrap.
- Inline: `<code>…</code>`.
- Hand-tag tokens with spans — no external highlighter, keeps the file self-contained:
  `.tok-kw` keyword · `.tok-str` string · `.tok-num` number · `.tok-com` comment
  · `.tok-fn` function name · `.tok-type` type · `.tok-var` identifier · `.tok-punc` punctuation.
- Diff lines inside a `<pre>`: wrap a line in `<span class="diff-add">…</span>` or
  `<span class="diff-del">…</span>` (each renders as a full-width tinted line).

## Diagrams (HTML only — never ASCII)
- `.diagram` — framed figure box; add a `<div class="caption">` at the bottom.
- `.flow` — horizontal row of steps. Children: `.node` boxes and `.arrow`
  separators (`.arrow.down` for vertical). Mark the changed step `.node.hot`.
- `.data-tag` — inline chip for example data on an edge, e.g. `<span class="data-tag">userId=42</span>`.
- `.uimock` (`.titlebar` + `.body`) — a small stylized app-UI frame for UI changes.

## Quiz
Markup per question (script auto-wires clicks — no per-question JS). The order below
shows the four required roles; vary their order in each generated question so position
does not reveal the answer:
```html
<div class="quiz">
  <div class="q">
    <div class="stem">Question?</div>
    <button class="opt" data-correct="false" data-fb="why this believable misconception is wrong">Plausible wrong option A</button>
    <button class="opt" data-correct="false" data-fb="why this different misconception is wrong">Plausible wrong option B</button>
    <button class="opt" data-correct="true"  data-fb="why this is right">The answer</button>
    <button class="opt" data-correct="false" data-comic="true" data-fb="Persona-shaped explanation of why the absurd premise contradicts the change">Obviously impossible, persona-voiced comic foil</button>
    <div class="feedback"></div>
  </div>
</div>
```
Every question needs exactly four options: two plausible false distractors, one true
answer, and one false `data-comic="true"` comic foil. The comic foil must be visibly,
factually impossible for the change in the question; do not make it a plausible answer
and try to salvage it with a sarcastic last clause. Its visible wording and feedback
must sound like the resolved persona, using that persona's cadence, references, and
attitude. Keep the non-comic options roughly equal length so length is not an answer
cue; give the comic foil only enough extra detail to make its contradiction obvious.
