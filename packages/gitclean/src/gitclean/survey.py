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
from dataclasses import dataclass, replace
from pathlib import Path

from gitclean.model import (
    Branch,
    MergeEvidence,
    NotOffered,
    PullRequest,
    PullRequestOutcome,
    Survey,
    Worktree,
)
from gitclean.ports import CommandPort, CommandResult

_SEP = "\x1f"
# The FULL refname leads deliberately, and everything the survey *records*
# about a ref is recovered from it. Short names are ambiguous in exactly the
# place it matters: git shortens `refs/remotes/origin/HEAD` to `origin` -- no
# slash, no HEAD suffix -- so a short-name filter reads the remote's symbolic
# HEAD as a local branch literally named `origin` and offers it for deletion.
# `refs/remotes/` as a prefix answers local-vs-remote with no guessing.
#
# The short form is kept all the same, because it answers a different question
# well. It is the shortest spelling that resolves back to this ref and no
# other -- git lengthens it the moment a shorter one would be ambiguous -- so
# it is exactly what a probe should hand to git, and exactly what should never
# be parsed for structure. `\x1f` and the newline are both safe as separators
# here, and that is measured rather than assumed: `git check-ref-format`
# rejects a refname containing either one.
_REF_FORMAT = _SEP.join(
    [
        "%(refname)",
        "%(refname:short)",
        "%(objectname)",
        "%(committerdate:iso-strict)",
        # The upstream's FULL refname leads its short form for the same reason
        # the branch's own does. Shortened, a tracked local branch and a ref a
        # remote publishes are the same kind of string -- and a local branch is
        # allowed to be named `origin/main` -- so nothing in the short name says
        # whether this branch has a copy on a server. `refs/remotes/` does.
        "%(upstream)",
        "%(upstream:short)",
        # The short form, not `%(upstream:track)`. The long one spells the
        # count out -- `[ahead 2]` -- but it is translated, so parsing it
        # breaks under a non-English locale. The short one is punctuation
        # (`=`, `>`, `<`, `<>`) and says nothing about a locale at all.
        "%(upstream:trackshort)",
        "%(HEAD)",
    ]
)
_REF_FIELDS = 8
_PR_LIMIT = 500
_PR_VIEW_FIELDS = "number,state,headRefName,mergedAt"
"""What one pull request has to say for itself before it authorises anything.

``mergedAt`` is asked for alongside ``state`` deliberately: they are one fact
stated twice, and requiring both to agree is what keeps a payload this cannot
read from being taken for a merge."""


def _first_line(result_out: str) -> str:
    return result_out.splitlines()[0].strip() if result_out else ""


def _whole_path(stdout: str) -> str:
    """A one-value `rev-parse` answer, read without cutting it short.

    Everything else this module reads a line of is something a newline cannot
    appear inside -- a refname, an object id, a date -- so there a line is the
    value. A filesystem path is not: it may legally contain a newline,
    `rev-parse` prints it raw, and `rev-parse` has no `-z` to frame it with, so
    the trick the worktree listing uses is not available. What it does have is
    exactly one value per query, terminated by the one newline it added itself
    -- so removing that suffix and nothing else recovers the path git reported,
    whatever the path contains. `.strip()` is wrong here for the same reason
    the first line is: a directory is allowed to end in a space.

    Neither truncation was cosmetic. `repo_root` is compared against the whole
    path the NUL-framed worktree listing hands back, so a cut-short one matches
    nothing and both guards on the worktree this process is running in miss --
    a bare sweep then plans away the directory it is executing in. A cut-short
    `git_common_dir` composes salvage directories outside the repository, which
    is where a bundle written before an irreversible push goes missing."""
    return stdout.removesuffix("\n")


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
        resolved = Path(_whole_path(root.stdout)) / _whole_path(common.stdout)
        return _whole_path(root.stdout), str(resolved)
    return _whole_path(root.stdout), _whole_path(common.stdout)


def _ref_exists(port: CommandPort, cwd: Path | None, ref: str) -> bool | None:
    """Whether the ref resolves, or None when git would not say.

    `show-ref --verify --quiet` exits 1 for a ref that is not there and 128
    when it could not look -- an unreadable ref store, a repository it will not
    open. Reading both as "not there" is how the report comes to state that the
    trunk no longer exists when nothing ever checked."""
    result = port.git(["show-ref", "--verify", "--quiet", ref], cwd=cwd)
    if result.ok:
        return True
    return False if result.returncode == 1 else None


def resolve_default_branch(port: CommandPort, cwd: Path | None) -> tuple[str | None, str | None]:
    """The repository's trunk -- the branch that is never a deletion candidate
    -- and, when nothing answered, the warning that says which tier declined.

    Discovered, never supplied by the caller. A caller who could name what
    merges are measured against could measure against something the real trunk
    is an ancestor of, and the trunk would then classify as merged and
    sweepable -- so the question is asked of the repository, and only of the
    repository.

    origin's published HEAD first, then a local main/master -- **each verified
    to resolve**. Returning the literal `main` when nothing answers used to
    look harmless: every merge probe against a ref that is not there fails, so
    nothing could be proven merged. But protection is assigned by *name*, and
    a repository whose trunk is `trunk` then has no protected branch at all:
    the real trunk is left indistinguishable from cruft, deletable like any
    other branch.

    The published-HEAD tier is the one most likely to be stale -- a dangling
    `origin/HEAD -> origin/master` is the standard leftover after a
    server-side rename -- and taking it on trust was worse than guessing,
    because the guess was then recorded as knowledge and suppressed the
    warning that would have said no branch is protected. An unproven name is
    not a default branch, whichever tier produced it.

    A tier git errored on is reported as unread rather than as absent. The
    verdict is the same either way -- an unverified name is not a trunk -- but
    the sentence is not, and telling someone their `main` does not exist when
    the probe never answered sends them to fix the wrong thing."""
    head = port.git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], cwd=cwd)
    published = _first_line(head.out).removeprefix("refs/remotes/origin/") if head.ok else ""
    candidates = [(published, f"refs/remotes/origin/{published}")] if published else []
    candidates += [(name, f"refs/heads/{name}") for name in ("main", "master")]
    unread: list[str] = []
    for name, ref in candidates:
        state = _ref_exists(port, cwd, ref)
        if state:
            return name, None
        if state is None:
            unread.append(ref)

    if unread:
        detail = f"git would not say whether {' or '.join(unread)} exists, so no tier was ruled out"
    elif published:
        detail = (
            f"origin publishes HEAD as origin/{published}, which no longer exists, and neither "
            f"main nor master exists"
        )
    elif head.ok or head.returncode == 1:
        detail = "origin has published no HEAD, and neither main nor master exists"
    else:
        detail = (
            f"origin's published HEAD could not be read (exit {head.returncode}), and neither "
            f"main nor master exists"
        )
    return None, (
        f"could not determine this repository's default branch: {detail}. Nothing here can be "
        f"told apart from the trunk, so nothing will be swept; publish origin's HEAD "
        f"(`git remote set-head origin -a`) and re-run, or delete what you want gone by "
        f"naming it"
    )


