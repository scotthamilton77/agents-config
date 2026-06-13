"""Tests for ``fetch_thread_id_map`` — the shared REST→GraphQL thread key bridge.

poll and snapshot both ingest review comments over REST (which exposes only the
comment ``databaseId``) but must key threads by the GraphQL ``reviewThreads`` node
id (``PRRT_*``) that ``Identity.thread_id`` is defined as and ``resolveReviewThread``
consumes. ``fetch_thread_id_map`` runs the one GraphQL query that bridges the two
key-spaces. The only mock point is the subprocess boundary (``RecordedRunner``).
"""

from __future__ import annotations

import json

from prgroom.gh import GhCli
from prgroom.gh.review_threads import fetch_thread_id_map
from prgroom.proc import CommandResult
from prgroom.prsession.pr_ref import PRRef
from tests.fakes import RecordedRunner

_REF = PRRef(owner="octo", repo="demo", number=7)


def _graphql(nodes: list[dict[str, object]]) -> CommandResult:
    """A gh-api-graphql success envelope carrying ``reviewThreads.nodes``."""
    envelope = {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": nodes}}}}}
    return CommandResult(returncode=0, stdout=json.dumps(envelope), stderr="")


def test_maps_every_comment_database_id_to_its_thread_node_id() -> None:
    # Two threads; the first has a root comment + a reply. Every comment's
    # databaseId must resolve to ITS thread's node id (siblings share a node id).
    nodes = [
        {"id": "PRRT_a", "comments": {"nodes": [{"databaseId": 101}, {"databaseId": 102}]}},
        {"id": "PRRT_b", "comments": {"nodes": [{"databaseId": 201}]}},
    ]
    gh = GhCli(RecordedRunner([_graphql(nodes)]))
    assert fetch_thread_id_map(gh, _REF) == {
        "101": "PRRT_a",
        "102": "PRRT_a",
        "201": "PRRT_b",
    }


def test_empty_map_when_pr_has_no_threads() -> None:
    gh = GhCli(RecordedRunner([_graphql([])]))
    assert fetch_thread_id_map(gh, _REF) == {}


def test_skips_comments_without_a_database_id() -> None:
    # databaseId is nullable in GraphQL (e.g. a pending review comment has no REST
    # representation) — such a comment contributes no key, but its siblings still do.
    nodes = [{"id": "PRRT_a", "comments": {"nodes": [{"databaseId": None}, {"databaseId": 102}]}}]
    gh = GhCli(RecordedRunner([_graphql(nodes)]))
    assert fetch_thread_id_map(gh, _REF) == {"102": "PRRT_a"}


def test_empty_map_when_response_shape_is_degenerate() -> None:
    # A 200 with a hollow data envelope (no repository/pullRequest) yields an empty
    # map rather than crashing — the guard branches must short-circuit cleanly.
    result = CommandResult(returncode=0, stdout=json.dumps({"data": {}}), stderr="")
    gh = GhCli(RecordedRunner([result]))
    assert fetch_thread_id_map(gh, _REF) == {}


def test_issues_a_graphql_query_against_the_pr() -> None:
    runner = RecordedRunner([_graphql([])])
    fetch_thread_id_map(GhCli(runner), _REF)
    argv = runner.calls[0]
    assert argv[:3] == ["gh", "api", "graphql"]
    # The PR coordinates ride as typed GraphQL variables (-F coerces pr to Int).
    assert "owner=octo" in argv
    assert "repo=demo" in argv
    assert "pr=7" in argv
