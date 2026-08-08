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

Every git call here is assembled by the shared argv constructor, and a name the
repository chose reaches git only through it or through the rev spelling beside
it. A probe added without one is the failure mode: the terminator is not a
habit to apply call site by call site, and the sites that forget it are the ones
nobody can type by hand.
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
from gitclean.ports import CommandPort, CommandResult, git_argv, git_rev

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
    root = port.git(git_argv("rev-parse", "--show-toplevel"), cwd=cwd)
    if not root.ok:
        return None
    common = port.git(git_argv("rev-parse", "--path-format=absolute", "--git-common-dir"), cwd=cwd)
    if not common.ok:
        # --path-format landed in git 2.31; older git still answers the plain
        # form, relative to the repo root.
        common = port.git(git_argv("rev-parse", "--git-common-dir"), cwd=cwd)
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
    result = port.git(git_argv("show-ref", "--verify", "--quiet", name=ref), cwd=cwd)
    if result.ok:
        return True
    return False if result.returncode == 1 else None


def _published_trunk(
    port: CommandPort, cwd: Path | None, remotes: tuple[str, ...]
) -> tuple[str, tuple[str, ...], str]:
    """The branch these remotes publish as their HEAD, the remotes that publish
    it, and -- when no single name came back -- the clause saying why.

    A published HEAD is a local symbolic ref that `git fetch` or `git remote
    set-head` wrote, so asking every configured remote costs no network round
    trip and this loop is as cheap as the single question it grew out of.

    One distinct name is the whole bar, and remotes that agree are worth as much
    as a remote on its own: what this tier produces is the trunk's *name*, and
    two servers that both call their trunk `main` are saying the same thing
    about it. Remotes that disagree are saying nothing that can be acted on --
    picking one of them would silently decide which repository's history every
    merge in the report is measured against, and picking the one that is ahead
    is what makes unmerged work look merged -- so the disagreement is handed
    back as prose and the tier declines. Declining costs a tier and leaves the
    local main/master below it to answer; guessing costs commits.

    A remote whose HEAD could not be read is one of those disagreements as far
    as anything here knows, so it declines the tier too -- even when another
    remote did answer. Accepting the name that came back would be taking
    agreement from a remote that was never asked: the read that failed is the
    one that might have contradicted it, and a trunk accepted on partial data is
    exactly what the disagreement rule above exists to refuse."""
    if not remotes:
        return "", (), "this repository has no configured remote to publish a HEAD"
    published: dict[str, str] = {}
    unreadable: list[tuple[str, int]] = []
    for remote in remotes:
        result = port.git(
            git_argv("symbolic-ref", "--quiet", name=f"refs/remotes/{remote}/HEAD"), cwd=cwd
        )
        if result.ok:
            name = _first_line(result.out).removeprefix(f"refs/remotes/{remote}/")
            if name:
                published[remote] = name
        elif result.returncode != 1:
            # Exit 1 is git saying this remote has published no HEAD, which is
            # an answer. Anything else is git declining to look, which is not.
            unreadable.append((remote, result.returncode))
    names = set(published.values())
    if len(names) > 1:
        spelled = ", ".join(f"{r} publishes {n}" for r, n in sorted(published.items()))
        return "", (), f"the configured remotes disagree about which branch is the trunk: {spelled}"
    if unreadable:
        listed = ", ".join(f"{remote} (exit {code})" for remote, code in unreadable)
        if names:
            # Withheld agreement rather than a missing HEAD, and the two are
            # worth separate sentences: something did answer here, and what
            # stopped the tier is that the remote which did not could have
            # contradicted it.
            answered = ", ".join(sorted(published))
            withheld = (
                f"the published HEAD of {listed} could not be read, and a remote that would "
                f"not answer could name a trunk other than the {next(iter(names))} that came "
                f"back from {answered}"
            )
            return "", (), withheld
        unread_detail = (
            f"{unreadable[0][0]}'s published HEAD could not be read (exit {unreadable[0][1]})"
            if len(unreadable) == 1
            else f"the published HEAD of these remotes could not be read: {listed}"
        )
        return "", (), unread_detail
    if len(names) == 1:
        trunk = next(iter(names))
        return trunk, tuple(r for r, n in published.items() if n == trunk), ""
    if len(remotes) == 1:
        return "", (), f"{remotes[0]} has published no HEAD"
    return "", (), f"none of this repository's remotes ({', '.join(remotes)}) has published a HEAD"


