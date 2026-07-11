"""Parser behavior against real `bd --json` golden captures.

Fixtures under tests/fixtures/ are raw `bd ... --json` stdout, captured
read-only from the main repo (decision 14). Every test here pins the parser's
mapping from bd's actual output shape to workcli's normalized `Item`/`DepEdge`
model -- not a shape we imagined.
"""

from __future__ import annotations

from pathlib import Path

from workcli.adapters.bd.parse import parse_dep_edges, parse_items, parse_labels
from workcli.model import DepEdge

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_show_single_element_array_parses_into_one_item():
    items = parse_items(_read("bd_show_wgclw9.1.json"))

    assert len(items) == 1
    item = items[0]
    assert item.id == "agents-config-wgclw.9.1"
    assert item.title == "workcli transport layer: twelve contract verbs over the Backend seam"
    assert item.type == "feature"
    assert item.status == "in_progress"
    assert item.priority == "P1"
    assert item.labels == ["implementation-ready", "shape-feat", "vision-85-5-10"]
    assert item.parent == "agents-config-wgclw.9"
    assert item.created == "2026-07-05T18:38:04Z"
    assert item.updated == "2026-07-10T22:33:13Z"


def test_parent_child_dependency_is_excluded_from_lean_deps_redundant_with_parent_field():
    # wgclw.9.1's only `dependencies[]` entry is the parent-child edge to its
    # own parent (agents-config-wgclw.9) -- already carried by `item.parent`,
    # so it must not also show up in `item.deps`.
    item = parse_items(_read("bd_show_wgclw9.1.json"))[0]

    assert item.deps == []


def test_non_structural_dependency_normalizes_to_lean_dep_edge():
    # wgclw.9's dependencies[] carries one real (non-parent-child) edge: a
    # full embedded bead plus `dependency_type` -- this must normalize down
    # to the lean {id, type, status} shape, dropping every other embedded field.
    item = parse_items(_read("bd_show_wgclw9.json"))[0]

    assert item.deps == [
        DepEdge(id="agents-config-fca6.12", type="discovered-from", status="closed")
    ]


def test_parent_child_dependents_become_children_other_dependents_do_not():
    # wgclw.9's dependents[] has two parent-child entries (its two children)
    # -- those become `children`. wgclw.9.1's dependents[] has one `blocks`
    # entry, which must NOT show up as a child.
    parent_item = parse_items(_read("bd_show_wgclw9.json"))[0]
    child_item = parse_items(_read("bd_show_wgclw9.1.json"))[0]

    assert parent_item.children == ["agents-config-wgclw.9.1", "agents-config-wgclw.9.2"]
    assert child_item.children == []


def test_multiline_notes_survive_as_a_proper_json_string_not_escaped_text():
    item = parse_items(_read("bd_show_wgclw9.json"))[0]

    assert "\n" in item.notes
    assert item.notes.splitlines()[0].startswith("Spec PR: https://github.com/")


def test_list_output_parses_every_item_including_ones_with_missing_optional_keys():
    # bd_list_open_limit5.json has 5 items; some omit `notes`/`assignee`/
    # `started_at`/`acceptance_criteria` entirely (bd only emits optional
    # fields when non-empty) -- those must default cleanly, not raise.
    items = parse_items(_read("bd_list_open_limit5.json"))

    assert [item.id for item in items] == [
        "agents-config-abn9.40.2",
        "agents-config-abn9.40.1",
        "agents-config-viiud",
        "agents-config-abn9.13.1",
        "agents-config-abn9.13",
    ]
    no_notes_item = next(item for item in items if item.id == "agents-config-abn9.13.1")
    assert no_notes_item.notes == ""


def test_list_output_dependency_edges_use_the_edge_shape_not_the_show_shape():
    # bd list's embedded dependencies[] carry raw edge rows
    # ({issue_id, depends_on_id, type}) rather than show's embedded full
    # bead + dependency_type -- and never carry a `status` for the other
    # end, since bd list doesn't fetch it. Non-parent-child edges still
    # normalize to DepEdge, just with status="".
    item = next(
        item
        for item in parse_items(_read("bd_list_open_limit5.json"))
        if item.id == "agents-config-abn9.13"
    )

    assert item.deps == [DepEdge(id="agents-config-abn9.11", type="discovered-from", status="")]


def test_list_output_items_never_carry_children_bd_list_has_no_dependents_field():
    items = parse_items(_read("bd_list_open_limit5.json"))

    assert all(item.children == [] for item in items)


def test_label_list_flat_string_array_passes_through_unchanged():
    labels = parse_labels(_read("bd_label_list_wgclw9.1.json"))

    assert labels == ["implementation-ready", "shape-feat", "vision-85-5-10"]


def test_dep_list_down_direction_normalizes_into_a_lean_dep_edge():
    # bd_dep_list_down.json is wgclw.9.1's default-direction ("depends on")
    # result: its parent, agents-config-wgclw.9, via a parent-child edge.
    edges = parse_dep_edges(_read("bd_dep_list_down.json"), self_id="agents-config-wgclw.9.1")

    assert edges == [DepEdge(id="agents-config-wgclw.9", type="parent-child", status="open")]


def test_dep_list_up_direction_normalizes_into_a_lean_dep_edge():
    # bd_dep_list_up.json is wgclw.9.1's --direction=up ("dependents")
    # result: wgclw.9.2, which is blocked behind it.
    edges = parse_dep_edges(_read("bd_dep_list_up.json"), self_id="agents-config-wgclw.9.1")

    assert edges == [DepEdge(id="agents-config-wgclw.9.2", type="blocks", status="open")]
