"""The citation lint over fixture trees.

Pins the decisions that decide whether this gate is usable at all. Half of these
tests are negative: what the check refuses to report is as much its contract as
what it reports, because a gate that flags ``done`` and ``queued`` in ordinary
prose gets switched off and then catches nothing.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.doc_lint import (
    ALWAYS_IN_SCOPE,
    EXEMPT_TREES,
    Finding,
    RepoIndex,
    build_index,
    count_suppressed,
    format_finding,
    in_scope,
    lint_markdown,
    lint_markdown_text,
    merge_rosters,
    project_asset_names,
    project_tracker_prefix,
    select_markdown,
    stale_exemptions,
)

_ASSETS: dict[str, frozenset[str]] = {
    "skills": frozenset({"grilling", "writing-skills"}),
    "rules": frozenset({"delegation"}),
    "commands": frozenset({"clean-up-git"}),
    "agents": frozenset(),
}


def _index(tmp_path: Path, tracked: list[str] | None = None) -> RepoIndex:
    return build_index(tmp_path, tracked=[Path(entry) for entry in tracked or []])


def _lint(
    tmp_path: Path,
    text: str,
    *,
    relpath: str = "README.md",
    tracked: list[str] | None = None,
    assets: dict[str, frozenset[str]] | None = None,
    tracker_prefix: str | None = None,
) -> list[Finding]:
    return lint_markdown_text(
        Path(relpath),
        text,
        repo_root=tmp_path,
        assets=_ASSETS if assets is None else assets,
        index=_index(tmp_path, tracked),
        tracker_prefix=tracker_prefix,
    )


def _write(root: Path, relpath: str, text: str = "x\n") -> Path:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Scope
# --------------------------------------------------------------------------


def test_dated_specs_are_out_of_scope() -> None:
    """A spec is a point-in-time proposal, so naming what does not exist yet is
    correct there — the same reason ``spec_lint`` carries a date cutoff."""
    assert in_scope(Path("docs/guide/configuration.md"))
    assert not in_scope(Path("docs/specs/2026-07-21-harness-rework.md"))
    assert not in_scope(Path("docs/specs/undated-note.md"))


def test_specs_are_dropped_from_the_fileset() -> None:
    """The exclusion holds at selection, not only as a predicate: the gate never
    opens a spec, so no future check can accidentally read one."""
    selected = select_markdown(
        [
            Path("README.md"),
            Path("docs/specs/2026-07-21-charter.md"),
            Path("docs/specs/appendix.md"),
        ]
    )
    assert selected == [Path("README.md")]


def test_a_dated_name_is_out_of_scope_wherever_the_date_sits() -> None:
    """A date leading the name and a date trailing it mean the same thing — a
    record of a moment — so a rule that saw only the prefix form would read the
    other as evergreen prose and demand it be corrected into a falsehood."""
    assert not in_scope(Path("docs/plans/2026-06-07-prgroom-impl.md"))
    assert not in_scope(Path("SWEEP-NOTES-2026-08-05.md"))
    assert in_scope(Path("CONTRIBUTING.md"))


def test_an_exempt_tree_and_non_markdown_files_are_out_of_scope() -> None:
    assert not in_scope(Path("docs/specs/anything.md"))
    assert not in_scope(Path("README.rst"))
    assert not in_scope(Path("src/user/.agents/skills/x/node_modules/dep/README.md"))


def test_an_exemption_with_no_content_behind_it_is_reported(tmp_path: Path) -> None:
    """An exemption matching nothing never fires, so it fails silent — the same
    retirement condition ``content_lint`` puts on its own register. It has already
    earned its keep: ``oss-snapshots/`` was extracted while this gate was being
    written, and this is what noticed."""
    for relpath in ALWAYS_IN_SCOPE:
        _write(tmp_path, str(relpath))
    assert stale_exemptions(tmp_path) == []

    for relpath in ALWAYS_IN_SCOPE:
        (tmp_path / relpath).unlink()
    (tmp_path / "docs" / "specs").rmdir()
    stale = stale_exemptions(tmp_path)
    assert any("docs/specs: exempt from doc-lint" in message for message in stale)


def test_every_exemption_states_a_reason() -> None:
    assert all(reason.strip() for reason in EXEMPT_TREES.values())


def test_the_charter_is_read_despite_the_exemptions_that_cover_it() -> None:
    """The one document the date rule and the specs exemption both cover and
    neither should: it is amended in place and the root ``AGENTS.md`` sends every
    reader to it as current orientation, so its citations are claims about the
    present. ``spec_lint`` carves the same file out of its own date floor."""
    charter = Path("docs/specs/2026-07-21-harness-rework-way-forward.md")
    assert charter in ALWAYS_IN_SCOPE
    assert in_scope(charter)
    assert not in_scope(Path("docs/specs/2026-07-22-workcli-completion-s2.md"))


def test_the_charter_reaches_a_lint_run_through_selection(tmp_path: Path) -> None:
    """Membership in the carve-out is not coverage. What matters is that the
    charter survives the selection the CLI actually performs and gets read: a
    regression anywhere on tracked-set → ``select_markdown`` → ``lint_markdown``
    would leave the scope predicate telling the truth and the document unread.
    """
    charter = next(iter(ALWAYS_IN_SCOPE))
    _write(tmp_path, "README.md", "Nothing to see.\n")
    _write(tmp_path, str(charter), "The runtime is `wgclw.30`, and see `docs/gone.md`.\n")

    paths = select_markdown([Path("README.md"), charter])
    assert charter in paths

    findings, _suppressed = lint_markdown(
        paths,
        repo_root=tmp_path,
        assets=_ASSETS,
        index=_index(tmp_path),
        tracker_prefix="widget-shop",
    )
    assert sorted(f.citation for f in findings if f.file == charter) == [
        "docs/gone.md",
        "wgclw.30",
    ]


def test_a_carve_out_with_no_document_behind_it_is_reported(tmp_path: Path) -> None:
    """A carve-out naming a file that is not there fires on nothing, so it fails
    silent — the retirement condition every exemption here carries. The charter
    retires at AC9, and this is what will notice."""
    for relpath in ALWAYS_IN_SCOPE:
        _write(tmp_path, str(relpath))
    (tmp_path / "docs" / "specs").mkdir(parents=True, exist_ok=True)
    assert stale_exemptions(tmp_path) == []

    for relpath in ALWAYS_IN_SCOPE:
        (tmp_path / relpath).unlink()
    stale = stale_exemptions(tmp_path)
    assert len(stale) == len(ALWAYS_IN_SCOPE)
    assert "harness-rework-way-forward" in stale[0]


# --------------------------------------------------------------------------
# The false-positive guard
# --------------------------------------------------------------------------


def test_ordinary_backticked_prose_is_never_a_finding(tmp_path: Path) -> None:
    """The contract that decides whether the gate survives contact with the repo.

    None of these spans is a citation, and every one of them would trip a check
    that judged a token because it happened to be in backticks.
    """
    text = (
        "A bead moves `open` -> `in_progress` -> `done`, and a blocked one is "
        "`blocked` until its dep clears. Pass `--dir` to point elsewhere; run "
        "`ruff check` and `uv run pytest -q`. The `work` facade wraps `bd`, and "
        "`gh pr view` reads the PR. Status may be `queued`.\n"
        "Set `branch = true` and `fail_under = 90`. See `and/or` handling.\n"
    )
    assert _lint(tmp_path, text) == []


def test_a_code_fence_is_not_prose(tmp_path: Path) -> None:
    """A fenced block is illustration, so nothing inside it claims anything about
    the repo — the same reading ``spec_lint`` gives, from the same masker."""
    text = "```\nsee packages/nonexistent/AGENTS.md and the `nope` skill\n```\n"
    assert _lint(tmp_path, text) == []


def test_deploy_space_and_out_of_tree_paths_are_not_claims(tmp_path: Path) -> None:
    """Four ways a path-shaped span says nothing about this checkout. ``.git`` is
    in there because a worktree makes it a file, which would otherwise make the
    gate's answer depend on which checkout it ran from."""
    text = (
        "Installed at `~/.claude/skills/foo/SKILL.md`; a skill lives at "
        "`skills/<name>/SKILL.md`. Hooks are in `.git/hooks/`. The archive is at "
        "`../agents-config-ARCHIVE/`. Docs at `https://example.com/a/b.md`.\n"
    )
    assert _lint(tmp_path, text) == []