def resolve_base_ref(
    port: CommandPort, cwd: Path | None, default_branch: str
) -> tuple[str, str | None]:
    """What merges are measured against, plus the warning when the preferred
    ref could not be read.

    Prefer the remote-tracking tip: it is what a PR actually merged into, and a
    stale local checkout of the default branch would under-report merges. The
    local fallback is correct when the remote-tracking ref is genuinely absent
    and merely quiet when the probe errored -- so the second case says so, and
    every merge verdict in the report is then known to have been measured
    against a ref that may be behind.

    Handed back as a **full ref path**, which is the only spelling that reaches
    the ref this function just proved exists. `origin/main` does not: git tries
    `refs/heads/` before `refs/remotes/`, so a repository holding a local branch
    of that name -- a legal ref, and what one `git branch origin/main` produces
    -- answers the short spelling with the local decoy, and every merge tier
    then measures against it. `branch --merged`, `rev-list`, `cherry` and
    `merge-base` would each be reading a history nobody asked about, and a bare
    sweep deletes unmerged work on the strength of it.

    A path beginning `refs/` is matched literally by the first of git's
    rev-parse rules, so no other ref can shadow it however the repository is
    arranged, and it needs no `--` terminator either: a ref path cannot begin
    with `-`. The warning below keeps the short form, being prose for a reader
    rather than a rev for git."""
    state = _ref_exists(port, cwd, f"refs/remotes/origin/{default_branch}")
    if state:
        return f"refs/remotes/origin/{default_branch}", None
    if state is None:
        return f"refs/heads/{default_branch}", (
            f"git would not say whether origin/{default_branch} exists, so merges here are "
            f"measured against the local {default_branch}, which may be behind the remote"
        )
    return f"refs/heads/{default_branch}", None


def read_remotes(port: CommandPort, cwd: Path | None) -> tuple[tuple[str, ...] | None, str | None]:
    """The configured remotes, or None when git would not list them.

    This is the one question that says where a remote's name stops inside a
    path under `refs/remotes/`. Remote names may contain slashes -- `git remote
    add team/origin <url>` is accepted -- so the ref path alone does not mark
    the boundary, and the first slash is a guess dressed up as a parse.

    None rather than an empty tuple when the read failed, because "this
    repository has no remotes" and "nobody could say" send a server ref in
    opposite directions: the first makes an unsplittable `refs/remotes/...`
    genuinely odd, the second makes every one of them unsplittable through no
    fault of its own. Neither is deleted either way; only the sentence differs.

    `git remote` is line-framed and that is safe here, unlike everywhere else
    in this module: git refuses to create a remote whose name holds a newline,
    and refuses to read a config key containing one, so no name it prints can
    span two lines."""
    result = port.git(["remote"], cwd=cwd)
    if not result.ok:
        return None, (
            f"could not read this repository's remote list (exit {result.returncode}); no ref "
            f"under refs/remotes/ can be split into a remote and a branch name, so none of them "
            f"is offered for deletion"
        )
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip()), None


def split_remote_ref(full: str, remotes: tuple[str, ...] | None) -> tuple[str, str] | str:
    """(remote, branch name) for a ref under `refs/remotes/`, or the
    measurement that stopped the split.

    The remote's name is matched against the ones git says are configured
    rather than taken to be everything before the first slash. Both failure
    modes are real and neither is guessable: a path no configured remote
    accounts for -- a tracking ref left behind by `git remote remove` -- and a
    path two of them could account for, which is what having both `team` and
    `team/origin` produces. A caller who wants either gone can still use git;
    what this must not do is pick one and issue a deletion against it."""
    rest = full.removeprefix("refs/remotes/")
    if remotes is None:
        return (
            f"the configured remote list could not be read, so which part of {full} names a "
            f"remote and which part names the branch on it is unknown"
        )
    matches = [r for r in remotes if rest.startswith(f"{r}/")]
    if len(matches) == 1:
        remote = matches[0]
        return remote, rest[len(remote) + 1 :]
    if not matches:
        return (
            f"no configured remote accounts for {full}, so nothing says which part of it names "
            f"a remote; a tracking ref outliving its remote looks exactly like this"
        )
    named = ", ".join(sorted(matches))
    return (
        f"{full} could be a branch on any of these configured remotes: {named} -- the ref path "
        f"does not say which, and a deletion issued against the wrong one is a deletion on a "
        f"repository nobody asked about"
    )


