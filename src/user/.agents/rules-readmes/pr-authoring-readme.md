# PR Authoring for Bot Review — Context

## Good PR body structure

1. **Scope** — what the change IS and IS NOT (files in scope, files intentionally untouched)
2. **Artifact nature** — code vs. design doc; current-state vs. desired-state
3. **Ground truth** — specific files/types the reviewer should check claims against
4. **Intentional gaps** — what is design-forward, placeholder, or out-of-scope so the bot does not flag it as missing
5. **Constraints** — house style, citation rules, conventions to honor

## Desired-state doc behavior

A design doc depicting the target architecture (components not yet built, adapters not yet wired) is doing its job. An automated reviewer flagging those elements as "contradicts current code" is also doing its job — but that class of finding is not a defect. Triage by class: contradiction → fix; "not yet built" → acknowledge in thread, resolve, stop.