def test_a_third_party_dotted_name_is_silence(tmp_path: Path) -> None:
    """A dotted root the repo does not know is far likelier to be a library than
    a stale citation, and a check that cannot tell them apart must not guess."""
    text = "It calls `yaml.safe_load` and `subprocess.run`, then `os.path.join`.\n"
    assert _lint(tmp_path, text) == []


def test_a_bare_identifier_outside_a_package_is_silence(tmp_path: Path) -> None:
    """Repo-wide prose gives a bare identifier no scope to resolve in, and
    resolving it against everything would resolve it against nothing."""
    _write(tmp_path, "packages/grind/src/grind/fold.py", "def apply_event() -> None: ...\n")
    text = "The runtime binds `some_removed_helper` and `AnotherGoneClass`.\n"
    assert _lint(tmp_path, text, tracked=["packages/grind/src/grind/fold.py"]) == []


def test_a_tracker_identifier_is_silence_in_every_frame(tmp_path: Path) -> None:
    """A tracker identifier is deliberately not judged, and this is what makes that
    a checked property instead of a claim in prose — the distinction this gate
    exists to enforce, so the module is the last place that should rest on one.

    Existence is the wrong question to ask of one: prose stating what a closed item
    decided is worth keeping, and only an identifier whose item was deleted is a
    dangling pointer, which nothing here can tell apart. The silence is
    over-determined rather than aimed — hyphens, a part opening with a digit, and a
    leading name that resolves to nothing each exclude the token on their own — so
    what this pins is the outcome and not any one rule. The frames are here for the
    same reason: a span becomes a claim only inside one, and loosening what counts
    as an asset name is what makes the marker line start reporting.
    """
    text = (
        "The decision behind this lives in `widget-shop-qq7.30.1`.\n"
        "\n"
        "Read `widget-shop-qq7.30.1` before changing this module.\n"
        "\n"
        "Consult `qq7.30.1` and `qq7.30` for the rationale.\n"
        "\n"
        "**REQUIRED BACKGROUND:** You MUST understand `widget-shop-qq7.30.1`.\n"
    )
    assert _lint(tmp_path, text) == []


def test_an_identifier_is_still_silence_when_the_namespace_is_known(tmp_path: Path) -> None:
    """Knowing this repo's own tracker namespace does not put ordinary prose's
    identifiers in scope. The carve-out is the whole of the widening: everywhere
    else, the reasoning above still holds."""
    text = "The decision behind this lives in `wgclw.30`.\n"
    assert _lint(tmp_path, text, tracker_prefix="agents-config") == []


def test_an_out_of_namespace_identifier_in_the_charter_is_a_dangling_pointer(
    tmp_path: Path,
) -> None:
    """In the one document a reader is told to orient by, an identifier from a
    tracker this repo's ``work`` cannot address sends them to a lookup that
    returns nothing — and nothing in the prose distinguishes that from having
    looked it up wrong. This is a pointer check, not an existence check: no
    tracker is consulted, only the namespace the identifier is in."""
    charter = str(next(iter(ALWAYS_IN_SCOPE)))
    text = "It becomes the executor loop of the new pipeline (`wgclw.30`).\n"
    findings = _lint(tmp_path, text, relpath=charter, tracker_prefix="agents-config")
    assert [f.citation for f in findings] == ["wgclw.30"]
    assert "namespace" in findings[0].reason


def test_an_identifier_that_says_where_it_resolves_is_not_a_finding(tmp_path: Path) -> None:
    """The remedy the finding asks for, and the shape the charter already uses:
    say where the pointer lands and it points somewhere again."""
    charter = str(next(iter(ALWAYS_IN_SCOPE)))
    text = (
        "The runtime — `wgclw.30`, resolvable in the private archive repository "
        "and not through `work` — is the one live workstream.\n"
    )
    assert _lint(tmp_path, text, relpath=charter, tracker_prefix="agents-config") == []