_WORKTREE_ATTRIBUTES = frozenset(
    {"worktree", "bare", "HEAD", "branch", "detached", "locked", "prunable"}
)
"""The attributes `git worktree list --porcelain` documents.

Read only by the fallback parser below, and read there as "keys this recognises"
rather than as "keys git has". A key outside this set means the block said
something that was not recorded, whether that is a path fragment or an
attribute a git somewhere has and this does not -- and both settle the same
way, as a block dropped rather than one recorded wrongly."""


@dataclass(frozen=True, slots=True)
class WorktreeListing:
    """git's own account of the worktrees, framed so a path survives it whole.

    Kept as one type because two callers need the same listing and the framing
    rule must not be written twice: the survey builds targets from it, and the
    executor re-asks it to confirm a removal. A rule about how to read git's
    output that exists in two places is a rule that will disagree with itself."""

    blocks: tuple[dict[str, str], ...]
    warnings: tuple[str, ...]
    dropped: int
    result: CommandResult
    """The command actually used, for the transcript an anomaly carries."""
    framed: bool = True
    """Whether the records came back NUL-framed, so a path is whole whatever it
    contains.

    False says this listing cannot prove it recorded every path -- not that it
    got one wrong. ``dropped`` counts the truncations that announced
    themselves; the ones that do not are the reason this flag exists, and the
    only honest thing to do with them is to stop concluding *absence* from a
    listing that may be a prefix of the truth. What a positive match means is
    unchanged."""

    @property
    def ok(self) -> bool:
        return self.result.ok

    def holds(self, path: str) -> bool:
        return any(block.get("worktree") == path for block in self.blocks)

    def can_place(self, path: str) -> bool:
        """Whether *this* path's absence from the listing means anything.

        A truncation only ever shortens a path at a newline, and it only
        corrupts the block it happens inside -- records are grouped by the empty
        record between them, so a fragment lands among its own worktree's
        attributes and nowhere else. A path with no newline in it therefore
        cannot be the truncated one, and no other worktree's truncation can hide
        it, so a framed listing and an unframed one answer alike about it.

        This is narrower than the rule the survey applies to a *selector*, and
        deliberately: there the string came from a caller and may be a shorter
        name -- a basename, say -- for a path whose newline is further up, so a
        selector with no newline in it proves nothing. Here the whole path is in
        hand."""
        return self.framed or "\n" not in path


def _parse_worktrees(records: list[str], *, framed: bool) -> tuple[list[dict[str, str]], int]:
    """Records into blocks, and the count of blocks that lost something.

    ``framed`` says the records came from `-z`, where a record boundary is a
    NUL and a path is therefore whole whatever it contains. Without it the
    boundary is a newline, which a path is allowed to contain and which git
    does not escape -- so a path holding one arrives as two records, the second
    of them read as a stray key.

    That stray key is the only evidence available in the unframed case, and it
    is nearly enough: a key this does not recognise means the block said
    something that was not recorded. The block is dropped rather than kept
    under a path that may be a prefix of the real one -- a truncated path is a
    name that matches nothing while the tree is sitting there, which is the
    answer this package exists not to give.

    A lock reason may hold a newline too, and needs no rule of its own: git
    quotes it here (`locked "reason\\nwhy"`) and leaves it raw only under `-z`,
    where a newline cannot end a record anyway. Documented behaviour in both
    directions, so it is read rather than guarded against.

    What it does not catch, and cannot: a path whose text after the newline
    begins with an attribute name -- `.../we\\nbare` -- reads as a well-formed
    block. Nothing in the unframed output distinguishes that from the real
    thing, which is why `-z` is asked for first rather than treated as a
    nicety, and why this parser runs only where git cannot provide it."""
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    lost = False
    dropped = 0
    for record in records:
        if not record:
            if current:
                if lost:
                    dropped += 1
                else:
                    blocks.append(current)
                current = {}
                lost = False
            continue
        key, _, value = record.partition(" ")
        if not framed and key not in _WORKTREE_ATTRIBUTES:
            lost = True
        current[key] = value
    if current:
        if lost:
            dropped += 1
        else:
            blocks.append(current)
    return blocks, dropped


def list_worktrees(port: CommandPort, cwd: Path | None) -> WorktreeListing:
    """`worktree list --porcelain`, asked with NUL framing where git has it.

    A worktree path may contain a newline, and the porcelain format does not
    escape one -- it is emitted raw, so a line-based reader records a truncated
    path and counts nothing as missing. `-z` frames every record with a NUL
    instead, which no path can contain. This is not an inference about the
    format: git documents `-z` as existing for exactly this, "to parse the
    output when a worktree path contains a newline character", and recommends
    combining it with `--porcelain`.

    Whether the running git offers it is a question rather than an assumption,
    so it is asked rather than predicted from a version. A git that declines
    gets the line-based read, with the parser refusing to record a block whose
    keys say it lost something. What must not happen is either reading: a
    truncated path taken for a whole one, or a listing described as complete
    when it is not.

    Which is why the fallback also travels as ``framed=False``. Dropping the
    blocks that announce their truncation is not the same as catching them all
    -- a path whose text after the newline begins with an attribute name reads
    as a well-formed block -- so the listing itself is marked as unable to prove
    it recorded every path. That costs nothing where `-z` answers, and where it
    does not it withholds one conclusion: that something absent from this
    listing is absent from the repository."""
    framed = port.git(["worktree", "list", "--porcelain", "-z"], cwd=cwd)
    if framed.ok:
        blocks, dropped = _parse_worktrees(framed.stdout.split("\0"), framed=True)
        return WorktreeListing(tuple(blocks), (), dropped, framed)
    plain = port.git(["worktree", "list", "--porcelain"], cwd=cwd)
    if not plain.ok:
        return WorktreeListing((), (), 0, plain, framed=False)
    blocks, dropped = _parse_worktrees(plain.stdout.splitlines(), framed=False)
    warnings = [
        f"this git would not list worktrees with NUL framing (exit {framed.returncode}), so a "
        f"worktree path containing a newline cannot be told from two records; a name matching "
        f"nothing here is not evidence that what it names is gone"
    ]
    if dropped:
        warnings.append(
            f"{dropped} listed worktree(s) whose records this could not account for were left "
            f"out rather than recorded under a path that may be cut short at a newline"
        )
    return WorktreeListing(tuple(blocks), tuple(warnings), dropped, plain, framed=False)


