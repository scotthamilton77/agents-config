"""Reads git and gh once, and proves merges properly.

The expensive part of this module is deliberate. ``git branch --merged`` is
the check most cleanup scripts stop at, and under a squash-merge workflow it
is wrong in both directions: it reports squash-merged branches as unmerged
(so cruft accumulates forever), and it says nothing about a branch whose PR
was closed unmerged. So merge evidence is resolved in tiers -- authoritative
PR state first, then ancestry, then patch-id equivalence, then a synthesised
squash commit -- and each tier that fires is recorded on the branch so a
reader can see *why* a deletion was called safe.

The tiers are ordered by cost. Batch reads (`for-each-ref`, `branch --merged`,
one `gh pr list`) answer most branches; the per-branch probes run only on the
residue nothing cheaper could resolve.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gitclean.model import Branch, MergeEvidence, PullRequest, Survey, Worktree
from gitclean.ports import CommandPort

_SEP = "\x1f"
# The FULL refname leads deliberately. Short names are ambiguous in exactly the
# place it matters: git shortens `refs/remotes/origin/HEAD` to `origin` -- no
# slash, no HEAD suffix -- so a short-name filter reads the remote's symbolic
# HEAD as a local branch literally named `origin` and offers it for deletion.
# `refs/remotes/` as a prefix answers local-vs-remote with no guessing.
_REF_FORMAT = _SEP.join(
    [
        "%(refname)",
        "%(refname:short)",
        "%(objectname)",
        "%(committerdate:iso-strict)",
        "%(upstream:short)",
        "%(HEAD)",
    ]
)
_PR_LIMIT = 500


def _first_line(result_out: str) -> str:
    return result_out.splitlines()[0].strip() if result_out else ""


def resolve_repo(port: CommandPort, cwd: Path | None) -> tuple[str, str] | None:
    """Return (repo_root, git_common_dir), or None when cwd is not a repo."""
    root = port.git(["rev-parse", "--show-toplevel"], cwd=cwd)
    if not root.ok:
        return None
    common = port.git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=cwd)
    if not common.ok:
        # --path-format landed in git 2.31; older git still answers the plain
        # form, relative to the repo root.
        common = port.git(["rev-parse", "--git-common-dir"], cwd=cwd)
        if not common.ok:
            return None
        resolved = Path(_first_line(root.out)) / _first_line(common.out)
        return _first_line(root.out), str(resolved)
    return _first_line(root.out), _first_line(common.out)


def resolve_default_branch(port: CommandPort, cwd: Path | None, override: str | None) -> str:
    """The branch everything else is measured against.

    Explicit override wins; then origin's published HEAD; then a local
    main/master. A wrong answer here silently mis-classifies every branch, so
    the fallback chain stops at conventional names rather than guessing from
    branch order."""
    if override:
        return override
    head = port.git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], cwd=cwd)
    if head.ok and head.out:
        return _first_line(head.out).removeprefix("refs/remotes/origin/")
    for candidate in ("main", "master"):
        probe = port.git(["show-ref", "--verify", "--quiet", f"refs/heads/{candidate}"], cwd=cwd)
        if probe.ok:
            return candidate
    return "main"


def resolve_base_ref(port: CommandPort, cwd: Path | None, default_branch: str) -> str:
    """Prefer the remote-tracking tip: it is what a PR actually merged into,
    and a stale local checkout of the default branch would under-report
    merges."""
    remote = port.git(
        ["show-ref", "--verify", "--quiet", f"refs/remotes/origin/{default_branch}"], cwd=cwd
    )
    return f"origin/{default_branch}" if remote.ok else default_branch


def read_worktrees(port: CommandPort, cwd: Path | None) -> tuple[list[Worktree], list[str]]:
    """Parse `worktree list --porcelain` and stat each tree for dirt.

    Returns the worktrees plus any parse warnings."""
    result = port.git(["worktree", "list", "--porcelain"], cwd=cwd)
    if not result.ok:
        return [], [f"could not list worktrees (exit {result.returncode})"]

    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line:
            if current:
                blocks.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        blocks.append(current)

    worktrees: list[Worktree] = []
    warnings: list[str] = []
    for index, block in enumerate(blocks):
        path = block.get("worktree", "")
        if not path:
            warnings.append(f"worktree block {index} had no path; skipped")
            continue
        branch_ref = block.get("branch")
        branch = branch_ref.removeprefix("refs/heads/") if branch_ref else None
        prunable = "prunable" in block
        if prunable:
            # The directory is gone by definition, so there is nothing to hold
            # uncommitted work and nothing to stat. Probing would fail and
            # report an unknown that is in fact perfectly well known.
            dirt: tuple[int, int, int] | None = (0, 0, 0)
        else:
            dirt = _count_dirt(port, Path(path))
            if dirt is None:
                warnings.append(
                    f"could not read the working-tree status of {path}; "
                    f"treating it as if it holds uncommitted work"
                )
        dirty_count, untracked_count, ignored_count = (
            dirt if dirt is not None else (None, None, None)
        )
        worktrees.append(
            Worktree(
                path=path,
                branch=branch,
                head=block.get("HEAD", ""),
                is_main=index == 0,
                locked="locked" in block,
                prunable=prunable,
                # Ignored files are counted but excluded from `dirty`: caches
                # and virtualenvs are not work at risk, and treating them as
                # such would make every finished worktree need --force.
                dirty=None if dirt is None else (dirt[0] + dirt[1]) > 0,
                dirty_file_count=dirty_count,
                untracked_file_count=untracked_count,
                ignored_file_count=ignored_count,
                last_activity=None,
            )
        )
    return worktrees, warnings


def _count_dirt(port: CommandPort, path: Path) -> tuple[int, int, int] | None:
    """(tracked-modified, untracked, ignored) counts, or None when git would
    not answer -- an unstatable tree is unknown, not clean.

    ``--ignored`` buys visibility, not a verdict. What it finds in practice is
    build detritus, so the caller reports the count rather than acting on it --
    see ``Worktree.ignored_file_count`` for the trade that settles."""
    status = port.git(
        ["status", "--porcelain=v1", "--untracked-files=normal", "--ignored=matching"], cwd=path
    )
    if not status.ok:
        return None
    dirty = 0
    untracked = 0
    ignored = 0
    for line in status.stdout.splitlines():
        if not line.strip():
            continue
        if line.startswith("!!"):
            ignored += 1
        elif line.startswith("??"):
            untracked += 1
        else:
            dirty += 1
    return dirty, untracked, ignored


def read_pull_requests(
    port: CommandPort, cwd: Path | None
) -> tuple[dict[str, PullRequest], str | None]:
    """One gh call for every PR in the repo, indexed by head ref.

    On a repo with several PRs per branch the newest wins -- the reopened or
    superseding PR is the one whose state describes the branch now."""
    if not port.has_gh():
        return {}, "gh not on PATH; merge evidence limited to git (squash merges invisible)"
    result = port.gh(
        [
            "pr",
            "list",
            "--state",
            "all",
            "--limit",
            str(_PR_LIMIT),
            "--json",
            "number,state,headRefName,headRefOid,url,updatedAt",
        ],
        cwd=cwd,
    )
    if not result.ok:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        return {}, f"gh pr list failed ({detail}); merge evidence limited to git"
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        return {}, f"gh pr list returned unparseable JSON ({exc}); merge evidence limited to git"
    if not isinstance(payload, list):
        return {}, "gh pr list returned a non-list payload; merge evidence limited to git"

    index: dict[str, PullRequest] = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        head = str(entry.get("headRefName", ""))
        if not head:
            continue
        pr = PullRequest(
            number=int(entry.get("number", 0)),
            state=str(entry.get("state", "")).upper(),
            url=str(entry.get("url", "")),
            updated_at=str(entry.get("updatedAt", "")),
            head_oid=str(entry.get("headRefOid", "")),
        )
        existing = index.get(head)
        if existing is None or pr.updated_at > existing.updated_at:
            index[head] = pr
    return index, None


def _merged_set(
    port: CommandPort, cwd: Path | None, base_ref: str, *, remote: bool
) -> tuple[set[str], str | None]:
    """Branches the batch ancestry check calls merged, plus a warning when it
    would not run. An empty set only costs the cheap tier -- the per-branch
    probes still answer -- so failure here degrades speed, not safety."""
    args = ["branch", "--merged", base_ref, "--format=%(refname:short)"]
    if remote:
        args.insert(1, "-r")
    result = port.git(args, cwd=cwd)
    if not result.ok:
        scope = "remote" if remote else "local"
        return set(), (
            f"batch ancestry check for {scope} branches failed "
            f"(exit {result.returncode}); falling back to per-branch probes"
        )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}, None


def _count_revs(port: CommandPort, cwd: Path | None, spec: str) -> int | None:
    """The commit count for a range, or None when git did not answer.

    None is load-bearing. Returning 0 for a failed count reads downstream as
    "nothing ahead of base", which resolves to ANCESTOR, which is proof of a
    merge -- so a transient failure would authorise deleting the branch it
    failed on."""
    result = port.git(["rev-list", "--count", spec], cwd=cwd)
    if not result.ok:
        return None
    try:
        return int(result.out)
    except ValueError:
        return None


def _patch_equal(port: CommandPort, cwd: Path | None, base_ref: str, name: str) -> bool:
    """True when every commit on the branch already has a patch-id in base --
    the rebase and cherry-pick cases that plain ancestry misses."""
    result = port.git(["cherry", base_ref, name], cwd=cwd)
    if not result.ok:
        return False
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return False
    return all(line.startswith("-") for line in lines)


def _squash_equal(port: CommandPort, cwd: Path | None, base_ref: str, name: str) -> bool:
    """True when the branch's whole tree, replayed as ONE commit on the merge
    base, has a patch-id already in base.

    This is the squash-merge case, and nothing cheaper detects it: the squashed
    commit on base shares no patch-id with any individual branch commit, and
    the branch tip is not an ancestor of anything. Synthesising the equivalent
    single commit and asking `git cherry` about *that* is the check that lines
    up with what a squash merge actually produced.

    `commit-tree` writes a loose object. It is unreachable and gc collects it;
    nothing in the repo's refs is touched."""
    base = port.git(["merge-base", base_ref, name], cwd=cwd)
    if not base.ok or not base.out:
        return False
    tree = port.git(["rev-parse", f"{name}^{{tree}}"], cwd=cwd)
    if not tree.ok or not tree.out:
        return False
    synthetic = port.git(
        ["commit-tree", _first_line(tree.out), "-p", _first_line(base.out), "-m", "gitclean-probe"],
        cwd=cwd,
    )
    if not synthetic.ok or not synthetic.out:
        return False
    cherry = port.git(["cherry", base_ref, _first_line(synthetic.out)], cwd=cwd)
    if not cherry.ok:
        return False
    lines = [line for line in cherry.stdout.splitlines() if line.strip()]
    return bool(lines) and all(line.startswith("-") for line in lines)


