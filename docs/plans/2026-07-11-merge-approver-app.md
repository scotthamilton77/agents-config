# Merge-Approver GitHub App Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** App-attested approving reviews satisfy branch protection's required review for authorized autonomous merges — opt-in by config presence, fail-loud to human on any error.

**Architecture:** Extend the merge-guard resolver to parse an optional `[merge-policy.approver]` block into the policy JSON; add a stdlib-only `approve_pr.py` (App JWT via openssl subprocess → installation token → APPROVE review pinned to head SHA); wire it into merge-guard Step 5 before the plain merge; scope the existing `--admin` ladder to human-instructed merges. GitHub-side ruleset riders (required `ci` check, dismiss stale reviews) land via `gh api`.

**Tech Stack:** Python >= 3.11 stdlib only (tomllib, urllib, subprocess), `openssl` binary, GitHub REST App APIs, `gh` CLI for ruleset config.

**Spec:** `docs/specs/2026-07-11-merge-approver-app-design.md` · **Bead:** agents-config-vaac.6

**File map:**

| File | Change |
|---|---|
| `src/user/.agents/skills/merge-guard/resolve_policy.py` | Parse `[merge-policy.approver]` → `approver` field in policy JSON |
| `src/user/.agents/skills/merge-guard/resolve_policy_test.py` | New behaviors + update full-dict defaults test |
| `src/user/.agents/skills/merge-guard/approve_pr.py` | **New** — the approver script |
| `src/user/.agents/skills/merge-guard/approve_pr_test.py` | **New** — unit tests (fake http/signer/clock) |
| `src/user/.agents/skills/merge-guard/approve_pr_test.sh` | **New** — smoke wrapper (sibling pattern) |
| `src/user/.agents/skills/merge-guard/SKILL.md` | Step 5 approval wiring + `--admin` ladder scoping + red flags |
| `docs/architecture/review-merge-policy/design.md` | Resolver contract + config schema amendment |
| `docs/specs/2026-07-11-merge-approver-app-design.md` | One-line mechanism alignment (§3.3 step 3) |
| `project-config.toml` | `[merge-policy.approver]` block (needs real App ID) |
| GitHub ruleset `main-protector` (id 15261436) | Riders via `gh api` — config-side, no repo file |

Conventions that bind every task: merge-guard scripts are **stdlib-only** (no PyJWT, no requests); tests are stdlib `unittest` run by a `*_test.sh` wrapper (the `[gates].test` glob discovers only `*_test.sh`); these files deploy to user space, so **no repo-internal paths** in code or tests.

---

### Task 1: Resolver — parse `[merge-policy.approver]`

**Files:**
- Modify: `src/user/.agents/skills/merge-guard/resolve_policy.py`
- Test: `src/user/.agents/skills/merge-guard/resolve_policy_test.py`

- [ ] **Step 1.1: Write failing tests** — append to `resolve_policy_test.py`:

