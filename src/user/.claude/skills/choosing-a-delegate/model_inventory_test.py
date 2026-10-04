#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest>=8"]
# ///
"""A lint that keeps the model routing table the only model inventory under src/.

The lint reads every Markdown file under ``src/`` except those beneath an
``evals/`` directory. It fails when a file names a model id the routing table
does not list, when a Markdown table row outside the routing table names any
model id, when the routing table's shape grows past its two tables and their
columns, and when the routing table is absent or lists no model id.

The lint and its cases live in this one suite, so ``make content-tests`` runs
both and nothing here deploys.

Run: uv run model_inventory_test.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

TABLE_REL = Path("user/.claude/skills/choosing-a-delegate/references/model-routing.md")

# One pattern per vendor naming scheme. Model ids are lowercase in every
# vendor's API, so the patterns are case-sensitive and a prose family name
# such as "GPT-6" is not read as an id. The OpenRouter ids carry their vendor
# prefix, which keeps a file name like "kimi-k3.md" from reading as an id.
# Extend this list when a vendor invents a new scheme.
ID_PATTERNS = (
    r"(?:anthropic/)?claude-[a-z]+-\d[a-z0-9.-]*",
    r"(?:openai/)?gpt-\d[a-z0-9.-]*",
    r"google/gemini-\d[a-z0-9.-]*",
    r"gemini-\d[a-z0-9.-]*",
    r"moonshotai/kimi-[a-z0-9.-]+",
    r"z-ai/glm-\d[a-z0-9.-]*",
)
# The look-behind stops a match from starting inside a longer token, so the
# agy pattern never fires on the tail of an OpenRouter Gemini id.
_ID = re.compile(r"(?<![\w/.-])(?:" + "|".join(ID_PATTERNS) + ")")

# A separator line is what makes a run of piped lines a Markdown table, with or
# without outer pipes.
_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")

# The first column of the tier grid is its row label, so it is allowed beside
# the four providers. The models table's model column carries a parenthetical
# in its header, so it is matched by its first word.
GRID_COLUMNS = ("tier", "anthropic", "openai", "google", "openrouter")
MODELS_COLUMNS = ("provider", "model", "in / out", "context", "accepted efforts")

_SKIPPED_DIRS = {"evals", "node_modules"}


def _ids(text: str) -> list[str]:
    # A sentence can end right after an id, so a trailing full stop is prose.
    return [m.group(0).rstrip(".-") for m in _ID.finditer(text)]


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _tables(lines: list[str]) -> list[tuple[int, list[str], list[int]]]:
    """Every Markdown table as (header line index, header cells, row line indexes)."""
    tables = []
    for i, line in enumerate(lines):
        if i == 0 or not _SEPARATOR.match(line) or "|" not in lines[i - 1]:
            continue
        rows = []
        j = i + 1
        while j < len(lines) and "|" in lines[j]:
            rows.append(j)
            j += 1
        tables.append((i - 1, _cells(lines[i - 1]), rows))
    return tables


def _header_key(cell: str) -> str:
    key = cell.replace("`", "").strip().lower()
    return "model" if key.startswith("model") else key


def _role(header: list[str]) -> str | None:
    """Which of the routing table's two tables a header opens, or None for any other table."""
    keys = [_header_key(c) for c in header]
    if keys[:1] == ["tier"]:
        return "tier grid"
    if keys[:2] == ["provider", "model"]:
        return "models table"
    return None


def _column_violations(where: str, name: str, header: list[str], expected: tuple[str, ...]) -> list[str]:
    keys = [_header_key(c) for c in header]
    out = [f"{where}: the {name} has column '{c}', which it may not hold" for c, k in zip(header, keys) if k not in expected]
    out += [f"{where}: the {name} lacks its '{e}' column" for e in expected if e not in keys]
    return out


