"""What a replayed reply has to satisfy, one named behaviour at a time.

Every check answers with the reason it failed or with nothing, so a red cell in
the matrix names the behaviour that regressed rather than the case that noticed.
Nothing here judges prose: each reads the map document the turn returned.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from grillui.drivers import document_problem
from grillui.schemas import GrillMasterDocument

SPEAKING_KIND = "informational"
SUBSTANCE = ("short", "title", "body", "options")
# An option is named by a letter, and the decision it belongs to by an id. A
# reply that says "option b" leaves the human to guess which board row moved.
OPTION = re.compile(r"\boptions?\s+([a-z])\b", re.IGNORECASE)
DECISION = re.compile(r"\b(?:d\d+|n-\d+-\d+)\b", re.IGNORECASE)
# Wide enough to hold "option b of d1" and "d2's option a" either way round.
QUALIFYING = 24


def the_reply_is_the_map_document(reply: str) -> str | None:
    """The turn came back in the one shape the board reads."""
    return document_problem(reply)


def the_rulings_are_the_ones_owed(document: GrillMasterDocument, owed: Sequence[str]) -> str | None:
    """Every decision the dispatch put in question is ruled on, and no other.

    Both directions matter. A missing ruling leaves a decision the human's own
    answer undermined standing as though it did not; an unowed one is the turn
    ruling on decisions nobody asked about, which is how five stands arrive on a
    turn that owed nothing.
    """
    ruled = sorted(one.decision for one in document.rulings)
    wanted = sorted(owed)
    if ruled == wanted:
        return None
    return f"rulings on {ruled or 'nothing'}, owed {wanted or 'nothing'}"


def added_nodes_carry_short_and_body(document: GrillMasterDocument) -> str | None:
    """A decision the turn adds arrives with the fields the board renders.

    The page draws a column from `short` and the question from `body`; a node
    missing either lands on the board as a blank the human cannot read.
    """
    thin = [
        one.get("title", "?")
        for one in document.updates
        if one.get("kind") == "add-node" and not (one.get("short") and one.get("body"))
    ]
    return None if not thin else f"add-node without short or body: {thin}"


def the_turn_speaks_once(document: GrillMasterDocument, limit: int = 1) -> str | None:
    """The turn addresses the human through one channel.

    A notice and a shelf of informational updates are two places the human has
    to read to learn one thing, and nothing tells them which is the answer.
    """
    speaking = sum(one.get("kind") == SPEAKING_KIND for one in document.updates)
    speaking += 1 if document.text.strip() else 0
    return None if speaking <= limit else f"{speaking} speech channels, at most {limit} allowed"


def option_references_name_their_decision(document: GrillMasterDocument) -> str | None:
    """An option is named with the decision it belongs to.

    The board carries an option `b` under most of its rows, so a bare letter is
    an instruction the human has to resolve against the whole map. Every place
    the turn speaks is read, because the human reads all of them and a rule that
    stopped at the notice would be satisfied by moving the sentence.
    """
    spoken = [document.text, *(str(one.get("text", "")) for one in document.updates)]
    bare = [
        found.group(0)
        for said in spoken
        for found in OPTION.finditer(said)
        if not DECISION.search(said[max(0, found.start() - QUALIFYING) : found.end() + QUALIFYING])
    ]
    return None if not bare else f"unqualified option references: {bare}"


def the_stop_verdict_is_expected(document: GrillMasterDocument, expected: bool) -> str | None:
    """The turn agrees with the case about whether the grilling is over."""
    met = bool(document.stop.met)
    return None if met == expected else f"stop met is {met}, expected {expected}"


def a_revise_supplies_what_it_revises(document: GrillMasterDocument) -> str | None:
    """A revision changes the decision, rather than only saying why it should.

    A revise carrying nothing but a reason leaves the question on the board
    exactly as it was: the human reads a paragraph of disagreement and finds
    the decision they were asked about unchanged.
    """
    empty = [
        one.get("target", "?")
        for one in document.updates
        if one.get("kind") == "revise" and not any(one.get(field) for field in SUBSTANCE)
    ]
    return None if not empty else f"revise supplying no change: {empty}"