```python
class TestApproverConfig(unittest.TestCase):
    RULE_BASED = (
        '[merge-policy]\n'
        'merge-authorization = "rule-based"\n'
        'merge-rule = "bot-quiescence"\n'
    )

    def test_absent_block_resolves_to_null(self):
        path = write_toml(self.RULE_BASED)
        code, out, err = run_resolver("--project-config", path)
        self.assertEqual(code, 0, err)
        self.assertIsNone(json.loads(out)["approver"])

    def test_valid_block_resolves_with_default_key_path_env(self):
        path = write_toml(
            self.RULE_BASED
            + '[merge-policy.approver]\ntype = "github-app"\napp-id = 123456\n')
        code, out, err = run_resolver("--project-config", path)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["approver"], {
            "type": "github-app",
            "app_id": 123456,
            "key_path_env": "MERGE_GUARD_APPROVER_KEY_PATH",
        })

    def test_key_path_env_override(self):
        path = write_toml(
            self.RULE_BASED
            + '[merge-policy.approver]\ntype = "github-app"\napp-id = 1\n'
              'key-path-env = "MY_KEY"\n')
        code, out, _ = run_resolver("--project-config", path)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["approver"]["key_path_env"], "MY_KEY")

    def test_approver_is_orthogonal_to_authorization_mode(self):
        # Valid under plain explicit mode too — approver is mechanism, not authorization.
        path = write_toml(
            '[merge-policy]\nmerge-authorization = "explicit"\n'
            '[merge-policy.approver]\ntype = "github-app"\napp-id = 7\n')
        code, out, err = run_resolver("--project-config", path)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["approver"]["app_id"], 7)

    def test_missing_app_id_is_policy_error(self):
        path = write_toml(
            self.RULE_BASED + '[merge-policy.approver]\ntype = "github-app"\n')
        code, _, err = run_resolver("--project-config", path)
        self.assertEqual(code, 1)
        self.assertIn("app-id", err)

    def test_unknown_type_is_policy_error(self):
        path = write_toml(
            self.RULE_BASED
            + '[merge-policy.approver]\ntype = "oauth-app"\napp-id = 1\n')
        code, _, err = run_resolver("--project-config", path)
        self.assertEqual(code, 1)
        self.assertIn("oauth-app", err)

    def test_non_integer_app_id_is_policy_error(self):
        path = write_toml(
            self.RULE_BASED
            + '[merge-policy.approver]\ntype = "github-app"\napp-id = "123"\n')
        code, _, err = run_resolver("--project-config", path)
        self.assertEqual(code, 1)
        self.assertIn("app-id", err)

    def test_unknown_key_is_policy_error(self):
        path = write_toml(
            self.RULE_BASED
            + '[merge-policy.approver]\ntype = "github-app"\napp-id = 1\nkey-path = "/x"\n')
        code, _, err = run_resolver("--project-config", path)
        self.assertEqual(code, 1)
        self.assertIn("key-path", err)
```

Also update `TestDefaults.test_no_config_file_yields_builtin_defaults`: add `"approver": None,` to the expected dict (this is the deliberate no-regression pin — the full-dict equality assertion).

- [ ] **Step 1.2: Run tests, verify the new ones fail**

Run: `python3 src/user/.agents/skills/merge-guard/resolve_policy_test.py -v`
Expected: `TestApproverConfig` tests FAIL (`KeyError: 'approver'` / unknown-key PolicyError for the block); defaults test FAILS on the missing key. Pre-existing tests still pass.

- [ ] **Step 1.3: Implement in `resolve_policy.py`**

Add `"approver"` to `MERGE_POLICY_KEYS` (line ~83). After the `PolicyError` class, add:

```python
APPROVER_KEYS = {"type", "app-id", "key-path-env"}
APPROVER_TYPES = {"github-app"}
DEFAULT_APPROVER_KEY_PATH_ENV = "MERGE_GUARD_APPROVER_KEY_PATH"


@dataclass(frozen=True)
class ApproverConfig:
    """Mechanical review-satisfaction identity — never an authorization source."""
    type: str
    app_id: int
    key_path_env: str = DEFAULT_APPROVER_KEY_PATH_ENV
```

Add field to `ReviewMergePolicy` (after the judge fields — it carries a default, so dataclass ordering is satisfied):

```python
    # Optional App-attested approver (spec: 2026-07-11-merge-approver-app-design).
    # Presence enables the approve-then-merge path; None = today's behavior.
    approver: ApproverConfig | None = None
```

Add the parser function and call it inside `resolve_policy()` right before `apply_labels`:

```python
def _parse_approver(merge: dict) -> ApproverConfig | None:
    if "approver" not in merge:
        return None
    section = merge["approver"]
    if not isinstance(section, dict):
        raise PolicyError("[merge-policy.approver] must be a table")
    _check_keys(section, APPROVER_KEYS, "merge-policy.approver")
    if "type" not in section:
        raise PolicyError("[merge-policy.approver]: missing required key 'type'")
    approver_type = _typed(section, "type", str, None)
    if approver_type not in APPROVER_TYPES:
        raise PolicyError(
            f"approver type: {approver_type!r} not in {sorted(APPROVER_TYPES)}")
    if "app-id" not in section:
        raise PolicyError("[merge-policy.approver]: missing required key 'app-id'")
    app_id = _typed(section, "app-id", int, None)
    key_path_env = _typed(section, "key-path-env", str, DEFAULT_APPROVER_KEY_PATH_ENV)
    if not key_path_env:
        raise PolicyError("key-path-env: must be a non-empty string")
    return ApproverConfig(type=approver_type, app_id=app_id, key_path_env=key_path_env)
```