def lint(src_root: Path) -> tuple[list[Path], list[str]]:
    """Lint the Markdown under ``src_root`` and return the files read and the violations.

    An empty violation list is a pass. A routing table that is absent, or that
    lists no model id, ends the run before any other file is read, because there
    is nothing to compare the other files against.
    """
    table_path = src_root / TABLE_REL
    if not table_path.is_file():
        return [], [f"{table_path}: the model routing table is absent"]

    table_lines = table_path.read_text(encoding="utf-8").splitlines()
    roles: dict[str, tuple[int, list[str], list[int]]] = {}
    violations = []
    for table in _tables(table_lines):
        role = _role(table[1])
        if role is None or role in roles:
            violations.append(
                f"{table_path}:{table[0] + 1}: the routing table holds a third table, "
                f"headed '{' | '.join(table[1])}'"
            )
        else:
            roles[role] = table
    for role, expected in (("tier grid", GRID_COLUMNS), ("models table", MODELS_COLUMNS)):
        if role in roles:
            line, header, _ = roles[role]
            violations += _column_violations(f"{table_path}:{line + 1}", role, header, expected)

    listed = set()
    for row in roles.get("models table", (0, [], []))[2]:
        cells = _cells(table_lines[row])
        if len(cells) > 1:
            listed.update(_ids(cells[1]))
    if not listed:
        return [], [*violations, f"{table_path}: the model routing table lists no model id"]

    files = sorted(
        p for p in src_root.rglob("*.md")
        if p.is_file() and not _SKIPPED_DIRS.intersection(p.relative_to(src_root).parts)
    )
    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        for n, text in enumerate(lines, start=1):
            for model in _ids(text):
                if model not in listed:
                    violations.append(f"{path}:{n}: names model id {model}, which the routing table does not list")
        if path == table_path:
            continue
        for _, _, rows in _tables(lines):
            for row in rows:
                for model in _ids(lines[row]):
                    violations.append(
                        f"{path}:{row + 1}: a table row names model id {model}; only the routing table may tabulate models"
                    )
    return files, violations


# --- Fixtures --------------------------------------------------------------

GRID = """| Tier | `anthropic` | `openai` | `google` | `openrouter` |
|---|---|---|---|---|
| `mid` | `sonnet` | `gpt-6.1-sol` | `gemini-3.8-flash` | `z-ai/glm-5.3` |
"""

MODELS_HEADER = "| Provider | Model (the `model` or `--model` value) | In / Out | Context | Accepted efforts |\n|---|---|---|---|---|\n"

ROWS = {
    "claude-opus-5-5": "| `anthropic` | `claude-opus-5-5` | $4.00 / $20.00 | 1M | `high` |",
    "gpt-6.1-sol": "| `openai` | `gpt-6.1-sol` | $2.00 / $10.00 | 272K | `high` |",
    "gemini-3.8-flash": "| `google` | `gemini-3.8-flash` | subscription | 1M | `low` |",
    "google/gemini-3.8-flash": "| `openrouter` | `google/gemini-3.8-flash` | $0.75 / $3.75 | 1M | `low` |",
    "moonshotai/kimi-k3": "| `openrouter` | `moonshotai/kimi-k3` | $0.70 / $10.00 | 1M | `low` |",
    "z-ai/glm-5.3": "| `openrouter` | `z-ai/glm-5.3` | $0.22 / $4.40 | 1M | `low` |",
}


def routing_table(rows=tuple(ROWS.values()), grid=GRID, models_header=MODELS_HEADER, extra=""):
    return f"# Model routing table\n\n## Pick by tier\n\n{grid}\n## Models\n\n{models_header}" + "\n".join(rows) + f"\n{extra}"


def tree(tmp_path: Path, files: dict[str, str], table: str | None = None) -> Path:
    """Build a src/ tree holding the routing table and ``files``, and return its root."""
    src = tmp_path / "src"
    if table is None:
        table = routing_table()
    if table:
        (src / TABLE_REL).parent.mkdir(parents=True)
        (src / TABLE_REL).write_text(table)
    for rel, text in files.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text)
    return src


