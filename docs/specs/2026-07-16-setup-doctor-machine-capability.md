# setup/doctor — Machine Capability Detection, Gap Resolution, and Config Generation

**Date:** 2026-07-16
**Status:** Draft (pending review)
**Beads:** agents-config-uxns2.6 (this spec's epic; continuations minted at merge)
**Related:** agents-config-abn9.35 (deployed-vs-src drift diff — absorbed here as one probe);
agents-config-abn9.8.24 (prgroom `--doctor` — same verb pattern, package-local scope, unaffected);
agents-config-uxns2.2 (generalized custom-harness agent config — §7 carves out its minimal
work-machine slice, the rest stays open); agents-config-abn9.40.3 /
`2026-07-04-openrouter-wiring-and-invoker-smoke.md` (the opencode provider block §7 parameterizes);
`2026-07-04-model-routing-policy-and-escalation-ladder.md` (its fallback chains consume §6's
disposition contract); `2026-07-06-profiles-scope-routing.md` (defines `~/.agents/` as the
user-owned config home and pins `profiles.toml` as never machine-written — honored in §5).
**Decision:** One probe engine, two verbs on the installer CLI — `doctor` (read-only,
offline-deterministic report) and `setup` (doctor + per-gap interactive resolution + config
writes). Four disposition states per gap; explicit dispositions persist to a doctor-owned
`~/.agents/machine.toml` (user scope) or a `[tools]` section of `project-config.toml`
(project scope); the default persists nothing. Provider endpoints — OpenRouter or any
OpenRouter-compatible internal proxy — are declared once in `machine.toml` and projected
into the opencode provider block by `setup`.

## 1. Problem

The discipline layer now assumes an environment it never verifies. `project-config.toml`
gates behavior per-repo; skills and rules invoke `gh`, `uv`, `bd`, the Codex plugin,
opencode, and ollama; the routing spec makes four provider families candidate dispatch
rungs; OpenRouter access rides an env key nothing checks. On the machine where all of that
happens to be installed, it works. On any other machine it fails one missing binary at a
time, mid-task, with no upfront diagnosis.

The portability milestone (PORT, agents-config-uxns2) makes this acute: the same discipline
layer must run on a work machine where OpenRouter, Ollama, and OpenCode are unavailable by
policy, Claude Code and Codex are present, and an internal OpenRouter-compatible API proxy
stands in for OpenRouter. Today there is no way to state any of that. Absence is
indistinguishable from misconfiguration, "not installed yet" is indistinguishable from
"forbidden here," and nothing writes the user- or project-level config that would encode
the difference.

Three narrow cousins exist and stay narrow: abn9.35 diffs deployed files against their
`src/` projection (one probe here, §4 row 12); abn9.8.24 doctors prgroom's `[verify]`
config only; the profiles spec routes what installs where but says nothing about what the
machine can run.

## 2. Locked decisions (owner interview, 2026-07-16)

These are requirements, not open questions:

1. **No standalone machine-profile artifact.** An earlier design draft proposed a declared
   per-machine constraint profile filtering the routing table. Rejected as
   over-complication: the disposition *is* the config. Doctor detects, asks once per gap,
   and persists the answer into surfaces that already exist or that doctor itself owns.
2. **Four disposition states per gap:** *install-and-rerun* (tool becomes present; nothing
   persisted), *off at user scope* (disabled on this machine, every project), *off at
   project scope* (disabled for this repo only), *auto-detect* (the default: persist
   nothing; absence at dispatch time simply skips the rung). An explicit "off" is a
   pre-answered detection; auto-detect costs zero new machinery because the routing spec's
   fail-lateral semantics already handle unavailable rungs.
3. **Offline-deterministic probes in v1.** Binary-on-PATH + version, env-var presence,
   config-file presence, drift diff. No network calls — no corp-network surprises, no
   false negatives from a flaky proxy. Endpoint reachability is an opt-in continuation.
4. **Sticky answers.** A persisted disposition is never re-asked; `setup --reset` reopens
   them. Anything else nags.
5. **Provider auth shape:** OpenRouter-compatible endpoints authenticate with a Bearer API
   key from an env var — exactly the existing opencode `{env:...}` mechanism. No custom
   headers, no mTLS, no credential helpers in v1.
6. **Setup scope:** dispositions plus scaffold — if `project-config.toml` is absent,
   `setup` offers to write a commented-defaults template. A full interactive onboarding
   wizard (walking gates, merge-policy, coverage) is a continuation, not v1.

## 3. CLI contract

Two subcommands on the installer CLI (`scripts/install.sh <verb>` /
`uv run python -m installer <verb>`). The shape conceptually parallels prgroom's *planned*
doctor/fix split (abn9.8.24, deferred — not yet built), but as two subcommands rather than
a flag pair, since these are general-purpose CLI verbs, not a package-local mode:

```
install.sh doctor [--json] [--project <path>]
install.sh setup  [--project <path>] [--defaults] [--reset]
```

- **`doctor`** — run every probe, print the report, exit. Read-only: writes nothing,
  prompts for nothing. `--json` emits the machine-readable envelope (§3.2). `--project`
  points at a repo other than the CWD for the project-scope probes; default is the CWD if
  it contains a `project-config.toml`, else user-scope probes only.
- **`setup`** — run doctor, then walk each *actionable gap* (§3.1) interactively with the
  four-option prompt, persist the answers (§5), and re-run the probes to confirm. Plain
  terminal prompts — this is a CLI, not an agent context. `--defaults` answers every
  prompt with auto-detect (persist nothing) for headless use. `--reset` clears persisted
  dispositions in the selected scope(s) and re-asks.

`doctor` and `setup` share one probe engine and one report renderer; `setup` is strictly
`doctor` + a resolution loop + writes. They are two sides of the same coin, not two
implementations.

### 3.1 Gap classes and exit codes

Each probe resolves to one of: `found` (with version where obtainable), `missing`,
`off-user`, `off-project`, `drift` (present but deviating from its expected projection),
`misconfigured` (present but structurally broken, e.g. provider entry names an env var
that is unset). `missing` on an *optional* row and `misconfigured` anywhere are the
actionable gaps `setup` walks. `off-*` rows render in the report (so a disabled tool is
visible, not invisible) but are never prompted — they are already answered.

Required rows accept only `install-and-rerun`: an `off-*` disposition on a required-severity
row is refused with an error (the discipline layer cannot run without them, so dispositioning
one away is self-defeating). A `missing` required row therefore always renders as an exit-code-1
defect, never as a walkable gap.

`doctor` exit codes: `0` all required rows found and no `misconfigured`; `1` a required
row is `missing` or any row is `misconfigured`; `2` probe-engine error. `drift` and
optional-`missing` do not affect the exit code — they are advisory.

### 3.2 JSON envelope

`doctor --json` emits one object: `schema` (versioned tag, `doctor-report-v1`),
`generated_at`, `machine_config` (path + whether `~/.agents/machine.toml` exists),
`project` (path + whether `project-config.toml` exists, or null), and `probes` — an array
of `{id, class, severity, state, version, detail, disposition_source}` where
`disposition_source` is `"user" | "project" | null`. The envelope is the integration
surface for anything downstream (a session-start hook, a dashboard, prgroom preflight);
the human table is a rendering of it.

## 4. Probe catalog

The catalog is a data table in the implementation, not code branches — adding a probe is a
row. Severity: **required** rows are what the discipline layer's core cannot run without;
everything else is **optional**.

| # | Probe id | Class | Severity | v1 detection |
|---|----------|-------|----------|--------------|
| 1 | `git` | core | required | binary on PATH + `git --version` |
| 2 | `gh` | core | required | binary + version; auth state NOT probed (locked decision 3) |
| 3 | `uv` | core | required | binary + version |
| 4 | `bd` | core | required | binary + version |
| 5 | `claude` | agent-cli | optional | binary + version |
| 6 | `codex` | agent-cli | optional | Codex plugin runtime present (companion script path per the Codex routing rule) or `codex` binary |
| 7 | `opencode` | agent-cli | optional | binary + version |
| 8 | `ollama` | agent-cli | optional | binary + version |
| 9 | `dolt` | support | optional | binary + version |
| 10 | `graphify` | support | optional | binary + version |
| 11 | provider entries | provider | optional | one probe per `[providers.*]` entry in `machine.toml` (§5.2): entry well-formed, named env var set, opencode projection present and consistent → else `misconfigured` |
| 12 | `deployed-drift` | config | optional | abn9.35's check: diff deployed files (`~/.claude/skills/`, rules, …) against their expected `src/` projection; requires running from an agents-config checkout, else `skipped` |
| 13 | `project-config` | config | optional | `project-config.toml` present in the target project; absent → the scaffold offer (locked decision 6) |

Notes:
- Row 11 is declaration-driven: doctor does not guess at providers; it validates what
  `machine.toml` declares. A machine with no `[providers.*]` entries has no provider gaps
  — OpenRouter access is itself declared as a provider entry (§7), not special-cased.
- Row 12 makes doctor the home abn9.35 wanted: that bead revives as the probe's
  implementation unit rather than a separate command.
- No probe touches the network, reads auth tokens, or shells into login flows.

## 5. Disposition model and persistence

### 5.1 States and precedence

Per gap: `install-and-rerun` / `off-user` / `off-project` / `auto-detect` (default).
Precedence at read time: **project `off` > user `off` > auto-detect**. There is no
affirmative "on" state — presence is "on"; forcing a tool on cannot be expressed because
it cannot be enforced.

### 5.2 `~/.agents/machine.toml` (user scope)

Doctor-owned: `setup` writes it, `doctor` and dispatch-time consumers read it. It lives in
`~/.agents/` beside the user-owned `profiles.toml` but is a distinct file — the profiles
spec pins `profiles.toml` as never machine-written, and this file is machine-written by
design. Never installed, never pruned, never templated from `src/`.

```toml
schema_version = 1

[tools.ollama]
disposition = "off"          # only "off" is ever persisted; auto-detect persists nothing
reason = "corp policy"       # optional free text, rendered in the doctor report

[providers.work-proxy]        # any OpenRouter-compatible endpoint, §7
base_url = "https://llm-proxy.internal.example.com/api/v1"
api_key_env = "WORK_PROXY_API_KEY"
models = ["internal/gpt-large", "internal/claude-proxy"]

[providers.openrouter]        # OpenRouter itself is just another entry
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
models = ["z-ai/glm-5.2", "fugu/fugu-ultra"]
```

### 5.3 `project-config.toml` `[tools]` (project scope)

```toml
[tools]
ollama = "off"                                        # bare form
opencode = { disposition = "off", reason = "corp policy" }  # table form, when a reason is worth recording
```

Both forms are legal; the bare string is shorthand for the table form without a `reason`.

`setup` edits only this section; it never rewrites the rest of the file (scaffold offer
aside, which only fires when the whole file is absent).

## 6. Consumers: dispatch-time disposition contract

Anything that selects a model rung or invokes an agent CLI consults, in order: project
`[tools]` off → user `machine.toml` off → runtime detection. An `off` at either scope
reads exactly like `missing` reads today — the rung is skipped and fallback proceeds
laterally, per the routing spec's provider-unavailable semantics. No consumer needs new
failure handling; `off` is a pre-answered detection (locked decision 2).

The model-routing spec (`2026-07-04-model-routing-policy-and-escalation-ladder.md`)
currently treats all four provider families as unconditionally candidate rungs. Its
amendment — fallback-chain resolution filters rungs through this disposition contract — is
a continuation item here rather than an edit in this PR, since that spec is a draft under
active review on its own beads.

## 7. OpenRouter-compatible endpoint parameterization

The narrow, work-machine slice of uxns2.2, extending the wiring that
`2026-07-04-openrouter-wiring-and-invoker-smoke.md` (abn9.40.3) specifies. That spec
hardcodes OpenRouter's identity in the opencode provider block; this section makes the
endpoint a parameter with OpenRouter as merely the default instance.

- **Single source of truth:** the `[providers.<name>]` entry in `machine.toml` (§5.2) —
  `base_url` + `api_key_env` + `models`. Bearer-key auth via the named env var, nothing
  more (locked decision 5).
- **Projection:** `setup` writes each declared provider into the opencode config as a
  custom provider block (`options.baseURL` + `options.apiKey = "{env:<api_key_env>}"` +
  the model list), preserving all other keys — the same additive discipline abn9.40.3's
  snippet mandates. The opencode block is a *projection*; the `machine.toml` entry is the
  declaration. Doctor's row-11 probe flags divergence between them as `misconfigured`.
- **Model ids need no mapping layer:** opencode addresses models as
  `providerID/modelID`, and the model list is already per-entry config — an internal
  proxy's model names are just the entry's `models` values.
- **Downstream reach:** any dispatcher that can reach OpenRouter rungs via
  `opencode run --model openrouter/<id>` reaches an internal proxy identically via
  `opencode run --model work-proxy/<id>` with zero dispatcher changes. prgroom AgentSpec
  links and routing-table rungs name `<provider>/<model>` tokens and are agnostic to which
  entry backs them.
- **uxns2.2's remainder stays open:** the generalized agent-config schema for arbitrary
  non-opencode harnesses (custom invocation commands, parameters, AgentSpec reconciliation)
  is untouched by this slice.

## 8. Non-goals (v1)

- **Network reachability probes** — opt-in `doctor --network` is a continuation.
- **Auth-state probing** — no "is `gh`/`claude`/`codex` logged in"; presence only.
- **Full project onboarding wizard** — the scaffold offer writes commented defaults; an
  interactive walk of gates/merge-policy/coverage is a continuation.
- **Forcing tools on, or per-archetype routing edits** — dispositions gate availability;
  routing preference stays the routing spec's problem.
- **Auto-installing missing tools** — `install-and-rerun` prints the install command
  (e.g. `brew install …`, `uv tool install …`) and stops; doctor never runs installers.
- **The uxns2.2 generalized harness schema** — only §7's slice ships here.

## 9. Acceptance criteria

1. `install.sh doctor` runs every catalog row offline, renders the table with per-row
   state/severity/version, and honors the §3.1 exit-code contract. `--json` emits the
   `doctor-report-v1` envelope.
2. `install.sh setup` walks exactly the actionable gaps with the four-option prompt,
   persists `off-user` to `~/.agents/machine.toml`, `off-project` to
   `project-config.toml [tools]`, persists nothing for auto-detect, and never re-asks a
   persisted disposition absent `--reset`. `--defaults` completes with zero prompts and
   zero writes.
3. A `[providers.<name>]` entry with `base_url`, `api_key_env`, and `models` projects into
   the opencode provider block additively (all pre-existing keys byte-preserved), and
   doctor reports `misconfigured` when the env var is unset or the projection diverges
   from the declaration.
4. With `ollama = "off"` at either scope, the doctor report shows `off-*` (with reason,
   when present) and setup does not prompt for it.
5. Row-12 drift probe reproduces abn9.35's deployed-vs-src diff from an agents-config
   checkout and reports `skipped` elsewhere.
6. `make ci-installer` green; probe engine and disposition precedence covered per the
   repo's coverage floor.

## Continuations

- feature: doctor probe engine + report (child of uxns2.6) — the §4 catalog as a data
  table, §3.1/§3.2 contracts, offline-only. AC: spec §9.1, §9.4, §9.5; abn9.35 closes as
  absorbed when its row-12 probe lands, or revives as this bead's sub-item.
- feature: setup resolution loop + persistence (child of uxns2.6, blocked by the probe
  engine) — four-option prompt, `machine.toml` + `[tools]` writers, `--defaults`,
  `--reset`, scaffold offer. AC: spec §9.2.
- feature: provider declaration → opencode projection (child of uxns2.2, related-to
  abn9.40.3 and blocked by its wiring) — §7's slice. AC: spec §9.3.
- task: model-routing spec amendment — fallback-chain resolution filters rungs through the
  §6 disposition contract (child of the routing spec's bead abn9.40.2). AC: routing spec
  names the precedence chain project-off > user-off > detection.
- task: opt-in `doctor --network` reachability probe for declared provider endpoints
  (child of uxns2.6, P3). AC: off by default; per-entry pass/fail with timeout.