def read_worktrees(
    port: CommandPort, cwd: Path | None
) -> tuple[list[Worktree], list[str], bool, int, bool]:
    """Parse `worktree list --porcelain` and stat each tree for dirt.

    Returns the worktrees, any parse warnings, whether the listing answered at
    all, how many blocks it lost, and whether its paths came back framed. The
    third is not derivable from an empty list -- a repository with only its main
    working tree produces one entry, but a listing that failed produces none,
    and "no worktree is there" is a conclusion only one of those supports. The
    last is the weaker cousin of that: the listing answered, and still cannot
    prove it named every path."""
    listing = list_worktrees(port, cwd)
    if not listing.ok:
        return (
            [],
            [f"could not list worktrees (exit {listing.result.returncode})"],
            False,
            0,
            listing.framed,
        )

    worktrees: list[Worktree] = []
    warnings: list[str] = list(listing.warnings)
    dropped_blocks = listing.dropped
    for index, block in enumerate(listing.blocks):
        path = block.get("worktree", "")
        if not path:
            # Counted as well as warned: a block nobody could read is a
            # worktree whose existence went unrecorded, which a later
            # "nothing matched" must not be allowed to call absence.
            warnings.append(f"worktree block {index} had no path; skipped")
            dropped_blocks += 1
            continue
        branch_ref = block.get("branch")
        branch = branch_ref.removeprefix("refs/heads/") if branch_ref else None
        prunable = "prunable" in block
        if prunable:
            # NOT "the directory is gone, so there is nothing to stat". git
            # says prunable whenever the path is merely UNREACHABLE -- moved
            # aside, or on a volume that is not mounted right now -- and the
            # tree, with its .env and its afternoon of uncommitted work, is
            # sitting intact wherever it went. Asserting (0, 0, 0) here was
            # the one place an unknown was manufactured into the answer that
            # authorises deletion. Nothing can be probed and nothing is known.
            dirt: tuple[int, int, int] | None = None
            warnings.append(
                f"git reports the worktree at {path} as prunable, which means only that its "
                f"path is unreachable from here -- the tree may still exist, holding work "
                f"nothing has copied; its contents are unknown"
            )
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
    return worktrees, warnings, True, dropped_blocks, listing.framed


def _count_dirt(port: CommandPort, path: Path) -> tuple[int, int, int] | None:
    """(tracked-modified, untracked, ignored) FILE counts, or None when git
    would not answer -- an unstatable tree is unknown, not clean.

    ``--ignored`` buys visibility, not a verdict. What it finds in practice is
    build detritus, so the caller reports the count rather than acting on it --
    see ``Worktree.ignored_file_count`` for the trade that settles.

    The flag pair is what makes these file counts rather than line counts, and
    both halves are load-bearing. Under ``--untracked-files=normal`` git
    collapses an untracked directory to a single line, so `node_modules/` is
    disclosed as one file when it is forty thousand -- the report understating
    what a deletion removes by orders of magnitude, in the one place the
    ignored-files trade is surfaced before an irreversible sweep. ``=all``
    expands that. Ignored content additionally needs ``traditional``: under
    ``matching`` any directory matching an ignore pattern re-collapses to its
    own line whatever the untracked mode says, and only ``traditional`` defers
    to ``=all``. Measured on a 2.5 GB checkout the pair costs ~0.15s against
    ~0.02s, and returns 47,620 ignored files where the old pair returned 90."""
    status = port.git(
        ["status", "--porcelain=v1", "--untracked-files=all", "--ignored=traditional"], cwd=path
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
) -> tuple[dict[str, PullRequest], str | None, str | None]:
    """One gh call for every PR in the repo, indexed by head ref.

    On a repo with several PRs per branch the newest wins -- the reopened or
    superseding PR is the one whose state describes the branch now.

    Returns the index, the error that cost us PR evidence entirely, and the
    warning that says the evidence is merely incomplete. They are separate
    because the consequences are: no PR data at all makes every squash merge
    invisible, whereas an incomplete list only leaves some branches to be
    judged on git evidence alone.

    Incomplete covers two things -- the list was cut off at the limit, or an
    entry came back in terms this cannot read. Both leave a branch with no PR
    beside a branch that genuinely has none, which is why the count of what was
    dropped travels rather than being swallowed by the `continue`."""
    if not port.has_gh():
        return (
            {},
            "gh not on PATH; merge evidence limited to git (squash merges invisible)",
            None,
        )
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
        return {}, f"gh pr list failed ({detail}); merge evidence limited to git", None
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        return (
            {},
            f"gh pr list returned unparseable JSON ({exc}); merge evidence limited to git",
            None,
        )
    if not isinstance(payload, list):
        return {}, "gh pr list returned a non-list payload; merge evidence limited to git", None

    gaps = (
        [
            f"only the {_PR_LIMIT} most recently updated pull requests were read; any branch "
            f"whose PR is older than those is judged on git evidence alone"
        ]
        if len(payload) >= _PR_LIMIT
        else []
    )

    unreadable = 0
    index: dict[str, PullRequest] = {}
    for entry in payload:
        if not isinstance(entry, dict):
            unreadable += 1
            continue
        head = str(entry.get("headRefName", ""))
        if not head:
            unreadable += 1
            continue
        try:
            number = int(entry.get("number", 0))
        except (TypeError, ValueError):
            # A PR number that is not a number is gh telling us something we
            # do not understand. Skipping the entry costs one branch its PR
            # evidence; letting int() raise costs the caller the whole report.
            unreadable += 1
            continue
        pr = PullRequest(
            number=number,
            state=str(entry.get("state", "")).upper(),
            url=str(entry.get("url", "")),
            updated_at=str(entry.get("updatedAt", "")),
            head_oid=str(entry.get("headRefOid", "")),
        )
        existing = index.get(head)
        if existing is None or pr.updated_at > existing.updated_at:
            index[head] = pr
    if unreadable:
        gaps.append(
            f"{unreadable} of the {len(payload)} pull requests gh listed could not be read and "
            f"were left out; a branch of theirs is judged on git evidence alone"
        )
    return index, None, "; ".join(gaps) if gaps else None