def _pr_covers_tip(port: CommandPort, cwd: Path | None, pr: PullRequest, head: str) -> bool:
    """True when what the PR decided demonstrably accounts for this tip.

    A PR's state describes the commit it had at its head, not every commit the
    branch has acquired since. Without this check a merged PR authorises
    deleting work pushed onto the branch *after* the merge -- which in a
    many-agent workflow is the normal way a second change begins.

    The question is containment, and it is directional. A tip *behind* the
    merged head is covered: a final commit made on the forge is routine and
    does not mean the branch moved on. A tip *ahead of* or divergent from it is
    not covered, and neither is one git cannot place -- the merged commit is
    frequently absent locally once the remote branch is gone, and an
    unanswerable question falls through to the tiers that read content."""
    if not pr.head_oid or not head:
        return False
    if pr.head_oid == head:
        return True
    return port.git(["merge-base", "--is-ancestor", head, pr.head_oid], cwd=cwd).ok


def _resolve_merge(
    port: CommandPort,
    cwd: Path | None,
    base_ref: str,
    name: str,
    *,
    pr: PullRequest | None,
    head: str,
    ancestor_merged: bool,
    unmerged_commits: int | None,
) -> tuple[bool, MergeEvidence]:
    """Tiered merge proof, cheapest conclusive answer first.

    Both PR tiers are gated on containment. Falling through costs only speed:
    the ancestry, patch-id and squash tiers below re-derive the answer from
    what is actually in the repository, which is the stronger evidence anyway."""
    if pr is not None and pr.state == "MERGED" and _pr_covers_tip(port, cwd, pr, head):
        return True, MergeEvidence.PR_MERGED
    if ancestor_merged:
        return True, MergeEvidence.ANCESTOR
    if unmerged_commits is not None and unmerged_commits == 0:
        # Spelled out rather than folded into `unmerged_commits == 0`: this
        # tier turns a count into proof of a merge, so an unanswered count
        # must visibly fall through instead of quietly satisfying it.
        return True, MergeEvidence.ANCESTOR
    if pr is not None and pr.state == "CLOSED" and _pr_covers_tip(port, cwd, pr, head):
        # Not merged -- but a human closed the PR, which is an explicit
        # decision to abandon the branch. classify turns that into SAFE, so it
        # is gated on containment too: "drop this" applies to what was in the
        # PR, not to commits that arrived afterwards.
        return False, MergeEvidence.PR_CLOSED_UNMERGED
    if _patch_equal(port, cwd, base_ref, name):
        return True, MergeEvidence.PATCH_EQUAL
    if _squash_equal(port, cwd, base_ref, name):
        return True, MergeEvidence.SQUASH_EQUAL
    return False, MergeEvidence.NONE


