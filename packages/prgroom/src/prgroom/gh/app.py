"""The GitHub App client — REST calls authored by an App identity, not the operator.

The ``gh`` adapter rides the operator's own ``gh`` auth and can carry neither an
App JWT nor an installation token, so App-authored calls need their own
transport. :class:`HttpTransport` is that seam: production wires
:class:`UrllibTransport`; tests inject a route-table fake. RS256 signing shells
out to ``openssl`` through the same :class:`~prgroom.proc.CommandRunner` boundary
the gh and git adapters use, so no cryptography dependency enters the package.

The installation token is narrowed at mint time to the one repository and
``pull_requests: write`` — the least privilege a review submission needs — so a
leaked token cannot exercise the installation's other grants. Every failure
arrives as a registry-tagged :class:`~prgroom.errors.PrgroomError`, and nothing
here retries: an App that cannot post is a hand-off, not a slow path.
"""

from __future__ import annotations

import base64
import json
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path
from typing import Any, Protocol, TypeVar, runtime_checkable

from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.proc import DEFAULT_SUBPROCESS_TIMEOUT, CommandRunner
from prgroom.prsession.pr_ref import PRRef

GITHUB_API = "https://api.github.com"

# GitHub's maximum page size for the reviews collection. Reviews come back
# oldest-first, so an App's own prior approval at the current head can sit past
# page 1 on a heavily-reviewed PR; every caller walks all pages rather than
# trusting the first one.
REVIEWS_PER_PAGE = 100

# The same ceiling for the changed-files collection, walked the same way: a file
# an anchor names can sit on any page, and a partial listing would silently
# demote a placeable anchor to body-only.
FILES_PER_PAGE = 100

# The App JWT's life: ``iat`` is backdated to absorb clock skew against GitHub's
# clock, and ``exp`` stays inside the 10-minute ceiling the API accepts.
_JWT_BACKDATE_SECONDS = 60
_JWT_LIFETIME_SECONDS = 540

# Wall-clock budget for one API round trip, matching the subprocess seam's.
_HTTP_TIMEOUT = 30.0

# How much of a response body a diagnostic may quote. Bounded so a large or
# hostile body cannot flood the log through an error path.
_EXCERPT = 200

T = TypeVar("T")

# Signs the JWT's ``<header>.<claims>`` string, returning the raw signature.
Signer = Callable[[str], bytes]


@runtime_checkable
class HttpTransport(Protocol):
    """One HTTP round trip against the GitHub API: ``(status, parsed body)``.

    The single injectable boundary for App-authenticated traffic, mirroring the
    :class:`~prgroom.proc.CommandRunner` seam the subprocess adapters share.
    """

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
    ) -> tuple[int, Any]: ...  # pragma: no cover  # the API returns object|array; callers narrow


class UrllibTransport:
    """Production transport. Structurally satisfies :class:`HttpTransport`.

    A 4xx or 5xx is *returned* as ``(status, body)`` rather than raised, because
    which statuses are expected is the caller's knowledge — a 404 on the
    installation lookup means the App is not installed, while a 404 elsewhere is
    an outright failure. Only a request that produced no status at all raises.
    """

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
    ) -> tuple[int, Any]:
        request = urllib.request.Request(  # noqa: S310  # url is this module's own API constant plus a typed PR ref, never operator input
            url,
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                # urllib sets no Content-Type for a bytes body; every bodied call
                # here sends JSON, so declare it rather than rely on the API
                # inferring it.
                **({"Content-Type": "application/json"} if body is not None else {}),
                **headers,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT) as response:  # noqa: S310  # same https URL this module built
                return int(response.status), _decode_json(response.read(), url)
        except urllib.error.HTTPError as exc:
            return exc.code, _error_body(exc)
        except (OSError, HTTPException) as exc:
            detail = f"network failure calling {url}: {exc}"
            raise _api_failed(detail) from exc


@dataclass(frozen=True, slots=True)
class MintedApp:
    """A short-lived installation token and the App's runtime bot login."""

    token: str
    login: str


