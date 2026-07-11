#!/usr/bin/env python3
"""approve_pr.py — submit an App-attested approving review on a PR.

Satisfies branch protection's required approving review with a GitHub App
identity, at merge time, pinned to the head SHA the merge-guard eligibility
floor checked. Spec: docs/specs/2026-07-11-merge-approver-app-design.md
(§3.3 "Approver script contract").

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
        proc = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_path],
            input=data, capture_output=True, timeout=30)
        if proc.returncode != 0:
            raise ApproveError(
                "openssl signing failed: "
                + proc.stderr.decode(errors="replace").strip())
        return proc.stdout
    return sign
