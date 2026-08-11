"""The citation lint: does the repo's prose name things that are still here?

Review catches a false sentence in a file someone is editing. It cannot catch a
true sentence that stopped being true, because nobody re-reads a file that is
not changing — which is how a six-week drift left a README, a whole user guide
and two primers confidently describing assets no agent can invoke. That class
accumulates silently and has no reviewer, so it needs a gate.

Two check classes, one pass:

1. **Symbol existence.** A backticked, code-shaped citation resolves — a cited
   repo path is on disk, and a cited Python symbol is bound in the module it is
   claimed to be in. Bound is established by walking the AST, never by grepping
   the name, because a grep matches the symbol's own mention in a comment and so
   confirms a citation using the citation.
2. **Asset existence.** Prose naming a skill, rule, command or agent names one
   that actually deploys. The roster comes from ``content_lint.deployed_asset_names``
   — the admission gate's own verdict over the staged tree — because presence in
   ``src/`` is not deployment, and because two independently derived rosters
   would disagree eventually and nothing would ever compare them.

**Silence is the default, and that is the whole design.** Backticked prose is
mostly not a citation: ``done``, ``queued``, ``--dir``, ``ruff check`` and a
hundred others would trip a check that assumed otherwise, and every false
positive spends a reader's trust until the gate gets switched off. So a token is
only judged when its *shape* makes it a claim about this repository and its
*context* says where the claim resolves. A token that fails either test is
ignored — not allowlisted, ignored, which is why there is no allowlist here to
widen. The cost is real and stated rather than hidden: the checks below miss
whole classes, and each one says which.

**What is out of scope, and why it is not an oversight.** ``spec_lint`` exempts
specs older than a cutoff date because a spec is a point-in-time proposal that is
*supposed* to name things that do not exist yet. The same reasoning reaches
further than ``docs/specs/``: any file whose name carries a ``YYYY-MM-DD`` date
is a record of a moment, and correcting its citations would falsify the record
rather than repair it. Evergreen prose — a README, a guide, a primer, an
orientation file — carries no date precisely because it claims to describe the
present, so it is exactly what this gate reads.

One dated document is read anyway, named in ``ALWAYS_IN_SCOPE``: the
harness-rework charter is amended in place rather than superseded, and the root
``AGENTS.md`` sends every reader to it as the current orientation. A document
that is maintained as the present tense makes claims about the present whatever
its filename says, and ``spec_lint`` carves the same file out of its own date
floor for the same reason.

**Tracker identifiers are not judged, and a check for them has a harder
question to settle first.** A token like ``widget-shop-qq7.30.1`` matches none of
the shapes above and its leading part names nothing in the tree, so it is
excluded several times over rather than by one rule. Existence is the wrong
question to ask of one anyway: prose stating what a closed item decided is worth
keeping, and only an identifier whose item was deleted is a dangling pointer, so
a check that cannot separate the two reports either every historical reference or
none of them, and both are useless. The cost is not in the code, either. This
would be the first check here that does not read the tree — existence lives in a
tracker, one out-of-process call per distinct identifier, in a gate that runs on
every change — and a cited identifier may belong to another project's tracker,
which the local one cannot adjudicate at all. Against all of that, the class does
not accumulate: stale identifiers are rare here, and ordinary editing of the
prose around them removes them. Evidence that they accumulate is what earns the
check.

Inside ``ALWAYS_IN_SCOPE`` the identifiers *are* judged, and the check is a
narrower one that answers none of the questions above. It never asks whether an
item exists, so no tracker is consulted and no out-of-process call is made: it
asks only whether the identifier is in the namespace this repo's own tracker
addresses, and if it is not, whether the sentence says where it does resolve. An
identifier from a retired tracker generation, cited bare in the one document a
reader is told to orient by, sends them to a lookup that returns nothing and
gives them no way to tell that from having looked it up wrong. That is a
dangling pointer on the face of the prose, which is the only kind this gate has
ever claimed to find.
"""

from __future__ import annotations

import ast
import re
import tomllib
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

from installer.core import namespaces
from installer.core.content_tests import BUILD_DIRS
from installer.core.spec_lint import fence_mask

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

# Whole trees this gate does not read, mapped to why. Kept tiny and reasoned: a
# tree here is a scope decision about a body of content, not an exception carved
# for one awkward finding, and the difference is that a scope decision can be
# stated in one sentence that stays true.
#
# An entry naming a directory that is not in the tree is itself a finding
# (``stale_exemptions``), the same retirement condition ``content_lint`` puts on
# ``UNGATED_ROOTS`` and for the same reason: an exemption matching nothing never
# fires, so it fails silent and is found only by someone reading this file.
# The worked example, and it is a past-tense one: ``oss-snapshots/`` held vendored
# third-party skills, whose citations describe their own repositories rather than
# this one — 161 tracked Markdown files that would have reported as staleness in
# somebody else's work. The tree was extracted while this gate was being written,
# the retirement check above fired on the very next run, and the entry came out.
# That is the mechanism working, which is why the account is worth keeping and the
# exemption is not.
EXEMPT_TREES: dict[Path, str] = {
    Path("docs/specs"): (
        "a spec is a point-in-time proposal and is supposed to name what does not exist yet"
    ),
}

# The documents read in spite of the rules above, mapped to nothing because the
# reason is one sentence: this repository maintains the charter as its current
# orientation, so it is present-tense prose wearing a dated name.
#
# An entry naming a file that is not there is itself a finding, the same
# retirement condition ``EXEMPT_TREES`` carries: the charter retires when the
# rework milestone closes, and a carve-out outliving its document would fire on
# nothing while reading as coverage.
ALWAYS_IN_SCOPE: frozenset[Path] = frozenset(
    {Path("docs/specs/2026-07-21-harness-rework-way-forward.md")}
)

# A dated filename declares the file a record of a moment; see the module
# docstring. Matched anywhere in the name rather than only as a prefix, because a
# date leading the name and a date trailing it declare the same thing — anchoring
# to the front would read ``SWEEP-NOTES-2026-08-05.md`` as evergreen prose and
# demand it be corrected into a falsehood. Only the leading form is in the tree
# today; matching anywhere costs nothing and needs no revisit when that changes.
_DATED_BASENAME_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# A trailing ``:12`` or ``:16-22`` on a path is a pointer into the file, not part
# of its name. Stripped before resolution, since otherwise every precise citation
# in the repo reports as a missing path.
_LINE_LOCATOR_RE = re.compile(":\\d+(?:[-\u2013]\\d+)?$")  # hyphen or en-dash range

# ``path/to/file.py::SomeSymbol`` \u2014 the repo's own convention for citing a symbol
# and its file in one span. Split rather than stripped: the symbol half is the
# strongest form of "defined where claimed" there is, since the author has said
# outright which file they mean.
_SYMBOL_LOCATOR_RE = re.compile(r"^(?P<path>[^:]+)::(?P<symbol>[A-Za-z_][A-Za-z0-9_]*)$")