SKILL = "user/.claude/skills/some-skill/SKILL.md"


# --- DEL-A1: an unlisted id anywhere fails, naming the file and the id ----

UNLISTED = [
    ("claude", "claude-quill-1-0"), ("claude", "claude-opus-5-6"),
    ("gpt", "gpt-7-nova"), ("gpt", "gpt-6.2-sol"),
    ("gemini-agy", "gemini-9-ultra"), ("gemini-agy", "gemini-3.9-flash"),
    ("gemini-openrouter", "google/gemini-9-ultra"), ("gemini-openrouter", "google/gemini-3.9-flash"),
    ("kimi", "moonshotai/kimi-x1"), ("kimi", "moonshotai/kimi-k4"),
    ("glm", "z-ai/glm-9-air"), ("glm", "z-ai/glm-5.4"),
]


@pytest.mark.parametrize(("vendor", "model"), UNLISTED, ids=[m for _, m in UNLISTED])
def test_del_a1_unlisted_id_in_a_sentence_fails_naming_file_and_id(tmp_path, vendor, model):
    src = tree(tmp_path, {SKILL: f"# Skill\n\nDispatch the review to `{model}` at `high`.\n"})
    _, violations = lint(src)
    assert len(violations) == 1, violations
    assert f"{src / SKILL}:3:" in violations[0]
    assert model in violations[0]


def test_del_a1_unlisted_id_three_directories_below_src_fails(tmp_path):
    rel = "one/two/three/notes.md"
    src = tree(tmp_path, {rel: "Try gpt-7-nova next.\n"})
    _, violations = lint(src)
    assert violations == [f"{src / rel}:1: names model id gpt-7-nova, which the routing table does not list"]


@pytest.mark.parametrize("model", list(ROWS))
def test_del_a1_listed_id_in_a_sentence_passes(tmp_path, model):
    src = tree(tmp_path, {SKILL: f"Dispatch the review to `{model}`.\n"})
    files, violations = lint(src)
    assert violations == []
    assert src / SKILL in files


# --- DEL-A2: the landed tree passes ----------------------------------------


def test_del_a2_landed_tree_passes():
    src_root = Path(__file__).resolve().parents[4]
    assert src_root.name == "src", src_root
    files, violations = lint(src_root)
    print(f"\nmodel inventory lint read {len(files)} files under {src_root}:")
    for path in files:
        print(f"  {path.relative_to(src_root)}")
    assert violations == [], "\n".join(violations)
    assert src_root / TABLE_REL in files


# --- DEL-A3: a fenced example passes only while its id is listed -----------

FENCED = "Run it:\n\n```bash\ncodex exec --model gpt-6.1-sol --effort high\n```\n"


def test_del_a3_fenced_example_with_listed_id_fails_once_its_row_is_removed(tmp_path):
    src = tree(tmp_path, {SKILL: FENCED})
    assert lint(src)[1] == []
    rows = [r for model, r in ROWS.items() if model != "gpt-6.1-sol"]
    src = tree(tmp_path / "unlisted", {SKILL: FENCED}, routing_table(rows=rows, grid=GRID.replace("`gpt-6.1-sol`", "")))
    assert lint(src)[1] == [f"{src / SKILL}:4: names model id gpt-6.1-sol, which the routing table does not list"]


# --- DEL-A4: nothing under an evals/ directory is read --------------------


@pytest.mark.parametrize("rel", [
    "user/.claude/skills/some-skill/evals/queries.md",
    "user/.claude/skills/some-skill/evals/one/two/queries.md",
])
def test_del_a4_evals_directory_is_not_read(tmp_path, rel):
    src = tree(tmp_path, {rel: "Can you run gpt-7-nova?\n", SKILL: "# Skill\n"})
    files, violations = lint(src)
    assert violations == []
    assert src / SKILL in files
    assert src / rel not in files


# --- DEL-A5: an absent or empty routing table fails and names it ----------