def read_pull_request(port: CommandPort, cwd: Path | None, number: str) -> PullRequestOutcome | str:
    """One pull request, asked for by number -- or the measurement that stopped
    the read.

    Every failure here is a sentence rather than an empty result, which is what
    separates this from the bulk read above. That one gathers evidence to lay
    beside branches nobody named: a gh that is absent or failing costs it a
    tier, the run continues, and each row says squash merges were invisible to
    it. Here the pull request is the authorisation itself. A read that did not
    answer leaves nothing to act on, so the only honest outcomes are the fact or
    the reason it is missing -- and a caller who is told which can fix it.

    ``number`` travels as the caller spelled it. It goes straight into an argv,
    and round-tripping it through ``int`` would change the string gh is asked
    for -- gh accepts a URL and a branch name there too, so the spelling that
    reaches it is worth keeping exact.

    The payload is read the way the bulk list is read: nothing is assumed about
    the shape gh returns, because an entry described in terms this does not
    understand is a fact nobody established, and the one thing it must not
    become is a merge.
    """
    if not port.has_gh():
        return f"gh is not on PATH, so nothing could say whether pull request #{number} merged"
    result = port.gh(["pr", "view", number, "--json", _PR_VIEW_FIELDS], cwd=cwd)
    if not result.ok:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        return f"gh pr view {number} failed ({detail})"
    try:
        payload = json.loads(result.stdout or "null")
    except json.JSONDecodeError as exc:
        return f"gh pr view {number} returned unparseable JSON ({exc})"
    if not isinstance(payload, dict):
        return f"gh pr view {number} returned a payload that describes no pull request"
    # Emptiness is decided before the value becomes a string, not after. JSON
    # null reaches here as None, and `str(None)` is the five-character word
    # "None" -- which is not empty, so a check made afterwards passes it, and a
    # field gh declined to answer becomes a branch name. Nothing then refuses,
    # and the scope narrows to a branch literally called None.
    raw_head = payload.get("headRefName")
    head = str(raw_head) if raw_head else ""
    if not head:
        return f"gh did not say which branch pull request #{number} was opened from"
    try:
        resolved = int(payload.get("number", 0))
    except (TypeError, ValueError):
        # A pull request number that is not a number is gh telling us something
        # this does not understand about the very thing being asked after.
        return f"gh answered for pull request #{number} with a number this could not read"
    raw_state = payload.get("state")
    merged_at = payload.get("mergedAt")
    return PullRequestOutcome(
        number=resolved,
        state=str(raw_state).upper() if raw_state else "",
        head_ref=head,
        merged_at=str(merged_at) if merged_at else None,
    )


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


def _unpushed_count(
    port: CommandPort, cwd: Path | None, *, name: str, spec: str, upstream: str, track: str
) -> tuple[int | None, str | None]:
    """Commits the upstream does not have, or None when that is not known.

    The tracking marker arrives free with the batch ref read and settles the
    common cases outright: `=` is in sync and `<` is behind-only, and neither
    has anything waiting to be pushed. Only a branch that is genuinely ahead
    costs a `rev-list`, which is the one place an exact count can come from.

    An upstream git records but cannot resolve reports as no marker at all --
    that is `[gone]`, the remote branch having been deleted. Nothing then
    proves these commits survive anywhere else, so the count is unknown rather
    than zero.

    ``name`` is what a reader is told and ``spec`` is what git is asked. They
    are the same string in every ordinary repository and come apart in the one
    that made this distinction necessary, so the two roles are separate
    parameters rather than one value used for both."""
    if not upstream:
        return None, None
    if not track:
        return None, (
            f"the upstream {upstream} of {name} no longer exists, so nothing "
            f"proves its commits are pushed; treating them as unpushed"
        )
    if ">" not in track:
        return 0, None
    count = _count_revs(port, cwd, f"{upstream}..{spec}")
    if count is None:
        return None, (
            f"could not count the commits on {name} missing from {upstream}; "
            f"it will not be treated as fully pushed"
        )
    return count, None


def _patch_equal(port: CommandPort, cwd: Path | None, base_ref: str, name: str) -> bool | None:
    """True when every commit on the branch already has a patch-id in base --
    the rebase and cherry-pick cases that plain ancestry misses. None when the
    probe errored: `git cherry` has no exit code meaning "no", so a non-zero
    exit is always a question that went unanswered rather than an answer of
    not-equivalent."""
    # `--` because the branch name is repo-derived: `refs/heads/-m` is a
    # perfectly legal ref that plumbing and remotes can both create, and
    # without the terminator `git cherry` reads it as a switch and errors.
    result = port.git(["cherry", base_ref, "--", name], cwd=cwd)
    if not result.ok:
        return None
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return False
    return all(line.startswith("-") for line in lines)


