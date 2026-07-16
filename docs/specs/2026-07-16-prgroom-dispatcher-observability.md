# prgroom Dispatcher Observability: Usage Wiring, Winner Provenance, Fallback Signal — Design

**Date:** 2026-07-16
**Status:** Approved (design)
**Beads:** agents-config-abn9.8.26 (dispatcher fallback observability — P1 bug).
**Related:** `2026-07-04-cost-telemetry-and-token-capture.md` — its §6 carves this spec's work out of that spec's scope; its §4 `spend_hook` shares the two dispatcher build sites and needs the winning link's `AgentSpec` + rung index, which §3 here exposes on one envelope; its §3.3 reserves the `tokens_total` / `reported_cost_usd` `UsageRecord` fields (this spec adds no `UsageRecord` fields — no collision). Bead agents-config-25rmt owns the token parser that will fill the `None` token fields in the rows this spec starts writing.

## 1. Problem

The fallback ladder has the right data model and zero operator-facing output. Three
verified-live gaps on current `main`, plus a channel-policy vacuum:

1. **`usage_hook` is never wired.** Both production dispatcher construction sites —
   `_build_cluster_dispatcher` (`cli.py:147-151`) and `_build_fix_dispatcher`
   (`cli.py:165-169`) — construct with only `runner=` and `chain=`, so
   `_Dispatcher.__init__`'s `usage_hook` defaults to `None` (`dispatcher.py:283`) and the
   guard at `dispatcher.py:344-345` drops every per-attempt record on the floor.
   `append_usage` (`usage.py:62`) has zero production callers. The dispatcher docstring at
   `dispatcher.py:296-297` ("the lifecycle wires it to usage.append_usage") is false.

2. **`decided_by` misattributes provenance.** `_decided_by` (`cli.py:122-133`) reads
   `chain.providers[0]` once, statically, before any dispatch. The string threads through
   the `cluster`/`fix` verbs (`cli.py:301,356`), the `run` aggregate (`cli.py:676-691`),
   and `Verbs.system` (`run.py:149-183`) into every `Disposition` stamped in
   `agent/fix.py` (`fix.py:153,235,275,341`). If ollama times out and the claude haiku
   link produces the result, every disposition still says `decided_by: "ollama gemma4"`.
   `_run_chain` (`dispatcher.py:304-338`) never exposes which `AgentSpec` won — the
   information does not exist at any call site that could stamp it correctly.

3. **Partial fallback is entirely silent.** `_run_chain`'s local
   `failures: list[_LinkFailure]` (`dispatcher.py:312`) is read exactly once, by
   `_render_failures` on the all-links-failed path (`dispatcher.py:338`). The moment a
   later link succeeds (`dispatcher.py:337`), every prior link's failure is discarded
   with the stack frame. A run where the primary fails on every dispatch for a week —
   paying the fallback's cost each time — produces no signal anywhere.

