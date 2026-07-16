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
- Receipt extension (additive `clis` field) + prune-side `uv tool uninstall`
  for deregistered CLIs.
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
    name: str          # package name, e.g. "workcli"
    package_dir: str   # repo-relative, e.g. "packages/workcli"
    binary: str        # console-script name, e.g. "work"
    smoke_args: tuple[str, ...]  # e.g. ("--protocol-version",)

CLI_PACKAGES: tuple[CliSpec, ...] = (
    CliSpec("workcli", "packages/workcli", "work", ("--protocol-version",)),
    CliSpec("prgroom", "packages/prgroom", "prgroom", ("--help",)),
)
```

Closed by design, like the `Tool` enum and unlike the plugins dir-scan:
`packages/` contains early packages that must NOT auto-deploy. Adding a CLI is
a deliberate one-line registry change.

## 4. Injected port

`IOPort` is prompts/logging only; subprocess work gets its own seam per the
package's pure-core/injected-IO discipline. In `core/clis.py` (protocol beside
its consumer, mirroring `io_port.py`'s layout):

```python
@runtime_checkable
class CliDeployPort(Protocol):
    def tool_install(self, package_dir: Path) -> CommandResult: ...
    def tool_uninstall(self, name: str) -> CommandResult: ...
    def which(self, binary: str) -> Path | None: ...
    def smoke(self, binary: str, args: tuple[str, ...]) -> CommandResult: ...
