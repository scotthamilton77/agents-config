# Retrospective deliverable shape

Section order and table shape for what a retrospective hands back.

## Section order

1. **Bottom line** — outcome, the avoidable cost, and the single highest-leverage
   change, stated up front.
2. **What went well** — wins worth repeating, each with its *why*.
3. **What slowed us down** — findings, each tagged `[target / root-cause]` and traced
   to its cause.
4. **Recommendations** — the prioritised table:

   | Recommendation | Target | Root cause | Lands in | Impact | Effort | Priority |
   |---|---|---|---|---|---|---|

   Every row carries a landing site. A row whose "Lands in" column reads "the
   summary" is not a recommendation.
5. **Apply?** — the offer to action approved items.

## Worked example (condensed)

> **Bottom line:** Feature shipped, but three correction round-trips did QA the
> system should have done. Highest-leverage fix: convert the two most-violated prose
> rules into mechanical gates.
>
> **What went well:** The todo list on the multi-step fix — *why:* it externalised
> state so nothing got dropped mid-task. Keep requesting it for anything multi-step.
>
> **What slowed us down:** Skipped the project's AGENTS.md, so a documented "register
> flags in two places" rule was missed `[Agent context / Compliance failure]` — the
> rule existed and was ignored, so more prose won't help.
>
> | Recommendation | Target | Root cause | Lands in | Impact | Effort | Priority |
> |---|---|---|---|---|---|---|
> | Pre-edit hook blocking the first edit until AGENTS.md is read | Tool availability & selection | Compliance failure | A hook, proposed as work | High | Med | P0 |
> | CI check: a flag must appear in both registration sites | Tool availability & selection | Compliance failure | The project's CI config, proposed as work | High | Low | P0 |
> | Record the newly-seen test-tautology pattern in the existing testing guidance | Agent context | Context gap | The testing doc already read at that decision point | Med | Low | P1 |

Note what the example does *not* contain: a fourth row proposing a new rule that
restates the ignored one — the dedup test working.