```python
    policy = replace(policy, approver=_parse_approver(merge))
    policy = apply_labels(policy, bead_labels)
```

(`asdict` serializes the nested dataclass to an object and `None` to `null` — no JSON changes needed. `_typed` raises the "expected integer/string" PolicyError for wrong-typed values, including TOML booleans.)

- [ ] **Step 1.4: Run tests, verify all pass**

Run: `python3 src/user/.agents/skills/merge-guard/resolve_policy_test.py -v`
Expected: ALL PASS (including every pre-existing test).

- [ ] **Step 1.5: Commit**

```bash
git add src/user/.agents/skills/merge-guard/resolve_policy.py src/user/.agents/skills/merge-guard/resolve_policy_test.py
git commit -m "feat(merge-guard): resolve optional [merge-policy.approver] block"
```

---

### Task 2: `approve_pr.py` — JWT construction and signing core

**Files:**
- Create: `src/user/.agents/skills/merge-guard/approve_pr.py`
- Create: `src/user/.agents/skills/merge-guard/approve_pr_test.py`

- [ ] **Step 2.1: Write the failing test file** — create `approve_pr_test.py`:

```python
#!/usr/bin/env python3
"""Unit tests for approve_pr.py (stdlib unittest; run via approve_pr_test.sh).

All GitHub traffic goes through an injected fake transport; signing through a
fake signer. No network, no keys, no repo-internal paths.
"""
import base64
import json
import unittest

import approve_pr


def b64pad(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


FAKE_SIGNER = lambda data: b"SIGNATURE"  # noqa: E731 - deliberate tiny fake
NOW = 1_000_000


class TestJwt(unittest.TestCase):
    def test_claims_pin_our_construction_choices(self):
        token = approve_pr.build_jwt(app_id=123456, now=NOW, signer=FAKE_SIGNER)
        header_b64, claims_b64, sig_b64 = token.split(".")
        self.assertEqual(json.loads(b64pad(header_b64)),
                         {"alg": "RS256", "typ": "JWT"})
        self.assertEqual(json.loads(b64pad(claims_b64)),
                         {"iat": NOW - 60, "exp": NOW + 540, "iss": "123456"})
        self.assertEqual(b64pad(sig_b64), b"SIGNATURE")

    def test_no_base64_padding_in_any_segment(self):
        token = approve_pr.build_jwt(app_id=1, now=NOW, signer=FAKE_SIGNER)
        self.assertNotIn("=", token)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2.2: Run to verify failure**

Run: `cd src/user/.agents/skills/merge-guard && python3 approve_pr_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'approve_pr'`

- [ ] **Step 2.3: Create `approve_pr.py` with the core**

```python
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
```

- [ ] **Step 2.4: Run tests, verify pass**

Run: `cd src/user/.agents/skills/merge-guard && python3 approve_pr_test.py -v`
Expected: 2 PASS

- [ ] **Step 2.5: Commit**

```bash
git add src/user/.agents/skills/merge-guard/approve_pr.py src/user/.agents/skills/merge-guard/approve_pr_test.py
git commit -m "feat(merge-guard): approve_pr.py JWT core (stdlib + openssl signer)"
```

---

### Task 3: `approve_pr.py` — API flow (mint, head check, idempotence, POST)

**Files:**
- Modify: `src/user/.agents/skills/merge-guard/approve_pr.py`
- Modify: `src/user/.agents/skills/merge-guard/approve_pr_test.py`

- [ ] **Step 3.1: Write failing tests** — append to `approve_pr_test.py`:

```python
class FakeHttp:
    """Route-table fake transport. Records every call for behavior assertions."""

    def __init__(self, routes):
        self.routes = routes  # {(method, url-suffix-after-API): (status, payload)}
        self.calls = []       # [(method, url, headers, body)]

    def __call__(self, method, url, headers, body=None):
        self.calls.append((method, url, headers, body))
        for (m, suffix), response in self.routes.items():
            if m == method and url == approve_pr.API + suffix:
                return response
        raise AssertionError(f"unexpected call: {method} {url}")

    def posted_reviews(self):
        return [json.loads(b) for m, u, _, b in self.calls
                if m == "POST" and u.endswith("/reviews")]


