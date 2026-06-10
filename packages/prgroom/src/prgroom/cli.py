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

import os
import sys
from typing import IO

import typer

from prgroom.config import PrgroomConfig
from prgroom.deps import Deps
from prgroom.errors import PreconditionError, PrgroomError, exit_code_for_tier
from prgroom.gh import GhClient
from prgroom.gh.client import GhCli
from prgroom.lifecycle import poll_pr
from prgroom.lifecycle.locking import with_lock
from prgroom.proc import SubprocessRunner
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.registry import resolve_store
from prgroom.prsession.state import bootstrap_state
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


@app.command()
def cluster(pr: str = typer.Argument(..., help="PR ref.")) -> None:
    """Group unprocessed items into fix-bundles for cohesive fix work."""
    _skeleton("cluster")


@app.command()
def fix(pr: str = typer.Argument(..., help="PR ref.")) -> None:
    """Dispatch the fix agent per cluster: decide disposition AND implement."""
    _skeleton("fix")


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
def status(pr: str = typer.Argument(..., help="PR ref.")) -> None:
    """Print current grooming state for inspection."""
    _skeleton("status")


@app.command()
def run(pr: str = typer.Argument(..., help="PR ref.")) -> None:
    """Aggregate: orchestrate the verbs in sequence until quiescent or capped."""
    _skeleton("run")


@app.command()
def sweep(repo: str = typer.Argument(..., help="owner/repo to sweep.")) -> None:
    """Cross-PR autonomous mode: list open PRs and run each serially."""
    _skeleton("sweep")


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
