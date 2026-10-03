# Model Catalog

The model inventory and routing table this project dispatches from is the
`choosing-a-delegate` skill's routing reference,
`src/user/.claude/skills/choosing-a-delegate/references/model-routing.md`. It
carries every provider (Anthropic, OpenAI, Google, OpenRouter), the model each
offers at each tier, and per model the price, context window and accepted
effort levels, dated at its head. Nothing
else in the repository carries a model price, and a routing decision anywhere
else cites that table rather than restating it.

One inventory lives in code rather than in that table: prgroom's dispatcher
default chains in `packages/prgroom/src/prgroom/agent/dispatcher.py`, which
name the CLI and model for each contract's primary and fallback links. A
project's `[agents.<contract>]` configuration overrides them.