4. **No channel policy.** Four output channels exist with no written rule for which
   carries what: `usage.jsonl` (schema defined, zero writers), `EscalationSink`
   (`escalation.py` — wired only for both-fail and audit-violation events via
   `StderrSink`, the sole sink `_build_sink()` constructs, `cli.py:172-178`), stdlib
   logging (exactly two `getLogger` sites — `subprocess_runner.py:71`,
   `prsession/legacy_export.py:43` — with zero handler/level configuration anywhere, so their
   WARNINGs reach stderr only via CPython's handler-of-last-resort happenstance), and the
   lifecycle's injected `warn` callbacks (`lifecycle/warn.py`). The stdout/stderr split
   (JSON envelope on stdout via `cli.py:711`, diagnostics on stderr) is emergent, not
   documented. Without a written story, the next observability need invents a fifth
   channel.

## 2. Decision: the package observability story

Every prgroom output belongs to exactly one of four channels, chosen by **who must do
what with it** — not by severity, not by module:

| Channel | Job | Writers | Reader |
|---|---|---|---|
| `usage.jsonl` (`append_usage`) | Durable, machine-readable, **per-attempt** dispatch telemetry: what ran, how long, what outcome | the dispatcher's `usage_hook` (§4) | post-hoc analysis; cost/routing tuning (sibling `spend.jsonl` holds per-**dispatch** cost — cost-telemetry spec §4) |
| `EscalationSink` (`escalation.py`) | **Human-judgment events**: something a human or external watcher must eventually act on — blocker dispositions, chain exhaustion, audit violations, lifecycle gates | `agent/fix.py`, `lifecycle/escalation.py` | operator / monitor-pr / future `bd` adapter |
| stdlib logging → stderr | **Operational diagnostics**: noteworthy but requiring no tracked action — config-key warnings, best-effort bridge failures, fallback events (§5) | module-level `getLogger(__name__)`; root config in `main()` only (§5) | whoever watches the process (human or driving agent) |
| `warn` callbacks (`lifecycle/warn.py`) | Grandfathered injected-callable variant of the logging channel, used by lifecycle verbs as a test seam | existing lifecycle code only | same as logging |

Two standing rules, to be recorded durably (§6): **stdout is reserved for contract
output** (the `status --json` envelope and the human `status` rendering); every
diagnostic goes to stderr. **No new channels**: a new observability need slots into one
of the four jobs above; new code preferring a diagnostic stream uses stdlib logging, not
a new `warn` plumbing.

Fallback telemetry under this story is a **defined combination**: `usage.jsonl` carries
the durable per-attempt record (§4), and stdlib logging at WARNING carries the explicit
partial-fallback signal (§5). `decided_by` — now truthful (§3) — is the persisted
per-item provenance.

Rejected alternatives:

- **`EscalationSink` at `Severity.WARN` for partial fallback** — the Sink is the
  human-judgment channel; a dispatch that *succeeded* after falling back requires no
  human action, and routing routine degradation there trains operators to ignore
  escalations (directly against the prime directive of fewer human interventions).
  Mechanically it also fails to cover the cluster path: the `cluster` verb builds no Sink
  at all (`cli.py:293-316`), and `run_cluster` swallows even total exhaustion into the
  degenerate fallback (`agent/cluster.py:83-87`), so Sink-based fallback telemetry would
  need new Sink threading through the cluster path for an event that is not
  human-judgment in the first place.
- **`usage.jsonl` alone** — rejected by the bead's own acceptance criterion: a human
  would have to diff `outcome` values across rows to notice a fallback; that is a query,
  not a signal.
- **A persisted per-item fallback field surfaced in `status --json`** — requires a state
  schema change plus a §4.6 envelope addition for a post-hoc query consumer that does not
  exist; the cluster contract has no `Disposition` at all, so a `Disposition`-level field
  could never cover cluster fallback anyway. Revisit if a consumer materializes (§10).
- **A full structured-logging framework** (structlog, JSON logs) — machinery without a
  consumer; the JSONL files (`usage.jsonl`, the escalation `FileSink`) already carry the
  machine-readable load.

## 3. Winner provenance: the `Dispatched[T]` envelope

`_run_chain` stops discarding the one fact only it knows — which link won. It returns a
generic envelope instead of the bare parsed output.

In `agent/dispatcher.py` (using the module's existing `TypeVar` `T`; the package floor is
Python 3.11, so `Generic[T]`, not PEP 695 syntax):

```python
@dataclass(frozen=True, slots=True)
class LinkFailure:                       # renamed from _LinkFailure; public because
    spec: AgentSpec                      # Dispatched.failures carries it outward.
    reason: str                          # __post_init__ normalization unchanged
    kind: str                            # "timeout" | "unavailable" | "error" | "malformed"


@dataclass(frozen=True, slots=True)
class Dispatched(Generic[T]):
    """One resolved dispatch: the parsed output plus which chain link produced it."""

    output: T
    winner: AgentSpec
    failures: tuple[LinkFailure, ...] = ()

    @property
    def rung(self) -> int:               # index of the winning link
        return len(self.failures)

    @property
    def fell_back(self) -> bool:
        return bool(self.failures)

    @property
    def decided_by(self) -> str:         # the one derivation, shared by all consumers
        return f"{self.winner.cli} {self.winner.model}"
```

`rung == len(failures)` is an invariant of the ladder, not a stored field: every link
before the winner either appended a `LinkFailure` and continued, or returned. Deriving it
keeps one source of truth, and it is exactly the `rung` the cost-telemetry spec's §4
spend bridge needs — that bead consumes this envelope instead of re-plumbing
`_run_chain`. `decided_by` keeps today's `"<cli> <model>"` format (`cli.py:133`) so
persisted state values stay format-compatible.

**Signature changes, exhaustively:**

- `_Dispatcher._run_chain(payload, parse) -> Dispatched[T]` — the success return at
  `dispatcher.py:337` becomes `Dispatched(output=parsed, winner=spec,
  failures=tuple(failures))`. The exhaustion path still raises
  `AllProvidersFailedError` unchanged (tier `RUNTIME_TRANSIENT`, code
  `RUNTIME_AGENT_UNAVAILABLE`) — the expected both-fail failure stays modeled as the
  typed, tiered exception callers already handle (`fix.py:99`,
  `agent/cluster.py:85-86`); `Dispatched` is the success shape only. No Result union: the
  §3.6 restart-safety exit-code mapping hangs off that exception's tier.
- `ClusterDispatcher.cluster(request) -> Dispatched[ClusterOutput]`;
  `FixDispatcher.fix(request) -> Dispatched[FixOutput]` (`dispatcher.py:425-442`).
- The Protocols in `agent/contracts.py` (`ClusterContract.cluster`, `FixContract.fix`)
  adopt the same return types. `contracts.py` imports `Dispatched` under
  `TYPE_CHECKING` only — `dispatcher.py` imports `contracts.py` at runtime, so the
  reverse edge must stay annotation-only (`from __future__ import annotations` is already
  in force); no runtime cycle. `CONTRACT_VERSION` stays 1: it versions the agent-facing
  JSON payloads (`ClusterInput.to_dict` et al.), which are byte-identical — the envelope
  changes Python signatures only.
- `run_fix` (`agent/fix.py:81`): **drops the `decided_by` parameter.** It reads
  `dispatched = dispatcher.fix(req)`, uses `dispatched.output` where `out` was used, and
  stamps `dispatched.decided_by` on every disposition built from that dispatch — clean
  rows, audit-flipped rows, and synthesized missing/duplicate rows alike (the winning
  agent produced the output being audited; prgroom's audit rejecting it does not change
  who decided). The both-fail path stamps a new module constant
  `_BOTH_FAIL_DECIDED_BY = "prgroom"` (`agent/fix.py`): no agent produced output, the
  ladder itself decided FAILED — consistent with `_decided_by`'s existing empty-chain
  degradation to `"prgroom"` (`cli.py:130-131`).
- `FixRunResult` (`agent/fix.py:58-78`) gains `decided_by: str` — the stamp used for
  this cluster's dispositions (winner string, or `"prgroom"` on both-fail) — because the
  8.15 side needs it after `run_fix` returns: the realpath containment flip
  (`lifecycle/fix.py:154`) and `resolve_routed_memory` (`lifecycle/fix.py:139-143`) both
  stamp provenance post-return. `RoutedMemory.decided_by` consequently records the actual
  winner too — an incidental correction with the same root cause, forced by the plumbing.
- `run_cluster` (`agent/cluster.py:90-104`): drops the unused `now`/`decided_by`
  parameters (their only rationale was the now-dead "uniform 8.7 signature";
  `_try_dispatch` reads `dispatched.output` for `audit_cluster` and the `clusters`
  access). Clustering still decides no disposition; the degenerate path never dispatched,
  so it has no provenance to record.
- Lifecycle: `cluster_pr` (`lifecycle/cluster.py:48-66`) and `fix_pr`
  (`lifecycle/fix.py:58-71`) drop their `decided_by` parameters; `_fix_one_cluster`
  reads `result.decided_by`. `Verbs.system` and `run_lifecycle` (`run.py:149-156,
  243-256`) drop `cluster_decided_by`/`fix_decided_by`.
- `cli.py`: **`_decided_by` is deleted** (`cli.py:122-133`).
  `_build_cluster_dispatcher() -> ClusterContract` and
  `_build_fix_dispatcher() -> FixContract` return bare dispatchers (no tuple); the
  `cluster`/`fix`/`run` verbs update accordingly. The `resolve-escalated` human path
  (`decided_by = "human:" + _git_user()`, `cli.py:541`) is untouched — separate,
  correct-by-construction provenance.

## 4. `usage.jsonl` wiring

Both builders pass the hook:

```python
dispatcher = FixDispatcher(
    runner=SubprocessAgentRunner(), chain=chain, usage_hook=append_usage
)
```

`append_usage`'s parameter type (`UsageRecord | None`) is a strict superset of the hook's
`Callable[[UsageRecord], None]` — directly assignable, no adapter. Constructor arguments
stay keyword-only, leaving the seam open for the sibling `spend_hook=` parameter to land
independently (cost-telemetry spec §4 interface contract).

**Failure containment:** `_emit_usage` (`dispatcher.py:340-358`) wraps the hook call —
`except Exception: _logger.warning("usage hook failed (%s attempt record dropped): %s",
outcome, exc)` — and continues. A hook failure (unwritable XDG dir, full disk) is an
expected environmental failure, not a contract breach: the modeled handling is a logged
drop, never an aborted dispatch and never a silent one (the WARNING is the signal). This
mirrors the cost spec's "never fail a dispatch over telemetry" rule.

**Concurrent writers:** prgroom's concurrency model is per-PR locking (`with_lock`,
`lifecycle/locking.py`; a concurrent run on the same PR exits 75 — `cli.py:666`), so two
`prgroom run` processes on *different* PRs are legal and, under M3/M4 multi-PR grooming,
the intended steady state — and both append to the one global
`$XDG_STATE_HOME/prgroom/usage.jsonl` (`resolve_state_dir()`, `prsession/file.py:34-41`,
is not per-PR). `append_usage` therefore takes `fcntl.flock(fh.fileno(), LOCK_EX)` on
the append handle before writing (the `with` block's close releases it; kernel-released
on process death, same no-stale-lock property as the FileStore). Locking the data file's
own descriptor — not a sidecar as `FileStore` uses — is correct here precisely because
the file is append-only: the FileStore sidecar exists because `os.replace` swaps the
inode out from under a data-file lock, and `usage.jsonl` is never replaced. Bare
`open("a")` O_APPEND was rejected as the sole guarantee: single-`write(2)` atomicity
depends on the line fitting the io buffer (an implementation detail nothing pins) and
does not hold on network filesystems. The lock's presence is review-verified — no test
asserts flock mechanics (that would test the kernel); the functional append behaviors
already pinned in `test_agent_usage.py` (never truncates, creates parent dirs, `None`
no-op) are unchanged.

