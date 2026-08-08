"""The scrubber: every spelling of the backend's identity it removes, and nothing else.

`redact` is the only mechanical guard over the one text the prose rule and its
AST scan cannot reach -- the sentences the backend writes at runtime, which no
reviewer can read before they exist. What the guard misses it misses silently:
the envelope leaves looking scrubbed either way, and the caller has no way to
tell a clean sentence from one that was never matched.

So the spellings are named here one at a time rather than checked by driving
the pattern's own alternation. A test that read the pattern would ratify
whatever the pattern happens to say and would go green the moment someone
shortened it; naming each spelling is a second, independent statement of what
this backend is called.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from workcli.adapters.bd.vocabulary import redact

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


# ── every spelling, named one at a time ──────────────────────────────────
#
# The placeholder is spelled out in each expectation rather than imported,
# for the same reason the spellings are: an expectation built from the
# module under test agrees with it by construction.
#
# Four names identify this backend: its binary, the plural noun that also
# names its environment variable and its storage directory, the singular noun
# it uses for one item, and the storage engine underneath. The singular was
# the spelling the pattern missed -- and it is the one whose removal from the
# facade's own vocabulary was a whole piece of earlier work, so a sentence
# carrying it back out undoes that quietly.
#
# The sentences are the backend's, not invented: the first three are captured
# failures this adapter has met, and the singular-noun cases are lifted
# verbatim from the backend's own help output (`bd --help`, `bd create
# --help`, `bd list --help` at version 1.0.3), which is where its user-facing
# vocabulary is authored.
@pytest.mark.parametrize(
    ("backend_text", "expected"),
    [
        # -- the binary --
        ("a bd error", "a [tracker] error"),
        ("run 'bd init' to create a new database", "run '[tracker] init' to create a new database"),
        # -- the plural noun, bare, dotted, and as an environment variable --
        ("no beads database found", "no [tracker] database found"),
        (
            "set BEADS_DIR to point to your .beads directory",
            "set [tracker]_DIR to point to your [tracker] directory",
        ),
        ("Back up your beads database", "Back up your [tracker] database"),
        # -- the singular noun: the spelling this file was written for --
        ("the bead was updated", "the [tracker] was updated"),
        ("Promote a wisp to a permanent bead", "Promote a wisp to a permanent [tracker]"),
        ("Entity URI or bead ID affected", "Entity URI or [tracker] ID affected"),
        ("Filter to descendants of this bead/epic", "Filter to descendants of this [tracker]/epic"),
        ("List child beads of a parent", "List child [tracker] of a parent"),
        # -- the storage engine --
        ("dolt push failed", "[tracker] push failed"),
        (
            "panic: dolt: runtime error at hash 0xdeadbeef",
            "panic: [tracker]: runtime error at hash 0xdeadbeef",
        ),
        # -- case is not a hiding place --
        ("Bead not found", "[tracker] not found"),
        ("BD exited nonzero", "[tracker] exited nonzero"),
        ("Beads is unreachable", "[tracker] is unreachable"),
        ("Dolt refused the write", "[tracker] refused the write"),
    ],
)
def test_every_spelling_of_the_backends_identity_is_scrubbed(
    backend_text: str, expected: str
) -> None:
    """
    Given a sentence the backend writes about itself
    When it is scrubbed on its way into a published field
    Then its name is gone and the diagnosis it carried is not.
    """
    assert redact(backend_text) == expected


def test_the_scrub_removes_the_identity_and_leaves_the_diagnosis() -> None:
    """
    Given the multi-line failure that names the backend three ways at once
    When it is scrubbed
    Then nothing of the backend's identity survives and the advice still reads.

    The missing-workspace report is the incident the scrubber was built for:
    one sentence carrying the binary, the environment variable and the storage
    directory. The scrub is deliberately narrow -- it takes the identity, not
    the diagnosis -- so the caller must still learn that a database is missing
    and that something can be run to create one.
    """
    scrubbed = redact(
        "Error: no beads database found\n"
        "Hint: run 'bd where' to inspect the resolved workspace, or 'bd init' to create a new "
        "database\n      or set BEADS_DIR to point to your .beads directory\n"
    )

    assert "database" in scrubbed
    assert "to create a new" in scrubbed
    for spelling in ("bd", "bead", "beads", "dolt"):
        assert spelling not in scrubbed.lower()


# ── nothing but the identity is touched ──────────────────────────────────

# The four names, lowercased: the closed set of things a redaction is allowed
# to have eaten out of real backend text.
_IDENTITY_SPELLINGS = frozenset({"bd", "bead", "beads", "dolt"})

# A generic word splitter -- deliberately not the scrubber's pattern, which is
# the thing under test. Word edges here are every non-alphanumeric character,
# so `BEADS_DIR`, `.beads` and `bead's` each come apart into the name and the
# characters around it.
_WORD_PARTS = re.compile(r"[^A-Za-z0-9]+")


def _captured_backend_words() -> list[str]:
    """Every distinct word in this package's real captured backend output.

    The JSON fixtures are output captured verbatim from the live backend, and
    they carry both the backend's own vocabulary and whatever prose users typed
    into item titles, descriptions and notes -- which is the widest sample of
    real text this package holds, and the sample a scrubber would mangle.
    """
    words: set[str] = set()
    for fixture in sorted(FIXTURES.glob("*.json")):
        words.update(
            part for part in _WORD_PARTS.split(fixture.read_text(encoding="utf-8")) if part
        )
    return sorted(words)


def test_the_corpus_is_big_enough_and_contains_the_spelling_at_issue() -> None:
    """
    Given the captured-output corpus the next test scans
    When it is read
    Then it is substantial and it does contain the singular noun.

    The control. The scan below is an assertion over a comprehension and would
    pass over an empty corpus, and it would pass just as quietly over a corpus
    that never happened to contain the spelling this file exists for.
    """
    words = _captured_backend_words()

    assert len(words) > 500
    assert "bead" in words
    assert "beads" in words


def test_no_word_of_real_backend_text_is_mangled_by_the_scrub() -> None:
    """
    Given every word the backend has actually been captured emitting
    When each one is scrubbed
    Then the only ones that change are the backend's four names.

    The widening risk runs the other way from the leak: an alternation loose
    enough to catch the singular noun could also eat an ordinary English word,
    and a diagnostic mangled into nonsense costs a caller the one thing an
    unrecognised failure had left to give. Measured against real captured text
    rather than argued about -- if the word edges ever slip, a word from this
    corpus lands in `mangled` and names itself.
    """
    mangled = [
        word
        for word in _captured_backend_words()
        if redact(word) != word and word.lower() not in _IDENTITY_SPELLINGS
    ]

    assert mangled == []


@pytest.mark.parametrize(
    "word",
    [
        "abdicate",  # the binary, mid-word
        "subdivide",
        "beadle",  # the singular noun, as a prefix
        "beadwork",
        "beaded",
        "doltish",  # the storage engine, as a prefix
        "embedded",
        "wisp",  # a backend concept, not its identity
    ],
)
def test_an_ordinary_word_that_merely_contains_a_name_survives(word: str) -> None:
    """
    Given an English word one of the backend's names sits inside
    When it is scrubbed
    Then it comes through untouched.

    The word edges are what make the alternation safe to widen, so they are
    asserted directly rather than left as a property of the corpus above --
    the corpus contains what the backend happened to write, not the cases a
    future widening would break.
    """
    assert redact(word) == word