# An inline code span, in the three lengths CommonMark allows here. The capture
# is the raw text between the backticks — what the author wrote, so that a
# finding can quote it back verbatim.
_CODE_SPAN_RE = re.compile(r"(`{1,3})([^`\n]+)\1")

# How this repository asserts that something is not there. Read off the tree, not
# invented — and every alternative measured against it, because the first draft
# of this used bare stems and suppressed 197 citations where 7 were wanted.
#
# **A marker must be a predicate, never a lemma.** ``retire`` alone matched 146
# citations, most of them in prose where retirement is this codebase's *domain
# vocabulary* rather than an announcement: ``RETIRED_CLIS``, "retiring one is not
# automatic", "a retired plugin's recorded root". Those sentences are about the
# machinery of retiring things, and they say nothing about whether the name
# beside them exists. Requiring a copula or an auxiliary — *was* retired, *now*
# archived, *no longer* — is what separates the announcement from the vocabulary.
# The cost of that precision is stated in ``_negates_existence``.
_NONEXISTENCE_RE = re.compile(
    r"\b(?:"
    r"(?:is|are|was|were|been|being|now|already|since|all|both)\s+"
    r"(?:retired|archived|gone|deleted|removed|dropped)"
    r"|no longer"
    r"|there (?:is|are|was|were) no\b"
    r"|(?:does|do|did) not (?:exist|ship|deploy)"
    r"|(?:doesn't|don't|didn't) exist"
    r"|never (?:existed|shipped|deployed)"
    r"|no such\b"
    r"|nothing (?:provides|ships)"
    r"|no implementation"
    r"|not deployed"
    r"|retired to\b"
    r"|used to (?:be|live|drive|exist|call|name)"
    r")",
    re.IGNORECASE,
)

# The second way prose says a thing is not here: it is somewhere else. Retired
# content in this repository was not deleted but moved to a private archive
# repository, and the charter names its companion documents there — so a path
# under that heading is not a claim about this tree at all.
#
# The marker names a *foreign* repository and never the bare noun: "in this
# repository" opens half the orientation prose here, and reading that as an
# elsewhere-claim would silence the tree. An ``owner/name`` slug or "the private
# archive" is what makes it foreign, which is also how the tree already writes
# it.
_ELSEWHERE_RE = re.compile(
    r"\b(?:in|into|from|under|to)\s+(?:the\s+|a\s+|another\s+)?(?:private\s+|public\s+)?"
    r"(?:`?[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+`?|archive)\s+(?:repo|repository)\b",
    re.IGNORECASE,
)

# How prose tells a reader to reach for something. This is what the asset check
# fires on, and narrowing it to this was the correction that made the check
# usable: naming an asset is not what harms a reader, *being told to use one that
# is not there* is. A mention — "this replaced the ``x`` skill", "the ``x`` skill
# handled clustering" — misleads nobody.
#
# Structural like the slash-command and kebab-case rules, not a list of names.
# ``used`` is deliberately absent: "the ``x`` skill used to drive it" is a
# retirement note, and admitting the past tense would read it as an instruction.
_DIRECTIVE_RE = re.compile(
    r"\b(?:run|runs|invoke|invokes|invoking|use|uses|using|read|reads|reading"
    r"|call|calls|apply|applies|follow|follows|consult|consults|see|refer to"
    r"|via|through|per|load|loads|launch|launches|reach for|delegate to"
    r"|hand to|dispatch to|route to|start with)\b",
    re.IGNORECASE,
)

# A sentence ends at terminal punctuation followed by whitespace. Markdown
# structure ends one too: a list item, a table row and a heading each carry an
# independent assertion, and a bullet often has no full stop at all — without
# these, one unterminated bullet would join the next and let a marker in one
# reach a citation in the other.
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")
_STRUCTURE_RE = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|#{1,6}\s|\|)")

# Suffixes that make a slash-free token a filename claim rather than a symbol.
# Deliberately excludes ``.md``: ``AGENTS.md`` and ``SKILL.md`` name a convention
# far more often than they name one file, and a check cannot tell which.
_FILENAME_SUFFIXES = frozenset({".py", ".sh", ".js"})

# Suffixes that make a token with a slash a path claim even when its first
# segment names nothing in the repo — which is how a citation of a *relocated*
# tree is caught at all, since the tree it names is exactly the thing no longer
# on disk.
_PATH_SUFFIXES = frozenset(
    {
        ".md",
        ".py",
        ".sh",
        ".js",
        ".ts",
        ".toml",
        ".json",
        ".jsonc",
        ".yml",
        ".yaml",
        ".txt",
        ".template",
        ".lock",
        ".jsonl",
        ".db",
        ".log",
        ".csv",
        ".cfg",
        ".ini",
        ".html",
        ".css",
    }
)

# Characters that disqualify a token from being any kind of citation: prose,
# shell fragments, placeholders and expressions all carry at least one.
_NOT_A_CITATION = frozenset(" \t\"'<>{}|$*=!?,;&^%@\\\u2026")

# Glob metacharacters, which a path citation may legitimately carry
# (``packages/*/AGENTS.md``). Held out of the path rejection set for that reason,
# and left in the symbol one: a glob in an identifier is not an identifier.
_GLOB_CHARS = frozenset("*?[")
_NOT_A_PATH = _NOT_A_CITATION - _GLOB_CHARS

# The kinds of deployed artifact prose names, mapped to the installer namespace
# each lives in. The four gated classes, and only those: prose also names hooks
# and workflows, but neither is addressed by name the way a skill is.
ASSET_KINDS: dict[str, str] = {kind: kind + "s" for kind in ("skill", "rule", "command", "agent")}

# ``the `x` skill`` and ``the skill `x` `` — both orders, because both are
# written. ``command`` is absent from the second form and constrained in the
# first (see ``_asset_citations``): in English "command" also means a shell
# command, and ``the `gh` command`` is not a claim about this repo's assets.
_ASSET_AFTER_RE = re.compile(r"`([^`\n]+)`\s+(skill|rule|command|agent)s?\b")
_ASSET_BEFORE_RE = re.compile(r"\b(skill|rule|agent)s?\s+`([^`\n]+)`(?![A-Za-z])")

# The third frame, and the one a rename actually strands: this repo's requirement
# marker, as ``writing-skills``' anatomy reference defines it and two skills write
# it — ``REQUIRED SUB-SKILL: Use `x` `` and ``REQUIRED BACKGROUND: You MUST
# understand `x` before using this skill``. Neither is reachable by adjacency, and
# the second shows why no widening of adjacency reaches it: the word "skill" in it
# names the *containing* document, not the thing cited, so the nearest kind word is
# about something else entirely. The marker takes over both jobs the adjacent word
# was doing — it says the span is a skill, and it says to go read it.
#
# **Distance is not the mechanism, and that was measured.** Letting a kind word
# anywhere in its sentence bind to a citation yields 60 candidates over this
# repository and not one is a citation: ``rules``/``skills``/``agents`` listed as
# the gated namespaces, ``scripts`` after "this skill's", ``gh`` after "the fix
# agent", a word already bound to the citation next door. A two-word bound still
# yields eleven, all wrong. The word is this repo's most-used noun; the marker is
# unambiguous, so the marker is the frame.
#
# Shouty, and punctuated. The colon is what separates the marker from the ordinary
# adjective — "a required skill" is prose — and only the two forms the convention
# defines are admitted, because a third would be a guess at prose nobody writes.
_REQUIREMENT_MARKER_RE = re.compile(r"\bREQUIRED (?:SUB-SKILL|BACKGROUND):")