def test_two_sentences_on_one_line_are_read_separately(tmp_path: Path) -> None:
    """The claim is sentence-scoped, and a line is not a sentence. When the same
    name appears twice on one line — once bare, once in a sentence saying where
    it resolves — one occurrence is a finding and the other is not, whichever
    order they come in. Reading the line as a single context reports both or
    neither, and which one depends on nothing the author can see."""
    charter = str(next(iter(ALWAYS_IN_SCOPE)))
    bare_first = (
        "The loop is `wgclw.30`. The runtime `wgclw.30` is resolvable in the "
        "private archive repository and not through `work`.\n"
    )
    findings = _lint(tmp_path, bare_first, relpath=charter, tracker_prefix="agents-config")
    assert [f.citation for f in findings] == ["wgclw.30"]

    elsewhere_first = (
        "The runtime `wgclw.30` is resolvable in the private archive repository "
        "and not through `work`. The loop is `wgclw.30`.\n"
    )
    findings = _lint(tmp_path, elsewhere_first, relpath=charter, tracker_prefix="agents-config")
    assert [f.citation for f in findings] == ["wgclw.30"]


def test_an_identifier_in_this_repo_namespace_is_never_judged(tmp_path: Path) -> None:
    """Existence stays the wrong question. An identifier ``work`` can address is
    addressable whatever its item's state, and asking a tracker would make a
    prose gate depend on out-of-process mutable state."""
    charter = str(next(iter(ALWAYS_IN_SCOPE)))
    text = "Its open questions are carried by `agents-config-9k9.157`, not by this list.\n"
    assert _lint(tmp_path, text, relpath=charter, tracker_prefix="agents-config") == []


def test_a_namespace_this_one_only_prefixes_is_a_different_namespace(tmp_path: Path) -> None:
    """Local means the identifier's own namespace, not a namespace this one
    happens to start. A sibling project called ``agents-config-tools`` mints
    ``agents-config-tools-abc.1``, which no ``work`` here can address — reading
    the shared prefix as ownership would wave through every neighbour whose name
    begins the same way."""
    charter = str(next(iter(ALWAYS_IN_SCOPE)))
    text = "The rest is carried by `agents-config-tools-abc.1`, elsewhere.\n"
    findings = _lint(tmp_path, text, relpath=charter, tracker_prefix="agents-config")
    assert [f.citation for f in findings] == ["agents-config-tools-abc.1"]


def test_dotted_numbers_that_are_not_identifiers_stay_silent(tmp_path: Path) -> None:
    """The shape has to separate an identifier from every other dotted token a
    spec carries — a version, a release, a date — or the check reports the
    charter's own prose at itself."""
    charter = str(next(iter(ALWAYS_IN_SCOPE)))
    text = (
        "Python `3.11`, release `0.1.0`, the `2026.07.21` snapshot and the "
        "`v1.2.3` tag are all in this sentence.\n"
    )
    assert _lint(tmp_path, text, relpath=charter, tracker_prefix="agents-config") == []


def test_the_namespace_is_read_off_the_project_and_never_written_down(tmp_path: Path) -> None:
    """Derived, so a rename cannot leave the gate judging every local identifier
    foreign. Every way of not having a name to read — no file, a file that will
    not parse, a file that names no project — answers ``None``, which turns the
    check off rather than turning it loose."""
    assert project_tracker_prefix(tmp_path) is None

    config = tmp_path / "project-config.toml"
    config.write_text('[project]\nname = "widget-shop"\n', encoding="utf-8")
    assert project_tracker_prefix(tmp_path) == "widget-shop"

    config.write_text("[project\n", encoding="utf-8")
    assert project_tracker_prefix(tmp_path) is None

    config.write_text('[install]\nprofiles = ["a"]\n', encoding="utf-8")
    assert project_tracker_prefix(tmp_path) is None

    config.write_text("[project]\nname = 7\n", encoding="utf-8")
    assert project_tracker_prefix(tmp_path) is None

    config.write_text('project = "not-a-table"\n', encoding="utf-8")
    assert project_tracker_prefix(tmp_path) is None


def test_identifiers_are_unjudged_when_the_namespace_is_unknown(tmp_path: Path) -> None:
    """No project name to read means no namespace to compare against, and a
    check that cannot tell local from foreign would report both. Silence is the
    default here as everywhere else."""
    charter = str(next(iter(ALWAYS_IN_SCOPE)))
    text = "It becomes the executor loop of the new pipeline (`wgclw.30`).\n"
    assert _lint(tmp_path, text, relpath=charter) == []


# --------------------------------------------------------------------------
# Path citations
# --------------------------------------------------------------------------


def test_a_missing_path_is_reported_with_file_and_line(tmp_path: Path) -> None:
    _write(tmp_path, "docs/guide/index.md")
    text = "See `docs/guide/index.md`.\nThen read `docs/guide/gone.md` for more.\n"
    findings = _lint(tmp_path, text)
    assert len(findings) == 1
    assert findings[0].line == 2
    assert findings[0].citation == "docs/guide/gone.md"
    assert "docs/guide/gone.md" in format_finding(findings[0])
    assert "README.md:2" in format_finding(findings[0])


def test_a_relocated_tree_is_caught_by_its_suffix_alone(tmp_path: Path) -> None:
    """The head segment of a relocated tree is missing *because* it moved, so a
    first-segment test can never see it; the file suffix is what makes the token
    a path claim at all."""
    _write(tmp_path, "docs/guide/index.md")
    findings = _lint(tmp_path, "Read `archive/docs/audits/rules.md`.\n")
    assert [f.citation for f in findings] == ["archive/docs/audits/rules.md"]


def test_a_line_locator_is_not_part_of_the_path(tmp_path: Path) -> None:
    """Otherwise the most precise citations in the repo are the ones that report
    as missing."""
    _write(tmp_path, "packages/grind/AGENTS.md")
    text = "See `packages/grind/AGENTS.md:19` and `packages/grind/AGENTS.md:16-22`.\n"
    assert _lint(tmp_path, text) == []