def _squash_equal(port: CommandPort, cwd: Path | None, base_ref: str, name: str) -> bool | None:
    """True when the branch's whole tree, replayed as ONE commit on the merge
    base, has a patch-id already in base. False when there is nothing to replay
    because the branch ends on the tree it began from. None when one of the
    steps errored, since a chain that stopped part-way proves nothing either
    way.

    This is the squash-merge case, and nothing cheaper detects it: the squashed
    commit on base shares no patch-id with any individual branch commit, and
    the branch tip is not an ancestor of anything. Synthesising the equivalent
    single commit and asking `git cherry` about *that* is the check that lines
    up with what a squash merge actually produced.

    `commit-tree` writes a loose object. It is unreachable and gc collects it;
    nothing in the repo's refs is touched.

    A name beginning with `-` -- `refs/heads/-m` is a legal ref that
    `update-ref` or a remote push can create -- is otherwise read by git as a
    switch. `--` genuinely terminates `merge-base`'s option parsing, so it is
    applied unconditionally, matching every other probe in this module.
    `rev-parse` has no terminator that survives here: both `--` and
    `--end-of-options` are echoed back as a literal output line rather than
    consumed, so the tree lookup instead names the branch by its full ref path
    when the short name would otherwise be misread -- a path never begins with
    `-`. That substitution is conditional, not unconditional like the one
    above: a remote-tracking branch's short name always carries its remote
    first (`origin/feat`, never bare `feat`) and already resolves correctly,
    while `refs/heads/` would be the wrong prefix for it."""
    base = port.git(["merge-base", base_ref, "--", name], cwd=cwd)
    if base.returncode == 1:
        # git's own answer, not a failed read: these histories share no commit,
        # so there is no base to replay the tree onto and no squash to find.
        return False
    if not base.ok or not base.out:
        return None
    ref = f"refs/heads/{name}" if name.startswith("-") else name
    tree = port.git(["rev-parse", f"{ref}^{{tree}}"], cwd=cwd)
    if not tree.ok or not tree.out:
        return None
    base_tree = port.git(["rev-parse", f"{_first_line(base.out)}^{{tree}}"], cwd=cwd)
    if not base_tree.ok or not base_tree.out:
        return None
    if _first_line(base_tree.out) == _first_line(tree.out):
        # The branch ends on the tree it started from -- work added and taken
        # off again -- so the commit synthesised below carries an empty diff,
        # and every empty diff has the same patch id as every other. `cherry`
        # would match it against any empty commit base picked up after the
        # fork, and a build retrigger leaves exactly one of those. The tier
        # would then report a squash nobody performed, against a branch whose
        # commits are the only copy of the work they hold.
        return False
    synthetic = port.git(
        ["commit-tree", _first_line(tree.out), "-p", _first_line(base.out), "-m", "gitclean-probe"],
        cwd=cwd,
    )
    if not synthetic.ok or not synthetic.out:
        return None
    cherry = port.git(["cherry", base_ref, _first_line(synthetic.out)], cwd=cwd)
    if not cherry.ok:
        return None
    lines = [line for line in cherry.stdout.splitlines() if line.strip()]
    return bool(lines) and all(line.startswith("-") for line in lines)


