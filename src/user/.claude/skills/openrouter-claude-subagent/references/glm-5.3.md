# `z-ai/glm-5.3` on this launcher

What this model does under each task shape, recorded from runs on this
launcher. Read before dispatching to it; the effort grid in the skill body does
not apply where a line here says otherwise.

- **Never a single-pass read of a whole artifact.** On that shape it returns
  thinking-only turns until the request times out. A log full of thinking-only
  warnings is a dead run to re-dispatch on another shape or model, not one to
  wait on.
- **A read of a change, or a walk, is the shape it takes.** Both finish.