def test_package_internal_coordinates_resolve(tmp_path: Path) -> None:
    """An architecture document for one subsystem addresses a file by however
    much of its path disambiguates it, and it is not wrong to."""
    _write(tmp_path, "packages/installer/src/installer/core/run.py", "def go() -> None: ...\n")
    tracked = ["packages/installer/src/installer/core/run.py"]
    assert _lint(tmp_path, "The engine is `core/run.py`.\n", tracked=tracked) == []
    assert _lint(tmp_path, "The tree is `src/installer/core/`.\n", tracked=tracked) == []
    findings = _lint(tmp_path, "The engine is `core/gone.py`.\n", tracked=tracked)
    assert [f.citation for f in findings] == ["core/gone.py"]


def test_a_component_boundary_is_required_for_a_suffix_match(tmp_path: Path) -> None:
    """Without it, ``run.py`` would be satisfied by ``prerun.py``."""
    _write(tmp_path, "packages/installer/src/installer/prerun.py", "x = 1\n")
    findings = _lint(
        tmp_path,
        "See `installer/run.py`.\n",
        tracked=["packages/installer/src/installer/prerun.py"],
    )
    assert [f.citation for f in findings] == ["installer/run.py"]


def test_a_glob_claims_a_populated_shape(tmp_path: Path) -> None:
    _write(tmp_path, "packages/grind/AGENTS.md")
    tracked = ["packages/grind/AGENTS.md"]
    assert _lint(tmp_path, "Each of `packages/*/AGENTS.md`.\n", tracked=tracked) == []
    findings = _lint(tmp_path, "Each of `packages/*/CHARTER.md`.\n", tracked=tracked)
    assert [f.citation for f in findings] == ["packages/*/CHARTER.md"]


def test_a_module_written_without_its_extension_resolves(tmp_path: Path) -> None:
    _write(tmp_path, "packages/prgroom/src/prgroom/proc.py", "def spawn() -> None: ...\n")
    findings = _lint(
        tmp_path,
        "Subprocess work lives in `src/prgroom/proc`.\n",
        tracked=["packages/prgroom/src/prgroom/proc.py"],
    )
    assert findings == []


def test_deployed_prose_is_not_judged_on_paths_but_still_on_assets(tmp_path: Path) -> None:
    """Prose under ``src/`` ships into other people's projects, where a path from
    this repo's root resolves to nothing — which is why this repo forbids citing
    one there. Its path-shaped spans are illustrations. Its asset names are not."""
    text = (
        "Put helpers in `scripts/helper.py` and see `references/aws.md`.\nUse the `nope` skill.\n"
    )
    findings = _lint(tmp_path, text, relpath="src/user/.agents/skills/writing-skills/refs.md")
    assert [(f.line, f.citation) for f in findings] == [(2, "nope")]


# --------------------------------------------------------------------------
# Symbol citations
# --------------------------------------------------------------------------


def test_a_symbol_locator_is_checked_in_both_halves(tmp_path: Path) -> None:
    """``file.py::Symbol`` is the strongest citation the repo writes, because the
    author has said outright which file they mean."""
    _write(tmp_path, "packages/grind/src/grind/fold.py", "class Folder:\n    pass\n")
    tracked = ["packages/grind/src/grind/fold.py"]
    assert _lint(tmp_path, "See `src/grind/fold.py::Folder`.\n", tracked=tracked) == []

    findings = _lint(tmp_path, "See `src/grind/fold.py::Unfolder`.\n", tracked=tracked)
    assert len(findings) == 1
    assert "defines no `Unfolder`" in findings[0].reason

    gone = _lint(tmp_path, "See `src/grind/gone.py::Folder`.\n", tracked=tracked)
    assert [f.reason for f in gone] == ["path does not exist"]


def test_a_dotted_citation_resolves_to_the_longest_real_module(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/installer/src/installer/core/spec_lint.py",
        "def lint_specs() -> None: ...\n",
    )
    _write(tmp_path, "packages/installer/src/installer/__init__.py", "")
    _write(tmp_path, "packages/installer/src/installer/core/__init__.py", "")
    text_ok = "Call `installer.core.spec_lint.lint_specs` from the edge.\n"
    assert _lint(tmp_path, text_ok) == []

    findings = _lint(tmp_path, "Call `installer.core.spec_lint.lint_nothing`.\n")
    assert len(findings) == 1
    assert "defines no `lint_nothing`" in findings[0].reason


def test_a_module_stem_resolves_only_inside_a_package(tmp_path: Path) -> None:
    """``sync.remote`` in a primer about git hooks is a git config key. A repo-wide
    stem lookup matched it to the installer's ``sync.py`` and reported a git
    setting as a missing symbol."""
    _write(tmp_path, "packages/installer/src/installer/core/sync.py", "def apply() -> None: ...\n")
    assert _lint(tmp_path, "Set `sync.remote` in the hook config.\n") == []

    findings = _lint(tmp_path, "Call `sync.remote`.\n", relpath="packages/installer/AGENTS.md")
    assert len(findings) == 1
    assert "defines no `remote`" in findings[0].reason


def test_a_file_named_in_the_same_sentence_is_where_a_symbol_must_be(tmp_path: Path) -> None:
    """The shape the repo's prose actually uses: the symbol and its file are two
    separate code spans in one sentence."""
    _write(tmp_path, "packages/installer/src/installer/core/clis.py", "CLI_PACKAGES = ()\n")
    tracked = ["packages/installer/src/installer/core/clis.py"]
    ok = "`CLI_PACKAGES` in `packages/installer/src/installer/core/clis.py` holds the list.\n"
    assert _lint(tmp_path, ok, tracked=tracked) == []

    bad = "`GONE_PACKAGES` in `packages/installer/src/installer/core/clis.py` holds it.\n"
    findings = _lint(tmp_path, bad, tracked=tracked)
    assert len(findings) == 1
    assert "defines no `GONE_PACKAGES`" in findings[0].reason


def test_a_bare_identifier_resolves_against_the_citing_package(tmp_path: Path) -> None:
    _write(tmp_path, "packages/grind/src/grind/fold.py", "def apply_event() -> None: ...\n")
    relpath = "packages/grind/AGENTS.md"
    assert _lint(tmp_path, "The fold runs `apply_event()`.\n", relpath=relpath) == []

    findings = _lint(tmp_path, "The fold runs `apply_gone()`.\n", relpath=relpath)
    assert [f.reason for f in findings] == ["nothing under packages/grind defines it"]