def _consulted_remotes(remotes: tuple[str, ...] | None) -> tuple[str, ...]:
    """The remotes whose account of the trunk this repository will accept.

    `origin` alone whenever it is configured, and that is behaviour worth
    stating rather than defaulting into. In a fork, `origin` and `upstream`
    legitimately disagree about the trunk, and the repository you are standing
    in is the one `origin` describes -- so consulting the others there could
    only replace a right answer with a refusal. Only where there is no `origin`
    does the rest of the remote list get a say.

    An unreadable remote list is not an empty one, and it is not a licence to
    ask more widely either: nothing can be enumerated, so this asks `origin` and
    no further, which is the reach any repository with an `origin` gets anyway.
    A transient failure to list remotes therefore costs nothing, and widens
    nothing on the strength of what nobody read."""
    return ("origin",) if remotes is None or "origin" in remotes else remotes


def resolve_default_branch(
    port: CommandPort, cwd: Path | None, remotes: tuple[str, ...] | None
) -> tuple[str | None, str | None, str | None]:
    """The repository's trunk -- the branch that is never a deletion candidate
    -- the remote whose published HEAD named it, and, when nothing answered,
    the warning that says which tier declined.

    Discovered, never supplied by the caller. A caller who could name what
    merges are measured against could measure against something the real trunk
    is an ancestor of, and the trunk would then classify as merged and
    sweepable -- so the question is asked of the repository, and only of the
    repository.

    A remote's published HEAD first, then a local main/master -- **each verified
    to resolve**. Returning the literal `main` when nothing answers looks
    harmless: every merge probe against a ref that is not there fails, so
    nothing can be proven merged. But protection is assigned by *name*, and
    a repository whose trunk is `trunk` then has no protected branch at all:
    the real trunk is left indistinguishable from cruft, deletable like any
    other branch.

    Which remote is asked is decided from the configured list rather than
    spelled `origin` in the question. Spelling it `origin` reaches no tier at
    all in a repository whose remote is called anything else -- and which has no
    local `main` or `master` either -- so no trunk resolves, nothing can be
    proven merged, and the tool is inert there. See the two helpers above for
    which remotes get a say and what settles a disagreement between them.

    The remote is handed back so that what merges are measured against can be
    that same remote's copy of the trunk rather than a second, independent
    guess. Only a sole publisher is recorded: where several remotes agree, the
    *name* is settled and which server's copy to measure against is not, and
    that second question is one the base ref resolves for itself.

    The published-HEAD tier is the one most likely to be stale -- a dangling
    `origin/HEAD -> origin/master` is the standard leftover after a
    server-side rename -- and taking it on trust is worse than guessing,
    because the guess is then recorded as knowledge and suppresses the
    warning that would otherwise say no branch is protected. An unproven name is
    not a default branch, whichever tier produced it.

    A tier git errored on is reported as unread rather than as absent. The
    verdict is the same either way -- an unverified name is not a trunk -- but
    the sentence is not, and telling someone their `main` does not exist when
    the probe never answered sends them to fix the wrong thing."""
    consulted = _consulted_remotes(remotes)
    published, publishers, declined = _published_trunk(port, cwd, consulted)
    source = publishers[0] if len(publishers) == 1 else None
    candidates: list[tuple[str, str, str | None]] = [
        (published, f"refs/remotes/{remote}/{published}", source) for remote in publishers
    ]
    candidates += [(name, f"refs/heads/{name}", None) for name in ("main", "master")]
    unread: list[str] = []
    for name, ref, from_remote in candidates:
        state = _ref_exists(port, cwd, ref)
        if state:
            return name, from_remote, None
        if state is None:
            unread.append(ref)

    if unread:
        detail = f"git would not say whether {' or '.join(unread)} exists, so no tier was ruled out"
    else:
        if not published:
            cause = declined
        elif len(publishers) == 1:
            cause = (
                f"{publishers[0]} publishes HEAD as {publishers[0]}/{published}, which no longer "
                f"exists"
            )
        else:
            cause = (
                f"{', '.join(publishers)} agree in publishing HEAD as {published}, and no "
                f"remote-tracking ref for it exists under any of them"
            )
        detail = f"{cause}, and neither main nor master exists"
    if remotes is None:
        detail = (
            f"this repository's remote list could not be read, so no remote beyond origin could "
            f"be consulted, and {detail}"
        )

    # Every remote this prescribes is one git listed. A repository with no
    # `origin` must not be told to publish origin's HEAD, and a repository whose
    # remote list went unread has no remote this can name at all -- there the
    # placeholder says what to do without asserting that any particular remote
    # is there to do it to.
    named = None if remotes is None else consulted
    remedies: list[str] = []
    if named is not None and len(named) == 1:
        remedies.append(
            f"publish {named[0]}'s HEAD (`git remote set-head {named[0]} -a`) and re-run"
        )
    elif consulted:
        remedies.append(
            "publish the HEAD of whichever remote holds your trunk "
            "(`git remote set-head <remote> -a`) and re-run"
        )
    remedies.append("delete what you want gone by naming it")
    warning = (
        f"could not determine this repository's default branch: {detail}. Nothing here can be "
        f"told apart from the trunk, so nothing will be swept; {', or '.join(remedies)}"
    )
    return None, None, warning


