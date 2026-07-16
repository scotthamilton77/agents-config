# Installer-Owned CLI Deploys (`work` + `prgroom`)

**Date:** 2026-07-15
**Bead:** agents-config-wgclw.9.9 (blocks agents-config-wgclw.9.4)
**Status:** Approved design (owner-approved in-session 2026-07-15)

## 1. Context and goal

`packages/workcli` (the `work` facade CLI) and `packages/prgroom` are real,
CI-gated CLI packages that no deployed user space can invoke: the installer has
no mechanism to put a CLI on PATH. The prgroom design plan
(`docs/plans/2026-05-12-prgroom-cli-design.md`, distribution section) and the
prgroom deployment HLD (`docs/architecture/prgroom/c4-deployment.md`) already
prescribe the pattern — installer-owned `uv tool install ./packages/<pkg>`,
idempotent, uninstalled on `--prune` — but the bash-era implementation was
retired when `install.sh` collapsed to a stub, and the Python installer never
re-adopted it.

This design adds a **generic CLI-deploy stage** to the Python installer and
wires **both** `workcli` (binary `work`) and `prgroom` (binary `prgroom`)
through it. Landing it unblocks the discipline-layer migration
(agents-config-wgclw.9.4): assets may only call `work` once the installer puts
it on PATH.

Owner decisions recorded (2026-07-15, in-session): scope = generic seam, both
CLIs wired now; mechanism = `uv tool install` stage (not launcher shims, not
zipapps).

## 2. Scope

In scope:

- A closed registry of deployable CLI packages (`workcli`, `prgroom`).
- A new injected subprocess port for `uv tool` operations + smoke checks.
- A deploy stage in the user install pipeline (skip / fresh / takeover /
  upgrade / dry-run semantics), consent-gated like file overwrites.
- Receipt extension (additive `clis` field) threaded through the existing
  `record_receipt`/`merge_receipt` write path, + prune-side
  `uv tool uninstall` for deregistered CLIs.
- Summary rendering of `cli:<name>` targets.
- Docs sweep: user guide, package AGENTS.md files, repo AGENTS.md, installer
  HLD.

Out of scope:

- Installing `bd` (external prerequisite, unchanged).
- Deploying `pdlc`, `holding-place`, or `vizsuite` (early packages; the
  registry is deliberately closed).
- Project-scoped installs (`--project` never deploys CLIs).
- The discipline-layer asset migration itself (agents-config-wgclw.9.4).
- Package `__version__` surfacing (digest-based staleness makes it unneeded).

## 3. Registry (pure data)

New module `packages/installer/src/installer/core/clis.py`:

```python
@dataclass(frozen=True, slots=True)
class CliSpec:
    name: str          # package name == uv tool name, e.g. "workcli"
    package_dir: str   # repo-relative, e.g. "packages/workcli"
    binary: str        # console-script name, e.g. "work"
    smoke_args: tuple[str, ...]  # e.g. ("--protocol-version",)

CLI_PACKAGES: tuple[CliSpec, ...] = (
    CliSpec("workcli", "packages/workcli", "work", ("--protocol-version",)),
    CliSpec("prgroom", "packages/prgroom", "prgroom", ("--help",)),
)

RETIRED_CLIS: tuple[str, ...] = ()  # names formerly in CLI_PACKAGES
```

Closed by design, like the `Tool` enum and unlike the plugins dir-scan:
`packages/` contains early packages that must NOT auto-deploy. Adding a CLI is
a deliberate one-line registry change. Retiring one moves its name to
`RETIRED_CLIS` — the closed historical allowlist that (together with
`CLI_PACKAGES`) bounds uninstall authority (§7): the receipt alone never
authorizes an uninstall.

## 4. Injected port

`IOPort` is prompts/logging only; subprocess work gets its own seam per the
package's pure-core/injected-IO discipline. In `core/clis.py` (protocol beside
its consumer, mirroring `io_port.py`'s layout):

