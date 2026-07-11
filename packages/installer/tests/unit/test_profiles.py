"""Behavioural tests for the profiles manifest + pure scope-routing resolver
(spec §10 items 1-11; docs/specs/2026-07-06-profiles-scope-routing.md).

# NOTE: spec §10 item 4 (the DYNAMIC-INCLUDE-ALL-RULES vs DYNAMIC-INCLUDE-RULES
# template-flattening boundary) is deferred to the orchestrator-wiring slice
# (S2/S3) — it concerns `templates.py`/the orchestrator, not this pure
# resolver, and is intentionally not implemented or tested here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.installignore import InstallIgnore
from installer.core.model import FileKind, Provenance, StagedItem, StagingPlan, Tool
from installer.core.profiles import (
    IncludeEntry,
    Manifest,
    Profile,
    ProfilesError,
    ResolvedPlan,
    Scope,
    UniverseRef,
    _selector_matches,
    _specificity,
    filter_plan_to_scope,
    load_manifest,
    project_universe,
    resolve,
)
from installer.core.staging import build_plan
from installer.tools.registry import get_adapter

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PROV = Provenance(kind="tool", name="claude")


def _ref(dest: str, tool: Tool = Tool.CLAUDE) -> UniverseRef:
    return UniverseRef(tool=tool, dest_relpath=Path(dest))


def _manifest(profiles: dict[str, Profile], scopes: dict[str, Scope] | None = None) -> Manifest:
    return Manifest(schema=1, scopes=scopes or {}, profiles=profiles)


def _profile(
    name: str, includes: tuple[IncludeEntry, ...] = (), excludes: tuple[str, ...] = ()
) -> Profile:
    return Profile(name=name, includes=includes, excludes=excludes)


_BASE_SCOPES = {
    "instructions": Scope.USER,
    "rules/**": Scope.USER,
    "skills/**": Scope.USER,
}
_BASE_UNIVERSE: dict[str, list[UniverseRef]] = {
    "rules/x": [_ref("rules/x.md")],
    "rules/y": [_ref("rules/y.md")],
    "skills/brainstorming": [_ref("skills/brainstorming")],
    "skills/writing-plans": [_ref("skills/writing-plans")],
    "instructions": [_ref("AGENTS.md")],
}
_BASE_MANIFEST = _manifest(
    {
        "a": _profile("a", includes=(IncludeEntry("rules/**", None),)),
        "b": _profile("b", includes=(IncludeEntry("skills/**", None),)),
        "full": _profile("full", includes=(IncludeEntry("**", None),)),
        "no-brainstorming": _profile("no-brainstorming", excludes=("skills/brainstorming",)),
    },
    _BASE_SCOPES,
)


def _dests(plan: ResolvedPlan, scope: Scope) -> set[Path]:
    return {ref.dest_relpath for ref in plan.included.get(scope, ())}


def _item(
    dest: str,
    *,
    kind: FileKind,
    namespace: str | None,
) -> StagedItem:
    return StagedItem(
        source_path=Path("/dev/null"),
        dest_relpath=Path(dest),
        kind=kind,
        namespace=namespace,
        provenance=_PROV,
    )


def test_selector_matches_double_star_matches_everything() -> None:
    assert _selector_matches("**", "instructions") is True
    assert _selector_matches("**", "skills/brainstorming") is True
    assert _selector_matches("**", "skills/x/y") is True


def test_selector_matches_prefix_double_star_matches_descendants() -> None:
    assert _selector_matches("skills/**", "skills/x") is True
    assert _selector_matches("skills/**", "skills/x/y") is True
    assert _selector_matches("skills/**", "rules/x") is False


def test_selector_matches_single_star_matches_one_segment_only() -> None:
    assert _selector_matches("skills/*", "skills/x") is True
    assert _selector_matches("skills/*", "skills/x/y") is False


def test_selector_matches_literal_matches_only_itself() -> None:
    assert _selector_matches("rules/memory-routing", "rules/memory-routing") is True
    assert _selector_matches("rules/memory-routing", "rules/memory-routing-2") is False
    assert _selector_matches("rules/memory-routing", "rules/memory-routing/extra") is False


def test_selector_matches_pattern_longer_than_key_no_match() -> None:
    assert _selector_matches("skills/x/y", "skills/x") is False


def test_selector_matches_double_star_mid_pattern_matches_any_gap() -> None:
    assert _selector_matches("a/**/b", "a/x/y/b") is True
    assert _selector_matches("a/**/b", "a/c") is False


def test_specificity_literal_beats_glob() -> None:
    assert _specificity("rules/memory-routing") > _specificity("rules/**")


def test_specificity_star_and_double_star_are_equal() -> None:
    assert _specificity("skills/*") == _specificity("skills/**")


def test_specificity_more_literal_segments_wins_among_globs() -> None:
    assert _specificity("skills/writing-plans/**") > _specificity("skills/**")


_SHIPPED_TOML = """
schema = 1