def resolve_base_ref(
    port: CommandPort,
    cwd: Path | None,
    default_branch: str,
    remotes: tuple[str, ...] | None,
    trunk_remote: str | None,
) -> tuple[str, str | None]:
    """What merges are measured against, plus the warning when the preferred
    ref could not be read.

    Prefer the remote-tracking tip: it is what a PR actually merged into, and a
    stale local checkout of the default branch would under-report merges. The
    local fallback is correct when the remote-tracking ref is genuinely absent
    and merely quiet when the probe errored -- so the second case says so, and
    every merge verdict in the report is then known to have been measured
    against a ref that may be behind.

    Whose copy of the trunk that is comes from ``trunk_remote`` -- the remote
    whose published HEAD named the default branch -- rather than from a second
    guess made here. Where the name came from a local `main` or `master`
    instead, nothing has nominated a remote, so the same one-distinct-answer
    rule the trunk tier uses applies again: exactly one remote holding a copy of
    the trunk is an answer, and several is not. Several is left to the local
    branch, because it is the direction that fails closed -- a base ref *behind*
    the real trunk under-reports merges, while one *ahead* of it reports
    unmerged work as merged.

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
    with `-`. The warnings below keep the short form, being prose for a reader
    rather than a rev for git."""
    candidates = (trunk_remote,) if trunk_remote is not None else _consulted_remotes(remotes)
    local = f"refs/heads/{default_branch}"
    found: list[str] = []
    unread: list[str] = []
    for remote in candidates:
        state = _ref_exists(port, cwd, f"refs/remotes/{remote}/{default_branch}")
        if state:
            found.append(remote)
        elif state is None:
            unread.append(remote)
    if len(found) > 1:
        listed = ", ".join(f"{remote}/{default_branch}" for remote in found)
        return local, (
            f"more than one remote holds a {default_branch} ({listed}) and no published HEAD "
            f"says which of them this repository's work merges into; measuring against one that "
            f"is ahead of the real trunk would report unmerged work as merged, so merges here "
            f"are measured against the local {default_branch}, which may be behind"
        )
    if unread:
        listed = " or ".join(f"{remote}/{default_branch}" for remote in unread)
        return local, (
            f"git would not say whether {listed} exists, so merges here are "
            f"measured against the local {default_branch}, which may be behind the remote"
        )
    if found:
        return f"refs/remotes/{found[0]}/{default_branch}", None
    return local, None


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
    result = port.git(git_argv("remote"), cwd=cwd)
    if not result.ok:
        return None, (
            f"could not read this repository's remote list (exit {result.returncode}); no ref "
            f"under refs/remotes/ can be split into a remote and a branch name, so none of them "
            f"is offered for deletion"
        )
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip()), None


