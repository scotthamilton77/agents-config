"""`work search` against a real backend holding more than one page of matches.

The hermetic tests pin the argv the adapter sends. Only a real backend can
show what that argv buys, and each of the three narrowings this fixture is
built to catch is invisible to a fake: a scripted runner returns whatever it
was scripted with, so it cannot truncate at a page boundary, cannot hide a
closed row, and cannot decline to look at a description.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from tests.integration.conftest import _bd_init, _make_driver, _run_bd

# One more than the backend's own default page, so a search that inherited
# that default comes back visibly short.
_PAGEFUL = 60
_TITLE_WORD = "pagefulword"
_DESCRIPTION_WORD = "descriptiononlyword"
_NOTES_WORD = "notesonlyword"
_CLOSED_WORD = "closedonlyword"


def _seed_lines() -> list[dict[str, object]]:
    lines: list[dict[str, object]] = [
        {"title": f"{_TITLE_WORD} match {i}", "issue_type": "task", "priority": 2}
        for i in range(_PAGEFUL)
    ]
    lines.append(
        {
            "title": "an item whose title says nothing",
            "issue_type": "task",
            "priority": 2,
            "description": f"the word {_DESCRIPTION_WORD} lives only here",
        }
    )
    lines.append({"title": "an item annotated later", "issue_type": "task", "priority": 2})
    lines.append({"title": f"{_CLOSED_WORD} work already finished", "issue_type": "task"})
    return lines


@pytest.fixture(scope="module")
def search_driver(bd_binary: str, tmp_path_factory: pytest.TempPathFactory):
    """One seeded install for the whole module: 63 items is too slow per test."""
    install = tmp_path_factory.mktemp("search_corpus_beads")
    _bd_init(bd_binary, install)

    seed = Path(install) / "seed.jsonl"
    seed.write_text("\n".join(json.dumps(line) for line in _seed_lines()) + "\n", encoding="utf-8")
    _run_bd(bd_binary, install, "import", str(seed))

    listing = json.loads(_run_bd(bd_binary, install, "list", "--json", "--limit", "0").stdout)
    by_title = {item["title"]: item["id"] for item in listing}
    _run_bd(bd_binary, install, "close", by_title[f"{_CLOSED_WORD} work already finished"])
    _run_bd(
        bd_binary,
        install,
        "note",
        by_title["an item annotated later"],
        f"a note mentioning {_NOTES_WORD}",
    )

    return _make_driver(bd_binary, install)


def _titles(driver: Callable[[Sequence[str]], dict], argv: Sequence[str]) -> list[str]:
    envelope = driver(argv)
    assert envelope["ok"] is True, envelope
    return [item["title"] for item in envelope["data"]["items"]]


def test_a_match_set_larger_than_one_page_arrives_whole(search_driver):
    # The backend's own default caps this at 50 and says nothing about it.
    assert len(_titles(search_driver, ["search", _TITLE_WORD])) == _PAGEFUL


def test_a_word_only_in_a_description_finds_its_item(search_driver):
    assert _titles(search_driver, ["search", _DESCRIPTION_WORD]) == [
        "an item whose title says nothing"
    ]


def test_a_word_only_in_a_note_finds_its_item(search_driver):
    assert _titles(search_driver, ["search", _NOTES_WORD]) == ["an item annotated later"]


def test_a_closed_item_is_still_found(search_driver):
    envelope = search_driver(["search", _CLOSED_WORD])

    assert envelope["ok"] is True, envelope
    assert [item["status"] for item in envelope["data"]["items"]] == ["closed"]


def test_the_caller_can_narrow_all_three_axes(search_driver):
    # Corpus: the description word is invisible to a title-only search.
    assert _titles(search_driver, ["search", _DESCRIPTION_WORD, "--in", "title"]) == []
    # Status: the closed item drops out of an open-only search.
    assert _titles(search_driver, ["search", _CLOSED_WORD, "--status", "open"]) == []
    # Bound: the caller's own cap is honored on the merged set.
    assert len(_titles(search_driver, ["search", _TITLE_WORD, "--limit", "3"])) == 3
