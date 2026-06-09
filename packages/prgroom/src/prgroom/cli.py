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

import sys
from typing import IO

import typer

from prgroom.errors import PreconditionError, PrgroomError, exit_code_for_tier

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


def _skeleton(verb: str) -> None:
    """Emit the shared not-yet-implemented notice and exit non-zero."""
    sys.stderr.write(f"prgroom: verb '{verb}' is a foundation skeleton — not yet implemented\n")
    raise typer.Exit(code=SKELETON_EXIT_CODE)


@app.command()
def poll(pr: str = typer.Argument(..., help="PR number, owner/repo#n, or URL.")) -> None:
    """Query gh for new review items, reviews, and CI status; update state."""
    _skeleton("poll")


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