def read_fetch_refspecs(
    port: CommandPort, cwd: Path | None
) -> tuple[dict[str, tuple[str, ...]] | None, str | None]:
    """Every configured `remote.<name>.fetch`, keyed by remote.

    This is what actually says which remote a path under `refs/remotes/`
    belongs to. The name in that path is a destination a refspec chose, not a
    remote naming itself: `git config remote.upstream.fetch
    '+refs/heads/*:refs/remotes/origin/*'` is legal, and puts upstream's
    branches under `refs/remotes/origin/` while a remote genuinely called
    `origin` sits beside them owning none of them.

    None rather than an empty mapping when the read failed, for the same
    reason `read_remotes` draws that line: "no remote configures a fetch
    refspec" and "nobody could say" are different answers, and only the second
    one is a hole in the survey. Exit 1 is the first of those -- `--get-regexp`
    spends it on "nothing matched" -- so only a worse code is a failure.

    `-z` because a config value may hold a newline; git writes one back for
    `\\n` in a value and would then split a single refspec across what a
    line-framed read calls two records. Each `-z` record is `key\\nvalue`, and
    a key holds no newline, so the first one in a record is the boundary."""
    result = port.git(git_argv("config", "-z", "--get-regexp", r"^remote\..*\.fetch$"), cwd=cwd)
    if not result.ok and result.returncode > 1:
        return None, (
            f"could not read this repository's fetch refspecs (exit {result.returncode}); "
            f"nothing says which remote a ref under refs/remotes/ was fetched by, so none of "
            f"them is offered for deletion"
        )
    specs: dict[str, list[str]] = {}
    for record in result.stdout.split("\0"):
        if not record:
            continue
        key, _, value = record.partition("\n")
        remote = key.removeprefix("remote.").removesuffix(".fetch")
        specs.setdefault(remote, []).append(value)
    return {remote: tuple(values) for remote, values in specs.items()}, None


def _refspec_destination_match(destination: str, full: str) -> str | None:
    """What `*` stood for when this destination matched, or None for no match.

    An exact destination matches exactly and captures the empty string, which
    is why the answer is a string-or-None rather than a truthy one: a literal
    refspec that matched returns `""`, and that is a match."""
    prefix, star, suffix = destination.partition("*")
    if not star:
        return "" if full == destination else None
    if not full.startswith(prefix) or not full.endswith(suffix):
        return None
    if len(full) < len(prefix) + len(suffix):
        return None
    return full[len(prefix) : len(full) - len(suffix)] if suffix else full[len(prefix) :]


def _fetch_sources(refspec: str, full: str) -> str | None:
    """The ref on the server that this refspec would fetch into `full`.

    A negative refspec (`^refs/heads/wip/*`) is skipped rather than
    interpreted. It narrows what a remote fetches, so honouring it could only
    ever remove a remote from the candidates -- and every caller here treats
    two candidates as a refusal. Ignoring one can therefore turn a correct
    single answer into a stated refusal, and can never turn it into a
    deletion issued against the wrong remote, which is the direction that
    matters."""
    spec = refspec.removeprefix("+")
    if spec.startswith("^"):
        return None
    source, colon, destination = spec.partition(":")
    if not colon:
        return None
    capture = _refspec_destination_match(destination, full)
    if capture is None:
        return None
    return source.replace("*", capture, 1) if "*" in source else source