**No `UsageRecord` schema changes.** `tokens_total`/`reported_cost_usd` belong to
agents-config-25rmt (cost spec §3.3); a `rung` column is derivable from row order within
one `(pr, contract)` dispatch and stays off the schema until a reader needs it. The one
row per attempt — outcome-tagged `success` / `timeout` / `unavailable` / `error` /
`malformed` / `cancelled`, token fields `None` — starts flowing to
`$XDG_STATE_HOME/prgroom/usage.jsonl` with this change alone.

## 5. Partial-fallback signal + logging configuration

`agent/dispatcher.py` gains the package's third module logger
(`_logger = logging.getLogger(__name__)`) and emits, per the §2 story:

- **Per failed link, at failure time** (streaming — a fix link's budget is up to 1800 s,
  `dispatcher.py:66`; an operator watching `run` learns of the primary's timeout when it
  happens, not half an hour later when the fallback finishes):
  `_logger.warning("%s link %s:%s failed (%s): %s", contract, spec.cli, spec.model,
  failure.kind, failure.reason)`.
- **On success-after-fallback, one summary line** — the greppable acceptance-criterion
  signal: `_logger.warning("%s dispatch fell back to %s:%s (rung %d); failed: %s",
  contract, winner.cli, winner.model, rung, _render_links(failures))`, where
  `_render_links` is the link-rendering half extracted from `_render_failures`
  (`dispatcher.py:445-448`) so the exhaustion detail and the fallback summary share one
  rendering. The line deliberately says "fell back to", **not** "decided by": it reports
  a dispatcher-layer fact (this dispatch resolved at rung N), and on the cluster path
  the caller can still discard the winning output — `run_cluster`'s audit loop
  (`agent/cluster.py:77-104`) rejects and re-dispatches, so one logical clustering can
  legitimately log up to two fallback summaries and then end degenerate with no agent
  deciding anything. Each summary stays true of its own dispatch; the missing
  *outcome*-level signal (this clustering ended degenerate) is the Continuations bug,
  whose notice names the attempt count so the trail reads coherently.
