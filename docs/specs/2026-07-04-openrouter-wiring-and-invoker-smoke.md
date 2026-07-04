# OpenRouter Provider Wiring + Real-Binary Invoker Smoke — Design

**Date:** 2026-07-04
**Status:** Draft (pending review)
**Beads:** agents-config-abn9.40.3 (OpenRouter wiring), agents-config-qptb4 (real-binary smoke). One spec, two beads — edits here affect both; each bead's AC section is separate (§8). abn9.40.3's own AC ("passes qptb4 smoke") makes qptb4 a blocker; the beads edge is created alongside this spec.
**Related:** `2026-07-04-model-routing-policy-and-escalation-ladder.md` (locked decision 5 makes OpenRouter a candidate rung family; §4.1 defines `provider = "openrouter"` resolution); `2026-07-04-cross-model-heavy-gate-panel.md` (consumes OpenCode profiles when present).
**Decision:** Wire OpenRouter as an opencode custom-provider block (env-keyed auth, named cheap-tier models) so any dispatcher can reach OpenRouter rungs via `opencode run --model openrouter/<id>` with zero prgroom code changes; prove the whole four-invoker OS boundary with an explicit opt-in real-binary smoke suite (new `real_binary` pytest marker, excluded from CI by default).

## 1. Problem

The routing spec's cheap tier (GLM 5.2, Fugu Ultra) is reachable only through OpenRouter,
and nothing in the repo wires it: `opencode.jsonc.template` has a single flat
`"model"` key, no provider table, no OpenRouter/GLM/Fugu references anywhere in shipped
config. Meanwhile prgroom's four invokers (claude/codex/opencode/ollama) are tested
entirely through fakes — argv shapes, `--effort` acceptance, codex stdout discipline,
opencode's model-token format, and stdout JSON parseability are all unverified
OS-boundary assumptions (PR #142 deep review, MINOR-8). The two problems gate each other:
wiring without the smoke is another stack of stipulations; the smoke without wiring
cannot exercise an OpenRouter rung.

## 2. OpenRouter wiring (bead agents-config-abn9.40.3)

### 2.1 opencode provider block

Extend `src/user/.opencode/opencode.jsonc.template` with a custom provider (OpenRouter is
OpenAI-compatible; opencode addresses models as `providerID/modelID`):

```jsonc
{
  "model": "moonshotai/kimi-k2.6",          // unchanged default
  "provider": {
    "openrouter": {
      "name": "OpenRouter",
      "options": { "apiKey": "{env:OPENROUTER_API_KEY}" },
      "models": {
        "z-ai/glm-5.2": {},
        "fugu/fugu-ultra": {}
      }
    }
  }
}
```

- Auth: `{env:OPENROUTER_API_KEY}` — config stays secret-free; the env var is documented
  in `docs/guide/configuration.md`. No key → provider unusable → dispatcher availability
  fallback moves to the next rung (fail-lateral, never fail-open).
- "Profiles" (the bead's word) = **named models under one provider block**, selected
  per-dispatch via `--model openrouter/<id>` — not multiple jsonc files. opencode's
  invoker already passes `spec.model` verbatim (`subprocess_runner.py:256-257`), so no
  prgroom change is needed.
- `ASSUMPTION:` exact option-key names (`options.apiKey`) and nested model IDs
  (`openrouter/z-ai/glm-5.2` — a two-slash token) follow opencode's documented
  custom-provider shape; the archived precedent in this repo is stale. **The smoke (§3)
  is the verification step** — implementation must adjust the block to whatever the real
  binary accepts and record the verified shape back into this spec's PR.

### 2.2 Reaching OpenRouter from prgroom chains

No `AgentSpec` change. An OpenRouter rung in `.prgroom.toml` is simply:

```toml
[agents.cluster]
primary   = { cli = "ollama",   model = "gemma4" }
fallback  = { cli = "opencode", model = "openrouter/z-ai/glm-5.2", timeout = 120 }
fallback2 = { cli = "claude",   model = "haiku", effort = "high" }
```

This worked example ships as `docs/guide/` content (the repo currently has **no**
runnable `.prgroom.toml` sample anywhere — this closes that gap). The routing-layer
`provider = "openrouter"` key exists only in `model-routing.toml` chain entries for
billing attribution (routing spec §4.1); prgroom's dialect does not carry it, and
prgroom's unknown-key handling is warn-and-ignore (`subprocess_runner.py:289-295`) — do
not put `provider` keys in `.prgroom.toml`.

### 2.3 Documented fallback ladder (the bead's second AC clause)

The ladder for cheap-tier dispatches is the routing table's, not a new mechanism:
OpenRouter rungs appear in archetype chains (`mechanical` preferred rung, `classifier`
alternates) with `provider = "openrouter"`; unavailability (no key, endpoint down,
binary missing) is a **lateral** availability fallback to the next rung; gate failure
**climbs**. This spec adds the OpenRouter-specific operational notes to the guide: env
var, expected failure shape when the key is absent (opencode exits non-zero → prgroom
classifies `unavailable` → next rung), and the two shipped model names.

## 3. Real-binary invoker smoke (bead agents-config-qptb4)

### 3.1 Gating — explicit opt-in, first-class

New in `packages/prgroom/pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = ["real_binary: dispatches a real agent CLI; opt-in via `make smoke-agents`"]
addopts = "-m 'not real_binary'"
```

and a Make target:

```make
smoke-agents:  ## real-binary invoker smoke (requires local CLIs; never in CI)
	cd packages/prgroom && uv run pytest -m real_binary -v
```

Rationale: the repo's one real-binary precedent (`test_git_real.py`'s bare `skipif`)
passes in CI only because git happens to exist on runners. Agent CLIs *could* appear on a
future runner image; an implicit-absence skip would then silently start spending money in
CI. The marker + default exclusion makes "non-CI-gating" (the bead's requirement) an
explicit property, not an accident of PATH. `make ci-prgroom` is unaffected (`addopts`
excludes the marker from every default pytest invocation, including `cov-prgroom`).

### 3.2 The smoke tests

`packages/prgroom/tests/smoke/test_real_invokers.py`, one test per invoker plus one
OpenRouter variant, each additionally `skipif` its binary is absent (and the OpenRouter
test skips without `OPENROUTER_API_KEY`):

| Test | Dispatch | Asserts |
|---|---|---|
| claude | `AgentSpec(cli="claude", model="haiku", extra={"effort": "low"})` | exit 0; `--effort` accepted; stdout yields a parseable object via `_loads_lenient` (envelope-unwrapped once the token-capture spec lands) |
| codex | `AgentSpec(cli="codex", model="gpt-5.4-mini")` | exit 0; stdout parseable; (observed) stderr trailer present |
| opencode | `AgentSpec(cli="opencode", model="<template default>")` | exit 0; `--model` token accepted; stdout parseable |
| opencode × OpenRouter | `AgentSpec(cli="opencode", model="openrouter/z-ai/glm-5.2")` | exit 0 with the §2.1 provider block active — **this row is abn9.40.3's AC** |
| ollama | `AgentSpec(cli="ollama", model="gemma4")` | stdin prompt path works; stdout parseable |

Common shape: a trivial contract prompt ("Return exactly this JSON object: {...}")
dispatched through `SubprocessAgentRunner` (the real spawn path, not fakes), generous
per-test timeout (120s), cheapest model per family. The suite exists to falsify argv and
stdout-discipline assumptions at the OS boundary — not to test model quality.

### 3.3 Cost posture

One run ≈ four trivial dispatches on cheapest rungs (haiku, gpt-5.4-mini, GLM,
local ollama) — negligible but not zero; it is manual and documented as such. Spend
attribution to the ledger arrives with the cost-telemetry spec; until then smoke runs
are unledgered by design.

## 4. Sequencing

qptb4's harness (§3.1–3.2, minus the OpenRouter row) has no dependencies and should land
first — it also verifies assumptions the token-capture spec builds on (envelope flag
acceptance, codex trailer presence). abn9.40.3 (§2) then lands and turns on the
OpenRouter row. The beads edge (abn9.40.3 blocked-by qptb4) encodes this.

## 5. Out of scope

- prgroom reading `model-routing.toml` (routing spec §10 deferral unchanged).
- Making prgroom's unknown-extra-key handling strict (warn-and-ignore noted; a
  fail-loud config validator is its own decision).
- Gemini CLI wiring (no gemini invoker exists in prgroom's `_KNOWN_CLIS`).
- CI execution of the smoke, ever, without a deliberate opt-in change to this design.
- Rate-limit/retry tuning for OpenRouter (availability fallback covers v1).

## 6. Test plan

The smoke suite *is* the test plan for the OS boundary. Unit-level: marker exclusion
(default `pytest` collects zero `real_binary` tests), env-gate skip (no
`OPENROUTER_API_KEY` → OpenRouter test skips with a named reason), and the guide example
`.prgroom.toml` parses through `load_chain` (fixture test — catches dialect drift).

## 7. Rollback / degradation

Everything is additive: the provider block is inert without the env key; the marker
excludes by default; the worked example is docs. Removal = revert.

## 8. Acceptance criteria

**agents-config-qptb4:** marker + addopts + `make smoke-agents` exist; the four invoker
tests run against real binaries locally and each asserts exit/argv/stdout-parseability;
default CI invocations collect none of them (`make ci-prgroom` output proves it);
`load_chain` fixture test for the worked `.prgroom.toml` example passes.

**agents-config-abn9.40.3:** `opencode.jsonc.template` ships the OpenRouter provider
block (verified shape per §2.1); `OPENROUTER_API_KEY` + fallback behavior documented in
the guide; the opencode × OpenRouter smoke row passes locally with a real key; the
worked chain example (§2.2) is in the guide. Verified model-ID token shape recorded in
the implementing PR.

## 9. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` opencode custom-provider block shape (§2.1) — pinned to be *verified by
  the smoke*, adjusted at implementation, and the verified shape recorded. If opencode
  cannot address OpenRouter models cleanly, fallback design is an OpenAI-compat base-URL
  provider entry; same seam, different keys.
- `ASSUMPTION:` `z-ai/glm-5.2` and `fugu/fugu-ultra` are the intended cheap-tier model
  ids (names taken from the routing spec's locked decision 5; exact OpenRouter catalog
  ids confirmed at implementation).
- `ASSUMPTION:` marker + `addopts` exclusion is acceptable as the repo's first registered
  pytest marker (a new convention, justified in §3.1 — implicit-absence skips are how CI
  starts spending money).
- `ASSUMPTION:` ollama smoke uses `gemma4` (the classifier row's local rung); any locally
  pulled model works — the test should accept an env override `PRGROOM_SMOKE_OLLAMA_MODEL`.