def read_branches(
    port: CommandPort,
    cwd: Path | None,
    *,
    base_ref: str,
    default_branch: str,
    prs: dict[str, PullRequest],
    worktree_by_branch: dict[str, str],
) -> tuple[list[Branch], list[str]]:
    result = port.git(
        ["for-each-ref", f"--format={_REF_FORMAT}", "refs/heads", "refs/remotes"], cwd=cwd
    )
    if not result.ok:
        return [], [
            f"could not list refs (exit {result.returncode}); "
            f"no branch was surveyed, so this report describes worktrees only"
        ]

    local_merged, local_warning = _merged_set(port, cwd, base_ref, remote=False)
    remote_merged, remote_warning = _merged_set(port, cwd, base_ref, remote=True)
    warnings = [w for w in (local_warning, remote_warning) if w]

    branches: list[Branch] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        fields = line.split(_SEP)
        if len(fields) < 6:
            continue
        full, name, head, committed, upstream, head_marker = (f.strip() for f in fields[:6])
        if not name or not full:
            continue

        is_remote = full.startswith("refs/remotes/")
        if is_remote and full.endswith("/HEAD"):
            # The remote's symbolic HEAD is a pointer, not a branch.
            continue
        remote = name.split("/", 1)[0] if is_remote and "/" in name else None
        short = name.split("/", 1)[1] if is_remote and remote else name

        if is_remote and short == default_branch:
            continue

        is_default = not is_remote and name == default_branch
        pr = None if is_default else prs.get(short)
        if is_default:
            # The default branch is surveyed only as the base; it is never a
            # deletion candidate, and probing it against itself is noise.
            unmerged: int | None = 0
            unpushed: int | None = 0
            merged, evidence = True, MergeEvidence.ANCESTOR
        else:
            unmerged = _count_revs(port, cwd, f"{base_ref}..{name}")
            if unmerged is None:
                warnings.append(
                    f"could not count the commits on {name} missing from {base_ref}; "
                    f"it will not be treated as merged"
                )
            unpushed = _count_revs(port, cwd, f"{upstream}..{name}") if upstream else None
            if upstream and unpushed is None:
                warnings.append(
                    f"could not count the commits on {name} missing from {upstream}; "
                    f"it will not be treated as fully pushed"
                )
            merged, evidence = _resolve_merge(
                port,
                cwd,
                base_ref,
                name,
                pr=pr,
                head=head,
                ancestor_merged=name in (remote_merged if is_remote else local_merged),
                unmerged_commits=unmerged,
            )

        branches.append(
            Branch(
                name=name,
                is_remote=is_remote,
                remote=remote,
                head=head,
                last_activity=committed or None,
                upstream=upstream or None,
                is_default=is_default,
                is_current=head_marker == "*",
                checked_out_at=worktree_by_branch.get(name),
                unpushed_commits=unpushed,
                unmerged_commits=unmerged,
                merged=merged,
                merge_evidence=evidence,
                pr=pr,
            )
        )
    return branches, warnings


