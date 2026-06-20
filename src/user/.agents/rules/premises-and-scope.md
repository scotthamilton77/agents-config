# Premises and Scope Estimation

- Before designing architectural rework, verify cited motivations against the actual architecture (diagrams, specs, code) — a collapsed premise is an early exit, not a design question.
- Before stating a scope estimate for any conversion or refactor, run a grep census of key signals; never estimate from reading the opening sections.
- Never state what a tool returned until the result is in context. Assert nothing from output you have not received.
- Treat absence or null from an aggregate query as "re-check via the authoritative single-record source" — never as a state value. Aggregate CLIs silently truncate at default limits.
