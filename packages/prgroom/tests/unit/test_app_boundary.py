"""The App client's boundary property, as one corpus rather than case by case.

Whatever shape a response arrives in, only a :class:`PrgroomError` may leave the
client, and a read the client could not trust may not be followed by a review
submission. The corpus sweeps every payload position the client reads against
every JSON shape it could hold, so a field added later is covered without a new
test — and it sweeps both flows that reach GitHub as the App, because each calls
a different set of endpoints on the way to the same single submission.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from prgroom.errors import ErrorCode, PrgroomError
from prgroom.gh import app
from prgroom.gh.app import FILES_PER_PAGE, GITHUB_API, REVIEWS_PER_PAGE, UrllibTransport
from prgroom.lifecycle.approve import approve_pr
from prgroom.lifecycle.post_verdict import Verdict, post_verdict_pr, render_body
from prgroom.proc import CommandResult
from prgroom.prsession.pr_ref import PRRef
from tests.fakes import RecordedRunner, RouteTableHttp

HEAD = "a" * 40
APP_ID = 4275336
KEY_PATH = Path("/keys/app.pem")
REF = PRRef(owner="octo", repo="demo", number=5)
LOGIN = "pr-hater[bot]"

PULL = "/repos/octo/demo/pulls/5"
APP = ("GET", "/app")
INSTALLATION = ("GET", "/repos/octo/demo/installation")
TOKEN = ("POST", "/app/installations/42/access_tokens")
PULL_READ = ("GET", PULL)
REVIEWS_PAGE_1 = ("GET", f"{PULL}/reviews?per_page={REVIEWS_PER_PAGE}&page=1")
FILES_PAGE_1 = ("GET", f"{PULL}/files?per_page={FILES_PER_PAGE}&page=1")
SUBMIT = ("POST", f"{PULL}/reviews")

CHANGED = "src/app.py"
FILES: list[dict[str, Any]] = [{"filename": CHANGED, "patch": "@@ -1,2 +1,4 @@\n+added\n"}]

VERDICT_TEXT = json.dumps({"head_sha": HEAD, "findings": [{"id": "f1"}]})
VERDICT = Verdict(
    text=VERDICT_TEXT,
    head_sha=HEAD,
    findings=({"id": "f1", "evidence": f"{CHANGED}:2 is wrong"},),
)

BASE_ROUTES: dict[tuple[str, str], tuple[int, Any]] = {
    APP: (200, {"slug": "pr-hater"}),
    INSTALLATION: (200, {"id": 42}),
    TOKEN: (201, {"token": "tok"}),
    PULL_READ: (200, {"head": {"sha": HEAD}}),
    REVIEWS_PAGE_1: (200, []),
    FILES_PAGE_1: (200, FILES),
    SUBMIT: (200, {"id": 99}),
}

# Every JSON shape a field or a whole body can arrive as. The booleans are here
# because a JSON boolean decodes to a Python bool, which is an int subclass and
# would otherwise satisfy an integer check.
SHAPES: list[Any] = [None, True, False, 0, 1, -1, 3.5, "", "text", [], [1], {}, {"x": 1}]


def transport(routes: dict[tuple[str, str], tuple[int, Any]]) -> RouteTableHttp:
    """The App-HTTP fake with its credential rule armed for this App.

    Every construction in this module goes through here, so a call site that
    drops or swaps a credential is refused wherever one is added.
    """
    return RouteTableHttp(routes, app_id=APP_ID)


def signing_runner() -> RecordedRunner:
    return RecordedRunner([CommandResult(0, "SHA2-256(stdin)= 0a0b\n", "")])


def call_approve(http: RouteTableHttp) -> str:
    return approve_pr(
        http=http,
        runner=signing_runner(),
        ref=REF,
        head_sha=HEAD,
        facts="{}",
        app_id=APP_ID,
        key_path=KEY_PATH,
        now=1_000_000,
    )


def call_post_verdict(http: RouteTableHttp) -> str:
    return post_verdict_pr(
        http=http,
        runner=signing_runner(),
        ref=REF,
        verdict=VERDICT,
        app_id=APP_ID,
        key_path=KEY_PATH,
        now=1_000_000,
    )


@dataclass(frozen=True)
class Flow:
    """One App-authored path to a single review submission.

    The two differ in which endpoints they read on the way and in what makes a
    listed review their own; everything the boundary property asserts is the same
    for both, which is why they are swept together rather than duplicated.
    """

    call: Callable[[RouteTableHttp], str]
    read_routes: list[tuple[str, str]]
    own_review: dict[str, Any]


APPROVE_FLOW = Flow(
    call=call_approve,
    read_routes=[APP, INSTALLATION, TOKEN, PULL_READ, REVIEWS_PAGE_1],
    own_review={"state": "APPROVED", "commit_id": HEAD, "user": {"login": LOGIN}},
)

POST_VERDICT_FLOW = Flow(
    call=call_post_verdict,
    read_routes=[APP, INSTALLATION, TOKEN, PULL_READ, REVIEWS_PAGE_1, FILES_PAGE_1],
    own_review={
        "state": "COMMENTED",
        # The body a first posting left, which is the rendered one rather than the
        # file: an entry carrying the file's bytes is not this flow's own review.
        "body": render_body(VERDICT),
        "commit_id": HEAD,
        "user": {"login": LOGIN},
    },
)

FLOWS = [
    pytest.param(APPROVE_FLOW, id="the-approval"),
    pytest.param(POST_VERDICT_FLOW, id="the-verdict-posting"),
]


def routes_with(route: tuple[str, str], response: tuple[int, Any]) -> dict[tuple[str, str], Any]:
    patched = dict(BASE_ROUTES)
    patched[route] = response
    return patched


def assert_only_prgroom_error_escapes(
    flow: Flow,
    routes: dict[tuple[str, str], tuple[int, Any]],
    *,
    submission_reachable: bool,
) -> None:
    """Run the flow and require that any failure is a coded one.

    A malformed payload may be a shape the client legitimately accepts, so a clean
    completion is allowed. What is not allowed is another exception type, or a
    review posted after a read the client could not trust.
    """
    http = transport(routes)
    try:
        flow.call(http)
    except PrgroomError as err:
        # A malformed body is a failed API call, and its diagnostic has to say so
        # with the status the call answered on and what it answered with — a bare
        # code leaves the reader unable to tell a broken API from a wrong
        # expectation of it.
        assert err.code is ErrorCode.RUNTIME_APPROVER_API_FAILED
        assert "HTTP " in err.render()
        if not submission_reachable:
            assert http.posted_reviews() == []
    except Exception as exc:  # the property under test is that this never happens
        pytest.fail(f"{type(exc).__name__} escaped the App client: {exc}")


@pytest.mark.parametrize("flow", FLOWS)
@pytest.mark.parametrize("shape", SHAPES, ids=repr)
def test_a_malformed_body_on_any_read_is_a_coded_failure(flow: Flow, shape: Any) -> None:
    for route in flow.read_routes:
        assert_only_prgroom_error_escapes(
            flow, routes_with(route, (BASE_ROUTES[route][0], shape)), submission_reachable=False
        )


@pytest.mark.parametrize("flow", FLOWS)
@pytest.mark.parametrize("shape", SHAPES, ids=repr)
def test_a_malformed_submission_response_is_a_coded_failure(flow: Flow, shape: Any) -> None:
    assert_only_prgroom_error_escapes(
        flow, routes_with(SUBMIT, (200, shape)), submission_reachable=True
    )


# Entries the scan cannot trust: it matched this App's review and then could not
# read the id naming it, or could not read a login at all. Acting on a page it
# half-understood is how a duplicate review gets posted.
REVIEW_OVERRIDES_REJECTED = [
    pytest.param({}, id="a-match-with-no-id"),
    pytest.param({"id": "7"}, id="a-match-with-a-string-id"),
    pytest.param({"id": True}, id="a-match-with-a-boolean-id"),
    pytest.param({"id": None}, id="a-match-with-a-null-id"),
    pytest.param({"id": [7]}, id="a-match-with-a-list-id"),
    pytest.param({"user": "malformed"}, id="a-string-user"),
    pytest.param({"user": []}, id="a-list-user"),
    pytest.param({"user": {}}, id="a-user-with-no-login"),
    pytest.param({"user": {"login": 7}}, id="a-numeric-login"),
    pytest.param({"id": 7, "commit_id": 3}, id="a-numeric-commit-id"),
    pytest.param({"id": 7, "commit_id": []}, id="a-list-commit-id"),
    pytest.param({"id": 7, "state": 3}, id="a-numeric-state"),
]

# Well-formed entries that are simply not this App's review of this head, built
# from the flow's own review so each differs from a match in exactly one way. A
# null user is GitHub's shape for a deleted account.
Entry = Callable[[dict[str, Any]], dict[str, Any]]

REVIEW_ENTRIES_NOT_MATCHING = [
    pytest.param(lambda own: {**own, "id": 7, "user": None}, id="a-deleted-reviewer"),
    pytest.param(lambda own: {**own, "id": 7, "commit_id": "b" * 40}, id="another-head"),
    pytest.param(
        lambda own: {**own, "id": 7, "state": "CHANGES_REQUESTED", "body": "not this verdict"},
        id="another-review-by-this-app",
    ),
    pytest.param(
        lambda own: {**own, "id": 7, "user": {"login": "someone-else"}}, id="another-identity"
    ),
    pytest.param(lambda _own: {"id": 7}, id="an-entry-carrying-only-an-id"),
    pytest.param(lambda _own: {}, id="an-empty-entry"),
]


@pytest.mark.parametrize("flow", FLOWS)
@pytest.mark.parametrize("overrides", REVIEW_OVERRIDES_REJECTED)
def test_a_review_entry_the_scan_cannot_trust_is_a_coded_failure(
    flow: Flow, overrides: dict[str, Any]
) -> None:
    entry = {**flow.own_review, **overrides}
    http = transport(routes_with(REVIEWS_PAGE_1, (200, [entry])))
    with pytest.raises(PrgroomError):
        flow.call(http)
    assert http.posted_reviews() == []


@pytest.mark.parametrize("flow", FLOWS)
@pytest.mark.parametrize("entry", REVIEW_ENTRIES_NOT_MATCHING)
def test_a_well_formed_entry_that_is_not_this_review_lets_the_flow_post(
    flow: Flow, entry: Entry
) -> None:
    http = transport(routes_with(REVIEWS_PAGE_1, (200, [entry(flow.own_review)])))
    flow.call(http)
    assert len(http.posted_reviews()) == 1


@pytest.mark.parametrize("flow", FLOWS)
def test_this_flows_own_review_short_circuits_the_submission(flow: Flow) -> None:
    # The deleted reviewer leads. A scan that stopped at the first entry it had
    # to skip would miss the App's own review behind it and post a duplicate.
    deleted = {**flow.own_review, "id": 6, "user": None}
    http = transport(routes_with(REVIEWS_PAGE_1, (200, [deleted, {**flow.own_review, "id": 7}])))
    message = flow.call(http)
    assert http.posted_reviews() == []
    assert "review 7" in message


@pytest.mark.parametrize("flow", FLOWS)
@pytest.mark.parametrize("shape", SHAPES, ids=repr)
def test_a_malformed_entry_beside_a_good_one_is_a_coded_failure(flow: Flow, shape: Any) -> None:
    assert_only_prgroom_error_escapes(
        flow,
        routes_with(REVIEWS_PAGE_1, (200, [{"id": 1, "state": "COMMENTED"}, shape])),
        submission_reachable=False,
    )


# Entries the files listing cannot be trusted with: a name the client cannot read
# is a file an anchor may name, and a patch in an unreadable shape is a file whose
# lines could not be enumerated. Either one demotes an anchor silently.
FILE_ENTRIES_REJECTED = [
    pytest.param({}, id="an-entry-with-no-filename"),
    pytest.param({"filename": 7}, id="a-numeric-filename"),
    pytest.param({"filename": True}, id="a-boolean-filename"),
    pytest.param({"filename": []}, id="a-list-filename"),
    pytest.param({"filename": {"path": CHANGED}}, id="an-object-filename"),
    pytest.param({"filename": CHANGED, "patch": 7}, id="a-numeric-patch"),
    pytest.param({"filename": CHANGED, "patch": True}, id="a-boolean-patch"),
    pytest.param({"filename": CHANGED, "patch": []}, id="a-list-patch"),
    pytest.param({"filename": CHANGED, "patch": {"diff": ""}}, id="an-object-patch"),
]

# Well-formed entries that simply make no line commentable.
FILE_ENTRIES_WITHOUT_LINES = [
    pytest.param({"filename": CHANGED}, id="a-file-reported-without-a-patch"),
    pytest.param({"filename": CHANGED, "patch": None}, id="a-file-whose-patch-is-null"),
    pytest.param({"filename": CHANGED, "patch": ""}, id="a-file-whose-patch-is-empty"),
    pytest.param({"filename": "other.py", "patch": "@@ -1 +1 @@\n"}, id="an-unrelated-file"),
]


@pytest.mark.parametrize("body", [3, [], {}, True], ids=repr)
def test_a_body_the_verdict_scan_cannot_compare_is_a_coded_failure(body: Any) -> None:
    # Only the verdict posting reads a review's body, so this one is not swept
    # over both flows. Reading it as a non-match would post the verdict twice.
    entry = {**POST_VERDICT_FLOW.own_review, "id": 7, "body": body}
    http = transport(routes_with(REVIEWS_PAGE_1, (200, [entry])))
    with pytest.raises(PrgroomError):
        call_post_verdict(http)
    assert http.posted_reviews() == []


@pytest.mark.parametrize("entry", FILE_ENTRIES_REJECTED)
def test_a_files_entry_the_client_cannot_read_is_a_coded_failure(entry: Any) -> None:
    http = transport(routes_with(FILES_PAGE_1, (200, [entry])))
    with pytest.raises(PrgroomError):
        call_post_verdict(http)
    assert http.posted_reviews() == []


@pytest.mark.parametrize("entry", FILE_ENTRIES_WITHOUT_LINES)
def test_a_files_entry_with_no_commentable_line_still_posts_the_envelope(entry: Any) -> None:
    http = transport(routes_with(FILES_PAGE_1, (200, [entry])))
    message = call_post_verdict(http)
    (posted,) = http.posted_reviews()
    assert "comments" not in posted
    assert "no line in the diff for finding f1" in message


@pytest.mark.parametrize("shape", SHAPES, ids=repr)
def test_a_malformed_files_entry_beside_a_good_one_is_a_coded_failure(shape: Any) -> None:
    assert_only_prgroom_error_escapes(
        POST_VERDICT_FLOW,
        routes_with(FILES_PAGE_1, (200, [*FILES, shape])),
        submission_reachable=False,
    )


# Each read field, the response carrying it, and the exact type it must be.
FIELD_CASES = [
    pytest.param(APP, 200, "slug", str, id="the-app-slug"),
    pytest.param(INSTALLATION, 200, "id", int, id="the-installation-id"),
    pytest.param(TOKEN, 201, "token", str, id="the-token"),
    pytest.param(SUBMIT, 200, "id", int, id="the-submitted-review-id"),
]

UNDECODABLE = [
    pytest.param(bytes([255]), id="a-lone-continuation-byte"),
    pytest.param(b'{"slug": "\xff\xfe"}', id="invalid-utf8-inside-valid-json-syntax"),
    pytest.param(b"\xc3\x28", id="a-truncated-multibyte-sequence"),
]


@pytest.mark.parametrize("flow", FLOWS)
@pytest.mark.parametrize(("route", "status", "field", "want"), FIELD_CASES)
@pytest.mark.parametrize("shape", SHAPES, ids=repr)
def test_a_read_field_of_the_wrong_type_is_rejected(
    flow: Flow, route: tuple[str, str], status: int, field: str, want: type, shape: Any
) -> None:
    if type(shape) is want:
        pytest.skip("the type this field requires")
    with pytest.raises(PrgroomError):
        flow.call(transport(routes_with(route, (status, {field: shape}))))


@pytest.mark.parametrize("flow", FLOWS)
@pytest.mark.parametrize("shape", SHAPES, ids=repr)
def test_a_head_sha_of_the_wrong_type_is_rejected(flow: Flow, shape: Any) -> None:
    if type(shape) is str:
        pytest.skip("the type this field requires")
    with pytest.raises(PrgroomError):
        flow.call(transport(routes_with(PULL_READ, (200, {"head": {"sha": shape}}))))


class FakeResponse:
    def __init__(self, status: int, payload: bytes) -> None:
        self.status = status
        self._payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


@pytest.mark.parametrize("raw", UNDECODABLE)
def test_a_success_body_that_is_not_valid_utf8_is_a_coded_failure(
    raw: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app._OPENER, "open", lambda *_a, **_k: FakeResponse(200, raw))
    with pytest.raises(PrgroomError):
        UrllibTransport().request("GET", f"{GITHUB_API}/app", headers={})


@pytest.mark.parametrize("raw", UNDECODABLE)
def test_an_error_body_that_is_not_valid_utf8_still_reports_its_status(
    raw: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = urllib.error.HTTPError(f"{GITHUB_API}/app", 502, "Bad Gateway", {}, io.BytesIO(raw))
    monkeypatch.setattr(app._OPENER, "open", lambda *_a, **_k: (_ for _ in ()).throw(error))
    assert UrllibTransport().request("GET", f"{GITHUB_API}/app", headers={})[0] == 502


def test_the_corpus_covers_every_shape_json_decodes_to() -> None:
    # Guards the corpus itself: a shape list that stopped covering the JSON type
    # space would quietly shrink every sweep above.
    decoded = {type(json.loads(text)) for text in ("null", "true", "1", "1.5", '""', "[]", "{}")}
    assert decoded <= {type(shape) for shape in SHAPES}


# What each endpoint answers when it works. Anything else is a failed call.
EXPECTED_STATUS = {
    APP: 200,
    INSTALLATION: 200,
    TOKEN: 201,
    PULL_READ: 200,
    REVIEWS_PAGE_1: 200,
    FILES_PAGE_1: 200,
    SUBMIT: 200,
}

# The other success code, the successes that carry no usable body, a redirect,
# and the error bands.
STATUSES = [200, 201, 202, 204, 301, 400, 401, 403, 404, 422, 500, 502, 503]

ENDPOINTS = [
    pytest.param(APP, id="the-app-lookup"),
    pytest.param(INSTALLATION, id="the-installation-lookup"),
    pytest.param(TOKEN, id="the-token-mint"),
    pytest.param(PULL_READ, id="the-live-head-read"),
    pytest.param(REVIEWS_PAGE_1, id="the-reviews-listing"),
    pytest.param(FILES_PAGE_1, id="the-files-listing"),
    pytest.param(SUBMIT, id="the-review-submission"),
]


@pytest.mark.parametrize("flow", FLOWS)
@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("status", STATUSES)
def test_an_unexpected_status_at_any_endpoint_stops_the_flow(
    flow: Flow, endpoint: tuple[str, str], status: int
) -> None:
    """A status the call did not ask for ends the run where it happened.

    The client reads a body only from the status it expects, so accepting any
    other one would carry an unparsed or absent payload into the next step — and,
    on a read before the submission, into a POST that should never have happened.
    """
    if status == EXPECTED_STATUS[endpoint]:
        pytest.skip("the status this call expects")
    if endpoint not in flow.read_routes and endpoint != SUBMIT:
        pytest.skip("an endpoint this flow never calls")
    # Unique per endpoint, so an excerpt assertion cannot pass on a substring
    # some other call happened to put in the message.
    marker = f"body-of-{endpoint[0]}-{endpoint[1]}"
    http = transport(routes_with(endpoint, (status, {"marker": marker})))
    with pytest.raises(PrgroomError) as caught:
        flow.call(http)

    expected_code = (
        ErrorCode.RUNTIME_APPROVER_NOT_INSTALLED
        if endpoint == INSTALLATION and status == 404
        else ErrorCode.RUNTIME_APPROVER_API_FAILED
    )
    assert caught.value.code is expected_code

    if expected_code is ErrorCode.RUNTIME_APPROVER_API_FAILED:
        # The status says what went wrong and the excerpt says what came back;
        # a diagnostic carrying one without the other cannot be acted on.
        rendered = caught.value.render()
        assert str(status) in rendered
        assert marker in rendered

    method, url, _, _ = http.calls[-1]
    assert (method, url) == (endpoint[0], GITHUB_API + endpoint[1])
    if endpoint is not SUBMIT:
        assert http.posted_reviews() == []


@pytest.mark.parametrize("flow", FLOWS)
def test_this_flows_own_review_is_found_beyond_the_first_page(flow: Flow) -> None:
    # A full page carrying no match is followed by the next one, and a match found
    # there still short-circuits. Stopping at a full page posts a second review.
    filler = [{"id": n, "user": {"login": "someone-else"}} for n in range(REVIEWS_PER_PAGE)]
    routes = dict(BASE_ROUTES)
    routes[REVIEWS_PAGE_1] = (200, filler)
    routes[("GET", f"{PULL}/reviews?per_page={REVIEWS_PER_PAGE}&page=2")] = (
        200,
        [{**flow.own_review, "id": 7}],
    )
    http = transport(routes)
    message = flow.call(http)
    assert http.posted_reviews() == []
    assert "review 7" in message


@pytest.mark.parametrize("flow", FLOWS)
def test_a_flow_calls_no_endpoint_outside_its_declared_set(flow: Flow) -> None:
    # Guards the sweeps themselves: a flow that grew an endpoint the corpus does
    # not list would be swept for statuses and shapes at every position but that
    # one, and the gap would not show as a failure anywhere.
    http = transport(BASE_ROUTES)
    flow.call(http)
    declared = {GITHUB_API + suffix for _, suffix in [*flow.read_routes, SUBMIT]}
    assert {url for _, url, _, _ in http.calls} == declared