def test_a_name_that_lives_as_data_still_counts(tmp_path: Path) -> None:
    """Event names, error codes and status values are real, findable things that
    live in the code as string literals. Calling them missing is the cry-wolf
    report that gets a gate switched off."""
    _write(
        tmp_path,
        "packages/grind/src/grind/payloads.py",
        'VALIDATORS = {"item_enqueued": None, "E_NOT_FOUND": None}\n',
    )
    text = "Events are `item_enqueued`; errors are `E_NOT_FOUND`.\n"
    assert _lint(tmp_path, text, relpath="packages/grind/AGENTS.md") == []


def test_a_docstring_is_not_a_definition(tmp_path: Path) -> None:
    """The literal index is bounded to identifier-shaped, short constants so that
    prose inside the module cannot vouch for a symbol the module deleted."""
    _write(
        tmp_path,
        "packages/prgroom/src/prgroom/errors.py",
        '"""An ``EscalationSink`` event is filed when the budget runs out."""\n',
    )
    findings = _lint(
        tmp_path, "Failures reach the `EscalationSink`.\n", relpath="packages/prgroom/AGENTS.md"
    )
    assert [f.citation for f in findings] == ["EscalationSink"]


def test_a_cross_package_citation_is_not_a_finding(tmp_path: Path) -> None:
    """Orientation files legitimately point across the boundary, and reporting
    those would punish the cross-reference that keeps the packages coherent."""
    _write(tmp_path, "packages/installer/src/installer/core/clis.py", "CLI_PACKAGES = ()\n")
    _write(tmp_path, "packages/gitclean/src/gitclean/cli.py", "def main() -> None: ...\n")
    text = "This package is listed in `CLI_PACKAGES`.\n"
    assert _lint(tmp_path, text, relpath="packages/gitclean/AGENTS.md") == []


def test_a_parameter_is_a_name(tmp_path: Path) -> None:
    _write(tmp_path, "packages/grind/tests/test_x.py", "def test_it(tmp_path):\n    pass\n")
    assert _lint(tmp_path, "Use `tmp_path`.\n", relpath="packages/grind/AGENTS.md") == []


def test_a_data_filename_is_never_read_as_a_symbol(tmp_path: Path) -> None:
    """``installer.toml`` is a filename. Reading it as a module attribute reported
    the repo's own config file as a missing symbol."""
    _write(tmp_path, "packages/installer/src/installer/__init__.py", "")
    _write(tmp_path, "packages/prgroom/src/prgroom/agent/usage.py", "def record() -> None: ...\n")
    assert _lint(tmp_path, "Config is `installer.toml`.\n") == []
    assert _lint(tmp_path, "Writes `usage.jsonl`.\n", relpath="packages/prgroom/AGENTS.md") == []


def test_a_bare_script_name_resolves_inside_its_package(tmp_path: Path) -> None:
    _write(tmp_path, "packages/grind/src/grind/fold.py", "def apply_event() -> None: ...\n")
    relpath = "packages/grind/AGENTS.md"
    assert _lint(tmp_path, "The fold lives in `fold.py`.\n", relpath=relpath) == []
    findings = _lint(tmp_path, "The fold lives in `unfold.py`.\n", relpath=relpath)
    assert [f.reason for f in findings] == ["no such file under packages/grind"]


def test_an_unparseable_module_reports_rather_than_vouches(tmp_path: Path) -> None:
    """A file the repo's own gates cannot parse is a defect, and reporting its
    citations as unresolved is a truthful symptom rather than a wrong answer."""
    _write(tmp_path, "packages/grind/src/grind/broken.py", "def (:\n")
    findings = _lint(tmp_path, "It binds `apply_event()`.\n", relpath="packages/grind/AGENTS.md")
    assert [f.citation for f in findings] == ["apply_event()"]


# --------------------------------------------------------------------------
# Asset citations
# --------------------------------------------------------------------------


def test_a_named_asset_must_be_one_that_deploys(tmp_path: Path) -> None:
    text = (
        "Read the `grilling` skill first, then the `retired-thing` skill.\n"
        "The `delegation` rule applies; the `codex-routing` rule does not.\n"
    )
    findings = _lint(tmp_path, text)
    assert [(f.line, f.citation) for f in findings] == [(1, "retired-thing"), (2, "codex-routing")]
    assert "skill" in findings[0].reason
    assert "rule" in findings[1].reason


def test_both_word_orders_are_read(tmp_path: Path) -> None:
    findings = _lint(tmp_path, "Invoke skill `retired-thing` before anything else.\n")
    assert [f.citation for f in findings] == ["retired-thing"]


def test_an_asset_name_is_normalised_to_the_roster_entry(tmp_path: Path) -> None:
    """Prose names an asset several ways and they all denote one roster entry."""
    text = (
        "See the `writing-skills/SKILL.md` skill, the `delegation.md` rule, and "
        "the `plugin:grilling` skill.\n"
    )
    assert _lint(tmp_path, text) == []


def test_a_shell_command_is_not_a_deployed_command(tmp_path: Path) -> None:
    """Unqualified, "command" means a shell command far more often than a deployed
    one, and admitting it made this the noisiest check in the module."""
    text = "Run the `gh` command, then the `bd` commands and the `status` command.\n"
    assert _lint(tmp_path, text) == []


def test_a_slash_command_is_checked(tmp_path: Path) -> None:
    assert _lint(tmp_path, "The `/clean-up-git` command drives it.\n") == []
    findings = _lint(tmp_path, "Run the `/grind-prgroom` command to drive it.\n")
    assert [f.citation for f in findings] == ["grind-prgroom"]


def test_a_code_identifier_beside_the_word_rule_is_not_an_asset(tmp_path: Path) -> None:
    """The noisiest false positive the asset check has: real code and config
    sitting next to the word "rule"."""
    text = (
        "The `pull_request` rule and the `required_status_checks` rule are "
        "GitHub's. `should_install_namespace` rules apply per tool, and the "
        "`[gates].test` command runs them.\n"
    )
    assert _lint(tmp_path, text) == []