HEAD = "a" * 40
MOVED = "b" * 40

BASE_ROUTES = {
    ("GET", "/app"): (200, {"slug": "merge-guard-approver"}),
    ("GET", "/repos/o/r/installation"): (200, {"id": 42}),
    ("POST", "/app/installations/42/access_tokens"): (201, {"token": "tok"}),
    ("GET", "/repos/o/r/pulls/5"): (200, {"head": {"sha": HEAD}}),
    ("GET", "/repos/o/r/pulls/5/reviews?per_page=100"): (200, []),
    ("POST", "/repos/o/r/pulls/5/reviews"): (200, {"id": 99}),
}

ARGS = ["--repo", "o/r", "--pr", "5", "--head-sha", HEAD,
        "--app-id", "123456", "--key-path", "/dev/null",
        "--facts", '{"rule": "bot-quiescence"}']


def run_main(routes):
    http = FakeHttp(routes)
    code = approve_pr.main(
        ARGS, http=http, signer_factory=lambda path: FAKE_SIGNER,
        clock=lambda: NOW)
    return code, http


class TestFlow(unittest.TestCase):
    def test_happy_path_posts_pinned_attestation(self):
        code, http = run_main(dict(BASE_ROUTES))
        self.assertEqual(code, 0)
        (review,) = http.posted_reviews()
        self.assertEqual(review["event"], "APPROVE")
        self.assertEqual(review["commit_id"], HEAD)
        self.assertIn("not a human review", review["body"])
        self.assertIn('{"rule": "bot-quiescence"}', review["body"])

    def test_moved_head_refuses_without_posting(self):
        routes = dict(BASE_ROUTES)
        routes[("GET", "/repos/o/r/pulls/5")] = (200, {"head": {"sha": MOVED}})
        code, http = run_main(routes)
        self.assertEqual(code, 1)
        self.assertEqual(http.posted_reviews(), [])

    def test_existing_app_approval_at_head_is_noop(self):
        routes = dict(BASE_ROUTES)
        routes[("GET", "/repos/o/r/pulls/5/reviews?per_page=100")] = (200, [{
            "id": 7, "state": "APPROVED", "commit_id": HEAD,
            "user": {"login": "merge-guard-approver[bot]"},
        }])
        code, http = run_main(routes)
        self.assertEqual(code, 0)
        self.assertEqual(http.posted_reviews(), [])

    def test_stale_or_foreign_approvals_do_not_shortcut(self):
        routes = dict(BASE_ROUTES)
        routes[("GET", "/repos/o/r/pulls/5/reviews?per_page=100")] = (200, [
            {"id": 1, "state": "APPROVED", "commit_id": MOVED,
             "user": {"login": "merge-guard-approver[bot]"}},   # stale commit
            {"id": 2, "state": "APPROVED", "commit_id": HEAD,
             "user": {"login": "some-human"}},                   # not our app
            {"id": 3, "state": "COMMENTED", "commit_id": HEAD,
             "user": {"login": "merge-guard-approver[bot]"}},    # not APPROVED
        ])
        code, http = run_main(routes)
        self.assertEqual(code, 0)
        self.assertEqual(len(http.posted_reviews()), 1)

    def test_token_mint_failure_exits_2_with_status(self):
        routes = dict(BASE_ROUTES)
        routes[("POST", "/app/installations/42/access_tokens")] = (
            401, {"message": "bad credentials"})
        code, http = run_main(routes)
        self.assertEqual(code, 2)
        self.assertEqual(http.posted_reviews(), [])

    def test_app_not_installed_exits_2(self):
        routes = dict(BASE_ROUTES)
        routes[("GET", "/repos/o/r/installation")] = (404, {"message": "Not Found"})
        code, _ = run_main(routes)
        self.assertEqual(code, 2)

    def test_missing_key_file_exits_2(self):
        http = FakeHttp({})
        code = approve_pr.main(
            [*ARGS[:-4], "--key-path", "/nonexistent/nope.pem",
             "--facts", "{}"],
            http=http, signer_factory=approve_pr.openssl_signer,
            clock=lambda: NOW)
        self.assertEqual(code, 2)
        self.assertEqual(http.calls, [])