```python
@runtime_checkable
class CliDeployPort(Protocol):
    def bin_dir(self) -> Path: ...
    def shim_path(self, binary: str) -> Path | None: ...
    def tool_list(self) -> frozenset[str] | None: ...
    def tool_install(self, package_dir: Path) -> CommandResult: ...
    def tool_uninstall(self, name: str) -> CommandResult: ...
    def update_shell(self) -> CommandResult: ...
    def which(self, binary: str) -> Path | None: ...
    def smoke(self, shim: Path, args: tuple[str, ...]) -> CommandResult: ...
```

`CommandResult` is a frozen dataclass `(ok: bool, output: str)` — output is
merged stdout+stderr, surfaced verbatim on failure.

**PATH-independence is load-bearing.** All installed-state decisions use uv's
bin dir directly, never the process PATH: `bin_dir()` resolves uv's shim
directory (`uv tool dir --bin`; on failure, fall back to uv's full documented
resolution order — `$UV_TOOL_BIN_DIR`, then `$XDG_BIN_HOME`, then
`$XDG_DATA_HOME/../bin`, then `~/.local/bin`);
`shim_path(binary)` returns `bin_dir()/<binary>` iff that
file exists, else `None`. `tool_list()` returns the installed uv tool names
(parsed `uv tool list`), or `None` when the query fails — consumers must
treat `None` as "ownership unproven" and fall toward consent, never toward
silent `--force`. `which` (plain `shutil.which`) is used **only** for
the PATH-reachability invariant (§6), never for install-state decisions.
`smoke` executes the shim by the **absolute path** it is given — a
`FileNotFoundError` there genuinely means the install is broken, not that
PATH is unconfigured. `update_shell` runs `uv tool update-shell` (uv's own
mechanism for ensuring the tool bin dir is on PATH via shell config —
verified present in uv 0.10.4).