# An asset name as this repo writes them: lowercase kebab-case. Anything else —
# an underscore, a capital, a space — is a code identifier or a config key that
# happened to sit next to the word "rule", which is the noisiest false positive
# the asset check has.
_ASSET_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# A work-item identifier: a lowercase slug, then a dotted path of child numbers
# — ``agents-config-9k9.215.8``, ``wgclw.30``, ``abn9.8.33``. Three narrowings
# keep it from reading every other dotted token in a spec as one, since the
# neighbours it sits beside are versions, releases and dates:
#
# * the dotted tail is numeric and mandatory, so ``pyproject.toml`` and
#   ``installer.core`` are other shapes entirely;
# * the token is lowercase, which is how the tracker mints them and is what
#   separates them from a spec's own ``AC4``/``S2``/``D1`` numbering;
# * the mint — the last hyphen-separated part before the tail — is 3 to 6
#   characters and carries a letter, so ``3.11``, ``0.1.0``, ``2026.07.21`` and
#   ``python3.11`` are all out.
_TRACKER_ID_RE = re.compile(r"^(?P<prefix>[a-z0-9]+(?:-[a-z0-9]+)*)(?:\.\d+)+$")
_MINT_RE = re.compile(r"^(?=.*[a-z])[a-z0-9]{3,6}$")

# Symbol shapes strong enough to be a claim on their own. Each demands structure
# that ordinary prose does not have — a call's parentheses, an underscore, or an
# internal capital — which is what keeps ``done``, ``queued`` and ``blocked`` out.
_CALL_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\(\)$")
_SNAKE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")
_UPPER_SNAKE_RE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$")
_CAMEL_RE = re.compile(r"^(?=.*[a-z])[A-Z][A-Za-z0-9]*[A-Z][A-Za-z0-9]*$")

_DOTTED_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")

# A string literal counts as a referable name when it is identifier-shaped and
# short. The length bound is what keeps docstrings and prose constants out of the
# index; without it the index matches nearly any citation and the check says
# nothing.
_LITERAL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_MAX_LITERAL_LENGTH = 64


@dataclass(frozen=True, slots=True)
class CitationContext:
    """What the sentence around one citation says about it.

    ``directive`` — the clause before it tells a reader to reach for it.
    ``negated`` — the sentence says the thing is not there.
    ``near_miss`` — this sentence does not, but a neighbouring one does. That is
    the most likely honest mistake, and naming it is the difference between a
    finding an author can act on and one they reverse-engineer by rephrasing.
    ``required`` — a requirement marker frames it, so it is a skill citation
    whatever sits beside it. That marker is an instruction on its own, which is why
    ``directive`` is true whenever this is: "You MUST understand ``x``" carries no
    verb the directive set has, and needs none.
    """

    directive: bool
    negated: bool
    near_miss: bool
    required: bool


@dataclass(frozen=True, slots=True)
class Finding:
    """One citation that does not resolve.

    ``citation`` is the author's own text so the finding can be found by search,
    and ``line`` is 1-based so it can be clicked. ``target`` is the repo-relative
    path a path finding resolved to, carried so the CLI can ask git whether that
    path is one it was told to ignore without re-deriving it.
    """

    file: Path
    line: int
    citation: str
    reason: str
    target: str | None = None


def format_finding(finding: Finding) -> str:
    """The human-readable rendering of one finding, for the CLI edge."""
    return f"{finding.file}:{finding.line}: `{finding.citation}` — {finding.reason}"


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def in_scope(relpath: Path) -> bool:
    """Whether a repo-relative path is prose this gate judges."""
    if relpath.suffix != ".md":
        return False
    if relpath in ALWAYS_IN_SCOPE:
        return True
    if any(relpath.is_relative_to(tree) for tree in EXEMPT_TREES):
        return False
    if _DATED_BASENAME_RE.search(relpath.name):
        return False
    return not BUILD_DIRS.intersection(relpath.parts)


def select_markdown(tracked: Iterable[Path]) -> list[Path]:
    """The in-scope subset of ``tracked``, sorted.

    Takes the tracked set rather than walking, because "tracked" is the property
    that matters and only git knows it: an untracked ``graphify-out/`` is a
    stale snapshot by construction and linting it would report the refactor that
    already happened.
    """
    return sorted({path for path in tracked if in_scope(path)})


def stale_exemptions(repo_root: Path) -> list[str]:
    """Scope entries naming content that is not there — an exemption over a
    directory that is gone, or a carve-out over a document that is gone. Both
    fail silent, and both are found only by someone reading this file."""
    return sorted(
        [
            f"{tree}: exempt from doc-lint, but no such directory exists — an exemption "
            "outliving its content is a standing authorisation for whatever lands there next"
            for tree in EXEMPT_TREES
            if not (repo_root / tree).is_dir()
        ]
        + [
            f"{relpath}: carved into doc-lint scope, but no such file exists — a carve-out "
            "outliving its document reads as coverage while checking nothing"
            for relpath in ALWAYS_IN_SCOPE
            if not (repo_root / relpath).is_file()
        ]
    )


# ---------------------------------------------------------------------------
# The Python symbol index
# ---------------------------------------------------------------------------


