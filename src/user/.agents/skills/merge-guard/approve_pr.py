#!/usr/bin/env python3
"""approve_pr.py — submit an App-attested approving review on a PR.

Satisfies branch protection's required approving review with a GitHub App
identity, at merge time, pinned to the head SHA the merge-guard eligibility
floor checked. See the merge-approver App design (2026-07-11), section 3.3
"Approver script contract".

The approval is mechanical policy attestation — never authorization. The
caller (merge-guard Step 5) runs it only after Axis-2 authorization and a
clean eligibility floor, and treats any non-zero exit as a terminal
hand-off to the human. Never retried, never escalated to --admin.

Usage:
    approve_pr.py --repo <owner/name> --pr <number> --head-sha <sha>
                  --app-id <id> --key-path <pem> [--facts <json>]

Exit codes:
    0 — approval submitted (or an approval by this App already exists at
        --head-sha: idempotent no-op, reported on stdout)
    1 — refused: live PR head != --head-sha (head moved since the
        eligibility check; re-run the merge gate)
    2 — environment/API failure (key unreadable, openssl/JWT failure, token
        mint failed, POST rejected); one-line diagnostic on stderr

Stdlib only (deploys into user space with the merge-guard skill). RS256
signing shells out to `openssl dgst -sha256 -sign` — an ambient binary of
the same order as the `gh`/`git` the skill already requires.
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Callable

API = "https://api.github.com"

# (method, url, headers, body) -> (status, parsed JSON). Injected in tests.
Http = Callable[[str, str, dict, bytes | None], tuple[int, object]]
Signer = Callable[[bytes], bytes]


class ApproveError(Exception):
    """Environment/API failure -> exit 2. Message is the one-line diagnostic."""


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def build_jwt(app_id: int, now: int, signer: Signer) -> str:
    header = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = b64url(json.dumps(
        {"iat": now - 60, "exp": now + 540, "iss": str(app_id)}).encode())
    signing_input = f"{header}.{claims}"
    return f"{signing_input}.{b64url(signer(signing_input.encode('ascii')))}"


def openssl_signer(key_path: str) -> Signer:
    def sign(data: bytes) -> bytes:
        try:
            proc = subprocess.run(
                ["openssl", "dgst", "-sha256", "-sign", key_path],
                input=data, capture_output=True, timeout=30)
        except FileNotFoundError as exc:
            raise ApproveError(
                "openssl not found on PATH — it is required to sign the App JWT"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ApproveError(
                "openssl signing timed out after 30s — the App key must be an "
                "unencrypted PEM (a passphrase prompt would hang here)") from exc
        if proc.returncode != 0:
            raise ApproveError(
                "openssl signing failed: "
                + proc.stderr.decode(errors="replace").strip())
        return proc.stdout
    return sign


def urllib_http(method: str, url: str, headers: dict,
                body: bytes | None = None) -> tuple[int, object]:
    request = urllib.request.Request(url, data=body, method=method, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        # urllib sets no Content-Type for a bytes body; every bodied call here
        # sends JSON, so declare it rather than rely on the API inferring it.
        **({"Content-Type": "application/json"} if body is not None else {}),
        **headers,
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        try:
            parsed: object = json.loads(payload or b"null")
        except json.JSONDecodeError:
            parsed = payload.decode(errors="replace")
        return exc.code, parsed
    except urllib.error.URLError as exc:
        raise ApproveError(f"network failure calling {url}: {exc.reason}") from exc


def _expect(status: int, payload: object, what: str, want: int = 200) -> object:
    if status != want:
        raise ApproveError(f"{what}: HTTP {status}: {json.dumps(payload)[:200]}")
    return payload


def mint(http: Http, jwt: str, repo: str) -> tuple[str, str]:
    """App JWT -> (short-lived installation token, app slug)."""
    headers = {"Authorization": f"Bearer {jwt}"}
    app = _expect(*http("GET", f"{API}/app", headers, None), "GET /app")
    status, inst = http("GET", f"{API}/repos/{repo}/installation", headers, None)
    if status == 404:
        raise ApproveError(
            f"app is not installed on {repo} (GET installation -> 404); "
            "install it via the App's settings page")
    inst = _expect(status, inst, "GET repo installation")
    # Scope the token to the single repo and the one permission this script
    # needs — a review POST. An unscoped token would carry every permission the
    # installation holds; least privilege bounds the blast radius if it leaks.
    scope = json.dumps({
        "repositories": [repo.split("/", 1)[1]],
        "permissions": {"pull_requests": "write"},
    }).encode()
    tok = _expect(*http("POST", f"{API}/app/installations/{inst['id']}/access_tokens",
                        headers, scope),
                  "mint installation token", want=201)
    return tok["token"], app["slug"]


def attestation_body(slug: str, head_sha: str, facts: str) -> str:
    # No rule-specific outcome (CI status, triage state) is asserted here: which
    # checks ran is a property of the authorizing merge rule, and this script
    # never re-verifies them. It attests only what it knows — the floor passed
    # and the merge was authorized — and records the caller's facts verbatim.
    return (
        f"Automated policy attestation by `{slug}[bot]` — **not a human review**.\n\n"
        f"The merge-guard eligibility floor passed at `{head_sha}` and the merge "
        "was authorized under this repo's merge policy.\n\n"
        f"Authorizing facts: `{facts}`"
    )


def run(args: argparse.Namespace, http: Http, signer: Signer, now: int) -> int:
    token, slug = mint(http, build_jwt(args.app_id, now, signer), args.repo)
    auth = {"Authorization": f"Bearer {token}"}
    prefix = f"{API}/repos/{args.repo}/pulls/{args.pr}"

    pr = _expect(*http("GET", prefix, auth, None), "GET pull request")
    live_head = pr["head"]["sha"]
    if live_head != args.head_sha:
        sys.stderr.write(
            f"refusing to approve: live head {live_head} != checked head "
            f"{args.head_sha} — re-run the merge gate against the new head\n")
        return 1

    # Paginate: reviews come back oldest-first, so a prior App approval at the
    # current head can sit past page 1 on a heavily-reviewed PR. Missing it would
    # post a duplicate approval, defeating idempotence.
    bot_login = f"{slug}[bot]"
    per_page = 100
    page = 1
    while True:
        reviews = _expect(
            *http("GET", f"{prefix}/reviews?per_page={per_page}&page={page}",
                  auth, None),
            "GET reviews")
        for review in reviews:
            if ((review.get("user") or {}).get("login") == bot_login
                    and review.get("state") == "APPROVED"
                    and review.get("commit_id") == args.head_sha):
                print(f"already approved by {bot_login} at {args.head_sha} "
                      f"(review {review['id']}) — idempotent no-op")
                return 0
        if len(reviews) < per_page:
            break
        page += 1

    body = json.dumps({
        "event": "APPROVE",
        "commit_id": args.head_sha,
        "body": attestation_body(slug, args.head_sha, args.facts),
    }).encode()
    review = _expect(*http("POST", f"{prefix}/reviews", auth, body),
                     "POST approving review")
    print(f"approved: review {review['id']} by {bot_login} "
          f"pinned to {args.head_sha}")
    return 0


def main(argv: list[str] | None = None, *, http: Http = urllib_http,
         signer_factory: Callable[[str], Signer] = openssl_signer,
         clock: Callable[[], float] = time.time) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--head-sha", required=True,
                        help="the head SHA the eligibility floor checked")
    parser.add_argument("--app-id", required=True, type=int)
    parser.add_argument("--key-path", required=True,
                        help="path to the App's private key PEM")
    parser.add_argument("--facts", default="{}",
                        help="eligibility facts JSON, recorded in the review body")
    args = parser.parse_args(argv)

    try:
        if args.repo.count("/") != 1 or not all(args.repo.split("/")):
            raise ApproveError(f"--repo must be owner/name, got {args.repo!r}")
        try:
            with open(args.key_path, "rb"):
                pass
        except OSError as exc:
            raise ApproveError(f"cannot read App key {args.key_path}: {exc}") from exc
        return run(args, http, signer_factory(args.key_path), int(clock()))
    except ApproveError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    except Exception as exc:  # noqa: BLE001 - boundary catch-all, mirrors resolve_policy
        sys.stderr.write(f"error: unexpected {type(exc).__name__}: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