def openssl_signer(runner: CommandRunner, key_path: Path) -> Signer:
    """Build an RS256 signer that shells out to ``openssl`` through ``runner``.

    ``-hex`` keeps the signature printable: the command seam is text-mode, and a
    raw DER signature would not survive it. ``-passin pass:`` supplies an empty
    passphrase so an encrypted key fails immediately with a decrypt error rather
    than blocking on a terminal prompt — the App key must be an unencrypted PEM.
    """

    def sign(payload: str) -> bytes:
        try:
            result = runner.run(
                [
                    "openssl",
                    "dgst",
                    "-sha256",
                    "-sign",
                    str(key_path),
                    "-hex",
                    "-passin",
                    "pass:",
                ],
                input=payload,
                timeout=DEFAULT_SUBPROCESS_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            detail = f"openssl timed out signing with {key_path}"
            raise _sign_failed(detail) from exc
        except OSError as exc:
            detail = f"openssl not runnable: {exc}"
            raise _sign_failed(detail) from exc
        if result.returncode != 0:
            raise _sign_failed(result.stderr.strip() or result.stdout.strip())
        return _decode_hex_signature(result.stdout)

    return sign


def build_jwt(app_id: int, now: int, sign: Signer) -> str:
    """Build the RS256 App JWT GitHub accepts in place of an installation token."""
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = _b64url(
        json.dumps(
            {
                "iat": now - _JWT_BACKDATE_SECONDS,
                "exp": now + _JWT_LIFETIME_SECONDS,
                "iss": str(app_id),
            }
        ).encode()
    )
    signing_input = f"{header}.{claims}"
    return f"{signing_input}.{_b64url(sign(signing_input))}"


def mint_installation_token(http: HttpTransport, jwt: str, ref: PRRef) -> MintedApp:
    """Exchange an App JWT for a token scoped to ``ref``'s repository alone.

    The login is derived from the slug the API reports rather than configured:
    renaming the App renames every review it authors, and a hardcoded login would
    silently stop matching them — turning the idempotence check into a duplicate
    approval.
    """
    headers = {"Authorization": f"Bearer {jwt}"}
    app: dict[str, Any] = _expect(
        http.request("GET", f"{GITHUB_API}/app", headers=headers), "app lookup"
    )
    status, payload = http.request(
        "GET", f"{GITHUB_API}/repos/{ref.owner}/{ref.repo}/installation", headers=headers
    )
    if status == 404:  # HTTP status literal is self-documenting
        raise PrgroomError(
            tier=Tier.RUNTIME_TERMINAL_USER,
            code=ErrorCode.RUNTIME_APPROVER_NOT_INSTALLED,
            detail=f"the App is not installed on {ref.owner}/{ref.repo}",
        )
    installation = _expect((status, payload), "installation lookup")
    installation_id = read_field(installation, "id", want=int, what="installation lookup")
    scope = json.dumps(
        {"repositories": [ref.repo], "permissions": {"pull_requests": "write"}}
    ).encode()
    minted: dict[str, Any] = _expect(
        http.request(
            "POST",
            f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers=headers,
            body=scope,
        ),
        "installation-token mint",
        want=201,
    )
    token = read_field(minted, "token", want=str, what="installation-token mint", status=201)
    return MintedApp(
        token=token, login=f"{read_field(app, 'slug', want=str, what='app lookup')}[bot]"
    )


def read_head_sha(http: HttpTransport, token: str, ref: PRRef) -> str:
    """The PR's live head SHA, read under the App's own token."""
    pull: dict[str, Any] = _expect(
        http.request("GET", _pull_url(ref), headers=_bearer(token)), "pull request read"
    )
    return read_field(pull, "head", "sha", want=str, what="pull request read")


def iter_reviews(http: HttpTransport, token: str, ref: PRRef) -> Iterator[dict[str, Any]]:
    """Yield every review on the PR, walking all pages oldest-first."""
    yield from _paginate(http, token, ref, "reviews", REVIEWS_PER_PAGE, "reviews listing")


def iter_files(http: HttpTransport, token: str, ref: PRRef) -> Iterator[dict[str, Any]]:
    """Yield every file the PR's diff touches, walking all pages."""
    yield from _paginate(http, token, ref, "files", FILES_PER_PAGE, "files listing")


def find_own_review(
    http: HttpTransport,
    token: str,
    ref: PRRef,
    login: str,
    *,
    match: Callable[[dict[str, Any]], bool],
) -> int | None:
    """The id of the first review by ``login`` that ``match`` accepts, if one is there.

    Both idempotence checks run through here so the reading of an untrusted page
    is decided once: a null user is GitHub's shape for a deleted account and is
    skipped, while a login or an id the page carries in the wrong shape fails the
    call. Acting on a page the scan half-understood is how a duplicate review gets
    posted, and ``match`` is only ever consulted for a review already known to be
    this identity's.
    """
    for review in iter_reviews(http, token, ref):
        if review.get("user") is None:
            continue
        if read_field(review, "user", "login", want=str, what="reviews listing") != login:
            continue
        if match(review):
            return read_field(review, "id", want=int, what="reviews listing")
    return None


def review_field(review: dict[str, Any], key: str) -> str | None:
    """A listed review's string field, or ``None`` when it is absent.

    Every predicate deciding whether a listed review is the one already posted
    reads through here, so a field arriving in a shape the scan cannot compare
    fails the call instead of quietly comparing unequal. A false non-match posts
    a second review; that is the failure this exists to prevent, and an absent
    field is the only shape it is safe to read as "not this one".
    """
    if key not in review:
        return None
    return read_field(review, key, want=str, what="reviews listing")


def submit_review(
    http: HttpTransport,
    token: str,
    ref: PRRef,
    *,
    event: str,
    body: str,
    commit_id: str,
    comments: Sequence[Mapping[str, Any]] = (),
) -> int:
    """Submit one review of ``event`` kind pinned to ``commit_id``; return its id.

    ``event`` is a parameter so the same call posts a comment-only review as
    readily as an approval — the pinning and the identity are what this function
    owns, not the verdict. ``comments`` are inline review comments submitted in
    the same request: GitHub rejects the whole submission when one of them names a
    line outside the diff, so a caller passes only anchors it has already placed
    against the diff, and an empty sequence sends no ``comments`` key at all.
    """
    fields: dict[str, Any] = {"event": event, "commit_id": commit_id, "body": body}
    if comments:
        fields["comments"] = [dict(comment) for comment in comments]
    review: dict[str, Any] = _expect(
        http.request(
            "POST",
            f"{_pull_url(ref)}/reviews",
            headers=_bearer(token),
            body=json.dumps(fields).encode(),
        ),
        "review submission",
    )
    return read_field(review, "id", want=int, what="review submission")


def _paginate(
    http: HttpTransport,
    token: str,
    ref: PRRef,
    collection: str,
    per_page: int,
    what: str,
) -> Iterator[dict[str, Any]]:
    """Walk every page of one of the PR's sub-collections, in the order it returns.

    A short page ends the walk; a full one is followed by another request, so a
    collection whose last page happens to be full costs one extra empty read
    rather than a silently truncated result.
    """
    page = 1
    while True:
        entries = _object_page(
            _expect(
                http.request(
                    "GET",
                    f"{_pull_url(ref)}/{collection}?per_page={per_page}&page={page}",
                    headers=_bearer(token),
                ),
                what,
            ),
            what,
            page,
        )
        yield from entries
        if len(entries) < per_page:
            return
        page += 1


def _decode_json(raw: bytes, url: str) -> Any:
    """Parse a success response's body; a body that is not JSON is an API failure.

    A proxy or captive portal can answer 200 with HTML, which is a failed call and
    must arrive as one rather than as a decoder traceback.
    """
    try:
        return json.loads(raw or b"null")
    except ValueError as exc:
        detail = f"non-JSON body from {url}: {raw.decode(errors='replace')[:_EXCERPT]}"
        raise _api_failed(detail) from exc


def _b64url(data: bytes) -> str:
    """Unpadded base64url — the JOSE segment encoding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _api_failed(detail: str) -> PrgroomError:
    return PrgroomError(
        tier=Tier.RUNTIME_TERMINAL_USER,
        code=ErrorCode.RUNTIME_APPROVER_API_FAILED,
        detail=detail,
    )


def _error_body(exc: urllib.error.HTTPError) -> Any:
    """An error status's body, best-effort: the status is the diagnostic that matters.

    A non-JSON body (an HTML error page) degrades to text; a body that cannot be
    read at all degrades to nothing.
    """
    try:
        raw = exc.read()
    except (OSError, HTTPException):
        return None
    try:
        return json.loads(raw or b"null")
    except ValueError:
        return raw.decode(errors="replace")[:_EXCERPT]


def _object_page(payload: Any, what: str, page: int, status: int = 200) -> list[dict[str, Any]]:
    """Validate one page of a listing before any of it is read.

    The whole page is checked before a single entry is yielded: a caller that
    consumed the entries preceding a bad one could miss the App's own review and
    post a duplicate, or miss a changed file and demote a placeable anchor.
    """
    if not isinstance(payload, list):
        detail = _diagnostic(
            what, status, payload, f"page {page} is {type(payload).__name__}, not a list"
        )
        raise _api_failed(detail)
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            detail = _diagnostic(
                what,
                status,
                payload,
                f"page {page} entry {index} is {type(entry).__name__}, not an object",
            )
            raise _api_failed(detail)
    return payload


def read_field(payload: Any, *path: str, want: type[T], what: str, status: int = 200) -> T:
    """Read a required field out of a response, or fail the call.

    Every field this client reads routes through here, so a response that parsed
    but does not carry what the next step needs is an API failure with a
    diagnostic naming the field, never an index or type error at the call site.
    """
    node = payload
    for depth, key in enumerate(path):
        if not isinstance(node, dict) or key not in node:
            missing = f"response has no {'.'.join(path[: depth + 1])}"
            raise _api_failed(_diagnostic(what, status, payload, missing))
        node = node[key]
    # bool is an int subclass, so a JSON boolean would otherwise satisfy an int
    # field and go on to address an installation or name a review.
    if not isinstance(node, want) or (want is not bool and isinstance(node, bool)):
        wrong = f"{'.'.join(path)} is {type(node).__name__}, not {want.__name__}"
        raise _api_failed(_diagnostic(what, status, payload, wrong))
    return node


def _diagnostic(what: str, status: int, payload: Any, problem: str) -> str:
    """One shape for every failed read: the call, its status, the problem, the body.

    A read that fails on a status the call expected still failed on a response,
    and naming the problem without what arrived leaves the reader guessing which
    of the two is wrong — the API or this client's expectation of it.
    """
    return f"{what}: HTTP {status}: {problem}: {json.dumps(payload, default=repr)[:_EXCERPT]}"


def _sign_failed(detail: str) -> PrgroomError:
    return PrgroomError(
        tier=Tier.RUNTIME_TERMINAL_USER,
        code=ErrorCode.RUNTIME_APPROVER_SIGN_FAILED,
        detail=detail,
    )


def _decode_hex_signature(out: str) -> bytes:
    """Extract the signature from ``openssl dgst -hex`` output.

    The line reads ``<algorithm>(stdin)= <hex>``, and the algorithm label differs
    across openssl versions, so the hex is everything after the last ``=``.
    """
    hex_digits = "".join(out.rpartition("=")[2].split())
    if not hex_digits:
        detail = f"openssl produced no signature: {out.strip()[:200]!r}"
        raise _sign_failed(detail)
    try:
        return bytes.fromhex(hex_digits)
    except ValueError as exc:
        detail = f"openssl produced an unreadable signature: {out.strip()[:200]!r}"
        raise _sign_failed(detail) from exc


def _expect(response: tuple[int, Any], what: str, *, want: int = 200) -> Any:
    """Return an expected-status response's body; any other status fails loud."""
    status, payload = response
    if status != want:
        detail = f"{what}: HTTP {status}: {json.dumps(payload)[:_EXCERPT]}"
        raise _api_failed(detail)
    return payload


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _pull_url(ref: PRRef) -> str:
    return f"{GITHUB_API}/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}"