Real implementation `UvCliDeploy`: `tool_install` is **lock-respecting** —
it exports fully pinned constraints from the package's committed lock
(`uv export --frozen --no-dev --no-emit-project -o <tmpfile>`, run against
the package dir) and installs with
`uv tool install --force --constraints <tmpfile> <abs package_dir>`, so the
deployed environment reflects the same dependency set CI audits (a plain
`uv tool install` resolves fresh and ignores `uv.lock`; prgroom's unbounded
`typer` bound would otherwise drift). A package without a `uv.lock`
installs unconstrained (mirroring §5's digest rule). `tool_uninstall` runs
`uv tool uninstall <name>`. All subprocess calls use
`subprocess.run(..., capture_output=True, text=True)` with bounded timeouts —
300s install (cold uv cache + dependency resolution can be slow), 30s smoke,
10s `bin_dir`/`tool_list`/`update_shell` — and `TimeoutExpired` /
`FileNotFoundError` map to `CommandResult(ok=False, output=...)` (or the
documented fallback for `bin_dir`, or `None` for `tool_list`).

Test fake `ScriptedCliDeploy`: per-method answer queues + transcript,
mirroring `ScriptedIO` (including the exhaustion-error self-diagnosis).

**Injection seam:** `main()` and `_run()` gain an optional
`cli_deploy: CliDeployPort | None = None` keyword (mirroring `io`);
`_run` constructs `UvCliDeploy` when not injected. Unit tests drive
`main(..., cli_deploy=ScriptedCliDeploy(...))`.

## 5. Source digest (staleness test)

`cli_source_digest(package_dir: Path) -> str` — a deterministic
`sha256:<hex>` over the sorted `(relpath, sha256(bytes))` of the package's
**deployable source**: `pyproject.toml`, `uv.lock`, and every file under
`src/**`. Excludes `__pycache__` directories and `*.pyc` (build churn is not
a reason to reinstall). Same construction as `receipt.dir_content_digest`,
with the exclusion filter and the explicit file list; lives in
`core/clis.py` beside its consumers.

Missing-input handling: `pyproject.toml` absent → loud error (a registry
entry pointing at a non-package is a wiring bug, fail fast); `uv.lock` absent
→ silently omitted from the digest input (a future lock-less package remains
deployable; the lock appearing later changes the digest, correctly forcing a
reinstall).

Digest inputs deliberately exclude `tests/**`, `README`, `AGENTS.md` — a
docs-only package change does not force a reinstall.

## 6. Deploy stage semantics

New function in `core/run.py`, called from `cli._run()`
(user path only) after `install_plugin_routes`, inside the receipt lock,
gated on `not args.prune_only`:

```python
def deploy_clis(
    specs: Sequence[CliSpec], *, repo_root: Path, prior: Receipt,
    deploy: CliDeployPort, io: IOPort,
    dry_run: bool = False, auto_yes: bool = False,
) -> CliDeployOutcome  # per-CLI outcomes (entry written / skipped / failed)
                       # + counters; any_failed is derived from the outcomes
```

Per registered CLI, in registry order. Two PATH-independent signals feed the
table: "shim present" means `shim_path(binary) is not None` (the uv bin dir
test, never `which`); "env present" means the tool's name appears in
`tool_list()`. A shim can exist without an env (stale link) and an env
without a shim (link removed) — a valid receipt entry proves ownership;
absent that proof, ANY evidence of an existing install (shim OR env, or an
unproven `tool_list() is None`) demands takeover consent, because
`uv tool install --force` silently replaces an existing environment:

| Prior receipt entry | Existing-install evidence | Digest vs receipt | Action |
|---|---|---|---|
| present | shim present | equal | **verify**: smoke the shim (absolute path); ok → `SKIPPED_IDENTICAL` (no install subprocess); smoke fails → heal-reinstall, no prompt (a corrupted-but-present install we own) |
| present | shim missing | (any) | heal-reinstall, no prompt (we own it per receipt; a missing shim means the tool is already unusable, so healing deliberately takes precedence over the upgrade prompt even when the digest also differs) |
| present | shim present | differs | **upgrade** → consent prompt (default No; `--yes` accepts) |
| absent | none (no shim AND `tool_list()` proves the env absent) | — | **fresh install**, no prompt (new-file semantics) |
| absent | shim present OR env present OR `tool_list()` is `None` (unproven) | — | **takeover** → consent prompt (default No; `--yes` accepts); never a silent `--force` |

- Consent declines count as skipped and leave the receipt's prior entry (if
  any) untouched.
- After a real install: resolve the shim via `shim_path(binary)` — missing
  now IS a failure (uv said ok but produced no shim) — then run the smoke
  command against that absolute path. Smoke failure → `io.err` with the
  command output, failure recorded, receipt entry NOT written (next run
  retries). Smoke success → receipt entry written with the new digest.
- **PATH-reachability invariant (a deployment requirement, not an
  advisory):** the whole point of this design is assets invoking bare
  `work`/`prgroom`, so an unreachable or shadowed binary is a deployment
  FAILURE, evaluated on **every run** for every registry CLI whose shim is
  present — skips included, so the steady state cannot go silently
  unusable. Three outcomes of `which(binary)`:
    - resolves inside `bin_dir()` → reachable, silent;
    - `None` (bin dir not on PATH) → offer a consent-gated
      `update_shell()` (`uv tool update-shell`, uv's own PATH-provisioning
      mechanism; `--yes` accepts, `--dry-run` reports would-run). On
      success, `io.info` that new shells pick up the PATH change (the
      current process env is unchanged, so `which` is NOT re-checked this
      run) and the run counts as resolved. Declined, or `update_shell`
      fails → `io.err` with the exact PATH line to add → deployment
      failure, exit 1;
    - resolves to a path *outside* `bin_dir()` → a foreign `<binary>`
      shadows the deployed one; `update_shell` cannot fix PATH *order* →
      `io.err` naming both paths with the remediation (remove/rename the
      foreign binary or reorder PATH) → deployment failure, exit 1.