def test_del_a5_absent_routing_table_fails_naming_it(tmp_path):
    src = tree(tmp_path, {SKILL: "Use gpt-6.1-sol.\n"}, table="")
    assert lint(src)[1] == [f"{src / TABLE_REL}: the model routing table is absent"]


def test_del_a5_routing_table_listing_no_id_fails_naming_it(tmp_path):
    src = tree(tmp_path, {SKILL: "# Skill\n"}, routing_table(rows=["| `anthropic` | `opus` | $4.00 / $20.00 | 1M | `high` |"]))
    assert lint(src)[1] == [f"{src / TABLE_REL}: the model routing table lists no model id"]


# --- DEL-A6: a table row outside the routing table may not name an id -----

SECOND_INVENTORIES = {
    "copied-routing-row": MODELS_HEADER + ROWS["z-ai/glm-5.3"] + "\n",
    "id-tier-effort": "| Tier | Model | Effort |\n|---|---|---|\n| mid | `gpt-6.1-sol` | high |\n",
    "id-purpose-outer-pipes": "| Model | Purpose |\n|---|---|\n| `gpt-6.1-sol` | review |\n",
    "id-purpose-no-outer-pipes": "Model | Purpose\n--- | ---\n`gpt-6.1-sol` | review\n",
}


@pytest.mark.parametrize("table", list(SECOND_INVENTORIES.values()), ids=list(SECOND_INVENTORIES))
def test_del_a6_table_row_naming_a_listed_id_fails_naming_file_and_line(tmp_path, table):
    src = tree(tmp_path, {SKILL: "# Skill\n\n" + table})
    violations = lint(src)[1]
    assert len(violations) == 1, violations
    assert violations[0].startswith(f"{src / SKILL}:5: a table row names model id ")


def test_del_a6_same_id_in_a_prose_sentence_passes(tmp_path):
    src = tree(tmp_path, {SKILL: "# Skill\n\nThe mid reviewer is `gpt-6.1-sol` at `high`, for review.\n"})
    files, violations = lint(src)
    assert violations == []
    assert src / SKILL in files


# --- DEL-A7: the routing table keeps its two tables and their columns ----


def test_del_a7_extra_tier_grid_column_fails_naming_it(tmp_path):
    grid = GRID.replace("`openrouter` |\n|---|", "`openrouter` | `xai` |\n|---|---|").replace("`z-ai/glm-5.3` |", "`z-ai/glm-5.3` | |")
    src = tree(tmp_path, {}, routing_table(grid=grid))
    violations = lint(src)[1]
    assert len(violations) == 1, violations
    assert "tier grid has column '`xai`'" in violations[0]


def test_del_a7_extra_models_column_fails_naming_it(tmp_path):
    header = MODELS_HEADER.replace("Accepted efforts |\n|---|", "Accepted efforts | Scope |\n|---|---|")
    src = tree(tmp_path, {}, routing_table(models_header=header))
    violations = lint(src)[1]
    assert len(violations) == 1, violations
    assert "models table has column 'Scope'" in violations[0]


def test_del_a7_dropped_models_column_fails_naming_it(tmp_path):
    header = MODELS_HEADER.replace(" Context |", "").replace("|---|---|---|---|---|", "|---|---|---|---|")
    src = tree(tmp_path, {}, routing_table(models_header=header))
    violations = lint(src)[1]
    assert len(violations) == 1, violations
    assert "models table lacks its 'context' column" in violations[0]


def test_del_a7_third_table_fails_naming_it(tmp_path):
    table = routing_table(extra="\n## Seats\n\n| Seat | Effort |\n|---|---|\n| mid | `high` |\n")
    src = tree(tmp_path, {}, table)
    line = table.splitlines().index("| Seat | Effort |") + 1
    assert lint(src)[1] == [
        f"{src / TABLE_REL}:{line}: the routing table holds a third table, headed 'Seat | Effort'"
    ]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-s"]))
