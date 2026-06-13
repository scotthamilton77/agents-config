"""prgroom CLI root — typer app with the MVP verb skeletons.

This is the foundation scaffold (bead 8.1). Every MVP verb is *wired and
discoverable* but carries no business logic yet: each skeleton prints a
``not-yet-implemented`` notice to stderr and exits with
:data:`SKELETON_EXIT_CODE`. The lifecycle that fills these in arrives in later
beads (Phase 1 impl). Argument shapes here are intentionally minimal — they
exist so ``prgroom <verb> --help`` works and so the entry point resolves.

Verb names with underscores in the function name render as hyphenated commands
(typer default); ``resolve_escalated`` is registered explicitly as
``resolve-escalated`` to keep the spec's §1 verb set verbatim.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import IO

import typer

from prgroom.agent.contracts import ClusterContract, FixContract
from prgroom.agent.dispatcher import (
    ClusterDispatcher,
    FixDispatcher,
    ProviderChain,
    load_chain,
)
from prgroom.agent.subprocess_runner import SubprocessAgentRunner
from prgroom.config import PrgroomConfig
from prgroom.deps import Deps
from prgroom.errors import ErrorCode, PreconditionError, PrgroomError, exit_code_for_tier
from prgroom.escalation import Sink, StderrSink
from prgroom.gh import GhClient
from prgroom.gh.client import GhCli
from prgroom.git import GitCli, GitClient
from prgroom.lifecycle import cluster_pr, fix_pr, is_terminal_for_cli, poll_pr
from prgroom.lifecycle.human_review import derive_human_review, fetch_human_review_inputs
from prgroom.lifecycle.locking import with_lock
from prgroom.lifecycle.status import build_status
from prgroom.proc import SubprocessRunner
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.registry import resolve_store
from prgroom.prsession.state import PRGroomingState, ReviewItem, bootstrap_state
from prgroom.prsession.store import StateNotFoundError, Store

# Foundation skeletons are not yet implemented; they exit non-zero so a caller
# never mistakes a skeleton's silence for a successful no-op. EX_UNAVAILABLE
# (sysexits 69) reads as "the requested service/verb is not available yet".
SKELETON_EXIT_CODE = 69

app = typer.Typer(
    name="prgroom",
    help="Deterministic PR-grooming CLI (foundation scaffold; verbs are skeletons).",
    no_args_is_help=True,
    add_completion=False,
)


def _build_store(name: str | None) -> Store:
    """Resolve the configured Store adapter (flag > env > default ``file``).

    A seam: tests monkeypatch this to inject an InMemoryStore. Production resolves
    the real ``file`` adapter via the registry's single-source-of-truth precedence.
    """
    return resolve_store(name, env=os.environ)


def _build_gh() -> GhClient:
    """Build the production gh adapter (real subprocess boundary).

    A seam: tests monkeypatch this to inject a recorded-response ``GhCli``, so the
    one production-wiring line is the boundary itself — exercised by the gh fit
    tests against ``GhCli``, never through this constructor.
    """
    return GhCli(SubprocessRunner())  # pragma: no cover - production boundary wiring


def _build_git() -> GitClient:
    """Build the production git adapter (real subprocess boundary).

    A seam: tests monkeypatch this to inject a fake ``GitClient``. The one
    production-wiring line is exercised by the git fit tests against ``GitCli``.
    """
    return GitCli(SubprocessRunner())  # pragma: no cover - production boundary wiring


def _decided_by(chain: ProviderChain) -> str:
    """Derive ``decided_by`` from a resolved chain's primary provider (``"<cli> <model>"``).

    The primary (first) provider is the one prgroom prefers; its ``cli`` + ``model``
    name the deciding agent on every disposition this run stamps (e.g.
    ``"claude opus[1m]"``). An empty chain (a misconfig the dispatcher would reject
    on dispatch) degrades to ``"prgroom"`` so the field is never blank.
    """
    if not chain.providers:
        return "prgroom"
    head = chain.providers[0]
    return f"{head.cli} {head.model}"


def _build_cluster_dispatcher() -> tuple[ClusterContract, str]:
    """Resolve the cluster provider chain + a dispatcher (flag/env/TOML → default).

    A seam: tests monkeypatch this to inject a stub dispatcher + a fixed
    ``decided_by``. Production resolves the chain via :func:`load_chain` and wires a
    :class:`ClusterDispatcher` over the real :class:`SubprocessAgentRunner`.
    """
    chain = load_chain("cluster", repo_config=None, model_override=None)  # pragma: no cover
    dispatcher = ClusterDispatcher(  # pragma: no cover - production wiring
        runner=SubprocessAgentRunner(), chain=chain
    )
    return dispatcher, _decided_by(chain)  # pragma: no cover - production wiring


def _build_fix_dispatcher() -> tuple[FixContract, str]:
    """Resolve the fix provider chain + a dispatcher (flag/env/TOML → default).

    A seam: tests monkeypatch this to inject a stub dispatcher + a fixed
    ``decided_by``. Production resolves the chain via :func:`load_chain` and wires a
    :class:`FixDispatcher` over the real :class:`SubprocessAgentRunner`.
    """
    chain = load_chain("fix", repo_config=None, model_override=None)  # pragma: no cover
    dispatcher = FixDispatcher(  # pragma: no cover - production wiring
        runner=SubprocessAgentRunner(), chain=chain
    )
    return dispatcher, _decided_by(chain)  # pragma: no cover - production wiring


def _build_sink() -> Sink:
    """Build the default escalation sink (stderr).

    A seam: tests monkeypatch this to record emitted escalations. The ``--bd-bead``
    / ``--escalation-file`` adapter selection is a later bead; MVP defaults to stderr.
    """
    return StderrSink()  # pragma: no cover - trivial production default


@app.callback()
def _root(
    ctx: typer.Context,
    store: str | None = typer.Option(
        None,
        "--store",
        help="State store adapter: file (default) or bd (deferred).",
        envvar=None,  # env precedence is owned by resolve_store, not typer
    ),
) -> None:
    """Resolve the state store eagerly so an invalid --store fails before any verb.

    An invalid ``--store`` renders the canonical 4-line block via
    :func:`handle_cli_error` and exits with the tier code (2, no traceback) right
    here — so the behavior is identical whether the app is driven through
    :func:`main` or directly (e.g. typer's ``CliRunner``). The resolved Store is
    stashed on ``ctx.obj`` for the verbs to consume. Precedence (flag > env >
    default) lives in :func:`resolve_store`, the single source of truth.
    """
    try:
        ctx.obj = _build_store(store)
    except PrgroomError as err:
        raise typer.Exit(code=handle_cli_error(err)) from err


def _skeleton(verb: str) -> None:
    """Emit the shared not-yet-implemented notice and exit non-zero."""
    sys.stderr.write(f"prgroom: verb '{verb}' is a foundation skeleton — not yet implemented\n")
    raise typer.Exit(code=SKELETON_EXIT_CODE)


@app.command()
def poll(
    ctx: typer.Context,
    pr: str = typer.Argument(..., help="PR ref: owner/repo#n or a full PR URL."),
) -> None:
    """Query gh for new review items, reviews, and CI status; update state (read-only).

    A locked verb (not the ``status`` carve-out): it acquires the PR lock via the
    §2 ``with_lock`` wrapper, then runs ``read → poll_pr → write`` under it. A
    malformed ref, lock contention, or a gh failure renders through
    :func:`handle_cli_error` with the tier's exit code — never a raw traceback.

    Accepts ``owner/repo#n`` or a full PR URL. A bare ``<n>`` is NOT yet resolvable
    (it needs a current-repo context seam — git remote → owner/repo — deferred to a
    later bead), so ``PRRef.parse`` is called without a ``default_repo`` here.
    """
    store: Store = ctx.obj
    try:
        ref = PRRef.parse(pr)
        gh = _build_gh()
        deps = Deps.system()
        config = PrgroomConfig.load()

        def _poll() -> None:
            try:
                state = store.read(ref)
            except StateNotFoundError:
                state = bootstrap_state(ref, now=deps.clock.now())
            state = poll_pr(state, ref=ref, gh=gh, deps=deps, config=config)
            store.write(ref, state)

        with_lock(store, ref, _poll)
    except PrgroomError as err:
        raise typer.Exit(code=handle_cli_error(err)) from err


def _read_or_no_state(store: Store, ref: PRRef) -> PRGroomingState:
    """Read the PR's state, raising ``PRECONDITION_NO_STATE`` if it was never polled.

    Direct invocation does NOT self-heal (the ``--no-prework`` column, §3.2): a
    missing state is a terminal user error (exit 2), not an auto-run-``poll`` path.
    The self-heal/prework chaining is the ``run`` aggregate's job (§3.3).
    """
    try:
        return store.read(ref)
    except StateNotFoundError as exc:
        raise PreconditionError(ErrorCode.PRECONDITION_NO_STATE, detail=ref.display()) from exc


def _needs_clustering(items: list[ReviewItem]) -> bool:
    """True iff any item still needs clustering (unclustered AND unprocessed)."""
    return any(item.cluster_id == "" and item.disposition is None for item in items)


def _has_clusters(items: list[ReviewItem]) -> bool:
    """True iff any clustered item is still unprocessed (fix has work to do)."""
    return any(item.cluster_id != "" and item.disposition is None for item in items)


@app.command()
def cluster(
    ctx: typer.Context,
    pr: str = typer.Argument(..., help="PR ref: owner/repo#n or a full PR URL."),
) -> None:
    """Group unprocessed items into fix-bundles for cohesive fix work.

    A locked verb: ``read → cluster_pr → write`` under the §2 ``with_lock`` wrapper.
    Direct-invocation preconditions (the ``--no-prework`` column, §3.2): no state →
    ``PRECONDITION_NO_STATE`` (exit 2); a terminal phase, an already-clustered state,
    or all items already processed → idempotent no-op exit 0; zero items in state →
    ``PRECONDITION_NO_ITEMS`` (no-work exit 0). Cluster decides no disposition and
    changes no phase.
    """
    store: Store = ctx.obj
    try:
        ref = PRRef.parse(pr)
        gh = _build_gh()
        git = _build_git()
        deps = Deps.system()
        config = PrgroomConfig.load()

        def _cluster() -> None:
            state = _read_or_no_state(store, ref)
            if is_terminal_for_cli(state.phase):
                return  # terminal-for-CLI: no autonomous work (no-op exit 0)
            if not state.items:
                raise PreconditionError(ErrorCode.PRECONDITION_NO_ITEMS, detail=ref.display())
            if not _needs_clustering(state.items):
                return  # already clustered / all processed → idempotent no-op exit 0
            dispatcher, decided_by = _build_cluster_dispatcher()
            with tempfile.TemporaryDirectory(prefix="prgroom-cluster-") as scratch:
                state = cluster_pr(
                    state,
                    ref=ref,
                    gh=gh,
                    git=git,
                    deps=deps,
                    config=config,
                    dispatcher=dispatcher,
                    decided_by=decided_by,
                    scratch_dir=Path(scratch),
                )
            store.write(ref, state)

        with_lock(store, ref, _cluster)
    except PrgroomError as err:
        raise typer.Exit(code=handle_cli_error(err)) from err


@app.command()
def fix(
    ctx: typer.Context,
    pr: str = typer.Argument(..., help="PR ref: owner/repo#n or a full PR URL."),
) -> None:
    """Dispatch the fix agent per cluster: decide disposition AND implement (local).

    A locked verb: ``read → fix_pr → write`` under the §2 ``with_lock`` wrapper.
    Direct-invocation preconditions (the ``--no-prework`` column, §3.2), in order:
    no state → ``PRECONDITION_NO_STATE`` (exit 2); a terminal phase or an
    all-dispositioned state (work already done) → idempotent no-op exit 0; items
    remain but none are clustered-unprocessed → ``PRECONDITION_NO_CLUSTERS``
    (no-work exit 0, "run cluster first"). Fix makes no phase change (end-of-cycle
    resolution is the run aggregate's job) and sets no ``last_error``. Commits land
    locally; nothing is pushed here.
    """
    store: Store = ctx.obj
    try:
        ref = PRRef.parse(pr)
        gh = _build_gh()
        git = _build_git()
        deps = Deps.system()
        config = PrgroomConfig.load()

        def _fix() -> None:
            state = _read_or_no_state(store, ref)
            if is_terminal_for_cli(state.phase):
                return  # terminal-for-CLI: no autonomous work (no-op exit 0)
            if not _has_clusters(state.items):
                # No clustered-unprocessed work. An all-dispositioned state is the
                # idempotent "already done" no-op (silent exit 0); only a genuinely
                # un-clustered state is the NO_CLUSTERS precondition ("run cluster").
                if state.items and all(item.disposition is not None for item in state.items):
                    return
                raise PreconditionError(ErrorCode.PRECONDITION_NO_CLUSTERS, detail=ref.display())
            dispatcher, decided_by = _build_fix_dispatcher()
            sink = _build_sink()
            with tempfile.TemporaryDirectory(prefix="prgroom-fix-") as scratch:
                state = fix_pr(
                    state,
                    ref=ref,
                    gh=gh,
                    git=git,
                    deps=deps,
                    config=config,
                    dispatcher=dispatcher,
                    sink=sink,
                    decided_by=decided_by,
                    scratch_dir=Path(scratch),
                )
            store.write(ref, state)

        with_lock(store, ref, _fix)
    except PrgroomError as err:
        raise typer.Exit(code=handle_cli_error(err)) from err


@app.command()
def push(pr: str = typer.Argument(..., help="PR ref.")) -> None:
    """Push any accumulated commits the fix agent produced."""
    _skeleton("push")


@app.command()
def rereview(pr: str = typer.Argument(..., help="PR ref.")) -> None:
    """Re-request review from required bot reviewers."""
    _skeleton("rereview")


@app.command()
def reply(pr: str = typer.Argument(..., help="PR ref.")) -> None:
    """Render and post replies for every item per template matrix."""
    _skeleton("reply")


@app.command()
def resolve(pr: str = typer.Argument(..., help="PR ref.")) -> None:
    """Resolve review threads whose disposition is fixed or already_addressed."""
    _skeleton("resolve")


@app.command(name="resolve-escalated")
def resolve_escalated(
    pr: str = typer.Argument(..., help="PR ref."),
    item_id: str = typer.Argument(..., help="gh id of the escalated item."),
    as_: str = typer.Option(..., "--as", help="Terminal disposition to flip the item to."),
    rationale: str = typer.Option("", "--rationale", help="Human rationale for the flip."),
) -> None:
    """Human-initiated reclassification of an escalated item."""
    _skeleton("resolve-escalated")


@app.command()
def wait(pr: str = typer.Argument(..., help="PR ref.")) -> None:
    """Sleep/poll until SHA changes or quiescence threshold trips."""
    _skeleton("wait")


@app.command()
def status(
    ctx: typer.Context,
    pr: str = typer.Argument(..., help="PR ref: owner/repo#n or a full PR URL."),
    json_out: bool = typer.Option(False, "--json", help="Emit the §4.6 status envelope as JSON."),
    locked: bool = typer.Option(
        False,
        "--locked",
        help="Acquire the PR lock for a strictly-consistent read (exit 75 under contention).",
    ),
) -> None:
    """Print current grooming state + the §4.6 merge-gate envelope (read-only).

    The §3.3 carve-out: the default path is LOCK-FREE — a single ``store.read`` that
    may observe a stale-but-internally-consistent snapshot under a concurrent write,
    never a partial one (writes are file-atomic). ``--locked`` acquires the PR lock
    via :func:`with_lock` for a strictly-consistent read and exits 75 under
    contention rather than blocking. Human-review is a live gh enrichment (labels +
    PR-approval reviews); ``human_review_satisfied`` is derived per-query, never
    persisted, and never gates the lifecycle.
    """
    store: Store = ctx.obj
    try:
        ref = PRRef.parse(pr)

        def _read() -> PRGroomingState:
            try:
                return store.read(ref)
            except StateNotFoundError as exc:
                # No state file yet — the PR was never polled. This is a user error
                # (exit 2), NOT a no-work success (a scheduler must not read exit-0
                # "done" for a PR that was simply never started). `status` is the
                # lock-free read carve-out, so it cannot self-heal by running prework.
                raise PreconditionError(
                    ErrorCode.PRECONDITION_NO_STATE,
                    detail=ref.display(),
                ) from exc

        state = with_lock(store, ref, _read) if locked else _read()
        # Build the gh adapter LAZILY — only after the state read succeeds — so the
        # fast-fail precondition paths (NO_STATE on a never-polled PR; LOCK_HELD under
        # --locked contention, which fails on the pre-read acquire) stay gh-independent.
        gh = _build_gh()
        labels, reviews = fetch_human_review_inputs(gh, ref)
        human_review = derive_human_review(labels=labels, reviews=reviews)
        envelope = build_status(state, human_review)
        _render_status(envelope, json_out=json_out)
    except PrgroomError as err:
        raise typer.Exit(code=handle_cli_error(err)) from err


@app.command()
def run(pr: str = typer.Argument(..., help="PR ref.")) -> None:
    """Aggregate: orchestrate the verbs in sequence until quiescent or capped."""
    _skeleton("run")


@app.command()
def sweep(repo: str = typer.Argument(..., help="owner/repo to sweep.")) -> None:
    """Cross-PR autonomous mode: list open PRs and run each serially."""
    _skeleton("sweep")


def _render_status(envelope: dict[str, object], *, json_out: bool) -> None:
    """Render the §4.6 status envelope as JSON (``--json``) or a human summary.

    ``--json`` emits the stable merge-gate handoff contract verbatim (indented). The
    default human view surfaces the operator-relevant fields — phase, CI, items,
    each merge gate, and the final ``auto_merge_eligible`` verdict — without losing
    the envelope's nested structure.
    """
    if json_out:
        sys.stdout.write(json.dumps(envelope, indent=2) + "\n")
        return
    last_error = envelope["last_error"] or "(clear)"
    sys.stdout.write(
        f"PR #{envelope['pr']}  phase={envelope['phase']}  round={envelope['round']}\n"
        f"  ci={envelope['ci_state']}  last_error={last_error}\n"
        f"  items={envelope['items_summary']}\n"
        f"  merge_gates={envelope['merge_gates']}\n"
        f"  human_review={envelope['human_review']}\n"
        f"  auto_merge_eligible={envelope['auto_merge_eligible']}\n"
    )


def handle_cli_error(err: PrgroomError, *, stderr: IO[str] | None = None) -> int:
    """Render a tier-tagged error and return its process exit code (§1, §3.3, §7.6).

    A :class:`PreconditionError` prints the canonical 4-line ``what/why/how``
    block; any other :class:`PrgroomError` prints a one-line code. The exit code
    is the tier's documented sysexits value.
    """
    out = stderr if stderr is not None else sys.stderr
    if isinstance(err, PreconditionError):
        out.write(err.render() + "\n")
    else:
        out.write(f"error: {err.code.value}\n")
    return exit_code_for_tier(err)


def main() -> None:
    """Console-script entry point (``prgroom``).

    Wraps the typer app so a tier-tagged :class:`PrgroomError` raised by a verb
    is rendered through :func:`handle_cli_error` and turned into the documented
    exit code, rather than surfacing as an uncaught traceback.
    """
    try:
        app()
    except PrgroomError as err:
        raise SystemExit(handle_cli_error(err)) from err