def referable_names(tree: ast.Module) -> frozenset[str]:
    """Every name a citation could reasonably mean by "it is in this module".

    Deliberately generous, in two directions that both cost coverage and buy
    truthfulness.

    First, depth: classes, functions, assignments, attribute targets and imports
    all count, at any nesting. A reader citing a method, a nested helper or a
    re-exported import is not wrong, and narrowing to module-level definitions
    would turn correct prose into findings.

    Second, and less obviously, **identifier-shaped string literals count too**.
    Half of what this repo's prose cites is not a Python binding at all: event
    names (``item_enqueued``), error codes (``E_NOT_FOUND``), status values
    (``in_progress``), config and column names. Those are real, findable things
    that live in the code as data, and a check that called them missing would
    produce exactly the cry-wolf report that gets a gate switched off. A literal
    qualifies only if it is identifier-shaped and short, which excludes
    docstrings and sentences — the constants that would make this index match
    anything.

    The cost is stated plainly: a symbol that was deleted while its name survived
    in some string still resolves. That is the direction to be wrong in, because
    a gate that is quiet about one stale citation still gets read, and one that
    invents a hundred does not.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            found.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            found.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            found.add(node.attr)
        elif isinstance(node, ast.arg):
            found.add(node.arg)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                found.add(alias.asname or alias.name.partition(".")[0])
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and len(node.value) <= _MAX_LITERAL_LENGTH
            and _LITERAL_NAME_RE.match(node.value)
        ):
            found.add(node.value)
    return frozenset(found)


@dataclass(frozen=True, slots=True)
class RepoIndex:
    """What the repo actually contains, in the shapes prose cites it by.

    ``modules`` is keyed by importable dotted path (``installer.core.spec_lint``)
    and ``packages`` by the dotted path of every directory above one, so a
    citation can be resolved to the longest prefix that is really a module before
    the remainder is checked as an attribute. ``by_stem`` carries the same files
    keyed by final component alone, which is how the abbreviated form prose
    actually uses — ``staging.shared_source_dir``, ``cli._run_project`` — resolves.

    ``tracked`` is every tracked file *and every directory above one*, keyed by
    final component, and it is what lets a path written in *package-internal*
    coordinates resolve. Architecture documents for one subsystem cite
    ``core/run.py`` and ``src/prgroom/lifecycle/``, not the full paths from the
    repo root, and both name real things. Directories are in there because most
    of those citations are directories.
    """

    names: Mapping[Path, frozenset[str]] = field(default_factory=dict)
    modules: Mapping[str, Path] = field(default_factory=dict)
    packages: frozenset[str] = frozenset()
    by_stem: Mapping[str, tuple[Path, ...]] = field(default_factory=dict)
    by_package: Mapping[Path, frozenset[str]] = field(default_factory=dict)
    filenames: Mapping[Path, frozenset[str]] = field(default_factory=dict)
    tracked: Mapping[str, tuple[Path, ...]] = field(default_factory=dict)

    def package_of(self, relpath: Path) -> Path | None:
        """The ``packages/<name>`` root a repo-relative path sits under, if any.

        A markdown file's package is the scope in which a bare symbol citation is
        resolvable at all: ``packages/grind/AGENTS.md`` saying ``conditions()``
        means grind's, and the same token in the root ``AGENTS.md`` means nothing
        a check can pin down.
        """
        for root in self.by_package:
            if relpath.is_relative_to(root):
                return root
        return None

    def resolves_as_suffix(self, target: str) -> bool:
        """Whether some tracked path ends with ``target``.

        The generous half of the path check, and it has to be generous: prose
        addresses a file by however much of its path disambiguates it, which is
        rarely the whole thing. Requiring a component boundary is what keeps
        ``run.py`` from matching ``prerun.py``.
        """
        trimmed = target.strip("/")
        suffix = "/" + trimmed
        return any(
            ("/" + path.as_posix()).endswith(suffix)
            for path in self.tracked.get(Path(trimmed).name, ())
        )

    def matches_glob(self, pattern: str) -> bool:
        """Whether any tracked path satisfies ``pattern``, anchored or not.

        Resolved against the tracked universe rather than the filesystem so that
        a pattern written in package-internal coordinates (``src/prgroom/*``)
        gets the same reading as a plain path in the same coordinates. ``fnmatch``
        lets ``*`` cross a separator, which is looser than a shell's — acceptable
        for a question whose only two answers are "something is there" and
        "nothing is".
        """
        for paths in self.tracked.values():
            for path in paths:
                posix = path.as_posix()
                if fnmatch(posix, pattern) or fnmatch(posix, f"*/{pattern}"):
                    return True
        return False


def _dotted_name(source_root: Path, module: Path) -> str:
    """``installer.core.spec_lint`` for a file under a package's ``src/``."""
    relative = module.relative_to(source_root)
    parts = (
        relative.parts[:-1]
        if relative.name == "__init__.py"
        else (*relative.parts[:-1], relative.stem)
    )
    return ".".join(parts)


def build_index(repo_root: Path, *, tracked: Iterable[Path]) -> RepoIndex:
    """Index the repo's Python under ``packages/``, plus every tracked path.

    ``packages/`` only, for the symbol half. ``src/`` holds Python too, but it is
    shipped skill scripts rather than an importable layout, and prose citing them
    cites their paths — which the path check already answers, without an import
    model that ``src/`` does not have.

    A module that will not parse is indexed with no names, which makes every
    citation into it a finding. That is the right direction to fail: a file the
    repo's own gates cannot parse is a defect, and reporting its citations as
    unresolved is a truthful symptom rather than a wrong answer.

    ``tracked`` comes from the caller because only git knows it, and it is the
    right question to ask: an untracked file is build output or scratch, and
    resolving a citation against one would call a document current on the
    strength of something nobody committed.
    """
    by_path: dict[str, set[Path]] = {}
    for path in tracked:
        for known in (path, *path.parents):
            if known != Path():
                by_path.setdefault(known.name, set()).add(known)
    tracked_index = {name: tuple(sorted(paths)) for name, paths in by_path.items()}

    packages_root = repo_root / "packages"
    if not packages_root.is_dir():
        return RepoIndex(tracked=tracked_index)

    names: dict[Path, frozenset[str]] = {}
    modules: dict[str, Path] = {}
    packages: set[str] = set()
    by_stem: dict[str, list[Path]] = {}
    by_package: dict[Path, set[str]] = {}
    filenames: dict[Path, set[str]] = {}

    for package_dir in sorted(p for p in packages_root.iterdir() if p.is_dir()):
        package_key = package_dir.relative_to(repo_root)
        by_package[package_key] = set()
        filenames[package_key] = set()
        source_root = package_dir / "src"
        for module in sorted(package_dir.rglob("*.py")):
            relative = module.relative_to(repo_root)
            if BUILD_DIRS.intersection(relative.parts):
                continue
            try:
                defined = referable_names(ast.parse(module.read_text(encoding="utf-8")))
            except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
                defined = frozenset()
            names[relative] = defined
            by_package[package_key] |= defined
            filenames[package_key].add(module.name)
            by_stem.setdefault(module.stem, []).append(relative)
            if source_root.is_dir() and module.is_relative_to(source_root):
                dotted = _dotted_name(source_root, module)
                modules[dotted] = relative
                parts = dotted.split(".")
                packages.update(".".join(parts[:i]) for i in range(1, len(parts)))

    return RepoIndex(
        names=names,
        modules=modules,
        packages=frozenset(packages),
        by_stem={stem: tuple(paths) for stem, paths in by_stem.items()},
        by_package={key: frozenset(found) for key, found in by_package.items()},
        filenames={key: frozenset(found) for key, found in filenames.items()},
        tracked=tracked_index,
    )


# ---------------------------------------------------------------------------
# Path citations
# ---------------------------------------------------------------------------


def _path_target(token: str, repo_root: Path) -> str | None:
    """The repo-relative path ``token`` asserts, or ``None`` if it asserts none.

    A token is a path claim when it has a separator, no character that rules it
    out as prose, and either a first segment that is really in the repo or a
    recognised file suffix. The two arms answer different questions and both are
    needed: the first accepts ``packages/**`` and ``.beads/AGENTS.md``, which
    carry no suffix; the second accepts ``archive/docs/audits/rules.md``, whose
    first segment is missing *because the tree was relocated* — the very case
    worth catching, and the one a first-segment test can never see.

    A trailing ``:12`` or ``:16-22`` is a pointer into the file rather than part
    of its name, and comes off before anything else — otherwise the most precise
    citations in the repo are the ones that report as missing.

    Five rejections carry the weight:

    - a leading ``~`` or ``/`` is deploy-space or absolute, and a leading ``..``
      leaves the checkout; none of the three is a claim about this tree;
    - a ``://`` is a URL;
    - a first segment of ``.git`` is git's own storage, not content — and in a
      worktree it is a *file*, so judging it would make the gate's answer depend
      on which checkout it ran from;
    - a first segment that is an installer *namespace* name (``skills/``,
      ``rules/``, …) is deploy-space too. A primer writing
      ``skills/<name>/SKILL.md`` is describing the shape of an install, not a
      path here, and there is no such directory at this repo's root to confuse
      it with.
    """
    target = _LINE_LOCATOR_RE.sub("", token)
    if "/" not in target or _NOT_A_PATH.intersection(target):
        return None
    if target.startswith(("~", "/", "#", "-", "..")) or "://" in target:
        return None
    head = target.split("/", 1)[0]
    if head in namespaces.ALL or head == ".git":
        return None
    if not ((repo_root / head).exists() or Path(target).suffix in _PATH_SUFFIXES):
        return None
    return target


def _path_exists(target: str, repo_root: Path, index: RepoIndex) -> bool:
    """Whether ``target`` is in the tree.

    Three ways to be there, in increasing generosity. On disk literally, which is
    also the only arm a directory or an untracked-but-real artifact can satisfy.
    By glob, because ``packages/*/AGENTS.md`` claims a *shape* is populated — one
    match makes it true and zero is what makes it stale. Or as the tail of some
    tracked path, because prose addresses a file by however much of its path
    disambiguates it: an architecture document for one subsystem writes
    ``core/run.py``, and it is not wrong.
    """
    if _GLOB_CHARS.intersection(target):
        pattern = target.rstrip("/")
        try:
            return any(repo_root.glob(pattern)) or index.matches_glob(pattern)
        except (NotImplementedError, ValueError):
            return True
    if (repo_root / target).exists() or index.resolves_as_suffix(target):
        return True
    # An extensionless tail is usually a module written in path form —
    # ``src/prgroom/proc`` for ``proc.py``. Tried last so a real directory of that
    # name always wins, and only when nothing else resolved.
    return not Path(target).suffix and index.resolves_as_suffix(f"{target}.py")


# ---------------------------------------------------------------------------
# Symbol citations
# ---------------------------------------------------------------------------


def _is_symbol_shaped(token: str) -> str | None:
    """The identifier ``token`` cites, or ``None`` if its shape is not a claim.

    Four shapes qualify, and each demands structure ordinary English lacks: a
    call's ``()``, a snake_case or SCREAMING_SNAKE underscore, or a CamelCase
    internal capital. This is where ``done``, ``queued``, ``blocked``, ``work``
    and ``bd`` are turned away — not by naming them, but by their having no shape
    to distinguish them from the words they are.
    """
    call = _CALL_RE.match(token)
    if call is not None:
        return call.group(1)
    if _SNAKE_RE.match(token) or _UPPER_SNAKE_RE.match(token) or _CAMEL_RE.match(token):
        return token
    return None


def _module_for(dotted: str, index: RepoIndex, scope: Path | None) -> tuple[Path, str] | None:
    """The module a dotted citation's leading part names, and the remainder.

    Resolution is longest-prefix-first over the real import layout, so
    ``installer.core.spec_lint.lint_specs`` resolves to the module and leaves
    ``lint_specs`` to be checked as an attribute.

    Prose also uses an abbreviated form — ``staging.shared_source_dir`` — and
    that one resolves by module stem, but **only inside a package**. Outside one
    the stem is not evidence of anything: ``sync.remote`` in a primer about git
    hooks is a git config key, and a repo-wide stem lookup happily matched it to
    the installer's ``sync.py`` and reported a git setting as a missing symbol.
    A stem citation with no package around it is silence.
    """
    parts = dotted.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:cut])
        module = index.modules.get(prefix)
        if module is not None:
            return module, parts[cut]
        if prefix in index.packages:
            # A real package directory, and the next component is neither a
            # submodule nor a package under it — nothing left to resolve into.
            return None
    if scope is None:
        return None
    candidates = tuple(
        path for path in index.by_stem.get(parts[0], ()) if path.is_relative_to(scope)
    )
    if len(candidates) == 1:
        return candidates[0], parts[1]
    return None