[scopes]
"instructions" = "user"
"skills/**" = "user"

[profiles.full]
include = ["**"]

[profiles.project-lean]
include = [
  "instructions",
  { select = "skills/writing-plans", scope = "project" },
]

[profiles.no-brainstorming]
exclude = ["skills/brainstorming"]
"""


def test_load_manifest_parses_scopes_and_profiles(tmp_path: Path) -> None:
    shipped = tmp_path / "profiles.toml"
    shipped.write_text(_SHIPPED_TOML)

    manifest = load_manifest(shipped)

    assert manifest.schema == 1
    assert manifest.scopes["instructions"] is Scope.USER
    assert manifest.scopes["skills/**"] is Scope.USER
    assert set(manifest.profiles) == {"full", "project-lean", "no-brainstorming"}
    assert manifest.profiles["full"].includes == (IncludeEntry("**", None),)
    lean = manifest.profiles["project-lean"]
    assert lean.includes[0].selector == "instructions"
    assert lean.includes[0].scope is None
    assert lean.includes[1].selector == "skills/writing-plans"
    assert lean.includes[1].scope is Scope.PROJECT
    assert manifest.profiles["no-brainstorming"].excludes == ("skills/brainstorming",)


def test_load_manifest_bad_schema_errors(tmp_path: Path) -> None:
    shipped = tmp_path / "profiles.toml"
    shipped.write_text('schema = 2\n[profiles.full]\ninclude = ["**"]\n')

    with pytest.raises(ProfilesError, match="2"):
        load_manifest(shipped)


def test_load_manifest_unknown_scope_errors(tmp_path: Path) -> None:
    shipped = tmp_path / "profiles.toml"
    shipped.write_text('schema = 1\n[scopes]\n"x" = "bogus"\n[profiles.full]\ninclude=["**"]\n')

    with pytest.raises(ProfilesError, match="bogus"):
        load_manifest(shipped)


def test_load_manifest_non_string_scope_value_errors(tmp_path: Path) -> None:
    shipped = tmp_path / "profiles.toml"
    shipped.write_text('schema = 1\n[scopes]\n"x" = 5\n[profiles.full]\ninclude=["**"]\n')

    with pytest.raises(ProfilesError):
        load_manifest(shipped)


def test_load_manifest_invalid_include_shape_errors(tmp_path: Path) -> None:
    shipped = tmp_path / "profiles.toml"
    shipped.write_text('schema = 1\n[scopes]\n"x" = "user"\n[profiles.full]\ninclude = [42]\n')

    with pytest.raises(ProfilesError):
        load_manifest(shipped)


def test_load_manifest_non_string_select_in_include_table_errors(tmp_path: Path) -> None:
    shipped = tmp_path / "profiles.toml"
    shipped.write_text(
        'schema = 1\n[scopes]\n"x" = "user"\n'
        '[profiles.full]\ninclude = [{ select = 5, scope = "user" }]\n'
    )

    with pytest.raises(ProfilesError):
        load_manifest(shipped)


def test_load_manifest_non_table_profile_entry_errors(tmp_path: Path) -> None:
    shipped = tmp_path / "profiles.toml"
    shipped.write_text('schema = 1\n[profiles]\nfull = "oops"\n')

    with pytest.raises(ProfilesError):
        load_manifest(shipped)


def test_load_manifest_non_string_exclude_errors(tmp_path: Path) -> None:
    shipped = tmp_path / "profiles.toml"
    shipped.write_text(
        'schema = 1\n[scopes]\n"x" = "user"\n[profiles.full]\ninclude=["**"]\nexclude = [42]\n'
    )

    with pytest.raises(ProfilesError):
        load_manifest(shipped)


def test_load_manifest_merges_user_profiles_by_name(tmp_path: Path) -> None:
    shipped = tmp_path / "profiles.toml"
    shipped.write_text(_SHIPPED_TOML)
    user = tmp_path / "user-profiles.toml"
    user.write_text('schema = 1\n[profiles.my-lean]\ninclude = ["instructions"]\n')

    manifest = load_manifest(shipped, user)

    assert "my-lean" in manifest.profiles
    assert "full" in manifest.profiles  # shipped profiles survive the merge


def test_load_manifest_duplicate_profile_name_errors(tmp_path: Path) -> None:
    shipped = tmp_path / "profiles.toml"
    shipped.write_text(_SHIPPED_TOML)
    user = tmp_path / "user-profiles.toml"
    user.write_text('schema = 1\n[profiles.full]\ninclude = ["instructions"]\n')

    with pytest.raises(ProfilesError, match="full"):
        load_manifest(shipped, user)


def test_load_manifest_user_scopes_table_errors(tmp_path: Path) -> None:
    shipped = tmp_path / "profiles.toml"
    shipped.write_text(_SHIPPED_TOML)
    user = tmp_path / "user-profiles.toml"
    user.write_text(
        'schema = 1\n[scopes]\n"x" = "user"\n[profiles.my-lean]\ninclude=["instructions"]\n'
    )

    with pytest.raises(ProfilesError):
        load_manifest(shipped, user)


def test_load_manifest_missing_user_file_is_ignored(tmp_path: Path) -> None:
    shipped = tmp_path / "profiles.toml"
    shipped.write_text(_SHIPPED_TOML)
    absent = tmp_path / "does-not-exist.toml"

    manifest = load_manifest(shipped, absent)

    assert set(manifest.profiles) == {"full", "project-lean", "no-brainstorming"}


def test_load_manifest_scalar_scopes_table_errors(tmp_path: Path) -> None:
    """A `scopes` value that is a scalar (`scopes = 1`) must fail loud with a
    ProfilesError, not an AttributeError from calling `.items()` on an int."""
    shipped = tmp_path / "profiles.toml"
    shipped.write_text('schema = 1\nscopes = 1\n[profiles.full]\ninclude = ["**"]\n')

    with pytest.raises(ProfilesError, match=r"\[scopes\] must be a table"):
        load_manifest(shipped)


def test_load_manifest_scalar_profiles_table_errors(tmp_path: Path) -> None:
    """A `profiles` value that is a scalar must fail loud with ProfilesError,
    not an AttributeError from `.items()`."""
    shipped = tmp_path / "profiles.toml"
    shipped.write_text("schema = 1\nprofiles = 1\n")

    with pytest.raises(ProfilesError, match=r"\[profiles\] must be a table"):
        load_manifest(shipped)


def test_load_manifest_string_include_errors(tmp_path: Path) -> None:
    """`include = "**"` (a bare string, not an array) must fail loud rather than
    silently iterating the string into per-character selectors."""
    shipped = tmp_path / "profiles.toml"
    shipped.write_text('schema = 1\n[scopes]\n"x" = "user"\n[profiles.full]\ninclude = "**"\n')

    with pytest.raises(ProfilesError, match="include must be an array"):
        load_manifest(shipped)


def test_load_manifest_string_exclude_errors(tmp_path: Path) -> None:
    """`exclude = "x"` (a bare string, not an array) must fail loud."""
    shipped = tmp_path / "profiles.toml"
    shipped.write_text(
        'schema = 1\n[scopes]\n"x" = "user"\n[profiles.full]\ninclude = ["**"]\nexclude = "x"\n'
    )

    with pytest.raises(ProfilesError, match="exclude must be an array"):
        load_manifest(shipped)


# ---------------------------------------------------------------------------
# project_universe — selector-key normalization (spec §3)
# ---------------------------------------------------------------------------


def test_project_universe_strips_md_suffix_for_namespaced_items() -> None:
    plan = StagingPlan(
        items={
            Path("rules/memory-routing.md"): _item(
                "rules/memory-routing.md", kind=FileKind.NAMESPACED_MD, namespace="rules"
            )
        },
        tool=Tool.CLAUDE,
    )

    universe = project_universe([plan])

    assert "rules/memory-routing" in universe
    assert universe["rules/memory-routing"] == [
        UniverseRef(tool=Tool.CLAUDE, dest_relpath=Path("rules/memory-routing.md"))
    ]


def test_project_universe_dir_item_has_no_suffix_to_strip() -> None:
    plan = StagingPlan(
        items={
            Path("skills/brainstorming"): _item(
                "skills/brainstorming", kind=FileKind.DIR, namespace="skills"
            )
        },
        tool=Tool.CLAUDE,
    )

    universe = project_universe([plan])

    assert "skills/brainstorming" in universe


def test_project_universe_preserves_non_md_namespaced_extension() -> None:
    plan = StagingPlan(
        items={
            Path("hooks/ruff-postedit.py"): _item(
                "hooks/ruff-postedit.py", kind=FileKind.OTHER, namespace="hooks"
            )
        },
        tool=Tool.CLAUDE,
    )

    universe = project_universe([plan])

    assert "hooks/ruff-postedit.py" in universe


def test_project_universe_root_other_collapses_to_instructions() -> None:
    plan = StagingPlan(
        items={
            Path("AGENTS.md"): _item("AGENTS.md", kind=FileKind.OTHER, namespace=None),
            Path("CLAUDE.md"): _item("CLAUDE.md", kind=FileKind.OTHER, namespace=None),
        },
        tool=Tool.CLAUDE,
    )

    universe = project_universe([plan])

    assert {ref.dest_relpath for ref in universe["instructions"]} == {
        Path("AGENTS.md"),
        Path("CLAUDE.md"),
    }


def test_project_universe_root_settings_kinds_collapse_to_settings() -> None:
    plan = StagingPlan(
        items={
            Path("settings.json"): _item(
                "settings.json", kind=FileKind.SETTINGS_JSON, namespace=None
            ),
            Path("opencode.jsonc"): _item("opencode.jsonc", kind=FileKind.JSONC, namespace=None),
        },
        tool=Tool.CLAUDE,
    )

    universe = project_universe([plan])

    assert {ref.dest_relpath for ref in universe["settings"]} == {
        Path("settings.json"),
        Path("opencode.jsonc"),
    }


def test_project_universe_unexpected_rootless_kind_errors() -> None:
    plan = StagingPlan(
        items={
            Path("weird"): _item("weird", kind=FileKind.DIR, namespace=None),
        },
        tool=Tool.CLAUDE,
    )

    with pytest.raises(ProfilesError):
        project_universe([plan])


def test_project_universe_unions_refs_across_tool_plans() -> None:
    claude_plan = StagingPlan(
        items={
            Path("rules/x.md"): _item("rules/x.md", kind=FileKind.NAMESPACED_MD, namespace="rules")
        },
        tool=Tool.CLAUDE,
    )
    codex_plan = StagingPlan(
        items={
            Path("rules/x.md"): _item("rules/x.md", kind=FileKind.NAMESPACED_MD, namespace="rules")
        },
        tool=Tool.CODEX,
    )

    universe = project_universe([claude_plan, codex_plan])

    assert {ref.tool for ref in universe["rules/x"]} == {Tool.CLAUDE, Tool.CODEX}


def test_project_universe_normalization_pin_against_real_universe(ignore: InstallIgnore) -> None:
    """spec §10 item 6 normalization pin: `rules/memory-routing` matches the
    staged `rules/memory-routing.md`, and `instructions` matches the tool-root
    instruction templates — both asserted directly via `project_universe`
    keys built from the real repo root."""
    plans = [build_plan(get_adapter(tool), repo_root=_REPO_ROOT, ignore=ignore) for tool in Tool]

    universe = project_universe(plans)

    assert "rules/memory-routing" in universe
    assert "instructions" in universe


# ---------------------------------------------------------------------------
# resolve() — spec §10 items 2, 3, 5, 6, 8, 9, 10, 11
# ---------------------------------------------------------------------------


def test_resolve_union_composition_is_order_independent() -> None:
    only_a = resolve(_BASE_MANIFEST, ["a"], _BASE_UNIVERSE, bound_scopes=frozenset({Scope.USER}))
    only_b = resolve(_BASE_MANIFEST, ["b"], _BASE_UNIVERSE, bound_scopes=frozenset({Scope.USER}))
    ab = resolve(_BASE_MANIFEST, ["a", "b"], _BASE_UNIVERSE, bound_scopes=frozenset({Scope.USER}))
    ba = resolve(_BASE_MANIFEST, ["b", "a"], _BASE_UNIVERSE, bound_scopes=frozenset({Scope.USER}))

    union_dests = _dests(only_a, Scope.USER) | _dests(only_b, Scope.USER)
    assert _dests(ab, Scope.USER) == union_dests
    assert _dests(ba, Scope.USER) == union_dests


def test_resolve_exclude_subtracts_matching_ref() -> None:
    plan = resolve(
        _BASE_MANIFEST,
        ["full", "no-brainstorming"],
        _BASE_UNIVERSE,
        bound_scopes=frozenset({Scope.USER}),
    )

    assert Path("skills/brainstorming") not in _dests(plan, Scope.USER)
    assert Path("rules/x.md") in _dests(plan, Scope.USER)


def test_resolve_exclude_wins_regardless_of_contributing_profile() -> None:
    plan = resolve(
        _BASE_MANIFEST,
        ["b", "no-brainstorming"],
        _BASE_UNIVERSE,
        bound_scopes=frozenset({Scope.USER}),
    )

    assert Path("skills/brainstorming") not in _dests(plan, Scope.USER)
    assert Path("skills/writing-plans") in _dests(plan, Scope.USER)


def test_resolve_exclude_that_subtracts_nothing_is_a_no_op() -> None:
    plan = resolve(
        _BASE_MANIFEST,
        ["a", "no-brainstorming"],
        _BASE_UNIVERSE,
        bound_scopes=frozenset({Scope.USER}),
    )

    assert _dests(plan, Scope.USER) == {Path("rules/x.md"), Path("rules/y.md")}


def test_resolve_exclude_matching_nothing_in_universe_errors() -> None:
    manifest = _manifest(
        {
            "bad": _profile(
                "bad", includes=(IncludeEntry("rules/**", None),), excludes=("nope/nope",)
            )
        },
        _BASE_SCOPES,
    )

    with pytest.raises(ProfilesError, match="nope/nope"):
        resolve(manifest, ["bad"], _BASE_UNIVERSE, bound_scopes=frozenset({Scope.USER}))


def test_resolve_zero_item_selection_errors() -> None:
    manifest = _manifest(
        {
            "self-canceling": _profile(
                "self-canceling",
                includes=(IncludeEntry("skills/brainstorming", None),),
                excludes=("skills/brainstorming",),
            )
        },
        _BASE_SCOPES,
    )

    with pytest.raises(ProfilesError, match="zero items"):
        resolve(manifest, ["self-canceling"], _BASE_UNIVERSE, bound_scopes=frozenset({Scope.USER}))


def test_resolve_unknown_profile_name_errors_naming_known_profiles() -> None:
    with pytest.raises(ProfilesError, match="a"):
        resolve(_BASE_MANIFEST, ["bogus"], _BASE_UNIVERSE, bound_scopes=frozenset({Scope.USER}))


def test_resolve_include_selector_matching_nothing_errors() -> None:
    manifest = _manifest(
        {"bad": _profile("bad", includes=(IncludeEntry("nope/nope", None),))}, _BASE_SCOPES
    )

    with pytest.raises(ProfilesError, match="nope/nope"):
        resolve(manifest, ["bad"], _BASE_UNIVERSE, bound_scopes=frozenset({Scope.USER}))


def test_resolve_explicit_scope_specificity_literal_beats_glob() -> None:
    manifest = _manifest(
        {
            "override": _profile(
                "override", includes=(IncludeEntry("skills/writing-plans", Scope.PROJECT),)
            ),
            "b": _BASE_MANIFEST.profiles["b"],
        },
        _BASE_SCOPES,
    )

    plan = resolve(
        manifest,
        ["override", "b"],
        _BASE_UNIVERSE,
        bound_scopes=frozenset({Scope.USER, Scope.PROJECT}),
    )

    assert Path("skills/writing-plans") in _dests(plan, Scope.PROJECT)
    assert Path("skills/writing-plans") not in _dests(plan, Scope.USER)
    assert Path("skills/brainstorming") in _dests(plan, Scope.USER)


def test_resolve_explicit_scope_tie_with_differing_scopes_errors() -> None:
    manifest = _manifest(
        {
            "p1": _profile("p1", includes=(IncludeEntry("skills/writing-plans", Scope.PROJECT),)),
            "p2": _profile("p2", includes=(IncludeEntry("skills/writing-plans", Scope.USER),)),
        },
        _BASE_SCOPES,
    )

    with pytest.raises(ProfilesError, match="p1"):
        resolve(
            manifest,
            ["p1", "p2"],
            _BASE_UNIVERSE,
            bound_scopes=frozenset({Scope.USER, Scope.PROJECT}),
        )


def test_resolve_scopes_table_tie_with_differing_scopes_errors() -> None:
    conflicting_scopes = {"rules/**": Scope.USER, "rules/*": Scope.PROJECT}
    manifest = _manifest(
        {"a": _profile("a", includes=(IncludeEntry("rules/**", None),))}, conflicting_scopes
    )

    with pytest.raises(ProfilesError, match="rules"):
        resolve(
            manifest,
            ["a"],
            _BASE_UNIVERSE,
            bound_scopes=frozenset({Scope.USER, Scope.PROJECT}),
        )


def test_resolve_no_scopes_match_errors_naming_the_key() -> None:
    manifest = _manifest(
        {"bad": _profile("bad", includes=(IncludeEntry("instructions", None),))},
        {},  # no [scopes] entries at all
    )

    with pytest.raises(ProfilesError, match="instructions"):
        resolve(manifest, ["bad"], _BASE_UNIVERSE, bound_scopes=frozenset({Scope.USER}))


def test_resolve_scope_override_routes_to_project_when_bound() -> None:
    manifest = _manifest(
        {
            "override": _profile(
                "override", includes=(IncludeEntry("skills/writing-plans", Scope.PROJECT),)
            )
        },
        _BASE_SCOPES,
    )

    plan = resolve(manifest, ["override"], _BASE_UNIVERSE, bound_scopes=frozenset({Scope.PROJECT}))

    assert Path("skills/writing-plans") in _dests(plan, Scope.PROJECT)
    assert Scope.USER not in plan.included


def test_resolve_scope_override_drops_when_project_unbound() -> None:
    # Selected alongside "a" (rules/** -> user) so the run has other USER-bound
    # items and the total-drop guard (step 8) does not also fire here — this
    # test pins the override item's own fate, not the whole-run guard.
    manifest = _manifest(
        {
            "override": _profile(
                "override", includes=(IncludeEntry("skills/writing-plans", Scope.PROJECT),)
            ),
            "a": _BASE_MANIFEST.profiles["a"],
        },
        _BASE_SCOPES,
    )

    plan = resolve(
        manifest, ["override", "a"], _BASE_UNIVERSE, bound_scopes=frozenset({Scope.USER})
    )

    assert Path("skills/writing-plans") not in _dests(plan, Scope.USER)
    assert Scope.PROJECT not in plan.included
    assert plan.dropped_counts.get(Scope.PROJECT, 0) == 1


def test_resolve_user_run_drops_project_scoped_entries_only() -> None:
    manifest = _manifest(
        {
            "override": _profile(
                "override", includes=(IncludeEntry("skills/writing-plans", Scope.PROJECT),)
            ),
            "b": _BASE_MANIFEST.profiles["b"],
        },
        _BASE_SCOPES,
    )

    plan = resolve(
        manifest, ["override", "b"], _BASE_UNIVERSE, bound_scopes=frozenset({Scope.USER})
    )

    assert plan.dropped_counts.get(Scope.PROJECT, 0) >= 1
    assert Scope.PROJECT not in plan.included
    # skills/writing-plans is routed to PROJECT by the explicit override
    # regardless of scope binding, so it drops rather than landing in USER.
    assert _dests(plan, Scope.USER) == {Path("skills/brainstorming")}


def test_resolve_total_drop_errors() -> None:
    manifest = _manifest(
        {
            "override": _profile(
                "override", includes=(IncludeEntry("skills/writing-plans", Scope.PROJECT),)
            )
        },
        _BASE_SCOPES,
    )

    with pytest.raises(ProfilesError):
        resolve(manifest, ["override"], _BASE_UNIVERSE, bound_scopes=frozenset({Scope.USER}))


def test_resolve_empty_selection_defaults_to_full() -> None:
    plan = resolve(_BASE_MANIFEST, [], _BASE_UNIVERSE, bound_scopes=frozenset({Scope.USER}))

    assert Path("rules/x.md") in _dests(plan, Scope.USER)
    assert Path("skills/brainstorming") in _dests(plan, Scope.USER)


# ---------------------------------------------------------------------------
# filter_plan_to_scope — pure plan filter
# ---------------------------------------------------------------------------


def test_filter_plan_to_scope_keeps_only_listed_paths() -> None:
    keep = _item("rules/keep.md", kind=FileKind.NAMESPACED_MD, namespace="rules")
    drop = _item("rules/drop.md", kind=FileKind.NAMESPACED_MD, namespace="rules")
    plan = StagingPlan(
        items={Path("rules/keep.md"): keep, Path("rules/drop.md"): drop}, tool=Tool.CLAUDE
    )

    filtered = filter_plan_to_scope(plan, [Path("rules/keep.md")])

    assert set(filtered.items) == {Path("rules/keep.md")}
    assert filtered.items[Path("rules/keep.md")] is keep
    assert filtered.tool == Tool.CLAUDE


def test_filter_plan_to_scope_does_not_mutate_input() -> None:
    keep = _item("rules/keep.md", kind=FileKind.NAMESPACED_MD, namespace="rules")
    plan = StagingPlan(items={Path("rules/keep.md"): keep}, tool=Tool.CLAUDE)

    filter_plan_to_scope(plan, [])

    assert Path("rules/keep.md") in plan.items


def test_filter_plan_to_scope_carries_over_kept_dir_overrides() -> None:
    dir_item = _item("skills/foo", kind=FileKind.DIR, namespace="skills")
    plan = StagingPlan(
        items={Path("skills/foo"): dir_item},
        tool=Tool.CLAUDE,
        dir_overrides={Path("skills/foo"): {Path("extra.txt"): b"data"}},
    )

    filtered = filter_plan_to_scope(plan, [Path("skills/foo")])

    assert filtered.dir_overrides == {Path("skills/foo"): {Path("extra.txt"): b"data"}}


# ---------------------------------------------------------------------------
# Golden / zero-breakage pin — spec §10 item 1
# ---------------------------------------------------------------------------


def test_golden_full_profile_is_byte_identical_to_todays_install(ignore: InstallIgnore) -> None:
    """No profiles anywhere -> staged plan identical to today's full install.
    Uses the REAL shipped profiles.toml against the REAL repo universe."""
    plans = {
        tool: build_plan(get_adapter(tool), repo_root=_REPO_ROOT, ignore=ignore) for tool in Tool
    }
    universe = project_universe(plans.values())
    manifest = load_manifest(_REPO_ROOT / "profiles.toml")

    resolved = resolve(manifest, (), universe, bound_scopes=frozenset({Scope.USER}))

    assert not any(count > 0 for count in resolved.dropped_counts.values())

    kept_user_paths = [ref.dest_relpath for ref in resolved.included[Scope.USER]]
    for tool, plan in plans.items():
        filtered = filter_plan_to_scope(plan, kept_user_paths)
        assert filtered.items == plan.items, f"{tool} plan changed under the full profile"


@pytest.mark.parametrize(
    "selection",
    [("full",), ("minimal-user",), ("sdlc",), ("full", "no-brainstorming")],
)
def test_shipped_profiles_resolve_against_real_universe(
    ignore: InstallIgnore, selection: tuple[str, ...]
) -> None:
    """Anti-drift guard on the shipped manifest itself: every selector in
    every shipped profile (not just `full`) must match >=1 real staged item,
    or resolution errors naming it — this is the brief's mandated pre-ship
    check, pinned as a permanent regression test."""
    plans = [build_plan(get_adapter(tool), repo_root=_REPO_ROOT, ignore=ignore) for tool in Tool]
    universe = project_universe(plans)
    manifest = load_manifest(_REPO_ROOT / "profiles.toml")

    resolve(manifest, selection, universe, bound_scopes=frozenset({Scope.USER}))
