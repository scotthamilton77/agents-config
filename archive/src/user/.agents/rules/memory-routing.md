# Memory Routing

A durable fact has one home, decided by scope. Route before writing.

- Repo-specific (a convention, gotcha, or workflow that only means something inside one project) → that repo's `AGENTS.md`, or a folder-scoped `AGENTS.md` when it's narrower than the repo (e.g. one package).
- General (your working style, a user preference, a cross-project correction) → the user `AGENTS.md` or your runtime's native user-scoped memory.
- Scope is the test, not topic: "this installer needs `make ci`" → repo; "user prefers vodka over rum" → native memory.
- One home, never two — mirrored facts drift and contradict. No native memory on your runtime? Surface the general fact to the user instead of inventing a store.