def split_remote_ref(
    full: str,
    remotes: tuple[str, ...] | None,
    refspecs: dict[str, tuple[str, ...]] | None,
) -> tuple[str, str] | str:
    """(remote, branch name on that remote) for a ref under `refs/remotes/`,
    or the measurement that stopped the split.

    Ownership is decided by asking which remote's fetch refspec puts a ref at
    this path, not by matching configured remote names against the path
    itself. The path is a destination some refspec chose; the remote whose
    name it happens to spell need not be the one that fetches it, and probing
    that remote reports a branch alive on the server as already gone.

    The branch name comes back out of the refspec's source side for the same
    reason: `+refs/heads/*:refs/remotes/origin/mirror/*` makes `mirror/` part
    of the local path and no part of what the server calls the branch, so the
    tail of the tracking path is the wrong string to hand `git push --delete`.

    Every failure mode here is real and none is guessable: a path no refspec
    accounts for, a path two remotes both fetch into, a remote configured with
    no fetch refspec at all, and a refspec that maps something other than a
    branch. A caller who wants any of them gone can still use git; what this
    must not do is pick one and issue a deletion against it."""
    rest = full.removeprefix("refs/remotes/")
    if remotes is None:
        return (
            f"the configured remote list could not be read, so which part of {full} names a "
            f"remote and which part names the branch on it is unknown"
        )
    if refspecs is None:
        return (
            f"this repository's fetch refspecs could not be read, so nothing says which remote "
            f"{full} was fetched by"
        )
    owners: dict[str, set[str]] = {}
    for remote in remotes:
        for refspec in refspecs.get(remote, ()):
            source = _fetch_sources(refspec, full)
            if source is not None:
                owners.setdefault(remote, set()).add(source)
    if not owners:
        return (
            f"no configured remote accounts for {full}: no remote's fetch refspec puts a ref "
            f"at that path, which is what a tracking ref outliving its remote -- or a remote "
            f"configured with no fetch refspec -- looks like"
        )
    if len(owners) > 1:
        named = ", ".join(sorted(owners))
        return (
            f"{full} is fetched into that path by more than one configured remote: {named} -- "
            f"nothing says which one holds it, and a deletion issued against the wrong one is "
            f"a deletion on a repository nobody asked about"
        )
    remote, sources = next(iter(owners.items()))
    if len(sources) > 1:
        spelled = ", ".join(sorted(sources))
        return (
            f"{remote} fetches {rest} through refspecs that disagree about what it is called "
            f"there: {spelled} -- a deletion has to name one of them and nothing says which"
        )
    source = next(iter(sources))
    if not source.startswith("refs/heads/"):
        return (
            f"{full} is fetched from {source}, which is not a branch on {remote}; deleting it "
            f"is not something `git push --delete` expresses"
        )
    return remote, source.removeprefix("refs/heads/")


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

    The blocks travel with the evidence about how well they were read -- what
    was dropped, and whether the framing that makes a path whole was available
    at all -- because the survey's conclusions about absence rest on both, and
    a caller handed the blocks alone would have no way to tell a listing that
    named everything from one that could not."""

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
    framed = port.git(git_argv("worktree", "list", "--porcelain", "-z"), cwd=cwd)
    if framed.ok:
        blocks, dropped = _parse_worktrees(framed.stdout.split("\0"), framed=True)
        return WorktreeListing(tuple(blocks), (), dropped, framed)
    plain = port.git(git_argv("worktree", "list", "--porcelain"), cwd=cwd)
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
            # sitting intact wherever it went. Asserting (0, 0, 0) here would
            # manufacture an unknown into the answer that authorises deletion.
            # Nothing can be probed and nothing is known.
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
    ~0.02s, and returns 47,620 ignored files where the weaker pair returns 90."""
    status = port.git(
        git_argv("status", "--porcelain=v1", "--untracked-files=all", "--ignored=traditional"),
        cwd=path,
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
    probes still answer -- so failure here degrades speed, not safety.

    ``base_ref`` is the one repo-derived name here and it goes in as a plain
    argument: it arrives as a full ref path, which is the spelling that needs no
    terminator, and it could not have taken one anyway with a format argument
    behind it."""
    remote_only = ("-r",) if remote else ()
    result = port.git(
        git_argv("branch", *remote_only, "--merged", base_ref, "--format=%(refname:short)"), cwd=cwd
    )
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
    failed on.

    The range is one argument with two revs inside it, so it goes in whole
    rather than as a terminated name -- `rev-list` spends `--` on a pathspec,
    and counting commits that touched a path is not this question. What keeps
    it from being read as an option is the spelling of the rev it opens with,
    which the callers settle before composing it."""
    result = port.git(git_argv("rev-list", "--count", spec), cwd=cwd)
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
    parameters rather than one value used for both. ``upstream`` splits the same
    way: the sentences below spell it as a reader knows it, and the range below
    those opens with it, which is the position an option-shaped name would be
    read from -- so that one copy is spelled by the rev constructor."""
    if not upstream:
        return None, None
    if not track:
        return None, (
            f"the upstream {upstream} of {name} no longer exists, so nothing "
            f"proves its commits are pushed; treating them as unpushed"
        )
    if ">" not in track:
        return 0, None
    count = _count_revs(port, cwd, f"{git_rev(upstream)}..{spec}")
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
    # The branch name is repo-derived, so it reaches git through the argv
    # constructor: `refs/heads/-m` is a perfectly legal ref that plumbing and
    # remotes can both create, and unterminated `git cherry` reads it as a
    # switch and errors.
    result = port.git(git_argv("cherry", base_ref, name=name), cwd=cwd)
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
    switch, and this tier is where both spellings that survive that are needed
    at once. `merge-base` takes the name as an argument of its own, so the argv
    constructor terminates it. The tree lookup composes the name into a rev
    expression instead, where nothing can be terminated, so it goes through the
    rev constructor beside it -- and both decisions live there rather than
    here."""
    base = port.git(git_argv("merge-base", base_ref, name=name), cwd=cwd)
    if base.returncode == 1:
        # git's own answer, not a failed read: these histories share no commit,
        # so there is no base to replay the tree onto and no squash to find.
        return False
    if not base.ok or not base.out:
        return None
    tree = port.git(git_argv("rev-parse", f"{git_rev(name)}^{{tree}}"), cwd=cwd)
    if not tree.ok or not tree.out:
        return None
    base_tree = port.git(git_argv("rev-parse", f"{_first_line(base.out)}^{{tree}}"), cwd=cwd)
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
        git_argv(
            "commit-tree",
            _first_line(tree.out),
            "-p",
            _first_line(base.out),
            "-m",
            "gitclean-probe",
        ),
        cwd=cwd,
    )
    if not synthetic.ok or not synthetic.out:
        return None
    cherry = port.git(git_argv("cherry", base_ref, _first_line(synthetic.out)), cwd=cwd)
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

    Falling through is the same for both, which is what tempts a single answer
    for the two. The report is not: False is git saying the merged head does not
    contain this tip, and None is git never having compared them. Printing the
    first for the second asserts a comparison of two commits as the reason a
    branch was held back, when one of them was not even here to compare."""
    if not pr.head_oid or not head:
        return None
    if pr.head_oid == head:
        return True
    result = port.git(git_argv("merge-base", "--is-ancestor", head, pr.head_oid), cwd=cwd)
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


def _advertised_heads(
    port: CommandPort, cwd: Path | None, remote: str
) -> tuple[set[str] | None, str | None]:
    """Every branch this remote currently advertises, or None and the warning
    when it would not say.

    Asked because everything under `refs/remotes/` is a local cache that a
    fetch refreshes and nothing invalidates. On a forge that deletes a branch
    when its pull request merges -- the common configuration -- that cache
    routinely names refs the server dropped weeks ago, so offering one as a
    target sends a reader after something that is not there.

    The refname is the LAST tab-separated field, which is the same comparison
    the deletion-time probe makes: `ls-remote` prints `<oid>\\t<refname>`, and
    reading the column rather than searching the line is what keeps an
    unrelated `a/feat/x` from answering for `feat/x`.

    Two separate protections, and it is worth not confusing them. The
    terminator the argv constructor applies ends option parsing, which is what
    keeps a branch or remote named like a flag from being read as one. It does
    *not* stop git accepting a path in the repository position -- nothing does.

    What covers that is where `remote` comes from: the decomposition against
    the configured remote list, so the only names reaching here are ones git
    itself listed. It matters because a name that is not a configured remote
    is not rejected -- a sibling directory of that name that happens to be a
    repository is opened instead and answers, well-formed, empty, and about
    somebody else entirely. An empty answer here means every branch is gone."""
    result = port.git(git_argv("ls-remote", "--heads", name=remote), cwd=cwd)
    if not result.ok:
        return None, (
            f"could not ask {remote} which branches it still has (exit {result.returncode}); "
            f"its refs are reported as this repository's remote-tracking refs hold them, which "
            f"may be out of date -- nothing here says any of them is gone"
        )
    return {
        line.split("\t")[-1].strip() for line in result.stdout.splitlines() if line.strip()
    }, None


def _verify_against_remotes(
    port: CommandPort, cwd: Path | None, branches: list[Branch]
) -> tuple[list[Branch], list[NotOffered], list[str]]:
    """The branches with the phantoms taken out, those phantoms, and the
    remotes that would not answer.

    A phantom is a remote-tracking ref whose server no longer advertises the
    branch it names. The deletion path already asks this question before
    spending anything on such a target; asking it during the survey is what
    keeps one from being offered as a target at all, so a reader is never shown
    a branch that is already gone.

    One probe per remote, and only for remotes some candidate ref belongs to.
    That is why this is a pass over the branches rather than a sweep over the
    configured remotes: a remote nobody has refs from -- a server that moved,
    a colleague's fork left in the config -- would otherwise cost a full
    network timeout to learn nothing about.

    A probe that did not answer leaves its branches exactly as they were. Not
    knowing what a server holds is not evidence that it holds nothing, and
    reading it that way would drop every one of that remote's refs out of the
    report on the strength of a connection that failed."""
    advertised: dict[str, set[str] | None] = {}
    kept: list[Branch] = []
    phantoms: list[NotOffered] = []
    warnings: list[str] = []
    for branch in branches:
        remote = branch.remote
        if remote is None:
            # A local branch: no server holds a copy, so there is nobody to ask.
            kept.append(branch)
            continue
        if remote not in advertised:
            heads, warning = _advertised_heads(port, cwd, remote)
            advertised[remote] = heads
            if warning is not None:
                warnings.append(warning)
        heads = advertised[remote]
        if heads is None or f"refs/heads/{branch.ref_name}" in heads:
            kept.append(branch)
            continue
        phantoms.append(
            NotOffered(
                name=branch.name,
                reason=f"{remote} no longer advertises refs/heads/{branch.ref_name}, so there "
                f"is nothing on the server to delete; what is left is {branch.ref}, the "
                f"remote-tracking ref a fetch created here, and `git fetch --prune {remote}` "
                f"is what clears it -- gitclean does not prune refs it did not create",
            )
        )
    return kept, phantoms, warnings


def read_branches(
    port: CommandPort,
    cwd: Path | None,
    *,
    base_ref: str,
    default_branch: str,
    prs: dict[str, PullRequest],
    worktree_by_branch: dict[str, str],
    remotes: tuple[str, ...] | None,
    refspecs: dict[str, tuple[str, ...]] | None,
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
        git_argv("for-each-ref", f"--format={_REF_FORMAT}", "refs/heads", "refs/remotes"), cwd=cwd
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
            # against the refspecs that put refs there. Nothing here reads the
            # short form: it is what git would let you *type*, which is a
            # different question from which remote fetched this.
            split = split_remote_ref(full, remotes, refspecs)
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
        # The trunk is measured like every other branch. Handing it zeroes and a
        # merge verdict is tempting, on the reasoning that probing it against
        # itself is noise, but both halves of that are wrong: the counts are
        # the most useful ones in the report -- `origin/main..main` is the
        # commits on the trunk that have not been pushed -- and asserting a
        # measurement nobody took is the exact habit that makes this tool
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
    # Last, over the branches this loop built: every server ref here was read
    # from a cache, and the servers themselves are the only thing that says
    # which of those refs still exist.
    branches, phantoms, probe_warnings = _verify_against_remotes(port, cwd, branches)
    not_offered.extend(phantoms)
    warnings.extend(probe_warnings)
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
    this is the wrong measurement for it.

    The head is an object id git printed, and it goes in as a plain argument: an
    object id cannot begin with `-`, and `show` spends `--` on a pathspec, so a
    terminator here would ask for a date filtered by a path of that name."""
    if worktree.branch:
        return activity_by_branch.get(worktree.branch)
    if worktree.prunable or not worktree.head:
        return None
    result = port.git(git_argv("show", "-s", "--format=%cI", worktree.head), cwd=cwd)
    return _first_line(result.out) if result.ok else None