def _dotted_finding(token: str, index: RepoIndex, scope: Path | None) -> str | None:
    """Why a dotted citation does not resolve, or ``None``.

    A token whose root the repo does not know is silence, not a finding: it is
    far more likely to be a third-party module (``yaml.safe_load``,
    ``subprocess.run``) than a stale citation, and a check that cannot tell the
    two apart must not guess.
    """
    if token in index.modules or token in index.packages:
        return None
    resolved = _module_for(token, index, scope)
    if resolved is None:
        return None
    module, attribute = resolved
    if attribute in index.names.get(module, frozenset()):
        return None
    return f"{module} defines no `{attribute}`"


def _line_module(line: str, repo_root: Path, index: RepoIndex) -> Path | None:
    """The single Python file this line cites, if it cites exactly one.

    This is what makes "defined where claimed" checkable at all when the symbol
    and its file are two separate code spans in one sentence — the shape the
    repo's prose actually uses (``CLI_PACKAGES`` in ``.../core/clis.py``). Two
    cited files means the sentence is about a relationship rather than a
    location, so the pairing is dropped rather than guessed at.
    """
    cited = [
        Path(target)
        for _column, token in _code_spans(line)
        if (target := _path_target(token, repo_root)) is not None
        and target.endswith(".py")
        and Path(target) in index.names
    ]
    return cited[0] if len(cited) == 1 else None


# ---------------------------------------------------------------------------
# Asset citations
# ---------------------------------------------------------------------------


def _foreign_identifier(token: str, tracker_prefix: str) -> bool:
    """Whether ``token`` is a work-item identifier no local ``work`` can address.

    Local means minted under this repository's own namespace, prefix and all.
    Anything else — an identifier from the tracker generation this repo archived,
    or from another project's tracker entirely — resolves somewhere a reader
    here cannot reach by the route they are told to use.
    """
    match = _TRACKER_ID_RE.match(token)
    if match is None:
        return False
    prefix = match.group("prefix")
    if _MINT_RE.match(prefix.rsplit("-", 1)[-1]) is None:
        return False
    return prefix != tracker_prefix and not prefix.startswith(f"{tracker_prefix}-")


