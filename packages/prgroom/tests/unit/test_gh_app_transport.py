"""The production HTTP transport, exercised against a stubbed ``urlopen``.

``urlopen`` is the system boundary this class exists to wrap, so stubbing it is
the sanctioned mock point — the same discipline the subprocess adapters follow.
What is pinned here is the transport's own decisions: which headers it sets, that
an error status is returned rather than raised, and that an unreachable host is
the one failure it converts into a coded error.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from http.client import IncompleteRead
from typing import Any

import pytest

from prgroom.errors import ErrorCode, PrgroomError
from prgroom.gh import app
from prgroom.gh.app import GITHUB_API, UrllibTransport

URL = f"{GITHUB_API}/app"


class FakeResponse:
    """The context-manager shape ``urlopen`` returns."""

    def __init__(self, status: int, payload: bytes) -> None:
        self.status = status
        self._payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def stub_urlopen(monkeypatch: pytest.MonkeyPatch, result: Any) -> list[urllib.request.Request]:
    """Route ``urlopen`` to ``result`` (returned, or raised if it is an exception)."""
    seen: list[urllib.request.Request] = []

    def fake(request: urllib.request.Request, timeout: float | None = None) -> Any:  # noqa: ARG001  # the transport's timeout is not what these tests pin
        seen.append(request)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(app._OPENER, "open", fake)
    return seen


def test_a_success_returns_the_status_and_parsed_body(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_urlopen(monkeypatch, FakeResponse(200, json.dumps({"slug": "pr-hater"}).encode()))
    assert UrllibTransport().request("GET", URL, headers={}) == (200, {"slug": "pr-hater"})


def test_an_empty_body_parses_to_none_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_urlopen(monkeypatch, FakeResponse(204, b""))
    assert UrllibTransport().request("GET", URL, headers={}) == (204, None)


def test_the_api_version_and_accept_headers_are_always_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = stub_urlopen(monkeypatch, FakeResponse(200, b"{}"))
    UrllibTransport().request("GET", URL, headers={"Authorization": "Bearer x"})
    (request,) = seen
    assert request.get_header("Accept") == "application/vnd.github+json"
    assert request.get_header("X-github-api-version") == "2022-11-28"
    assert request.get_header("Authorization") == "Bearer x"


def test_a_bodied_call_declares_json_because_urllib_will_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = stub_urlopen(monkeypatch, FakeResponse(201, b"{}"))
    UrllibTransport().request("POST", URL, headers={}, body=b'{"a": 1}')
    (request,) = seen
    assert request.get_header("Content-type") == "application/json"
    assert request.data == b'{"a": 1}'
    assert request.get_method() == "POST"


def test_a_bodiless_call_declares_no_content_type(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = stub_urlopen(monkeypatch, FakeResponse(200, b"{}"))
    UrllibTransport().request("GET", URL, headers={})
    assert seen[0].get_header("Content-type") is None


def test_an_error_status_is_returned_with_its_body_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The caller decides which statuses are expected: a 404 on the installation
    # lookup means something a 404 elsewhere does not.
    error = urllib.error.HTTPError(
        URL, 404, "Not Found", {}, io.BytesIO(json.dumps({"message": "Not Found"}).encode())
    )
    stub_urlopen(monkeypatch, error)
    assert UrllibTransport().request("GET", URL, headers={}) == (404, {"message": "Not Found"})


def test_a_non_json_error_body_degrades_to_text(monkeypatch: pytest.MonkeyPatch) -> None:
    error = urllib.error.HTTPError(URL, 502, "Bad Gateway", {}, io.BytesIO(b"<html>nope</html>"))
    stub_urlopen(monkeypatch, error)
    status, payload = UrllibTransport().request("GET", URL, headers={})
    assert status == 502
    assert payload == "<html>nope</html>"


def test_an_unreachable_host_becomes_a_coded_error_not_a_urllib_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_urlopen(monkeypatch, urllib.error.URLError("no route to host"))
    with pytest.raises(PrgroomError) as caught:
        UrllibTransport().request("GET", URL, headers={})
    assert caught.value.code is ErrorCode.RUNTIME_APPROVER_API_FAILED
    assert "no route to host" in caught.value.detail


def test_the_transport_satisfies_the_protocol_structurally() -> None:
    from prgroom.gh.app import HttpTransport

    assert isinstance(UrllibTransport(), HttpTransport)


def test_a_success_whose_body_is_not_json_is_a_coded_error_not_a_decode_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A proxy or captive portal answers 200 with HTML; the caller must see the
    # registry error every other API failure arrives as.
    stub_urlopen(monkeypatch, FakeResponse(200, b"<html>bad gateway</html>"))
    with pytest.raises(PrgroomError) as caught:
        UrllibTransport().request("GET", URL, headers={})
    assert caught.value.code is ErrorCode.RUNTIME_APPROVER_API_FAILED
    assert "<html>bad gateway</html>" in caught.value.detail


class UnreadableResponse(FakeResponse):
    """A response whose headers arrived and whose body then fails mid-read."""

    def __init__(self, error: Exception) -> None:
        super().__init__(200, b"")
        self._error = error

    def read(self) -> bytes:
        raise self._error


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(TimeoutError("timed out mid-body"), id="a-read-timeout"),
        pytest.param(OSError("connection reset"), id="a-socket-error"),
        pytest.param(IncompleteRead(b"partial"), id="an-incomplete-read"),
    ],
)
def test_an_io_failure_while_reading_the_body_is_a_coded_error(
    error: Exception, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_urlopen(monkeypatch, UnreadableResponse(error))
    with pytest.raises(PrgroomError) as caught:
        UrllibTransport().request("GET", URL, headers={})
    assert caught.value.code is ErrorCode.RUNTIME_APPROVER_API_FAILED


def test_an_error_status_whose_body_cannot_be_read_still_reports_the_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = urllib.error.HTTPError(URL, 503, "Service Unavailable", {}, None)
    monkeypatch.setattr(error, "read", lambda: (_ for _ in ()).throw(TimeoutError("no body")))
    stub_urlopen(monkeypatch, error)
    assert UrllibTransport().request("GET", URL, headers={})[0] == 503


def test_a_redirect_is_reported_as_the_status_it_answered_on() -> None:
    # The opener the transport calls carries a handler that declines every
    # redirect, so a 3xx surfaces as that endpoint's unexpected status instead of
    # a request to somewhere the caller never named.
    handler = next(
        h for h in app._OPENER.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)
    )
    declined = handler.redirect_request(
        urllib.request.Request(f"{GITHUB_API}/app"),  # noqa: S310  # never opened; the handler only inspects it
        io.BytesIO(b""),
        301,
        "Moved Permanently",
        {"location": "https://elsewhere.example/app"},
        "https://elsewhere.example/app",
    )
    assert declined is None
