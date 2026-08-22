"""The wire contract, checked across the serialisation boundary.

Two failures that every other gate is blind to. A field the backend projects
into a payload the page fetches, which no page code reads: from Python's side
the field is used -- declared, validated, projected, logged -- and only the
JavaScript on the other side of the JSON is silent about it. And a value the
spec's normative schemas name as belonging to an enum, with no counterpart in
the Literals here: prose and type drift apart with nothing comparing them.

What this cannot see, so that the limits are stated rather than discovered:

- A reader is a textual match, not a parse. A DOM property, a local variable or
  a key of some unrelated object with the same name credits a field nothing
  actually reads -- the receipt's `updates` is credited today by a read of a log
  entry's `payload.updates`. A match is evidence, not proof.
- Only the page's own `<script>` block is searched; the CSS is left out, because
  a class selector reads the same as a property access under a textual match.
  The popped-out thread window's boot script is a JavaScript string inside that
  block, so its readers do count -- as ordinary text, indistinguishable from a
  mention in a comment.
- Only three reader shapes are recognised: `.name`, `["name"]` and `"name":`.
  The page uses no destructuring or computed keys today; a field read only that
  way would fail here as unread -- loudly, and the fix is this list, not the
  page.
- Only endpoints the page fetches by literal path are walked. A path assembled
  at runtime is invisible, and so is every response model behind it.
- Fields inside an untyped mapping have no declaration to walk. `talk`, `mandate`
  and a log entry's `payload` are `dict`s, so their keys -- the `why` and `zoom`
  seeds among them -- are outside the field half of this check entirely.
- The enum half is one-directional. A spec value with no Literal fails; a Literal
  value the spec never names does not, because the Literals carry states the
  normative schemas were never meant to enumerate.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, get_args, get_origin

from pydantic import BaseModel

from grillui import schemas
from grillui.api import PAGE, create_app

if TYPE_CHECKING:
    from fastapi import FastAPI

    from grillui.log import SessionLog

# The spec, from this file rather than from the working directory: the package
# gate runs pytest with the package as its cwd.
SPEC = Path(__file__).resolve().parents[4] / "docs" / "specs" / "2026-08-18-grilling-ui-v1.md"

# Field names this check makes no claim about. A name here is neither reported
# nor credited, and each one is here for a reason that is not "it was failing".
UNCHECKED = frozenset(
    {
        # The accepted receipt answers whichever client authored the write, and
        # these four are addressed to an agent reasoning about its own next turn
        # rather than to the page: `node` echoes the decision a fold will
        # materialise, and `applied`/`as`/`amendments` say what the backend landed
        # instead of what was sent. A page that renders none of them is not a page
        # missing anything.
        "applied",
        "as",
        "amendments",
        "node",
    }
)

# A backticked token as the spec writes an enum member: lowercase, hyphens.
MEMBER = r"`([a-z][a-z0-9-]*)`"
# The two shapes the spec's §8 enum sentences actually take. Both are runs of
# backticked tokens; what separates an enum from the field lists that surround
# it is the joiner. An enum either ends in `... or `x`` -- "`sent` or `amended`",
# "`open`, `parked`, `closed` or `folded`" -- or is introduced by "one of". A
# field list ("`id`, `title`, `created`, `ended`, all strings") is comma-only and
# uninitiated, and a pair joined by "and" is prose, so neither shape takes them.
ENUM_RUN = re.compile(rf"{MEMBER}(?:,\s+{MEMBER})*,?\s+or\s+{MEMBER}")
ENUM_ONE_OF = re.compile(rf"one of\s+({MEMBER}(?:,\s+{MEMBER})*)")

FETCH = re.compile(r"""srv(?:Get|Post)\(\s*["'](/[a-z0-9_-]+)["']""")


def page_script(html: str) -> str:
    """The page's script, without its stylesheet."""
    return html.split("<script>", 1)[1].rsplit("</script>", 1)[0]


def fetched_paths(script: str) -> set[str]:
    """The endpoint paths the page asks for by name."""
    return set(FETCH.findall(script))


def wire_names(annotation: Any, seen: set[type[BaseModel]] | None = None) -> set[str]:
    """Every field name reachable from a response model, as it goes on the wire.

    The alias wins where there is one, because the alias is what the page sees.
    """
    seen = set() if seen is None else seen
    names: set[str] = set()
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in seen:
            return names
        seen.add(annotation)
        for name, field in annotation.model_fields.items():
            names.add(field.alias or name)
            names |= wire_names(field.annotation, seen)
        return names
    for argument in get_args(annotation):
        names |= wire_names(argument, seen)
    return names


def page_visible_fields(app: FastAPI, paths: set[str]) -> set[str]:
    """What the backend projects into the payloads the page fetches."""
    names: set[str] = set()
    for route in app.routes:
        model = getattr(route, "response_model", None)
        if model is not None and getattr(route, "path", None) in paths:
            names |= wire_names(model)
    return names


def has_reader(script: str, name: str) -> bool:
    """Whether the page reads a field of this name, crudely: a property access,
    a subscript by string key, or an object literal declaring the key."""
    quoted = re.escape(name)
    return any(
        re.search(pattern, script)
        for pattern in (
            rf"\.{quoted}\b",
            rf"""\[\s*["']{quoted}["']\s*\]""",
            rf"""["']{quoted}["']\s*:""",
        )
    )


def unread_fields(script: str, names: set[str], unchecked: frozenset[str] = UNCHECKED) -> list[str]:
    """The projected fields no page code reads."""
    return sorted(n for n in names - unchecked if not has_reader(script, n))


def spec_enum_values(section: str) -> set[str]:
    """Every value the section's enum sentences name."""
    values: set[str] = set()
    for run in ENUM_RUN.finditer(section):
        values |= set(re.findall(MEMBER, run.group(0)))
    for introduced in ENUM_ONE_OF.finditer(section):
        values |= set(re.findall(MEMBER, introduced.group(1)))
    return values


def literal_values(annotation: Any, seen: set[type[BaseModel]] | None = None) -> set[str]:
    """Every string a Literal in this annotation admits."""
    seen = set() if seen is None else seen
    if get_origin(annotation) is Literal:
        return {a for a in get_args(annotation) if isinstance(a, str)}
    values: set[str] = set()
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in seen:
            return values
        seen.add(annotation)
        for field in annotation.model_fields.values():
            values |= literal_values(field.annotation, seen)
        return values
    for argument in get_args(annotation):
        values |= literal_values(argument, seen)
    return values


def declared_literals() -> set[str]:
    """The union of every Literal the schemas declare -- the standalone aliases
    and the ones written inline on a model's field."""
    values: set[str] = set()
    for member in vars(schemas).values():
        values |= literal_values(member)
    return values


def normative_schemas() -> str:
    """The spec's normative-schema section, and nothing around it."""
    return SPEC.read_text(encoding="utf-8").split("## 8. Normative schemas", 1)[1].split("## 9.")[0]


def test_every_page_visible_field_has_a_page_reader(log: SessionLog) -> None:
    script = page_script(PAGE.read_text(encoding="utf-8"))
    paths = fetched_paths(script)
    assert paths, "the page fetches nothing this check can recognise"
    names = page_visible_fields(create_app(log), paths)
    assert len(names) > 20, "the walk found too few fields to be walking the images"
    assert unread_fields(script, names) == []


def test_every_spec_enum_value_has_a_literal() -> None:
    values = spec_enum_values(normative_schemas())
    assert len(values) > 10, "the enum sentences matched too little to be reading section 8"
    assert sorted(values - declared_literals()) == []


def test_a_projected_field_with_no_reader_is_named() -> None:
    script = "var a = node.title; var b = node.turns;"
    assert unread_fields(script, {"title", "turns", "tier"}) == ["tier"]


def test_the_allowlist_suppresses_an_unread_field() -> None:
    script = "var a = node.title;"
    assert unread_fields(script, {"title", "tier"}, unchecked=frozenset({"tier"})) == []


def test_a_spec_enum_value_with_no_literal_is_named() -> None:
    section = "- `state` — one of `open`, `parked`, `abandoned`;\n- `tier` — `fast` or `warm`.\n"
    assert sorted(spec_enum_values(section) - declared_literals()) == ["abandoned", "warm"]


def test_a_field_list_is_not_read_as_an_enum() -> None:
    section = "- `session` — object: `id`, `title`, `created`, `ended`, all strings.\n"
    assert spec_enum_values(section) == set()


def test_the_page_script_excludes_the_stylesheet() -> None:
    page = "<style>.tier { color: red }</style><script>var a = 1;</script>"
    assert "tier" not in page_script(page)
