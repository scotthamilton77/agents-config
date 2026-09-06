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
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.proc import DEFAULT_SUBPROCESS_TIMEOUT, CommandRunner
from prgroom.prsession.pr_ref import PRRef

GITHUB_API = "https://api.github.com"

# GitHub's maximum page size for the reviews collection. Reviews come back
# oldest-first, so an App's own prior approval at the current head can sit past
# page 1 on a heavily-reviewed PR; every caller walks all pages rather than
# trusting the first one.
REVIEWS_PER_PAGE = 100

# The App JWT's life: ``iat`` is backdated to absorb clock skew against GitHub's
# clock, and ``exp`` stays inside the 10-minute ceiling the API accepts.
_JWT_BACKDATE_SECONDS = 60
_JWT_LIFETIME_SECONDS = 540

# Wall-clock budget for one API round trip, matching the subprocess seam's.
_HTTP_TIMEOUT = 30.0

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
                return int(response.status), json.loads(response.read() or b"null")
        except urllib.error.HTTPError as exc:
            # An error status still carries a body worth surfacing in the
            # diagnostic; a non-JSON one (an HTML error page) degrades to text.
            raw = exc.read()
            try:
                return exc.code, json.loads(raw or b"null")
            except json.JSONDecodeError:
                return exc.code, raw.decode(errors="replace")
        except urllib.error.URLError as exc:
            raise PrgroomError(
                tier=Tier.RUNTIME_TERMINAL_USER,
                code=ErrorCode.RUNTIME_APPROVER_API_FAILED,
                detail=f"network failure calling {url}: {exc.reason}",
            ) from exc


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
    installation: dict[str, Any] = _expect((status, payload), "installation lookup")
    scope = json.dumps(
        {"repositories": [ref.repo], "permissions": {"pull_requests": "write"}}
    ).encode()
    minted: dict[str, Any] = _expect(
        http.request(
            "POST",
            f"{GITHUB_API}/app/installations/{installation['id']}/access_tokens",
            headers=headers,
            body=scope,
        ),
        "installation-token mint",
        want=201,
    )
    return MintedApp(token=str(minted["token"]), login=f"{app['slug']}[bot]")


def read_head_sha(http: HttpTransport, token: str, ref: PRRef) -> str:
    """The PR's live head SHA, read under the App's own token."""
    pull: dict[str, Any] = _expect(
        http.request("GET", _pull_url(ref), headers=_bearer(token)), "pull request read"
    )
    return str(pull["head"]["sha"])


def iter_reviews(http: HttpTransport, token: str, ref: PRRef) -> Iterator[dict[str, Any]]:
    """Yield every review on the PR, walking all pages oldest-first."""
    page = 1
    while True:
        reviews: list[dict[str, Any]] = _expect(
            http.request(
                "GET",
                f"{_pull_url(ref)}/reviews?per_page={REVIEWS_PER_PAGE}&page={page}",
                headers=_bearer(token),
            ),
            "reviews listing",
        )
        yield from reviews
        if len(reviews) < REVIEWS_PER_PAGE:
            return
        page += 1


def submit_review(
    http: HttpTransport,
    token: str,
    ref: PRRef,
    *,
    event: str,
    body: str,
    commit_id: str,
) -> int:
    """Submit one review of ``event`` kind pinned to ``commit_id``; return its id.

    ``event`` is a parameter so the same call posts a comment-only review as
    readily as an approval — the pinning and the identity are what this function
    owns, not the verdict.
    """
    payload = json.dumps({"event": event, "commit_id": commit_id, "body": body}).encode()
    review: dict[str, Any] = _expect(
        http.request("POST", f"{_pull_url(ref)}/reviews", headers=_bearer(token), body=payload),
        "review submission",
    )
    return int(review["id"])


def _b64url(data: bytes) -> str:
    """Unpadded base64url — the JOSE segment encoding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


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
        raise PrgroomError(
            tier=Tier.RUNTIME_TERMINAL_USER,
            code=ErrorCode.RUNTIME_APPROVER_API_FAILED,
            detail=f"{what}: HTTP {status}: {json.dumps(payload)[:200]}",
        )
    return payload


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _pull_url(ref: PRRef) -> str:
    return f"{GITHUB_API}/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}"