```

`CommandResult` is a frozen dataclass `(ok: bool, output: str)` — output is
merged stdout+stderr, surfaced verbatim on failure (uv's own PATH warnings
ride along).

Real implementation `UvCliDeploy`: `tool_install` runs
`uv tool install --force <abs package_dir>`; `tool_uninstall` runs
`uv tool uninstall <name>`; `which` delegates to `shutil.which`; `smoke` runs
`<binary> <args...>` with a timeout. All subprocess calls
`subprocess.run(..., capture_output=True, text=True)` with a bounded timeout
(60s install, 10s smoke); `TimeoutExpired` and `FileNotFoundError` (uv absent
— impossible by construction since the installer runs under `uv run`, but fail
loud anyway) map to `CommandResult(ok=False, output=...)`.

Test fake `ScriptedCliDeploy`: per-method answer queues + transcript,
mirroring `ScriptedIO` (including the exhaustion-error self-diagnosis).

## 5. Source digest (staleness test)

`cli_source_digest(package_dir: Path) -> str` — a deterministic
`sha256:<hex>` over the sorted `(relpath, sha256(bytes))` of the package's
**deployable source**: `pyproject.toml`, `uv.lock`, and every file under
`src/**`. Excludes `__pycache__` directories and `*.pyc` (build churn is not a
reason to reinstall). Same construction as `receipt.dir_content_digest`, with
the exclusion filter and the explicit file list; lives in `core/clis.py`
beside its consumers.

Digest inputs deliberately exclude `tests/**`, `README`, `AGENTS.md` — a
docs-only package change does not force a reinstall.

## 6. Deploy stage semantics

New function `deploy_clis(...)` in `core/run.py`, called from `cli._run()`
(user path only) after `install_plugin_routes`, inside the receipt lock,
gated on `not args.prune_only`. Per registered CLI, in registry order:

| Prior receipt entry | Shim on PATH | Digest vs receipt | Action |
|---|---|---|---|
| present | found | equal | `SKIPPED_IDENTICAL` (no subprocess) |
| present | missing | (any) | reinstall, no prompt (heal a user uninstall — we own it per receipt) |
| present | found | differs | **upgrade** → consent prompt (default No; `--yes` accepts) |
| absent | missing | — | **fresh install**, no prompt (new-file semantics) |
| absent | found | — | **takeover** of a manual install → consent prompt (default No; `--yes` accepts) |

- Consent declines count as skipped and leave the receipt's prior entry (if
  any) untouched.
- After a real install: run the smoke command. Smoke failure → `io.err` with
  the command output, failure recorded, receipt entry NOT written (next run
  retries). Smoke success → receipt entry written with the new digest.
- Post-install, if `which(binary)` still misses, warn that `~/.local/bin` is
  not on PATH (non-fatal; uv's own warning text is also in the surfaced
  output).
- `--dry-run`: report would-skip / would-install / would-upgrade /
  would-take-over per CLI; no subprocess calls, no lock (consistent with the
  dry-run-writes-nothing contract).
- No-TTY without `--yes` at a consent point → `ConsentRequiredError`, exit 1
  (existing convention).
- Counters map onto the existing summary vocabulary under target name
  `cli:<name>`: fresh/heal → `created`, upgrade/takeover-accepted →
  `updated`, skip/decline → `skipped`, uninstall → `pruned`. The summary
  renders these as ordinary per-target blocks.
- Any install/smoke failure ultimately returns exit 1 from `_run` (after the
  summary renders), never a silent success.

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

Integrity compatibility follows the `dir_digest` precedent exactly:
`canonical_bytes` includes a `"clis"` key **only when the tuple is non-empty**,
so every receipt written before this field existed hashes byte-identically and
its persisted integrity still validates. No `SCHEMA_VERSION` bump.
`receipt_store` read/write round-trips the field, defaulting absent → empty.

Prune half (runs under `--prune` / `--prune-only`, after the file prune): a
CLI named in the prior receipt's `clis` but absent from `CLI_PACKAGES` is
retired → consent-gated `uv tool uninstall` (per-item prompt, `--yes`
auto-accepts, `--dry-run` previews). Uninstall of a tool uv no longer knows
(user removed it manually) is treated as success — the desired state is
"absent". The rewritten receipt carries only the registry's surviving,
successfully-deployed CLIs.

A CORRUPT prior receipt disables the CLI prune half exactly as it disables
file pruning (fail closed); the deploy half still runs, treating every CLI by
the no-prior-entry rows of the decision table.

## 8. Failure posture

- No silent fallbacks: every subprocess failure surfaces via `io.err` with
  the command output, and the run exits non-zero.
- The stage never raises on a deploy failure mid-loop; it records the failure
  and continues to the next CLI (one broken package must not block the
  other), then the run reports exit 1.
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

1. Skip: receipt digest equal + shim present → no subprocess calls, skipped
   counter.
2. Fresh install: no receipt entry, no shim → install runs, no consent
   prompt, created counter, receipt entry written.
3. Heal: receipt entry present, shim missing → reinstall without prompt.
4. Upgrade: digest differs → consent prompt; accept → install + updated
   counter + new digest; decline → skipped, prior entry retained.
5. Takeover: no receipt entry, shim present → consent prompt; decline →
   skipped, no entry.
6. Dry-run: each branch reports would-X, zero subprocess calls, receipt
   untouched.
7. Smoke failure: install ok, smoke fails → err surfaced, no receipt entry,
   exit 1.
8. Install failure: `tool_install` not ok → err surfaced, other CLI still
   processed, exit 1.
9. PATH warning: post-install `which` misses → warn emitted, entry still
   written (deploy succeeded; PATH is user config).
10. Prune: prior `clis` entry not in registry → consent-gated uninstall,
    pruned counter, entry dropped; `--dry-run` previews; uninstall-of-absent
    treated as success.
11. Receipt round-trip: `clis` field read/write; legacy receipt (no field)
    loads as empty and its integrity still validates; canonical_bytes omits
    empty `clis`.
12. No-TTY without `--yes` at a CLI consent point → `ConsentRequiredError`
    path, exit 1.
13. `--project` run performs no CLI deploys.

Gate: `make ci-installer` (ruff, format, mypy --strict, pytest --cov 90%
branch, pip-audit, entry-verify) green before push; delivery routes HEAVY at
the completion gate (`packages/**` floors it).

## 11. Continuations

- none — this spec is the deliverable's design; implementation proceeds under
  the same bead (agents-config-wgclw.9.9), and the discipline-layer migration
  it unblocks is already tracked (agents-config-wgclw.9.4).
