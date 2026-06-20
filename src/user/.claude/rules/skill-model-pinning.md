# Skill Model Pinning

Do not pin a small model (e.g. `model: haiku`) in a skill's frontmatter — skills run inside the parent conversation context, so a context larger than the model's window causes `ContextLimitExceeded`. Small models belong on agents (fresh context). Default: `model: sonnet[1m]`.