def _asset_name(token: str) -> str | None:
    """The asset name a code span carries, normalised, or ``None``.

    Prose names an asset several ways — bare, as a slash command, as a path to
    its entry file, plugin-qualified — and they all denote the same roster entry,
    so they are normalised to it. The kebab-case test at the end is the filter
    that matters: it turns away ``pull_request``, ``required_status_checks`` and
    ``should_install_namespace``, all of which are real code or config sitting
    next to the word "rule".
    """
    name = token.strip().strip("/")
    name = name.removesuffix("/SKILL.md").removesuffix(".md")
    name = name.rpartition(":")[2] if ":" in name else name
    return name if _ASSET_NAME_RE.match(name) else None


def _asset_citations(line: str, marked: frozenset[str]) -> list[tuple[str, str, str, str]]:
    """``(kind, namespace, name, token)`` for every asset this line names.

    ``command`` is accepted only in its slash form. Unqualified, the word means a
    shell command far more often than a deployed one — ``the `gh` command``,
    ``the `bd` commands``, ``the `status` command`` — and admitting it would make
    this the noisiest check in the module rather than one of the sharpest.

    ``marked`` holds the spans on this line that a requirement marker frames, and
    they are skills: both marker forms the convention defines cite one. The set
    arrives from the caller rather than being read off the line here because a
    marker leads a paragraph and Markdown wraps it, so the marker and the name it
    requires need not share a line — only a sentence, which is what
    ``citation_contexts`` walks. A span an adjacent word already claimed is not
    claimed a second time: ``REQUIRED SUB-SKILL: Use the `x` skill`` names one
    thing and earns one finding.

    The author's raw ``token`` rides along because the same span can be read two
    ways: ``the `writing-skills/SKILL.md` skill`` is path-shaped *and* an asset
    name, and without knowing the asset check claimed it, the path check would
    report the entry file as a missing path on top.
    """
    found: list[tuple[str, str, str, str]] = []
    for match in _ASSET_AFTER_RE.finditer(line):
        token, kind = match.group(1), match.group(2)
        if kind == "command" and not token.startswith("/"):
            continue
        name = _asset_name(token)
        if name is not None:
            found.append((kind, ASSET_KINDS[kind], name, token))
    for match in _ASSET_BEFORE_RE.finditer(line):
        kind, token = match.group(1), match.group(2)
        name = _asset_name(token)
        if name is not None:
            found.append((kind, ASSET_KINDS[kind], name, token))
    claimed = {token for _kind, _namespace, _name, token in found}
    # Walked in the line's own order, not the set's, so the report is the same on
    # every run over the same file.
    for _column, token in _code_spans(line):
        if token not in marked or token in claimed:
            continue
        claimed.add(token)
        name = _asset_name(token)
        if name is not None:
            found.append(("skill", ASSET_KINDS["skill"], name, token))
    return found


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------


def _code_spans(line: str) -> list[tuple[int, str]]:
    """``(column, text)`` for every inline code span on one line."""
    return [(m.start(), m.group(2)) for m in _CODE_SPAN_RE.finditer(line)]


def _negates_existence(sentence: str) -> bool:
    """Whether ``sentence`` asserts that something is not there — either gone, or
    resolving in a named foreign repository, which is not-here in the sense that
    decides whether a citation is a claim about this tree.

    Three families are deliberately **absent** from the marker set, each because
    the tree contains a counter-example:

    - ``replaces``/``superseded``. ``docs/architecture/installer/index.md`` says
      the installer package "replaces the 1788-line ``scripts/install.sh``" —
      and that script is still on disk, still the entry point. Supersession is a
      claim about lineage, not about existence, so admitting it would silence
      live citations to buy two findings.
    - ``removed``/``deleted`` in the present tense. ``prgroom``'s design says a
      label "persists … rather than being removed", which is a *negated*
      removal; the past-tense forms are in the set, the bare verb is not.
    - ``nothing reads``/``nothing enforces``. Those say a thing is unused, which
      is the opposite of saying it is absent — the root ``AGENTS.md`` uses one
      about ``project-config.toml``, a file that is very much there.
    """
    return (
        _NONEXISTENCE_RE.search(sentence) is not None or _ELSEWHERE_RE.search(sentence) is not None
    )


def _directive_before(sentence: str, position: int) -> bool:
    """Whether the clause up to ``position`` tells a reader to reach for it.

    Position matters and is the whole point: "Run the ``x`` skill" is an
    instruction, while "the ``x`` skill runs nightly" is a description that
    happens to contain the same verb. Only what precedes the citation counts.
    """
    return _DIRECTIVE_RE.search(sentence[:position]) is not None


def _sentences(lines: Sequence[str], fenced: Sequence[bool]) -> list[list[tuple[str, list[int]]]]:
    """The prose as blocks of sentences, each paired with the lines it spans.

    Markdown hard-wraps, so a sentence is not a line: ``packages/prgroom/AGENTS.md``
    names a skill on one line and says it is archived on the next, and a
    line-scoped rule cannot see the two together. A block is joined across its
    wrapped lines and then split, which is why the pairing is a *list* of lines.

    Blocks end at a blank line, a fence, or a structural marker, so a citation
    and a marker are only ever read together when they sit in one assertion.
    Grouping by block rather than returning one flat list is what lets a finding
    look at its sentence's *neighbours* — the near-miss an author is most likely
    to hit, where the name is in one sentence and its retirement in the next.
    """
    out: list[list[tuple[str, list[int]]]] = []
    block: list[tuple[int, str]] = []

    def flush() -> None:
        if not block:
            return
        sentences: list[tuple[str, list[int]]] = []
        # Offsets of each line's first character within the joined block, so a
        # sentence's span can be mapped back to the lines it came from.
        joined = " ".join(text for _number, text in block)
        starts: list[int] = []
        cursor = 0
        for _number, text in block:
            starts.append(cursor)
            cursor += len(text) + 1

        position = 0
        for sentence in _SENTENCE_END_RE.split(joined):
            begin = joined.find(sentence, position)
            if begin < 0:  # pragma: no cover - split output always occurs in order
                begin = position
            end = begin + len(sentence)
            covered = [
                number
                for index, (number, text) in enumerate(block)
                if starts[index] < end and starts[index] + len(text) > begin
            ]
            sentences.append((sentence, covered))
            position = end
        out.append(sentences)
        block.clear()

    for index, line in enumerate(lines, start=1):
        if fenced[index - 1] or not line.strip() or _STRUCTURE_RE.match(line):
            flush()
            if fenced[index - 1] or not line.strip():
                continue
        block.append((index, line))
    flush()
    return out