- **Clean dispatch (rung 0): zero log lines** — the no-noise guard.
- **Exhaustion: no additional dispatcher line** — every link already logged its own
  failure, the fix path escalates `AllProvidersFailedError` through the Sink
  (`fix.py:148-162`), and the cluster path degenerates by design; a third rendering is
  noise, not signal.
- **Cancelled: no warning** — a deliberate abort is not degradation; the `cancelled`
  usage row (`dispatcher.py:320`) still emits.

**Root logging configuration** (the answer to "does scope widen to a
basicConfig retrofit": yes, minimally — one call, one knob, no per-module handlers):

- `main()` (`cli.py:737`) calls, before `app()`:
  `logging.basicConfig(stream=sys.stderr, level=level, format="prgroom %(levelname)s
  %(name)s: %(message)s")`, with `level, notice = _resolve_log_level(
  os.environ.get("PRGROOM_LOG_LEVEL"))` and the notice (if any) written to stderr.
- `_resolve_log_level(raw: str | None) -> tuple[int, str | None]` — a pure `cli.py`
  helper: `None`/empty → `(logging.WARNING, None)`; a case-insensitive standard level
  name → `(that level, None)`; anything else → `(logging.WARNING, "prgroom: unknown
  PRGROOM_LOG_LEVEL <raw>; using WARNING")`. **Fail-lateral by design:** a typo'd env
  var must never take down an autonomous overnight run; it degrades to the default,
  loudly.
- Library modules never call `basicConfig`/`addHandler` — module-level
  `getLogger(__name__)` only. `basicConfig` no-ops when the root already has handlers
  (embedding-safe). Typer `CliRunner` tests drive `app()` rather than `main()`, with one
  known exception: `test_cli_errors.py:76` drives `main()` to pin the exit-code
  contract, so that test process does gain the root stderr handler — benign (pytest
  captures stderr; a second `basicConfig` no-ops) but stated here so the implementer is
  not surprised mid-PR. Log assertions use `caplog` throughout.
- The two existing sites (`subprocess_runner.py:71,291`;
  `prsession/legacy_export.py:43,245`) need no changes: their WARNINGs now flow through
  a deliberately configured handler instead of CPython's handler-of-last-resort
  happenstance.

## 6. Docstring and documentation corrections

- `dispatcher.py:296-297` — replace the false lifecycle claim: "one UsageRecord per
  ATTEMPT (failed links included) is pushed through this hook — the production
  dispatcher builders in the CLI wire it to `usage.append_usage`; `None` (tests,
  embedders) disables emission." True only once §4 lands; corrected in the same PR.
- `usage.py` module docstring — the "when the agent CLI emits a usage line" framing
  predates the hook; restate: one row per chain-link attempt via the dispatcher's
  `usage_hook`, appended under an exclusive `flock` because concurrent per-PR processes
  share the file (§4), token fields `None` pending agents-config-25rmt.
- `packages/prgroom/AGENTS.md` — add an "Observability channels" section carrying the §2
  table, the stdout-reservation rule, and the no-new-channels rule. The spec is a dated
  point-in-time artifact; the package AGENTS.md is the living home contributors actually
  read, so the story survives there.
- `agent/cluster.py` module docstring — drop the "uniform 8.7 signature" paragraph
  (`now`/`decided_by` no longer exist to explain).

## 7. Out of scope

- The `spend_hook` + `spend.jsonl` bridge — cost-telemetry spec §4 (bead
  agents-config-abn9.40.1); this spec only keeps the constructor seam open and exposes
  the winner/rung data it needs.
- `UsageRecord` token/cost fields — bead agents-config-25rmt (cost spec §3.3).
- `status --json` provenance or fallback fields — no consumer today; revisit per §10.
- `--escalation-file` / `bd` sink adapter selection — already charted as a later bead
  (`cli.py:172-178` docstring).
- Migrating the lifecycle `warn` callbacks to stdlib logging — grandfathered channel
  (§2); churn with no signal gain.
- A degenerate-clustering notice at the `run_cluster` layer — charted in Continuations.
- Per-repo `.prgroom.toml` chain resolution (`repo_config=None`, `cli.py:142-146`) — a
  separate, already-documented gap; today's fix therefore always attributes against the
  shipped default chains, which is fine: attribution is per-dispatch, not per-config.

## 8. Sequencing

One bead, one PR. Order-independent with agents-config-25rmt and agents-config-abn9.40.1
(cost spec §8): the only interlocks are the keyword-only constructor seam and the
reserved `UsageRecord` field names, both honored here. Within the PR the natural order is
§3 (the envelope — the type checker drives the ripple through contracts, fix, cluster,
lifecycle, CLI), then §4 (wiring), then §5 (logging), landing as one unit.

## 9. Test plan and acceptance criteria

Behaviors, one red-green cycle each (no bulk test-first). Fakes throughout — a fake
`AgentRunner` scripted per link and stub contract implementations; no mocks-on-calls
assertions; log assertions via `caplog`; file assertions via `tmp_path` +
`XDG_STATE_HOME`.

**`tests/unit/test_agent_dispatcher.py`:**

1. Fallback success carries provenance: chain of a timing-out link then a succeeding
   link → the returned `Dispatched` has `output` parsed from the second link's stdout,
   `winner` equal to the second `AgentSpec`, `rung == 1`, and `failures` holding the
   timeout `LinkFailure`. This is the root regression guard for the `decided_by`
   misattribution — the data now provably exists at the boundary.
2. Clean-primary dispatch: first link succeeds → `rung == 0`, `fell_back` is false,
   `failures` empty, and `caplog` holds **zero** WARNING records (the no-noise guard).
3. Per-link streaming warning + summary: an erroring link then a succeeding link →
   `caplog` holds one WARNING naming the contract, `cli:model`, kind, and reason, plus
   exactly one "dispatch fell back to" summary WARNING naming the winner and rung.
4. Exhaustion logs no summary: every link fails → `AllProvidersFailedError` raised with
   tier/code unchanged, per-link WARNINGs present, and no "fell back" line (the
   both-fail signal remains the Sink escalation, not a log line).
5. Usage-hook containment: a hook that raises `OSError` on every call → the dispatch
   still returns the winner's `Dispatched`, and one "usage hook failed" WARNING per
   dropped attempt appears. Telemetry never fails a dispatch.
6. The three existing per-attempt hook behaviors
   (`test_agent_dispatcher.py:584-641` — one record per attempt across the ladder;
   outcome tagging for unavailable/error/malformed; the cancelled record before an
   abort) survive, mechanically updated for the envelope return.

**`tests/unit/test_agent_fix.py`:**

7. The winner stamps every disposition: a stub `FixContract` returning
   `Dispatched(output=<valid FixOutput>, winner=AgentSpec(cli="codex",
   model="gpt-5.6-terra"), failures=(<one timeout>,))` → every disposition's
   `decided_by == "codex gpt-5.6-terra"` and `FixRunResult.decided_by` matches. **The
   bead-item-2 regression case**: under the old code this read the chain head.
8. Audit-flipped and synthesized rows stamp the winner too: an output omitting a
   requested id and carrying a per-item audit violation → the synthesized and flipped
   FAILED dispositions carry the winner string, not a static configured-primary.
9. Both-fail stamps `"prgroom"`: a dispatcher raising `AllProvidersFailedError` → every
   disposition's `decided_by == "prgroom"`, `FixRunResult.decided_by == "prgroom"`, and
   the per-item WARN escalations are unchanged.

**`tests/unit/test_agent_cluster.py`:**

10. `run_cluster` consumes the envelope: a stub returning
    `Dispatched(ClusterOutput(...), ...)` → assignments unchanged; a dispatcher raising
    both-fail twice still degenerates (existing behavior over the new signature).

**`tests/unit/test_cli_dispatcher_helpers.py`:**

11. Production wiring appends usage rows: monkeypatch `cli.SubprocessAgentRunner` to a
    fake runner scripted fail-then-succeed and point `XDG_STATE_HOME` at `tmp_path`;
    dispatch through the dispatcher `_build_fix_dispatcher()` returns →
    `usage.jsonl` holds exactly two rows with outcomes `["error", "success"]` and
    `contract == "fix"`. **The bead-item-1 regression guard** — it exercises the exact
    construction line that omitted the hook (today hidden behind
    `# pragma: no cover - production wiring`).
12. `_resolve_log_level`: `None` → `(WARNING, None)`; `"info"` and `"DEBUG"`
    (case-insensitive) → the named level with no notice; `"verbose"` →
    `(WARNING, notice naming the bad value)`. Not a tautology: it pins the fail-lateral
    choice — garbage degrades loudly instead of crashing an autonomous run.

**`tests/unit/test_lifecycle_fix.py` / `test_lifecycle_fix_memory_routing.py`:**

13. The lifecycle uses the dispatch's provenance after `run_fix` returns: with a stub
    dispatch whose winner is the fallback link, the realpath containment-flip
    dispositions (`lifecycle/fix.py:154`) and `RoutedMemory.decided_by` both stamp the
    winner string.

**Existing-test ripple** (mechanical, no new behavior — §3's signature changes break
these files; every row lands in the same PR or `make ci-prgroom` never goes green):

| File | What breaks | Mechanical update |
|---|---|---|
| `test_cli_dispatcher_helpers.py` | imports the deleted `_decided_by` (line 16); two tests pin it | delete both tests with the helper — the empty-chain → `"prgroom"` behavior re-pins at the new seam via behavior 9 (an empty chain raises `AllProvidersFailedError` before any link) |
| `test_cli_fix.py:121`, `test_cli_cluster.py:121`, `test_cli_run.py:40-41,120-121` | monkeypatched `_build_*_dispatcher` lambdas return `(stub, "…")` 2-tuples | return the bare stub; the stubs' `cluster`/`fix` methods wrap returns in `Dispatched(output=…, winner=…)` |
| `test_agent_fix.py` | ~20 `run_fix(..., decided_by="prgroom")` sites; the signature pin at line 522 lists `decided_by`; `FixDispatcherStub` returns bare `FixOutput` | drop the kwarg at every site; the pin becomes `{"req", "dispatcher", "git", "now"}`; stub returns wrap in `Dispatched` |
| `test_agent_fix_contextual_memory.py:62,72` | `run_fix(..., decided_by="agent")` | same kwarg drop + `Dispatched`-wrapping stub |
| `test_agent_cluster.py` | seven `run_cluster(req, disp, now=_NOW, decided_by=…)` sites | drop both kwargs; stubs return `Dispatched` |
| `test_lifecycle_cluster.py:135` | `cluster_pr(..., decided_by=…)` | drop the kwarg; the stub contract returns `Dispatched` |
| `test_lifecycle_fix.py`, `test_lifecycle_fix_memory_routing.py` | `fix_pr(..., decided_by=…)` sites; bespoke `FixContract` fakes return bare `FixOutput` | drop the kwarg; fakes return `Dispatched` (these two files also host behavior 13's new assertions) |
| `test_lifecycle_run.py:662-664,700-702` | `Verbs.system` / `run_lifecycle` called with `cluster_decided_by` / `fix_decided_by` | drop both kwargs |
| `test_contracts_fit.py` | the fake providers driven through the `ClusterContract`/`FixContract` Protocols return bare outputs | wrap in `Dispatched`; `mypy --strict` pins the fit |

Boundary of the sweep: `Disposition(decided_by=…)` constructions — ubiquitous in
lifecycle tests — are **untouched**; the persisted field survives, only dispatch-path
*parameters* die. Enumerate stragglers before pushing with
`grep -rn "decided_by\|_build_cluster_dispatcher\|_build_fix_dispatcher" tests/`: the
type checker catches direct-call signature misses, but monkeypatched lambdas are opaque
to mypy, so the grep is the authoritative sweep.

**AC (agents-config-abn9.8.26):** behaviors 1–13 covered, committed one red-green cycle
at a time; the existing-test ripple above applied in full; `make ci-prgroom` green, run
from the worktree root (repo coverage floor applies). Restating the bead's acceptance criteria against the design: `usage.jsonl`
receives one row per chain-link attempt including failures in production wiring
(behaviors 6, 11); `Disposition.decided_by` names the agent that actually produced the
winning output, `"prgroom"` on chain exhaustion (behaviors 7–9, 13); a partial fallback
emits explicit stderr WARNINGs — per-link plus a summary — with no `usage.jsonl`
hand-diffing (behavior 3); the observability story is written down (§2 here plus the
`packages/prgroom/AGENTS.md` section, §6); the dispatcher docstring is corrected (§6,
verified in review — no test asserts docstring text).

## 10. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` no consumer parses `Disposition.decided_by` expecting the
  configured-primary string. Grep-verified in-repo: the field is serialized verbatim
  (`state.py:84-125`) and read by nothing — not `build_status`, not the legacy export.
  If an external report keys on it, the winner string is a value change, not a shape
  change.
- `ASSUMPTION:` stderr WARNINGs are a sufficient "explicit discoverable signal" for
  today's operators (a human or monitor-pr watching `run` output). Alternative — a
  persisted per-item fallback flag surfaced through `status --json` — rejected until a
  post-hoc query consumer materializes; it costs a state-schema and §4.6 envelope
  addition and still cannot cover the disposition-less cluster path.
- `ASSUMPTION:` `CONTRACT_VERSION` stays 1 — it versions the agent-facing JSON payload
  shapes, which are byte-identical; the `Dispatched` envelope changes Python signatures
  only.
- `ASSUMPTION:` `"prgroom"` on both-fail is the honest stamp (nothing produced output;
  the ladder decided FAILED), consistent with the existing empty-chain degradation.
  Alternative — keep stamping the configured primary — rejected: it is exactly the
  misattribution this bead exists to fix, applied to a dispatch that never happened.
- `ASSUMPTION:` fail-lateral on `PRGROOM_LOG_LEVEL` (garbage → WARNING + notice) beats
  fail-fast: an autonomous overnight run must not die on a typo'd env var, and the
  degradation is loud.
- `ASSUMPTION:` cross-PR process concurrency is the only multi-writer case for
  `usage.jsonl` (per-PR locking already serializes same-PR runs), and `flock` on the
  append descriptor is a sufficient guarantee: it serializes writers on local
  filesystems and NFSv4. A state dir on a filesystem with no working `flock` (some
  NFSv3 mounts) degrades to bare O_APPEND semantics — accepted for an MVP telemetry
  file; the package already stakes its state locking on `flock`
  (`prsession/file.py`), so this adds no new platform assumption.

## Continuations

- bug: cluster degenerate-fallback is silent at the `run_cluster` layer — AC: when
  `run_cluster` returns `degenerate=True`, one stderr WARNING (channel 3, §2) names the
  PR and the attempt count and states that degenerate per-item clustering was used
  after two failed dispatch attempts; a clean clustering emits nothing. This is the
  outcome-level counter-signal to §5's per-dispatch summaries: without it, a trail of
  one or two "dispatch fell back to" lines can precede a silently-degenerate outcome
  when the audit rejects both dispatches. (Discovered while placing the fallback
  signal: `_try_dispatch` swallows `AllProvidersFailedError` — `agent/cluster.py:83-87`
  — so the Sink never hears cluster exhaustion; this spec's per-link WARNINGs make the
  link failures visible, but the degenerate *outcome* itself still surfaces nowhere.)