def test_a_verbed_span_is_not_an_asset_name(tmp_path: Path) -> None:
    """``the wrapping skill `exec`s the binary`` is a sentence, not a citation."""
    assert _lint(tmp_path, "The wrapping skill `exec`s the binary on PATH.\n") == []


def test_project_scoped_assets_are_real(tmp_path: Path) -> None:
    """A second location, not a second derivation: the admission gate judges what
    ``src/`` ships and says nothing about what this repo installs for itself."""
    (tmp_path / ".claude" / "skills" / "admit-request").mkdir(parents=True)
    (tmp_path / ".claude" / "commands").mkdir(parents=True)
    (tmp_path / ".claude" / "commands" / "local-thing.md").write_text("x\n", encoding="utf-8")

    roster = project_asset_names(tmp_path)
    assert roster["skills"] == frozenset({"admit-request"})
    assert roster["commands"] == frozenset({"local-thing"})

    merged = merge_rosters(_ASSETS, roster)
    assert merged["skills"] == frozenset({"grilling", "writing-skills", "admit-request"})
    assert _lint(tmp_path, "Run the `admit-request` skill.\n", assets=merged) == []


def test_merging_rosters_keeps_namespaces_apart() -> None:
    merged = merge_rosters({"skills": frozenset({"a"})}, {"rules": frozenset({"a"})})
    assert merged == {"skills": frozenset({"a"}), "rules": frozenset({"a"})}


# --------------------------------------------------------------------------
# The fileset
# --------------------------------------------------------------------------


def test_an_unreadable_file_is_a_finding_not_an_exception(tmp_path: Path) -> None:
    """The run reports on the whole fileset or it reports nothing anyone can
    act on."""
    findings, _suppressed = lint_markdown(
        [Path("gone.md")], repo_root=tmp_path, assets=_ASSETS, index=_index(tmp_path)
    )
    assert len(findings) == 1
    assert "unreadable" in findings[0].reason


def test_the_pass_reads_every_file_in_the_fileset(tmp_path: Path) -> None:
    _write(tmp_path, "README.md", "Run the `retired-thing` skill.\n")
    _write(tmp_path, "CONTRIBUTING.md", "See `docs/gone.md`.\n")
    findings, _suppressed = lint_markdown(
        [Path("CONTRIBUTING.md"), Path("README.md")],
        repo_root=tmp_path,
        assets=_ASSETS,
        index=_index(tmp_path),
    )
    assert [f.file.name for f in findings] == ["CONTRIBUTING.md", "README.md"]


def test_an_index_over_a_repo_without_packages_is_still_usable(tmp_path: Path) -> None:
    index = build_index(tmp_path, tracked=[Path("README.md")])
    assert index.modules == {}
    assert index.resolves_as_suffix("README.md")


# --------------------------------------------------------------------------
# Non-existence claims
# --------------------------------------------------------------------------


def test_prose_saying_a_thing_is_gone_is_not_a_finding(tmp_path: Path) -> None:
    """The rule that decides whether this gate gets adopted or worked around.

    "The `merge-guard` skill has been retired" is the *correct* remediation for
    stale documentation — it is what a reader arriving from an older install
    needs. Reporting it leaves only two ways to silence the gate, un-backticking
    the name or deleting the sentence, and both are worse prose.
    """
    text = "**Nothing enforces this.** The `merge-guard` skill that read it has been retired.\n"
    assert _lint(tmp_path, text) == []


def test_the_claim_reaches_across_a_hard_wrap(tmp_path: Path) -> None:
    """Markdown wraps prose, so a sentence is not a line: this repo names a skill
    on one line and says it is archived on the next. A line-scoped rule cannot
    see the two together."""
    text = (
        "It was built to replace the `wait-for-pr-comments` and\n"
        "`reply-and-resolve-pr-threads` skills, both now archived along with the\n"
        "`monitor-pr` skill that used to drive it.\n"
    )
    assert _lint(tmp_path, text) == []


def test_a_negative_existence_claim_covers_symbols_and_paths_too(tmp_path: Path) -> None:
    """Retirement is one case of a general shape — prose asserting a thing does
    not exist — so the rule is not special to the asset check."""
    _write(tmp_path, "packages/grind/src/grind/fold.py", "def apply_event() -> None: ...\n")
    relpath = "packages/grind/AGENTS.md"
    symbol = "Status is derived by the fold. There is no `status_changed` event.\n"
    assert _lint(tmp_path, symbol, relpath=relpath) == []

    path = "The `docs/audits/rules.md` report was deleted in the sweep.\n"
    assert _lint(tmp_path, path) == []


def test_the_retirement_lemma_alone_suppresses_nothing(tmp_path: Path) -> None:
    """Retirement is this codebase's *domain vocabulary*, not only an
    announcement. Matching the bare stem suppressed 197 citations where 7 were
    wanted — ``RETIRED_CLIS``, "retiring one is not automatic", "a retired
    plugin's recorded root" all say nothing about whether the name beside them
    exists. A marker has to be a predicate.
    """
    text = (
        "Retiring one is not automatic: uninstall authority is bounded by a "
        "registry, so run the `gone-skill` skill to add a retired entry.\n"
    )
    findings = _lint(tmp_path, text)
    assert [f.citation for f in findings] == ["gone-skill"]


def test_supersession_is_not_absence(tmp_path: Path) -> None:
    """The tree's own counter-example: the installer package "replaces the
    1788-line `scripts/install.sh`" — and that script is still on disk, still
    the entry point. Admitting ``replaces`` would silence live citations."""
    _write(tmp_path, "scripts/install.sh", "#!/bin/sh\n")
    text = (
        "The package that replaces `scripts/install.sh` is the one to run; "
        "use the `gone-skill` skill for the rest.\n"
    )
    findings = _lint(tmp_path, text)
    assert [f.citation for f in findings] == ["gone-skill"]


def test_unused_is_not_absent(tmp_path: Path) -> None:
    """ "Nothing reads it" says a thing is unused, which is the opposite of saying
    it is missing — the root orientation file uses that phrasing about a config
    file that is very much there."""
    text = "Nothing reads it today, and the `gone-skill` skill is how you would.\n"
    findings = _lint(tmp_path, text)
    assert [f.citation for f in findings] == ["gone-skill"]