def suppressed_citations(lines: Sequence[str], fenced: Sequence[bool]) -> set[tuple[int, str]]:
    """``(line, span text)`` for every citation inside a non-existence claim.

    Prose that names a thing in order to say the thing is gone must not be
    reported as prose naming a thing that is gone. That sentence is the *correct*
    remediation for stale documentation — "the ``merge-guard`` skill has been
    retired" is what a reader arriving from an older install needs — and the only
    ways to silence a check that flags it are to un-backtick the name or delete
    the sentence. Both are worse prose, which is how a gate gets worked around.

    **The whole sentence is suppressed, not the negated name.** Deciding which
    name a clause negates needs a parser this does not have, so a sentence that
    both retires one thing and cites another silences both. The cost is real and
    one-directional: it can hide a finding, never invent one. The way to trip
    over it by accident is to write "the ``old`` skill was retired; use ``new``
    instead" in one sentence — if ``new`` is *also* missing, nothing reports it.
    Two sentences, and both are judged.
    """
    return {key for key, context in citation_contexts(lines, fenced).items() if context.negated}


def citation_contexts(
    lines: Sequence[str], fenced: Sequence[bool]
) -> dict[tuple[int, str], CitationContext]:
    """What the prose around each citation says about it.

    One traversal answering both questions the checks ask — is this sentence
    telling me to use the thing, and does it say the thing is gone — so the two
    can never be computed from different readings of the same paragraph.

    Keyed by ``(line, span text)``. A token repeated on one line in two different
    sentences collapses to one entry; the first sentence's reading wins. Rare
    enough to be worth the simple key, and the direction it errs in depends on
    which sentence came first, so it is recorded here rather than relied upon.
    """
    contexts: dict[tuple[int, str], CitationContext] = {}
    for block in _sentences(lines, fenced):
        negations = [_negates_existence(sentence) for sentence, _covered in block]
        for index, (sentence, covered) in enumerate(block):
            neighbours = negations[max(index - 1, 0) : index + 2]
            for number in covered:
                for _column, token in _code_spans(lines[number - 1]):
                    quoted = f"`{token}`"
                    position = sentence.find(quoted)
                    if position < 0:
                        continue
                    required = _REQUIREMENT_MARKER_RE.search(sentence[:position]) is not None
                    contexts.setdefault(
                        (number, token),
                        CitationContext(
                            directive=required or _directive_before(sentence, position),
                            negated=negations[index],
                            near_miss=not negations[index] and any(neighbours),
                            required=required,
                        ),
                    )
    return contexts


# A citation no sentence claimed — inside a table cell the block walk split
# differently, say. Neither directive nor negated, so the asset check stays quiet
# and the path and symbol checks stay live, which is the conservative reading.
_NO_CONTEXT = CitationContext(directive=False, negated=False, near_miss=False, required=False)


def _asset_reason(kind: str, context: CitationContext) -> str:
    """What the author has to do about it, not just what is wrong.

    A gate that knows what it wants and will not say gets reverse-engineered by
    trial and error — write correct English, get flagged, guess, rephrase, get
    flagged again. That is how a gate ends up deleted, so the finding carries its
    own remedy. The near-miss wording is separate because it is the most likely
    honest mistake and it has a different fix: the words are already there, one
    sentence too far away.
    """
    if context.near_miss:
        # Careful with this wording: the neighbouring retirement may be about a
        # *different* name — that is exactly the live case in
        # ``installer-design.md``, where the retired thing is the agent and the
        # flagged thing is a harness built-in. So the message points at the
        # near-miss without asserting the neighbour is about this name.
        return (
            f"tells a reader to use a {kind} that nothing provides — a neighbouring "
            "sentence carries a retirement clause and this check reads one sentence at "
            "a time, so if this one is gone too, say so in this sentence"
        )
    return (
        f"tells a reader to use a {kind} that nothing provides — if it is gone, say so "
        "in this sentence and the mention stops being a finding; if it is not, the "
        "artifact is missing from src/"
    )


def lint_markdown_text(
    relpath: Path,
    text: str,
    *,
    repo_root: Path,
    assets: Mapping[str, frozenset[str]],
    index: RepoIndex,
    tracker_prefix: str | None = None,
) -> list[Finding]:
    """Both checks over one file's text. Pure: nothing is read from disk for
    ``relpath`` itself, so a caller can drive this from fixtures.

    ``tracker_prefix`` is this repository's work-item namespace; without it, or
    outside ``ALWAYS_IN_SCOPE``, identifiers are not judged at all."""
    scope = index.package_of(relpath)
    judged_namespace = tracker_prefix if relpath in ALWAYS_IN_SCOPE else None
    # Prose under ``src/`` deploys into *other* people's projects, where a path
    # from this repo's root resolves to nothing — which is why this repo forbids
    # citing one there in the first place. Every path-shaped span in that tree is
    # therefore an illustration (``references/aws.md``, ``evals/evals.json``), and
    # checking them reported a dozen examples as defects. The asset check still
    # runs there, because a deployed skill naming a skill is a real claim.
    check_paths = not relpath.is_relative_to("src")
    findings: list[Finding] = []
    lines = text.splitlines()
    mask = fence_mask(lines)
    contexts = citation_contexts(lines, mask)
    for number, (line, fenced) in enumerate(zip(lines, mask, strict=True), start=1):
        if fenced:
            continue

        marked = frozenset(
            token
            for _column, token in _code_spans(line)
            if contexts.get((number, token), _NO_CONTEXT).required
        )
        claimed: set[str] = set()
        for kind, namespace, name, token in _asset_citations(line, marked):
            claimed.add(token)
            context = contexts.get((number, token), _NO_CONTEXT)
            # Only an instruction to reach for the asset. A mention misleads
            # nobody — and the mention is what a retirement note is made of, so
            # firing on it made the check fire on its own remedy.
            if context.negated or not context.directive:
                continue
            if name not in assets.get(namespace, frozenset()):
                findings.append(
                    Finding(
                        file=relpath,
                        line=number,
                        citation=name,
                        reason=_asset_reason(kind, context),
                    )
                )

        module = _line_module(line, repo_root, index)
        for _column, token in _code_spans(line):
            if token in claimed or contexts.get((number, token), _NO_CONTEXT).negated:
                continue
            if judged_namespace is not None and _foreign_identifier(token, judged_namespace):
                findings.append(
                    Finding(
                        file=relpath,
                        line=number,
                        citation=token,
                        reason=(
                            f"names a work item outside this repo's `{judged_namespace}` tracker "
                            "namespace — a reader is told to resolve it with `work` and "
                            "cannot; say in this sentence where it does resolve"
                        ),
                    )
                )
                continue
            located = _SYMBOL_LOCATOR_RE.match(token)
            if located is not None:
                findings.extend(
                    _located_findings(located, token, relpath, number, repo_root, index)
                )
                continue
            target = _path_target(token, repo_root)
            if target is not None:
                if check_paths and not _path_exists(target, repo_root, index):
                    findings.append(
                        Finding(
                            file=relpath,
                            line=number,
                            citation=token,
                            reason="path does not exist",
                            target=target,
                        )
                    )
                continue
            if _NOT_A_CITATION.intersection(token) or _GLOB_CHARS.intersection(token):
                continue
            if _DOTTED_RE.match(token):
                # A recognised file suffix settles what the dots mean before the
                # import layout gets a chance to guess: ``installer.toml`` is a
                # filename, and reading it as a module attribute reported the
                # repo's own config file as a missing symbol.
                suffix = Path(token).suffix
                if suffix in _FILENAME_SUFFIXES:
                    findings.extend(_filename_findings(token, relpath, number, index, scope))
                    continue
                if suffix in _PATH_SUFFIXES:
                    continue
                reason = _dotted_finding(token, index, scope)
                if reason is not None:
                    findings.append(
                        Finding(file=relpath, line=number, citation=token, reason=reason)
                    )
                continue
            symbol = _is_symbol_shaped(token)
            if symbol is not None:
                findings.extend(
                    _symbol_findings(symbol, token, relpath, number, index, module, scope)
                )
    return findings