def parse_timestamp(value: str | None) -> datetime | None:
    """An aware datetime, or None when the value cannot be read.

    The two clocks gitclean reads do NOT agree on format: git's
    `committerdate:iso-strict` carries the committer's local UTC offset
    (`...T09:00:00-05:00`) while gh always emits UTC (`...T12:00:00Z`).
    Comparing those as strings is wrong in the direction that costs work --
    lexically `-05:00` sorts before `Z`, so a commit made AFTER a PR closed
    can read as before it. Every comparison goes through here so both sides
    are real instants."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def idle_since(last_activity: str | None, now: datetime, window: timedelta) -> bool:
    """True when the timestamp is older than the window. An unparseable or
    missing timestamp is NOT idle -- an unknown age must never be evidence for
    deletion."""
    parsed = parse_timestamp(last_activity)
    if parsed is None:
        return False
    return (now - parsed) > window


def survey(
    port: CommandPort,
    *,
    cwd: Path | None = None,
    base_override: str | None = None,
) -> Survey | str:
    """Full read pass. Returns the Survey, or a message when cwd is not a repo."""
    resolved = resolve_repo(port, cwd)
    if resolved is None:
        return "not inside a git repository"
    repo_root, common_dir = resolved

    default_branch = resolve_default_branch(port, cwd, base_override)
    base_ref = base_override or resolve_base_ref(port, cwd, default_branch)

    head = port.git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
    current = _first_line(head.out) if head.ok else None
    if current == "HEAD":
        current = None

    worktrees, warnings = read_worktrees(port, cwd)
    worktree_by_branch = {w.branch: w.path for w in worktrees if w.branch}

    prs, gh_error = read_pull_requests(port, cwd)
    branches, branch_warnings = read_branches(
        port,
        cwd,
        base_ref=base_ref,
        default_branch=default_branch,
        prs=prs,
        worktree_by_branch=worktree_by_branch,
    )
    warnings.extend(branch_warnings)

    # A worktree's age is the age of the branch it holds; that is only known
    # once the branches have been read, hence the second pass.
    activity_by_branch = {b.name: b.last_activity for b in branches}
    worktrees = [
        replace(w, last_activity=activity_by_branch.get(w.branch) if w.branch else None)
        for w in worktrees
    ]

    return Survey(
        repo_root=repo_root,
        git_common_dir=common_dir,
        base_ref=base_ref,
        default_branch=default_branch,
        current_branch=current,
        gh_available=port.has_gh(),
        gh_error=gh_error,
        worktrees=tuple(worktrees),
        branches=tuple(branches),
        warnings=tuple(warnings),
    )