def _pr_covers_tip(port: CommandPort, cwd: Path | None, pr: PullRequest, head: str) -> bool | None:
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
    unanswerable question falls through to the tiers that read content.

    Falling through is the same for both, which is why the two used to share an
    answer. The report is not: False is git saying the merged head does not
    contain this tip, and None is git never having compared them. Printing the
    first for the second asserts a comparison of two commits as the reason a
    branch was held back, when one of them was not even here to compare."""
    if not pr.head_oid or not head:
        return None
    if pr.head_oid == head:
        return True
    result = port.git(["merge-base", "--is-ancestor", head, pr.head_oid], cwd=cwd)
    if result.ok:
        return True
    return False if result.returncode == 1 else None


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
) -> tuple[bool, MergeEvidence, bool | None, tuple[str, ...]]:
    """Tiered merge proof, cheapest conclusive answer first: whether the branch
    is merged, the tier that said so, whether the PR covered the tip, and the
    probes that errored on the way.

    ``name`` goes into an argv, so it must be a spelling that denotes this ref
    and no other -- git's own `%(refname:short)`, which is exactly that. The
    caller-facing name is not: `origin/main` is a legal local branch, and a
    probe spelled that way would measure it instead of the server's copy.

    Both PR tiers are gated on containment. Falling through costs only speed:
    the ancestry, patch-id and squash tiers below re-derive the answer from
    what is actually in the repository, which is the stronger evidence anyway.

    The last two returns exist because falling through is not self-describing.
    ``MergeEvidence.NONE`` is the same value whether four tiers ran and none
    fired or two of them errored, and only one of those is a measurement."""
    covers_tip: bool | None = None
    failures: list[str] = []
    if pr is not None and pr.state == "MERGED":
        covers_tip = _pr_covers_tip(port, cwd, pr, head)
        if covers_tip:
            return True, MergeEvidence.PR_MERGED, covers_tip, ()
    if ancestor_merged:
        return True, MergeEvidence.ANCESTOR, covers_tip, ()
    if unmerged_commits is not None and unmerged_commits == 0:
        # Spelled out rather than folded into `unmerged_commits == 0`: this
        # tier turns a count into proof of a merge, so an unanswered count
        # must visibly fall through instead of quietly satisfying it.
        return True, MergeEvidence.ANCESTOR, covers_tip, ()
    if pr is not None and pr.state == "CLOSED":
        covers_tip = _pr_covers_tip(port, cwd, pr, head)
        if covers_tip:
            # Not merged, and this tier authorises nothing: a closed PR says
            # someone stopped wanting the change, never that its commits exist
            # anywhere else. It is gated on containment so the report speaks
            # about what was in the PR rather than about commits that arrived
            # afterwards.
            return False, MergeEvidence.PR_CLOSED_UNMERGED, covers_tip, ()
    patch = _patch_equal(port, cwd, base_ref, name)
    if patch:
        return True, MergeEvidence.PATCH_EQUAL, covers_tip, ()
    if patch is None:
        failures.append(
            f"the patch-id probe against {base_ref} errored, so a rebased or cherry-picked "
            f"merge would not have been seen"
        )
    squash = _squash_equal(port, cwd, base_ref, name)
    if squash:
        return True, MergeEvidence.SQUASH_EQUAL, covers_tip, tuple(failures)
    if squash is None:
        failures.append(
            f"the squash-equivalence probe against {base_ref} errored, so a squash merge "
            f"would not have been seen"
        )
    return False, MergeEvidence.NONE, covers_tip, tuple(failures)


def read_branches(
    port: CommandPort,
    cwd: Path | None,
    *,
    base_ref: str,
    default_branch: str,
    prs: dict[str, PullRequest],
    worktree_by_branch: dict[str, str],
    remotes: tuple[str, ...] | None,
) -> tuple[list[Branch], list[str], bool, list[NotOffered], int, int]:
    """The branches, the warnings, whether the ref read answered at all, the
    refs deliberately left out of the first list, and two counts of what this
    read could not fully account for.

    The third is not derivable from an empty branch list, and a worktree row
    needs it: with no refs read there was nothing a commit could have been
    proven merged against.

    The fourth exists because "not a target" and "not in the repository" are
    different facts that a bare absence from ``branches`` cannot tell apart --
    and only one of them lets a caller be told there is nothing to delete.

    The counts are rows nobody could parse and refs nobody could split. Both
    travel because both leave a spelling a caller might use matching nothing,
    and a miss that means nothing must never settle as absence."""
    result = port.git(
        ["for-each-ref", f"--format={_REF_FORMAT}", "refs/heads", "refs/remotes"], cwd=cwd
    )
    if not result.ok:
        return (
            [],
            [
                f"could not list refs (exit {result.returncode}); "
                f"no branch was surveyed, so this report describes worktrees only"
            ],
            False,
            [],
            0,
            0,
        )

    local_merged, local_warning = _merged_set(port, cwd, base_ref, remote=False)
    remote_merged, remote_warning = _merged_set(port, cwd, base_ref, remote=True)
    warnings = [w for w in (local_warning, remote_warning) if w]

    branches: list[Branch] = []
    not_offered: list[NotOffered] = []
    dropped = 0
    unsplit = 0
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        fields = line.split(_SEP)
        if len(fields) < _REF_FIELDS:
            # Counted, not swallowed. A row nobody could parse is a ref whose
            # existence went unrecorded, and a later "nothing matched that
            # name" cannot tell that apart from the ref not being there.
            dropped += 1
            continue
        full, probe_ref, head, committed, upstream_ref, upstream, track, head_marker = (
            f.strip() for f in fields[:_REF_FIELDS]
        )
        if not probe_ref or not full:
            dropped += 1
            continue

        is_remote = full.startswith("refs/remotes/")
        if is_remote and full.endswith("/HEAD"):
            # The remote's symbolic HEAD is a pointer, not a branch.
            not_offered.append(
                NotOffered(
                    # Recorded from the full path rather than the short form:
                    # git shortens refs/remotes/origin/HEAD to a bare `origin`,
                    # which is not a spelling anybody would type at this tool.
                    name=full.removeprefix("refs/remotes/"),
                    reason="the remote's symbolic HEAD, which points at a branch rather than "
                    "being one; delete the branch it names instead",
                )
            )
            continue

        if is_remote:
            # The whole of the decomposition, and it is done from the full path
            # against the configured remote list. Nothing here reads the short
            # form: it is what git would let you *type*, which is a different
            # question from where the remote's name ends.
            split = split_remote_ref(full, remotes)
            if isinstance(split, str):
                # Unsplittable, so nothing can be issued against it -- but it
                # is sitting right there, and a caller who names it must not be
                # told it is already gone. NotOffered keeps those two answers
                # apart for the full `<remote>/<ref>` spelling; the count keeps
                # them apart for every other one, since the spelling this could
                # not recover is the one a caller is most likely to use.
                not_offered.append(
                    NotOffered(name=full.removeprefix("refs/remotes/"), reason=split, unsplit=True)
                )
                unsplit += 1
                continue
            remote, ref_name = split
            name = full.removeprefix("refs/remotes/")
        else:
            remote, ref_name = None, full.removeprefix("refs/heads/")
            name = ref_name

        if is_remote and ref_name == default_branch:
            not_offered.append(
                NotOffered(
                    name=name,
                    reason=f"the server's copy of the trunk ({default_branch}); gitclean does "
                    f"not offer it for deletion, and git will do it if you truly mean to",
                )
            )
            continue

        is_default = not is_remote and name == default_branch
        # A PR keyed by the trunk's name targets it rather than proposing it,
        # so it says nothing about whether the trunk is finished with. Keyed by
        # what the *server* calls the branch, which for a remote-tracking ref
        # is the half of the path the remote's name does not account for.
        pr = None if is_default else prs.get(ref_name)
        # The trunk is measured like every other branch. It used to be handed
        # zeroes and a merge verdict on the reasoning that probing it against
        # itself is noise, but both halves of that were wrong: the counts are
        # the most useful ones in the report -- `origin/main..main` is the
        # commits on the trunk that have not been pushed -- and asserting a
        # measurement nobody took is the exact habit that made this tool
        # dangerous. Nothing needs the shortcut: the trunk is kept out of the
        # sweep by identity, not by carrying a manufactured verdict.
        #
        # From here down every string handed to git is `probe_ref` and every
        # string shown to a reader is `name`. They are the same in any
        # repository that has not been arranged to make them differ, and the
        # separation is what makes the arranged one measure the right ref: a
        # probe spelled `origin/main` resolves to the *local* branch of that
        # name when one exists, so the report would carry the local branch's
        # history under the server ref's row.
        unmerged = _count_revs(port, cwd, f"{base_ref}..{probe_ref}")
        if unmerged is None:
            warnings.append(
                f"could not count the commits on {name} missing from {base_ref}; "
                f"it will not be treated as merged"
            )
        unpushed, unpushed_warning = _unpushed_count(
            port, cwd, name=name, spec=probe_ref, upstream=upstream, track=track
        )
        if unpushed_warning:
            warnings.append(unpushed_warning)
        merged, evidence, covers_tip, probe_failures = _resolve_merge(
            port,
            cwd,
            base_ref,
            probe_ref,
            pr=pr,
            head=head,
            # Both sides of this comparison are git's own short form, produced
            # by the same shortening on the same repository, so equal strings
            # are the same ref and different strings are not.
            ancestor_merged=probe_ref in (remote_merged if is_remote else local_merged),
            unmerged_commits=unmerged,
        )
        warnings.extend(f"{name}: {failure}" for failure in probe_failures)

        branches.append(
            Branch(
                name=name,
                ref=full,
                probe_ref=probe_ref,
                ref_name=ref_name,
                is_remote=is_remote,
                remote=remote,
                head=head,
                last_activity=committed or None,
                upstream=upstream or None,
                upstream_ref=upstream_ref or None,
                is_default=is_default,
                is_current=head_marker == "*",
                checked_out_at=worktree_by_branch.get(name),
                unpushed_commits=unpushed,
                unmerged_commits=unmerged,
                merged=merged,
                merge_evidence=evidence,
                pr=pr,
                pr_covers_tip=covers_tip,
                probe_failures=probe_failures,
            )
        )
    if dropped:
        warnings.append(
            f"{dropped} ref row(s) could not be parsed and are missing from this report; "
            f"a name that matches nothing may be one of them"
        )
    if unsplit:
        warnings.append(
            f"{unsplit} ref(s) under refs/remotes/ could not be split into a remote and a "
            f"branch name; they are listed under the full spelling git gave, and the shorter "
            f"name a remote would know them by could not be recovered"
        )
    return branches, warnings, True, not_offered, dropped, unsplit


def _worktree_activity(
    port: CommandPort,
    cwd: Path | None,
    worktree: Worktree,
    activity_by_branch: dict[str, str | None],
) -> str | None:
    """The commit date of what this worktree holds -- its branch's tip, or its
    detached HEAD.

    It dates the *commit*, not the checkout, and the two come apart: a worktree
    created ten seconds ago at a two-year-old tag reports a two-year-old
    timestamp. Nothing judges on it, which is why the discrepancy is tolerable
    -- it is a fact for a reader, and no rule reads it. If anything ever does,
    this is the wrong measurement for it."""
    if worktree.branch:
        return activity_by_branch.get(worktree.branch)
    if worktree.prunable or not worktree.head:
        return None
    result = port.git(["show", "-s", "--format=%cI", worktree.head], cwd=cwd)
    return _first_line(result.out) if result.ok else None


def survey(port: CommandPort, *, cwd: Path | None = None) -> Survey | str:
    """Full read pass. Returns the Survey, or a message when cwd is not a repo."""
    resolved = resolve_repo(port, cwd)
    if resolved is None:
        return "not inside a git repository"
    repo_root, common_dir = resolved

    resolved_default, default_branch_warning = resolve_default_branch(port, cwd)
    # The name is still needed downstream to compare against, but it is now
    # known to be a guess -- so it protects nothing it cannot prove, and the
    # flag travels with the survey so the run can report that it is guessing.
    default_branch = resolved_default if resolved_default is not None else "main"
    base_ref, base_ref_warning = resolve_base_ref(port, cwd, default_branch)

    head = port.git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
    current = _first_line(head.out) if head.ok else None
    if current == "HEAD":
        current = None
    # `None` is also what a detached HEAD reports, so a failed read has to say
    # so out loud or it arrives as a measurement of a checkout on no branch.
    current_warning = (
        None
        if head.ok
        else (
            f"could not read which branch this checkout is on (exit {head.returncode}); "
            f"the current branch is reported as unknown, not as a detached HEAD"
        )
    )

    worktrees, warnings, worktrees_known, dropped_worktrees, worktrees_framed = read_worktrees(
        port, cwd
    )
    if base_ref_warning is not None:
        warnings.append(base_ref_warning)
    if current_warning is not None:
        warnings.append(current_warning)
    worktree_by_branch = {w.branch: w.path for w in worktrees if w.branch}

    prs, gh_error, pr_evidence_gap = read_pull_requests(port, cwd)
    if pr_evidence_gap:
        warnings.append(pr_evidence_gap)
    remotes, remotes_warning = read_remotes(port, cwd)
    if remotes_warning is not None:
        warnings.append(remotes_warning)
    read = read_branches(
        port,
        cwd,
        base_ref=base_ref,
        default_branch=default_branch,
        prs=prs,
        worktree_by_branch=worktree_by_branch,
        remotes=remotes,
    )
    branches, branch_warnings, branches_known, not_offered, dropped_refs, unsplit_refs = read
    warnings.extend(branch_warnings)

    # A worktree's age is the age of the branch it holds; that is only known
    # once the branches have been read, hence the second pass.
    activity_by_branch = {b.name: b.last_activity for b in branches}
    worktrees = [
        replace(w, last_activity=_worktree_activity(port, cwd, w, activity_by_branch))
        for w in worktrees
    ]

    if default_branch_warning is not None:
        warnings.append(default_branch_warning)

    return Survey(
        repo_root=repo_root,
        git_common_dir=common_dir,
        base_ref=base_ref,
        default_branch=default_branch,
        default_branch_known=resolved_default is not None,
        current_branch=current,
        gh_available=port.has_gh(),
        gh_error=gh_error,
        pr_evidence_gap=pr_evidence_gap,
        worktrees=tuple(worktrees),
        branches=tuple(branches),
        branches_known=branches_known,
        worktrees_known=worktrees_known,
        dropped_refs=dropped_refs,
        dropped_worktrees=dropped_worktrees,
        worktrees_framed=worktrees_framed,
        unsplit_refs=unsplit_refs,
        remotes=remotes or (),
        remotes_known=remotes is not None,
        not_offered=tuple(not_offered),
        warnings=tuple(warnings),
    )