def test_the_claim_does_not_reach_the_next_sentence(tmp_path: Path) -> None:
    """The scope is one sentence, because one sentence is one assertion."""
    text = "The `old-skill` skill has been retired. Use the `gone-skill` skill instead.\n"
    findings = _lint(tmp_path, text)
    assert [f.citation for f in findings] == ["gone-skill"]


def test_the_claim_does_not_reach_the_next_bullet(tmp_path: Path) -> None:
    """A bullet often has no full stop at all, so without a structural boundary
    one unterminated list item would join the next and carry its marker over."""
    text = "- The `old-skill` skill was archived\n- Run the `gone-skill` skill\n"
    findings = _lint(tmp_path, text)
    assert [f.citation for f in findings] == ["gone-skill"]


def test_one_sentence_retiring_and_directing_hides_both(tmp_path: Path) -> None:
    """The documented way to trip over this by accident, pinned so it stays a
    known cost rather than a surprise: deciding *which* name a clause negates
    needs a parser this does not have, so a sentence that both retires one thing
    and points at another silences both. Two sentences, and both are judged."""
    text = "The `old-skill` skill was retired; use the `gone-skill` skill instead.\n"
    assert _lint(tmp_path, text) == []


def test_a_path_the_sentence_puts_in_another_repository_is_not_a_claim_here(
    tmp_path: Path,
) -> None:
    """Not-here has a second form: the thing is somewhere else. The charter names
    its companion documents in the archive repository, and this repo's own rule
    sends readers there rather than into this tree — so those paths resolving
    against this tree is not the question."""
    text = (
        "**Companions**, all in the `scotthamilton77/agents-config-ARCHIVE` "
        "repository: `SAVEPOINTS/handoff.md` (diagnosis), `SAVEPOINTS/NOTES.md` "
        "(raw verdicts).\n"
    )
    assert _lint(tmp_path, text) == []


def test_an_unnamed_archive_is_not_a_foreign_repository(tmp_path: Path) -> None:
    """A qualifier is what names the destination. "The archive repository" could
    be this repo's own archive of anything, so it resolves nowhere a reader can
    check and cannot stand in for saying where the thing went."""
    text = "The report is held only in the archive repository, at `docs/audits/gone.md`.\n"
    assert [f.citation for f in _lint(tmp_path, text)] == ["docs/audits/gone.md"]


def test_this_repository_is_not_another_repository(tmp_path: Path) -> None:
    """The marker has to name a foreign repository, never the noun alone: "in
    this repository" is on nearly every orientation page here, and reading it as
    an elsewhere-claim would silence the tree."""
    text = "The pipeline lives in this repository, at `packages/gone/loop.py`.\n"
    assert [f.citation for f in _lint(tmp_path, text)] == ["packages/gone/loop.py"]


def test_the_reach_of_the_rule_is_reported() -> None:
    """A silencing rule that leaves no trace is a rule nobody can audit, and this
    one can hide a real finding."""
    assert count_suppressed("Run the `gone-skill` skill.\n") == 0
    assert count_suppressed("The `old-skill` skill has been retired.\n") == 1
    both = "The `old-skill` skill and `docs/gone.md` are now archived.\n"
    assert count_suppressed(both) == 2

    # Both forms of not-here are silencing rules, so both are on the count. A
    # reach that reported only retirements would understate itself by exactly
    # the class the reader has no other way to see.
    elsewhere = "The companions live in the private archive repository: `SAVEPOINTS/x.md`.\n"
    assert count_suppressed(elsewhere) == 1
    assert count_suppressed("The companions live in this repository: `SAVEPOINTS/x.md`.\n") == 0


# --------------------------------------------------------------------------
# Directive frames
# --------------------------------------------------------------------------


def test_only_an_instruction_to_use_an_asset_is_a_finding(tmp_path: Path) -> None:
    """The correction that made the asset check usable. Naming an absent asset
    misleads nobody; being *told to reach for* one does. Firing on the mention
    made the check fire on the sentence that repairs the decay."""
    directive = "Invoke the `gone-skill` skill before anything else.\n"
    assert [f.citation for f in _lint(tmp_path, directive)] == ["gone-skill"]

    mention = "`prgroom` is a CLI that supersedes the `gone-skill` skill.\n"
    assert _lint(tmp_path, mention) == []


def test_the_directive_must_precede_the_citation(tmp_path: Path) -> None:
    """ "Run the `x` skill" is an instruction; "the `x` skill runs nightly" is a
    description that happens to contain the same verb."""
    assert _lint(tmp_path, "Run the `gone-skill` skill nightly.\n") != []
    assert _lint(tmp_path, "The `gone-skill` skill runs nightly.\n") == []


def test_a_reference_frame_counts_as_directive(tmp_path: Path) -> None:
    """A pointer is an instruction to go there: a table row saying "via the `x`
    skill" sends a reader after it exactly as "run" does."""
    row = "| **Interactive** | User in chat, via the `gone-skill` skill | n/a |\n"
    assert [f.citation for f in _lint(tmp_path, row)] == ["gone-skill"]


def test_a_lineage_claim_is_not_a_directive(tmp_path: Path) -> None:
    """Prose describing what a tool replaced tells nobody to use the replaced
    thing, so it is not the harm this check exists to catch."""
    text = "It was built to replace the `gone-skill` skill and the `also-gone` skill.\n"
    assert _lint(tmp_path, text) == []


def test_an_internal_role_described_in_passing_is_not_a_directive(tmp_path: Path) -> None:
    """A design document naming its own dispatch roles — "the `fix` agent runs
    with fresh context" — is describing its architecture, not routing a reader
    to a deployed artifact."""
    text = "Across retries the `gone-agent` agent runs with fresh context each dispatch.\n"
    assert _lint(tmp_path, text) == []