def survey(port: CommandPort, *, cwd: Path | None = None) -> Survey | str:
    """Full read pass. Returns the Survey, or a message when cwd is not a repo."""
    resolved = resolve_repo(port, cwd)
    if resolved is None:
        return "not inside a git repository"
    repo_root, common_dir = resolved

    # Read before the trunk is resolved rather than beside the other reads
    # below: which remote's published HEAD gets to name the default branch is
    # decided from this list, so it has to be in hand first. Its warning joins
    # the others further down, where there is a list to put it in.
    remotes, remotes_warning = read_remotes(port, cwd)
    resolved_default, trunk_remote, default_branch_warning = resolve_default_branch(
        port, cwd, remotes
    )
    # The name is still needed downstream to compare against, but it is now
    # known to be a guess -- so it protects nothing it cannot prove, and the
    # flag travels with the survey so the run can report that it is guessing.
    default_branch = resolved_default if resolved_default is not None else "main"
    base_ref, base_ref_warning = resolve_base_ref(port, cwd, default_branch, remotes, trunk_remote)

    head = port.git(git_argv("rev-parse", "--abbrev-ref", "HEAD"), cwd=cwd)
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
    if remotes_warning is not None:
        warnings.append(remotes_warning)
    refspecs, refspecs_warning = read_fetch_refspecs(port, cwd)
    if refspecs_warning is not None:
        warnings.append(refspecs_warning)
    read = read_branches(
        port,
        cwd,
        base_ref=base_ref,
        default_branch=default_branch,
        prs=prs,
        worktree_by_branch=worktree_by_branch,
        remotes=remotes,
        refspecs=refspecs,
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
