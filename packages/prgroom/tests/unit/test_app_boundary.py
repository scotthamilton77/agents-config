"""The App client's boundary property, as one corpus rather than case by case.

Whatever shape a response arrives in, only a :class:`PrgroomError` may leave the
client, and a read the client could not trust may not be followed by a review
submission. The corpus sweeps every payload position the client reads against
every JSON shape it could hold, so a field added later is covered without a new
test.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from prgroom.errors import PrgroomError
from prgroom.gh.app import GITHUB_API, REVIEWS_PER_PAGE, UrllibTransport
from prgroom.lifecycle.approve import approve_pr
from prgroom.proc import CommandResult
from prgroom.prsession.pr_ref import PRRef
from tests.fakes import RecordedRunner, RouteTableHttp

HEAD = "a" * 40
APP_ID = 4275336
KEY_PATH = Path("/keys/app.pem")
REF = PRRef(owner="octo", repo="demo", number=5)

PULL = "/repos/octo/demo/pulls/5"
APP = ("GET", "/app")
INSTALLATION = ("GET", "/repos/octo/demo/installation")
TOKEN = ("POST", "/app/installations/42/access_tokens")
PULL_READ = ("GET", PULL)
REVIEWS_PAGE_1 = ("GET", f"{PULL}/reviews?per_page={REVIEWS_PER_PAGE}&page=1")
SUBMIT = ("POST", f"{PULL}/reviews")

BASE_ROUTES: dict[tuple[str, str], tuple[int, Any]] = {
    APP: (200, {"slug": "pr-hater"}),
    INSTALLATION: (200, {"id": 42}),
    TOKEN: (201, {"token": "tok"}),
    PULL_READ: (200, {"head": {"sha": HEAD}}),
    REVIEWS_PAGE_1: (200, []),
    SUBMIT: (200, {"id": 99}),
}

# Every JSON shape a field or a whole body can arrive as. The booleans are here
# because a JSON boolean decodes to a Python bool, which is an int subclass and
# would otherwise satisfy an integer check.
SHAPES: list[Any] = [None, True, False, 0, 1, -1, 3.5, "", "text", [], [1], {}, {"x": 1}]

# The reads that precede the submission: a failure in any of them leaves the PR
# untouched.
READ_ROUTES = [APP, INSTALLATION, TOKEN, PULL_READ, REVIEWS_PAGE_1]

MATCHING = {"state": "APPROVED", "commit_id": HEAD, "user": {"login": "pr-hater[bot]"}}

# Entries the scan cannot trust: it matched this App's approval and then could not
# read the id naming it, or could not read a login at all. Acting on a page it
# half-understood is how a duplicate approval gets posted.
REVIEW_ENTRIES_REJECTED = [
    pytest.param({**MATCHING}, id="a-match-with-no-id"),
    pytest.param({**MATCHING, "id": "7"}, id="a-match-with-a-string-id"),
    pytest.param({**MATCHING, "id": True}, id="a-match-with-a-boolean-id"),
    pytest.param({**MATCHING, "id": None}, id="a-match-with-a-null-id"),
    pytest.param({**MATCHING, "id": [7]}, id="a-match-with-a-list-id"),
    pytest.param({**MATCHING, "user": "malformed"}, id="a-string-user"),
    pytest.param({**MATCHING, "user": []}, id="a-list-user"),
    pytest.param({**MATCHING, "user": {}}, id="a-user-with-no-login"),
    pytest.param({**MATCHING, "user": {"login": 7}}, id="a-numeric-login"),
]

# Well-formed entries that are simply not this App's approval at this head. A null
# user is GitHub's shape for a deleted account.
REVIEW_ENTRIES_NOT_MATCHING = [
    pytest.param({**MATCHING, "id": 7, "user": None}, id="a-deleted-reviewer"),
    pytest.param({**MATCHING, "id": 7, "state": "COMMENTED"}, id="a-comment-only-review"),
    pytest.param({**MATCHING, "id": 7, "commit_id": "b" * 40}, id="an-approval-of-another-head"),
    pytest.param({"id": 7}, id="an-entry-carrying-only-an-id"),
    pytest.param({}, id="an-empty-entry"),
]

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


def run_approve(routes: dict[tuple[str, str], tuple[int, Any]]) -> tuple[str, RouteTableHttp]:
    http = RouteTableHttp(routes)
    return call_approve(http), http


def routes_with(route: tuple[str, str], response: tuple[int, Any]) -> dict[tuple[str, str], Any]:
    patched = dict(BASE_ROUTES)
    patched[route] = response
    return patched


def assert_only_prgroom_error_escapes(
    routes: dict[tuple[str, str], tuple[int, Any]], *, submission_reachable: bool
) -> None:
    """Run the flow and require that any failure is a coded one.

    A malformed payload may be a shape the client legitimately accepts, so a clean
    completion is allowed. What is not allowed is another exception type, or a
    review posted after a read the client could not trust.
    """
    http = RouteTableHttp(routes)
    try:
        call_approve(http)
    except PrgroomError:
        if not submission_reachable:
            assert http.posted_reviews() == []
    except Exception as exc:  # the property under test is that this never happens
        pytest.fail(f"{type(exc).__name__} escaped the App client: {exc}")


@pytest.mark.parametrize("route", READ_ROUTES, ids=lambda r: f"{r[0]}-{r[1]}")
@pytest.mark.parametrize("shape", SHAPES, ids=repr)
def test_a_malformed_body_on_any_read_is_a_coded_failure(
    route: tuple[str, str], shape: Any
) -> None:
    assert_only_prgroom_error_escapes(
        routes_with(route, (BASE_ROUTES[route][0], shape)), submission_reachable=False
    )


@pytest.mark.parametrize("shape", SHAPES, ids=repr)
def test_a_malformed_submission_response_is_a_coded_failure(shape: Any) -> None:
    assert_only_prgroom_error_escapes(routes_with(SUBMIT, (200, shape)), submission_reachable=True)


@pytest.mark.parametrize("entry", REVIEW_ENTRIES_REJECTED)
def test_a_review_entry_the_scan_cannot_trust_is_a_coded_failure(entry: Any) -> None:
    http = RouteTableHttp(routes_with(REVIEWS_PAGE_1, (200, [entry])))
    with pytest.raises(PrgroomError):
        call_approve(http)
    assert http.posted_reviews() == []


@pytest.mark.parametrize("entry", REVIEW_ENTRIES_NOT_MATCHING)
def test_a_well_formed_entry_that_is_not_the_approval_lets_the_flow_post(entry: Any) -> None:
    _, http = run_approve(routes_with(REVIEWS_PAGE_1, (200, [entry])))
    assert len(http.posted_reviews()) == 1


@pytest.mark.parametrize("shape", SHAPES, ids=repr)
def test_a_malformed_entry_beside_a_good_one_is_a_coded_failure(shape: Any) -> None:
    assert_only_prgroom_error_escapes(
        routes_with(REVIEWS_PAGE_1, (200, [{"id": 1, "state": "COMMENTED"}, shape])),
        submission_reachable=False,
    )


@pytest.mark.parametrize(("route", "status", "field", "want"), FIELD_CASES)
@pytest.mark.parametrize("shape", SHAPES, ids=repr)
def test_a_read_field_of_the_wrong_type_is_rejected(
    route: tuple[str, str], status: int, field: str, want: type, shape: Any
) -> None:
    if type(shape) is want:
        pytest.skip("the type this field requires")
    with pytest.raises(PrgroomError):
        run_approve(routes_with(route, (status, {field: shape})))


@pytest.mark.parametrize("shape", SHAPES, ids=repr)
def test_a_head_sha_of_the_wrong_type_is_rejected(shape: Any) -> None:
    if type(shape) is str:
        pytest.skip("the type this field requires")
    with pytest.raises(PrgroomError):
        run_approve(routes_with(PULL_READ, (200, {"head": {"sha": shape}})))


def test_the_apps_own_approval_still_short_circuits() -> None:
    message, http = run_approve(routes_with(REVIEWS_PAGE_1, (200, [{**MATCHING, "id": 7}])))
    assert http.posted_reviews() == []
    assert "review 7" in message


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
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: FakeResponse(200, raw))
    with pytest.raises(PrgroomError):
        UrllibTransport().request("GET", f"{GITHUB_API}/app", headers={})


@pytest.mark.parametrize("raw", UNDECODABLE)
def test_an_error_body_that_is_not_valid_utf8_still_reports_its_status(
    raw: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = urllib.error.HTTPError(f"{GITHUB_API}/app", 502, "Bad Gateway", {}, io.BytesIO(raw))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: (_ for _ in ()).throw(error))
    assert UrllibTransport().request("GET", f"{GITHUB_API}/app", headers={})[0] == 502


def test_the_corpus_covers_every_shape_json_decodes_to() -> None:
    # Guards the corpus itself: a shape list that stopped covering the JSON type
    # space would quietly shrink every sweep above.
    decoded = {type(json.loads(text)) for text in ("null", "true", "1", "1.5", '""', "[]", "{}")}
    assert decoded <= {type(shape) for shape in SHAPES}