def test_a_requirement_marker_cites_a_skill_no_word_sits_beside(tmp_path: Path) -> None:
    """The blind spot, and the shape a rename actually strands.

    Verbatim in form from ``writing-skills``' subagent-testing reference. The word
    "skill" is four words past the name and refers to the *containing* document —
    "before using this skill" — so nothing beside the citation identifies it, and a
    check keyed on adjacency reads the whole sentence as ordinary prose. Six
    references in that shape survived a skill being amalgamated under a new name
    and this gate reported none of them. The marker is what makes it a citation.
    """
    text = (
        "**REQUIRED BACKGROUND:** You MUST understand `retired-thing` before using "
        "this skill. That skill defines the loop.\n"
    )
    assert [f.citation for f in _lint(tmp_path, text)] == ["retired-thing"]


def test_the_sub_skill_marker_is_read_without_a_directive_verb(tmp_path: Path) -> None:
    """The marker is itself the instruction, so it does not need one beside it.

    The convention's other form, as ``choosing-a-delegate`` writes it. Adjacency
    cannot see this one either: what precedes the name is the marker's colon, not
    whitespace after the bare word.
    """
    text = "REQUIRED SUB-SKILL: Use `retired-thing` once you know who is doing the work.\n"
    assert [f.citation for f in _lint(tmp_path, text)] == ["retired-thing"]


def test_a_kind_word_elsewhere_in_the_sentence_claims_nothing(tmp_path: Path) -> None:
    """Why the marker and not the distance. Measured over this repository: letting
    a kind word anywhere in the sentence bind to a citation produced 60 candidates
    and not one of them was a citation. Four real sentences, each a way the word
    lands near a span it has nothing to do with — a list of the gated namespaces, a
    possessive pointing into the skill's own directory, a design document naming its
    dispatch roles, and a word already bound to the citation next door.
    """
    namespaces = "Applies to any artifact in a gated namespace: `rules`, `skills`, `agents`.\n"
    possessive = "Run it from this skill's `scripts` directory; the path it prints is absolute.\n"
    role = "**The fix agent never calls `gh`** (a locked premise; see the reasons there).\n"
    next_door = "Route an `openrouter` lens through the `grilling` skill and a `codex` lens on.\n"
    for text in (namespaces, possessive, role, next_door):
        assert _lint(tmp_path, text) == [], text


def test_a_requirement_marker_frames_only_what_follows_it(tmp_path: Path) -> None:
    """The same positional rule the directive check has, and for the same reason: a
    marker is a lead-in, so a name before it or in the next sentence is not the name
    it requires."""
    before = "The `also-gone` note came first. REQUIRED SUB-SKILL: Use `grilling` now.\n"
    assert _lint(tmp_path, before) == []

    after = "REQUIRED SUB-SKILL: Use `grilling`. Separately, `also-gone` is mentioned.\n"
    assert _lint(tmp_path, after) == []


def test_a_retirement_note_survives_a_name_far_from_the_word(tmp_path: Path) -> None:
    """The composition that a looser citation rule would break.

    Real prose from the configuration guide, hard wrap and all. ``merge-authorization``
    is kebab-case, is nothing that deploys, sits nowhere near a kind word, and shares
    its sentence with three directive verbs — so the only thing standing between it and
    a finding is the non-existence rule, which reaches it across the wrap. A rule that
    let a distant kind word claim a span would turn this correct retirement note into a
    finding, and the note is the *remedy* for stale documentation, not the disease.
    """
    text = (
        "**Nothing enforces this.** The `merge-guard` skill that read it has been\n"
        "retired, no code reads `merge-authorization`, and nothing polls for reviews, so\n"
        "`[review-expectations]` has no effect either.\n"
    )
    assert _lint(tmp_path, text) == []


def test_the_non_existence_rule_reaches_a_marked_citation_too(tmp_path: Path) -> None:
    """A requirement marker does not exempt its citation from the rule that silences a
    retirement note. Otherwise the correct way to record that a required skill is gone
    would be the one sentence this gate refuses to accept, and there would be no way to
    write the remedy — which is how a gate gets worked around rather than used."""
    text = (
        "**REQUIRED BACKGROUND:** You MUST understand `retired-thing` before using "
        "this skill, but that skill is now archived.\n"
    )
    assert _lint(tmp_path, text) == []


def test_a_marker_does_not_make_every_span_after_it_a_skill_name(tmp_path: Path) -> None:
    """The marker says where to look for a citation, and the kebab-case filter still
    says whether there is one. Otherwise a marker pointing at a document or a flag
    would report it as a skill nothing provides."""
    text = "REQUIRED BACKGROUND: read `docs/guide/index.md` and pass `--dry-run` first.\n"
    findings = _lint(tmp_path, text)
    assert [f.reason for f in findings] == ["path does not exist"]


def test_a_marked_citation_is_reported_once(tmp_path: Path) -> None:
    """Both the marker and the adjacent word claim this span, and a reader gets one
    finding rather than the same line twice."""
    text = "REQUIRED SUB-SKILL: Use the `retired-thing` skill first.\n"
    assert [f.citation for f in _lint(tmp_path, text)] == ["retired-thing"]


def test_a_finding_says_how_to_clear_it(tmp_path: Path) -> None:
    """A gate that knows what it wants and will not say gets reverse-engineered
    by trial and error, which is how a gate ends up deleted."""
    findings = _lint(tmp_path, "Run the `gone-skill` skill.\n")
    assert len(findings) == 1
    assert "say so in this sentence" in findings[0].reason
    assert "missing from src/" in findings[0].reason


def test_an_adjacent_retirement_is_named_as_a_near_miss(tmp_path: Path) -> None:
    """The most likely honest mistake: the words are already there, one sentence
    too far away. The wording stays conditional because the neighbouring
    retirement may be about a different name — which is the live case."""
    text = "Run the `gone-skill` skill. The `old-skill` skill was retired.\n"
    findings = _lint(tmp_path, text)
    assert len(findings) == 1
    assert "one sentence at a time" in findings[0].reason
    assert "if this one is gone too" in findings[0].reason


def test_a_path_finding_carries_the_target_it_resolved(tmp_path: Path) -> None:
    """So the CLI can ask git whether that path is one it was told to ignore,
    without re-deriving the path from the author's raw span."""
    findings = _lint(tmp_path, "See `docs/generated/out.md:12` for the dump.\n")
    assert [f.target for f in findings] == ["docs/generated/out.md"]
    assert [f.citation for f in findings] == ["docs/generated/out.md:12"]