```

- [ ] **Step 3.2: Run to verify failure**

Run: `cd src/user/.agents/skills/merge-guard && python3 approve_pr_test.py -v`
Expected: `TestFlow` FAILS (`AttributeError: module 'approve_pr' has no attribute 'main'`); `TestJwt` still passes.

- [ ] **Step 3.3: Implement the flow** — append to `approve_pr.py`:

```python
def urllib_http(method: str, url: str, headers: dict,
                body: bytes | None = None) -> tuple[int, object]:
    request = urllib.request.Request(url, data=body, method=method, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
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
    tok = _expect(*http("POST", f"{API}/app/installations/{inst['id']}/access_tokens",
                        headers, b""),
                  "mint installation token", want=201)
    return tok["token"], app["slug"]


def attestation_body(slug: str, head_sha: str, facts: str) -> str:
    return (
        f"Automated policy attestation by `{slug}[bot]` — **not a human review**.\n\n"
        f"The merge-guard eligibility floor passed at `{head_sha}`: CI green, bot "
        "review clean at head, all review feedback triaged.\n\n"
        f"Attestation facts: `{facts}`"
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

    reviews = _expect(*http("GET", f"{prefix}/reviews?per_page=100", auth, None),
                      "GET reviews")
    bot_login = f"{slug}[bot]"
    for review in reviews:
        if ((review.get("user") or {}).get("login") == bot_login
                and review.get("state") == "APPROVED"
                and review.get("commit_id") == args.head_sha):
            print(f"already approved by {bot_login} at {args.head_sha} "
                  f"(review {review['id']}) — idempotent no-op")
            return 0

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
```

- [ ] **Step 3.4: Run tests, verify all pass**

Run: `cd src/user/.agents/skills/merge-guard && python3 approve_pr_test.py -v`
Expected: ALL PASS (2 JWT + 7 flow)

- [ ] **Step 3.5: Commit**

```bash
git add src/user/.agents/skills/merge-guard/approve_pr.py src/user/.agents/skills/merge-guard/approve_pr_test.py
git commit -m "feat(merge-guard): approve_pr.py API flow — mint, head pin, idempotence, POST"
```

---

### Task 4: Test wrapper + spec mechanism alignment

**Files:**
- Create: `src/user/.agents/skills/merge-guard/approve_pr_test.sh`
- Modify: `docs/specs/2026-07-11-merge-approver-app-design.md` (§3.3 step 3)

- [ ] **Step 4.1: Create `approve_pr_test.sh`** (sibling pattern; the `[gates].test` glob discovers only `*_test.sh`):

```bash
#!/usr/bin/env bash
# Smoke wrapper: runs the Python unittest suite for approve_pr.py.
# The [gates].test glob only discovers *_test.sh, hence this shim.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "[approve_pr_test]"

skip() {
    echo "" >&2
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
    echo "SKIPPED: approve_pr suite NOT RUN (python3 >=3.11 unavailable)" >&2
    echo "reason: $1" >&2
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
    echo "" >&2
    exit 0
}

if ! command -v python3 >/dev/null 2>&1; then
    skip "python3 not found on PATH"
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    skip "python3 < 3.11"
fi

cd "$HERE" && python3 approve_pr_test.py -v
```

Then: `chmod +x src/user/.agents/skills/merge-guard/approve_pr_test.sh`

- [ ] **Step 4.2: Run wrapper, verify pass**

Run: `src/user/.agents/skills/merge-guard/approve_pr_test.sh`
Expected: suite runs, ALL PASS, exit 0

- [ ] **Step 4.3: Align spec §3.3 step 3** — in `docs/specs/2026-07-11-merge-approver-app-design.md`, replace the sentence

> `3. Fetch the PR. If \`reviewDecision\` is already \`APPROVED\` → exit 0 (idempotent).`

with

> `3. Fetch the PR. If this App already has an APPROVED review at \`--head-sha\` (REST reviews list filtered to the App's \`[bot]\` login — \`reviewDecision\` is GraphQL-only) → exit 0 (idempotent).`

- [ ] **Step 4.4: Commit**

```bash
git add src/user/.agents/skills/merge-guard/approve_pr_test.sh docs/specs/2026-07-11-merge-approver-app-design.md
git commit -m "test(merge-guard): approve_pr smoke wrapper; align spec idempotence mechanism"
```

---

### Task 5: merge-guard SKILL.md wiring

**Files:**
- Modify: `src/user/.agents/skills/merge-guard/SKILL.md`

No unit tests (prose); verification is the live tracer bullet (Task 9).

- [ ] **Step 5.1: Insert the pre-merge approval subsection** in Step 5, immediately AFTER the full-floor re-clear paragraph ("...where review state has the most time to shift underneath it.") and BEFORE the `gh pr merge` code block:

```markdown
**Pre-merge approval (only when the policy carries an approver).** If
`POLICY_JSON.approver` is non-null AND
`gh pr view <n> --json reviewDecision -q .reviewDecision` reads
`REVIEW_REQUIRED`, satisfy the review requirement with the App attestation
before merging:

    KEY_ENV="<policy.approver.key_path_env>"           # e.g. MERGE_GUARD_APPROVER_KEY_PATH
    if [ -z "${!KEY_ENV:-}" ]; then
      echo "approver configured but \$$KEY_ENV is unset — merge by hand" >&2
      exit 3                                            # fail loud; hand off
    fi
    python3 "${CLAUDE_SKILL_DIR}/approve_pr.py" \
      --repo <owner>/<repo> --pr <n> \
      --head-sha "<head_ref_oid from the re-cleared floor JSON>" \
      --app-id <policy.approver.app_id> \
      --key-path "${!KEY_ENV}" \
      --facts '<compact JSON: {"rule": <merge_rule>, "bot_clean_review_at_head": ..., "ci_state": ...} from facts>'

- Exit 0 → re-read `gh pr view <n> --json reviewDecision -q .reviewDecision`.
  `APPROVED` → proceed to the plain merge below (the script is idempotent: an
  existing App approval at this head is a no-op). Still `REVIEW_REQUIRED` →
  **HALT and hand off**: the App's approval did not satisfy the rule — a
  design assumption is falsified; report it, do not merge, do not `--admin`.
- Exit 1 (head moved) → re-run from Step 3 against the new head. Never
  retry blind.
- Exit 2 (key/mint/API failure) → **HALT. Report the script's stderr
  verbatim and hand off to the human.** Never retry silently, never fall
  back to `--admin`. The approver failing is a hand-off, not a bypass
  ticket.
- `reviewDecision` already `APPROVED` (or null — no review requirement) →
  skip this step entirely.

The approver is **mechanism, not authorization**: it never runs unless
Axis 2 already authorized the merge (a rule that held, or an explicit
in-session instruction) and the floor re-cleared. Under `never` it is
unreachable. The review it posts states what it attests and that it is not
a human review.
```

- [ ] **Step 5.2: Scope the `--admin` ladder to human-instructed merges.** In the Step 5 `facts.admin_bypass` table, replace the `current_actor_can_bypass == true` row's action text with:

```markdown
| `current_actor_can_bypass == true` **and the merge was human-instructed in-session** (explicit-mode merge word or named force-merge) | GitHub already grants the authenticated identity a standing bypass on this rule. Retry once: `gh pr merge <n> --squash --admin --match-head-commit "<head_ref_oid>"`. Announce plainly that `--admin` was used, quote the rejection text that justified it, and note why — the identity holds a pre-existing GitHub bypass grant, and eligibility + authorization were already confirmed independently of it. |
| `current_actor_can_bypass == true` **and the merge is autonomous** (`rule-based`, no in-session human instruction) | **Fail closed — `--admin` is never an autonomous path** (PR #240: the auto-mode classifier blocks unsupervised `--admin`, and policy agrees). Hand off to the human, or configure `[merge-policy.approver]` so autonomous merges satisfy the review rule instead of bypassing it. |
```

- [ ] **Step 5.3: Add red-flag rows** to the Red Flags table:

```markdown
| "approve_pr.py failed, fall back to `--admin`" | No. The approver's fail-loud contract IS the design: exit != 0 → hand off to the human. `--admin` never launders an approver failure. |
| "Rule held, GitHub wants a review, I hold a bypass — `--admin` it" | Autonomous `--admin` is dead (PR #240 precedent). The approver path exists precisely for this; if it isn't configured, hand off. |
```

- [ ] **Step 5.4: Commit**

```bash
git add src/user/.agents/skills/merge-guard/SKILL.md
git commit -m "docs(merge-guard): wire pre-merge App approval; scope --admin ladder to human-instructed merges"
```

---

### Task 6: HLD amendment — `docs/architecture/review-merge-policy/design.md`

**Files:**
- Modify: `docs/architecture/review-merge-policy/design.md`

- [ ] **Step 6.1: Extend the Resolver contract** — in the `ReviewMergePolicy = {...}` block (after the judge fields), add:

```
    # Optional App-attested approver (mechanism, not authorization; None = absent)
    approver: {type: "github-app", app_id: int, key_path_env: str} | None,
```

And to the invalid-combinations bullet list, append:

```markdown
  - `[merge-policy.approver]` present with an unknown `type` (only
    `"github-app"` is implemented), a missing or non-integer `app-id`, an
    empty `key-path-env`, or any unrecognized key.
```

- [ ] **Step 6.2: Extend the Config schema section** — after the `[merge-policy]` key table, add:

```markdown
`[merge-policy.approver]` (optional sub-table — presence enables the
approve-then-merge path in merge-guard Step 5; absence preserves prior
behavior exactly):

| Key | Type | Default |
|---|---|---|
| `type` | `"github-app"` | — (required) |
| `app-id` | int | — (required) |
| `key-path-env` | str (env var naming the PEM path) | `"MERGE_GUARD_APPROVER_KEY_PATH"` |

The approver is orthogonal to `merge-authorization`: it is mechanism for
satisfying GitHub's required-review rule on an **already-authorized** merge
(rule-based rule held, or explicit human instruction), never an
authorization source. Key material never appears in config — only the name
of the environment variable that points to it.
Spec: `docs/specs/2026-07-11-merge-approver-app-design.md`.
```

- [ ] **Step 6.3: Commit**

```bash
git add docs/architecture/review-merge-policy/design.md
git commit -m "docs(architecture): add [merge-policy.approver] to review-merge-policy contract"
```

---

### Task 7: Ruleset riders (GitHub-side config — run, don't commit)

No repo files. Requires repo admin (`gh` as the owner). Do this from any checkout.

- [ ] **Step 7.1: Fetch current ruleset** (rules must be sent whole — PUT replaces):

```bash
gh api repos/scotthamilton77/agents-config/rulesets/15261436 > /tmp/ruleset-current.json
```

- [ ] **Step 7.2: Apply riders** — required `ci` status check + dismiss stale reviews. `strict_required_status_checks_policy: false` deliberately (linear-history squash flow; merge-guard re-checks freshness itself, and `strict` would demand a rebase per merge):

```bash
python3 - <<'EOF'
import json
cur = json.load(open("/tmp/ruleset-current.json"))
rules = [r for r in cur["rules"] if r["type"] != "required_status_checks"]
for r in rules:
    if r["type"] == "pull_request":
        r["parameters"]["dismiss_stale_reviews_on_push"] = True
rules.append({"type": "required_status_checks", "parameters": {
    "strict_required_status_checks_policy": False,
    "required_status_checks": [{"context": "ci"}],
}})
json.dump({"name": cur["name"], "target": cur["target"],
           "enforcement": cur["enforcement"],
           "bypass_actors": cur["bypass_actors"],
           "conditions": cur["conditions"], "rules": rules},
          open("/tmp/ruleset-new.json", "w"), indent=2)
EOF
gh api -X PUT repos/scotthamilton77/agents-config/rulesets/15261436 --input /tmp/ruleset-new.json
```

(If the sandbox rejects the heredoc, write the Python to a temp file first — same code.)

- [ ] **Step 7.3: Verify**

```bash
gh api repos/scotthamilton77/agents-config/rulesets/15261436 --jq '[.rules[] | {type, parameters}]'
```

Expected: `required_status_checks` rule present with context `ci`; `pull_request.dismiss_stale_reviews_on_push: true`; all previous rules intact.

---

### Task 8: `project-config.toml` approver block — **blocked on owner input (App ID)**

**Files:**
- Modify: `project-config.toml` (the `[merge-policy]` area)

Prerequisite: the owner has created + installed the `merge-guard-approver` App and provided its numeric App ID.

- [ ] **Step 8.1: Add the block** directly under the existing `[merge-policy]` keys:

```toml
# Optional App-attested approver: satisfies GitHub's required-approving-review
# on already-authorized merges (merge-guard Step 5). Presence enables; the key
# travels via the env var below, never through config.
[merge-policy.approver]
type         = "github-app"
app-id       = 0   # <- replace with the real merge-guard-approver App ID
key-path-env = "MERGE_GUARD_APPROVER_KEY_PATH"
```

- [ ] **Step 8.2: Verify the resolver accepts the real config**

```bash
python3 src/user/.agents/skills/merge-guard/resolve_policy.py --project-config project-config.toml | python3 -c "import json,sys; print(json.load(sys.stdin)['approver'])"
```

Expected: the approver object with the real App ID.

- [ ] **Step 8.3: Commit**

```bash
git add project-config.toml
git commit -m "feat(config): enable merge-guard App-attested approver"
```

---

### Task 9: Live tracer bullet (verifies spec §6 assumptions (a) and (b))

Prerequisites: App created + installed, key at the env-var path, Tasks 1–8 done, this branch pushed as a PR, PR groomed to floor-clean (CI green, Copilot clean).

Until the installer runs, invoke the **worktree source path** explicitly (the installed `~/.claude/skills/merge-guard/` copy is stale until `scripts/install.sh`).

- [ ] **Step 9.1: Approve this PR via the new script**

```bash
python3 src/user/.agents/skills/merge-guard/approve_pr.py \
  --repo scotthamilton77/agents-config --pr <this-PR> \
  --head-sha "$(gh pr view <this-PR> --json headRefOid -q .headRefOid)" \
  --app-id <real-app-id> --key-path "$MERGE_GUARD_APPROVER_KEY_PATH" \
  --facts '{"rule": "bot-quiescence", "tracer": true}'
```

Expected: `approved: review <id> by merge-guard-approver[bot] pinned to <sha>`

- [ ] **Step 9.2: Verify assumption (a) — the approval satisfies the rule**

```bash
gh pr view <this-PR> --json reviewDecision -q .reviewDecision
```

Expected: `APPROVED`. If still `REVIEW_REQUIRED` → assumption falsified; STOP, hand off, revisit design (spec §4 last-but-one row).

- [ ] **Step 9.3: Verify assumption (b) — merge via the normal merge-guard flow** (full Step 3 re-clear, then plain merge with `--match-head-commit`). Expected: merge succeeds with no `--admin`, no classifier objection. PR #240 follows the same recipe immediately after.

---

### Post-implementation gates (session-level, not plan tasks)

Changes under `src/**` floor the completion gate at **HEAVY**: run `gate-triage`, then `Workflow({name: "quality-gate", args: <triage JSON>})`, then `verify-checklist`. Delivery continues through `finishing-a-development-branch` → PR → `wait-for-pr-comments` → merge-guard (which, fittingly, this PR upgrades). Close bead agents-config-vaac.6 only after the tracer bullet lands and beads are pushed.