- **Receipt vs. exit code on reachability failure (deliberate divergence
  from the reviewers' "do not persist" letter, honoring its substance):**
  the receipt keeps its established contract — a mirror of install state on
  disk — so a successful install+smoke IS receipted even when reachability
  fails; the run's exit code (1) and `io.err` carry deployment health.
  Refusing the receipt would force a wasteful `--force` reinstall on every
  run in an unreachable environment while fixing nothing (the install
  itself is fine; PATH is the defect, and it is re-checked every run
  regardless). The installer still never reports overall success while a
  CLI is unreachable or shadowed.
- `--dry-run`: report would-skip / would-install / would-upgrade /
  would-take-over (and would-run-update-shell) per CLI; no
  `tool_install`/`tool_uninstall`/`smoke`/`update_shell` calls, no lock
  (consistent with the dry-run-writes-nothing contract; `bin_dir`/
  `shim_path`/`tool_list`/`which`/digest reads are non-mutating and stay
  available so the preview reports real decisions; the verify row reports
  would-skip without smoking).
- No-TTY without `--yes` at a consent point → `ConsentRequiredError`, exit 1
  (existing convention).
- Counters map onto the existing summary vocabulary under target name
  `cli:<name>`: fresh/heal → `created`, upgrade/takeover-accepted →
  `updated`, skip/decline → `skipped`, uninstall → `pruned`.
- **Summary rendering (required change):** `render_summary`'s report-target
  set is built from its `tools`/`plugins` arguments today, so `cli:<name>`
  keys would be silently dropped. The `render_summary` call and
  `_report_targets` are extended with the deployed CLI target names
  (`clis=[...]`) so each CLI renders as an ordinary per-target block.
- **Failure surfacing:** a deploy/smoke failure increments no counter — it
  surfaces via the `io.err` line (with subprocess output) and the run's exit
  code. `deploy_clis` returns a failure indicator; `_run` carries it out of
  the lock (`with`) block and returns exit 1 **after** the summary renders,
  never a silent success. The stage never raises on a deploy failure
  mid-loop: it records and continues to the next CLI (one broken package
  must not block the other).

`--project` runs (`_run_project`) do not deploy CLIs: CLI deploys are
user-space state (`uv tool` environments are per-user, not per-project).

## 7. Receipt extension and prune

CLI deploys must not masquerade as file entries — the file-orphan prune
machinery would `rm` the shim, but uninstalling a uv tool means
`uv tool uninstall` (env + shim). Instead, `Receipt` gains an additive field:

```python
@dataclass(frozen=True, slots=True)
class CliReceiptEntry:
    name: str      # registry name == uv tool name, e.g. "workcli"
    binary: str    # e.g. "work"
    digest: str    # cli_source_digest at install time

@dataclass(frozen=True, slots=True)
class Receipt:
    ...
    clis: tuple[CliReceiptEntry, ...] = ()
```

Integrity compatibility follows the `dir_digest` precedent analogously (that
precedent appends a positional list element only when present; here the
mechanism is a `"clis"` dict key included **only when the tuple is
non-empty**), so every receipt written before this field existed hashes
byte-identically and its persisted integrity still validates. No
`SCHEMA_VERSION` bump. `receipt_store` read/write round-trips the field,
defaulting absent → empty; each `clis` entry's `name`/`binary`/`digest` is
validated as a non-null string on read, CORRUPT otherwise (the store's
established fail-closed discipline — a malformed entry must not drive
deploy/prune decisions).

Downgrade caveat (accepted): a pre-feature installer reading a
`clis`-bearing receipt computes integrity without `clis` and sees a mismatch
→ CORRUPT → prune fail-closed (skipped, receipt untouched) and consent
re-prompts. Fail-closed with no data loss; noted, not mitigated.

**Write-path threading (required change; the write path is
`record_receipt` → `merge_receipt`, which reconstructs the `Receipt` and
would otherwise silently drop `clis`):** BOTH halves feed the merge,
mirroring the file precedent (`prune_pipeline` returns `pruned_paths`, which
`_run` threads into `record_receipt`). The deploy half's `CliDeployOutcome`
(§6) carries per-CLI results; the CLI prune half returns
`uninstalled_cli_names: set[str]` (uninstalls that actually completed).
`cli._run` threads both into `record_receipt` → `merge_receipt`, which
builds the new `clis` tuple over the **union** of registry CLIs and prior
`clis` entries:

- registry CLI → the new entry when this run deployed it, else the retained
  prior entry (skip/decline/failure keep the old record);
- non-registry prior entry (a retired CLI) → dropped iff its name is in
  `uninstalled_cli_names`, else retained (a declined or failed uninstall
  keeps the record, so retirement is retried next prune).

Under `--prune-only` the deploy half never runs: its contribution defaults
to empty and prior entries for registry CLIs are retained as-is, while
completed uninstalls still drop — so a retired CLI converges (entry gone)
even on a prune-only run. Both new `record_receipt`/`merge_receipt`
parameters default to empty, and `_run_project` passes neither — a
`--project` run compiles unchanged and leaves any `clis` in its
project-local receipt untouched (there are none in practice).

Prune half (runs under `--prune` / `--prune-only`, after the file prune): a
CLI named in the prior receipt's `clis` but absent from `CLI_PACKAGES` is
retired → consent-gated `uv tool uninstall` (per-item prompt, `--yes`
auto-accepts, `--dry-run` previews, no-TTY without `--yes` →
`ConsentRequiredError` exit 1 — same convention as the deploy side).
**Uninstall authority is bounded by the closed registry history, never by
the receipt:** the name must appear in `CLI_PACKAGES ∪ RETIRED_CLIS` (§3)
for an uninstall to even be offered — the receipt's integrity digest is
tamper-evidence, not authentication, so a receipt entry naming a foreign
tool (e.g. `ruff`) must not become deletion authority under `--prune
--yes`. A prior `clis` entry whose name is outside that closed set is
warned about and relinquished (dropped from the receipt without any
uninstall — we never owned it; mirrors the file-prune drift-relinquish
posture). A declined uninstall retains the receipt entry (the tool is
still installed; retirement is retried next prune). Uninstall of an
allowlisted tool uv no longer knows (user removed it manually) is treated
as success — the desired state is "absent".

A CORRUPT prior receipt disables the CLI prune half exactly as it disables
file pruning (fail closed); the deploy half still runs, treating every CLI by
the no-prior-entry rows of the decision table — and because those rows
demand takeover consent whenever ANY existing-install evidence is present
(shim, env, or an unproven `tool_list()`), receipt corruption can never
convert an existing environment into a silent `--force` replacement.
Consequence (accepted, mirrors the downgrade caveat): `record_receipt` is
gated on a non-corrupt prior, so a deploy under a corrupt receipt is not
persisted — each subsequent run re-encounters the install evidence with no
prior entry and re-prompts as a takeover until the receipt is reset or
repaired. Fail-closed, no data loss, no unconsented overwrite.

## 8. Failure posture

- No silent fallbacks: every subprocess failure surfaces via `io.err` with
  the command output, and the run exits non-zero.
- The stage never raises on a deploy failure mid-loop; it records the failure
  and continues to the next CLI, then the run reports exit 1 (§6 failure
  surfacing).
- `ConsentRequiredError` propagates (exit 1) — same as file installs.

## 9. Docs sweep (same PR)

- Repo `AGENTS.md`: both "not yet installed by the installer" notes
  (workcli, prgroom) become "installed by the installer".
- `docs/guide/getting-started.md`: mention `work` + `prgroom` land on PATH.
- `docs/guide/configuration.md`: the "Optional: the prgroom CLI" manual
  `uv tool install` section becomes installer-owned.
- `packages/prgroom/AGENTS.md`: "Not installed by the installer" section
  updated.
- `packages/workcli/AGENTS.md` / `README.md`: invocation notes gain the
  installed-binary path.
- `docs/architecture/installer/` HLD amended in place: new stage in the
  engine C4 (`c4-l3-engine.md`), receipt schema addition (`data-view.md`),
  sequence update (`sequences.md`), `installer-design.md` overview.

## 10. Test plan

Unit tests through `ScriptedCliDeploy` + `ScriptedIO`, each pinning a coded
decision (house convention; no tautologies):

1. Verify/skip: receipt digest equal + shim present → smoke runs against
   the absolute shim path; ok → no install/uninstall calls, skipped
   counter; smoke FAILS → heal-reinstall without prompt (corrupted-but-
   present owned install).
2. Fresh install: no receipt entry, no shim, `tool_list()` proves env
   absent → install runs, no consent prompt, created counter, receipt
   entry written.
3. Heal: receipt entry present, shim missing → reinstall without prompt.
4. Upgrade: digest differs → consent prompt; accept → install + updated
   counter + new digest; decline → skipped, prior entry retained.
5. Takeover: no receipt entry + ANY existing-install evidence — shim
   present, OR env in `tool_list()` with no shim, OR `tool_list()` is
   `None` (unproven) → consent prompt; accept → install + updated counter
   + entry written; decline → skipped, no entry. Never a promptless
   `--force` on any of the three evidence triggers.
6. Dry-run: each branch reports would-X, zero
   install/uninstall/smoke calls, receipt untouched.
7. Smoke failure: install ok, smoke fails → err surfaced, no receipt entry,
   exit 1; smoke runs against the absolute shim path (asserted via the
   fake's transcript). Install-ok-but-no-shim is likewise a failure.
8. Install failure: `tool_install` not ok → err surfaced, other CLI still
   processed, exit 1.
9. Reachability invariant: `which` inside `bin_dir()` → silent, exit 0;
   `which` is `None` → update-shell consent prompt — accept + success →
   info notice, run resolved (exit 0), entry written; decline OR
   `update_shell` failure → `io.err` with the PATH line, exit 1 (entry
   still written — install state is receipted, deployment health is the
   exit code); `which` outside `bin_dir()` → shadowing `io.err` naming
   both paths, exit 1; the invariant also fires on a `SKIPPED_IDENTICAL`
   run (steady-state enforcement, not deploy-only).
10. Prune: prior `clis` entry not in registry but in `RETIRED_CLIS` →
    consent-gated uninstall, pruned counter, entry dropped; decline →
    entry retained (retirement retried next prune); a prior entry whose
    name is OUTSIDE `CLI_PACKAGES ∪ RETIRED_CLIS` (tampered/foreign, e.g.
    `ruff`) → NO uninstall offered even under `--yes`, warn + entry
    relinquished; `--dry-run` previews; uninstall-of-absent treated
    as success; **`--prune-only` run** (deploy half never ran) still drops a
    completed uninstall's entry through the real
    `record_receipt`/`merge_receipt` path while retaining registry CLIs'
    prior entries.
11. Receipt round-trip: `clis` field read/write; legacy receipt (no field)
    loads as empty and its integrity still validates; canonical_bytes omits
    empty `clis`; a malformed `clis` entry (non-string field) reads as
    CORRUPT; **second no-op run** reads back a non-empty `clis` through
    the real `record_receipt`/`merge_receipt` path and skips.
12. No-TTY without `--yes` at a CLI consent point (deploy AND prune sides)
    → `ConsentRequiredError` path, exit 1.
13. `--project` run performs no CLI deploys and leaves any pre-existing
    `clis` in the project-local receipt untouched.
14. CORRUPT prior receipt: CLI prune half skipped (fail closed); deploy half
    runs treating every CLI by the no-prior-entry rows; the deploy is not
    persisted (receipt untouched).
15. Digest rules: missing `pyproject.toml` → loud error; missing `uv.lock`
    → omitted (and adding a lock later changes the digest); a change under
    `tests/**` or `__pycache__`/`*.pyc` does not change the digest.
16. Lock-respecting install: `tool_install` exports pinned constraints
    from the package lock and passes `--constraints` (asserted via the
    fake's transcript); a lock-less package installs unconstrained.
17. `bin_dir` fallback: with the `uv tool dir --bin` query forced to fail,
    resolution honors `$UV_TOOL_BIN_DIR`, then `$XDG_BIN_HOME`, then
    `$XDG_DATA_HOME/../bin` (only `XDG_DATA_HOME` configured), then
    `~/.local/bin`.

Gate: `make ci-installer` (ruff, format, mypy --strict, pytest --cov 90%
branch, pip-audit, entry-verify) green before push; delivery routes HEAVY at
the completion gate (`packages/**` floors it).

## 11. Continuations

- none — this spec is the deliverable's design; implementation proceeds under
  the same bead (agents-config-wgclw.9.9), and the discipline-layer migration
  it unblocks is already tracked (agents-config-wgclw.9.4).

## Review feedback

- 2026-07-15 ralf-review cycle 1 (fresh-eyes, opus): 1 Critical, 4 Major,
  7 Minor. All folded: C1/M1 PATH-independent decision
  signal + absolute-path smoke (§4, §6); M2 explicit
  `record_receipt`/`merge_receipt` threading (§7); M3 summary-rendering
  extension (§6); M4 + m6 test-plan branches (§10 items 5, 10, 12, 14); m1
  timeouts (§4); m2 downgrade caveat (§7); m3 failure surfacing (§6); m4
  injection seam (§4); m5 exit-flag control flow (§6); m7 digest
  missing-input rules (§5).
- 2026-07-15 ralf-review cycle 2 (fresh-eyes, opus, against the cycle-1
  revision): 0 Blocking, 1 Critical, 3 Major, 7 Minor. All folded: C1
  prune-half `uninstalled_cli_names` threading + union merge rule +
  `--prune-only` convergence (§7, §10 item 10); M1 advisory evaluated every
  run (§6, §10 item 9); M2 `_run_project` call-site defaults (§7, §10 item
  13); M3 digest-branch tests (§10 item 15); m1 `clis` entry validation
  (§7, §10 item 11); m2 heal-over-upgrade rationale (§6); m3 corrupt-receipt
  persistence consequence (§7, §10 item 14); m4 advisory no-warn branch
  (§10 item 9); m5 `deploy_clis` signature/return contract (§6); m6
  "analogously" precision (§7); m7 `bin_dir` env-override fallback (§4).
  Recorded verdict per the ralf-review budget contract (2 cycles,
  exhausted with a Critical present in the final cycle): **FAIL** — the
  verdict is recorded as-is; the folds above improve the artifact but do
  not upgrade the score.
- 2026-07-16 Codex cross-model round 1 (adversarial: needs-attention, 3
  high / 1 medium; native: 2 P1 / 1 P2). All folded: PATH reachability
  promoted from advisory to deployment invariant with consent-gated
  `uv tool update-shell` and hard error on decline/shadow (§6, §10 item
  9; receipt-vs-exit-code divergence rationale recorded); ownership
  verification via `tool_list()` — takeover consent on any
  existing-install evidence, corrupt receipt can never silent-`--force`
  (§4, §6, §7, §10 items 2/5); uninstall authority bounded by
  `CLI_PACKAGES ∪ RETIRED_CLIS`, foreign receipt names relinquished
  without uninstall (§3, §7, §10 item 10); lock-respecting install via
  `uv export --frozen` + `--constraints` (§4, §10 item 16); full uv
  bin-dir fallback precedence incl. `$XDG_DATA_HOME/../bin` (§4, §10
  item 17); verify-on-skip smoke with heal-on-fail (§6, §10 item 1).
