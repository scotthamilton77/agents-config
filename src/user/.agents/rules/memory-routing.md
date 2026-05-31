# Memory Routing

A durable fact has exactly one correct home, decided by its **scope**. Route before you write.

| Fact's scope | Home | Why |
|---|---|---|
| **Repo-specific** — a convention, gotcha, decision, or workflow that only means something inside one project | That repo's `AGENTS.md` — or a **folder-scoped** `AGENTS.md` when it only applies to a subtree (e.g. one package) | Versioned with the code, travels with the repo, visible to every tool and teammate that opens it |
| **General** — your working style, a user preference, or a correction that holds across every project | Your runtime's native/personal memory system | Follows you between projects; not bound to any one codebase |

- **Scope is the test, not topic.** "*This* installer needs `make ci` before push" → repo `AGENTS.md`. "User prefers vodka over rum" → native memory.
- **Go folder-scoped when the fact is narrower than the repo** — a fact that only applies under `packages/foo/` belongs in `packages/foo/AGENTS.md`, not the root.
- **One home, never two.** Don't mirror a fact into both native memory and an `AGENTS.md`; duplicated facts drift and then contradict each other.
- **No native memory on your runtime?** General facts have no durable store — surface them to the user instead of inventing one.