def _located_findings(
    located: re.Match[str],
    token: str,
    relpath: Path,
    number: int,
    repo_root: Path,
    index: RepoIndex,
) -> list[Finding]:
    """A ``path/to/file.py::Symbol`` citation, checked in both halves.

    The strongest citation the repo writes and therefore the one worth resolving
    exactly: the author has named the file, so "defined where claimed" is a
    question with a single answer. A path that does not resolve is reported as a
    path; a path that does, with a symbol that is not in it, is reported as the
    symbol. Neither half is skipped because the other failed.
    """
    path, symbol = located.group("path"), located.group("symbol")
    target = _path_target(path, repo_root)
    if target is None:
        return []
    if not _path_exists(target, repo_root, index):
        return [Finding(file=relpath, line=number, citation=token, reason="path does not exist")]
    module = next(
        (
            known
            for known in index.tracked.get(Path(target).name, ())
            if ("/" + known.as_posix()).endswith("/" + target.strip("/")) and known in index.names
        ),
        None,
    )
    if module is None or symbol in index.names.get(module, frozenset()):
        return []
    return [
        Finding(file=relpath, line=number, citation=token, reason=f"{module} defines no `{symbol}`")
    ]


def _filename_findings(
    token: str, relpath: Path, number: int, index: RepoIndex, scope: Path | None
) -> list[Finding]:
    """A bare ``foo.py`` citation, resolved within the citing file's package.

    Only within a package: repo-wide, a bare filename is ambiguous by
    construction, and the citation carries no evidence of which one was meant.
    """
    if scope is None or token in index.filenames.get(scope, frozenset()):
        return []
    return [
        Finding(file=relpath, line=number, citation=token, reason=f"no such file under {scope}")
    ]


def _symbol_findings(
    symbol: str,
    token: str,
    relpath: Path,
    number: int,
    index: RepoIndex,
    module: Path | None,
    scope: Path | None,
) -> list[Finding]:
    """A bare identifier, resolved against the strongest context available.

    A file named in the same sentence is the strongest, and it is the only
    context in which "defined *where claimed*" is a question with an answer. With
    no such file, the citing document's own package is the fallback scope; with
    neither — the root ``AGENTS.md``, a guide, a primer — the token is left
    alone, because a bare identifier in repo-wide prose could be about anything
    and a check that resolved it against everything would resolve it against
    nothing.

    An identifier the citing package does not define but another one does is not
    a finding either. Package orientation files legitimately point across the
    boundary — ``packages/gitclean/AGENTS.md`` names ``CLI_PACKAGES``, which is
    the installer's — and reporting those would punish exactly the cross-reference
    that keeps the packages coherent.
    """
    if module is not None:
        if symbol in index.names.get(module, frozenset()):
            return []
        return [
            Finding(
                file=relpath, line=number, citation=token, reason=f"{module} defines no `{symbol}`"
            )
        ]
    if scope is None or symbol in index.by_package.get(scope, frozenset()):
        return []
    if any(symbol in defined for defined in index.by_package.values()):
        return []
    return [
        Finding(
            file=relpath, line=number, citation=token, reason=f"nothing under {scope} defines it"
        )
    ]


def project_asset_names(repo_root: Path) -> dict[str, frozenset[str]]:
    """Assets this repository keeps for its own use, under ``.claude/``.

    A second *location*, not a second derivation of the deployed roster: the
    admission gate judges what ``src/`` ships to other projects and says nothing
    about what this repo installs for itself. Both are real, and prose naming
    either is right — the ``admit-request`` gate lives here and is named in the
    root orientation file, which the deployed roster alone would call missing.
    """
    found: dict[str, frozenset[str]] = {}
    for namespace in ASSET_KINDS.values():
        directory = repo_root / ".claude" / namespace
        if not directory.is_dir():
            continue
        found[namespace] = frozenset(
            child.stem if child.suffix == ".md" else child.name
            for child in directory.iterdir()
            if child.is_dir() or child.suffix == ".md"
        )
    return found


def project_tracker_prefix(repo_root: Path) -> str | None:
    """The namespace this repository's own work items are minted under, read off
    ``project-config.toml``'s project name, or ``None`` when there is nothing to
    read it from.

    Derived rather than written down here, because a gate carrying its own copy
    of the project's name is one rename away from judging every local identifier
    foreign. ``None`` is a working answer and not a failure: without a namespace
    the check cannot tell local from foreign, so it does not run — the same
    silence every other rule here defaults to.
    """
    path = repo_root / "project-config.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    project = data.get("project")
    if not isinstance(project, dict):
        return None
    name = project.get("name")
    return name if isinstance(name, str) and name else None


def merge_rosters(*rosters: Mapping[str, frozenset[str]]) -> dict[str, frozenset[str]]:
    """Union asset rosters per namespace."""
    merged: dict[str, frozenset[str]] = {}
    for roster in rosters:
        for namespace, names in roster.items():
            merged[namespace] = merged.get(namespace, frozenset()) | names
    return merged


def count_suppressed(text: str) -> int:
    """How many citations in ``text`` a non-existence claim silenced.

    Reported on every run. A silencing rule that leaves no trace is a rule
    nobody can audit, and this one can hide a real finding — so its reach is a
    number on the output rather than something you learn by reading the source.
    """
    lines = text.splitlines()
    return len(suppressed_citations(lines, fence_mask(lines)))


def lint_markdown(
    paths: Sequence[Path],
    *,
    repo_root: Path,
    assets: Mapping[str, frozenset[str]],
    index: RepoIndex,
    tracker_prefix: str | None = None,
) -> tuple[list[Finding], int]:
    """Lint every path in ``paths``, which must be repo-relative and in scope.

    Returns the findings and the number of citations suppressed across the whole
    fileset. An unreadable file is a finding rather than an exception: the run
    reports on the whole fileset or it reports nothing anyone can act on.
    """
    findings: list[Finding] = []
    suppressed = 0
    for relpath in paths:
        try:
            text = (repo_root / relpath).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            findings.append(
                Finding(file=relpath, line=1, citation=str(relpath), reason=f"unreadable: {exc}")
            )
            continue
        suppressed += count_suppressed(text)
        findings.extend(
            lint_markdown_text(
                relpath,
                text,
                repo_root=repo_root,
                assets=assets,
                index=index,
                tracker_prefix=tracker_prefix,
            )
        )
    return findings, suppressed
