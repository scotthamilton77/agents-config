# Merge-Approver GitHub App — App-Attested PR Approval for Autonomous Merges

**Date:** 2026-07-11
**Status:** Draft (pending review)
**Bead:** agents-config-vaac.6
**Decision:** A repo-scoped GitHub App identity (`merge-guard-approver[bot]`), driven
by the merge-guard skill at merge time, submits the approving review that satisfies
branch protection's `required_approving_review_count` — only after the merge-guard
eligibility floor has passed, pinned to the checked head SHA. The behavior is opt-in
by presence of a `[merge-policy.approver]` config block and fails loud to human
intervention on any error. Two ruleset riders land alongside: required status check
`ci` and `dismiss_stale_reviews_on_push: true`.

## 1. Problem

Taking the repo public activated the `main-protector` ruleset on `main`. Its
`pull_request` rule requires **1 approving review** — which no actor in the current
system can supply:

- The agent authors PRs as the repo owner; GitHub forbids approving your own PR.
- Copilot code review only ever comments; it never approves.
- The owner's ruleset bypass (`RepositoryRole: admin, bypass_mode: always`) is
  exercisable only via `gh pr merge --admin`, which the auto-mode classifier
  correctly blocks for an unsupervised agent (observed on PR #240).

Net effect: every rule-based autonomous merge dead-ends at
`reviewDecision: REVIEW_REQUIRED` and hands the merge back to the human — defeating
the repo's `rule-based` / `bot-quiescence` merge policy and the prime directive
(get the human out of the babysitting job).

Two adjacent gaps surfaced during diagnosis:

- The ruleset has **no required status checks** — GitHub itself would merge a
  red-CI PR; only merge-guard's floor prevents it.
- A PR-open-time auto-approval (GitHub Actions workflow) was considered and
  rejected: it flips `reviewDecision` to `APPROVED` before Copilot review and
  grooming even start — a chronologically false signal to both humans and agents
  reading PR state.

## 2. Goals and non-goals

**Goals**

1. Autonomous merges **satisfy** branch protection rather than bypass it.
2. External/fork PRs still face a required human review — the protection stays
   meaningful for contributors now that the repo is public.
3. The approval signal is honest: distinct bot identity, issued only after the
   merge gate actually passed, pinned to the exact head SHA, with a body stating
   what it attests and that it is not a human review.
4. Opt-in by configuration presence: absent the config block, behavior today is
   preserved byte-for-byte.
5. Fail loud: any approver failure halts the merge with a specific error and hands
   off to the human. Never a silent fallback, never `--admin`.

**Non-goals**

- Replacing or weakening the merge-guard eligibility floor (it remains the quality
  gate; the approval is mechanical satisfaction of GitHub's rule, not a second gate).
- Auto-approving external contributors' PRs.
- Automating `--admin`/bypass merges (autonomous use is permanently out of scope;
  classifier-blocked by design). A **human-directed** `--admin` merge — the owner
  explicitly instructing it in-session — remains available as the owner's
  emergency lever, exercised by the owner directly or by the agent as directed
  proxy.
- Hosting anything: no webhooks, no server. The App is an identity with a keypair.

## 3. Design

### 3.1 The App identity

A **GitHub App** (not an OAuth App — OAuth Apps act *as the authorizing user*, who
is the PR author and cannot self-approve; a GitHub App has its own `[bot]` identity
whose approvals count toward `required_approving_review_count`).

One-time manual setup per install target (owner does this; the agent cannot):

1. GitHub → Settings → Developer settings → GitHub Apps → New GitHub App.
   - Name: `merge-guard-approver` (display identity: `merge-guard-approver[bot]`).
   - Webhook: **unchecked** (no hosted receiver).
   - Permissions: **Pull requests: Read & write** and **Contents: Read & write** —
     both required. Without `Contents: write`, GitHub records the App's approving
     review but does **not** count it toward `required_approving_review_count`
     (`reviewDecision` stays `REVIEW_REQUIRED`). This widens the key's blast radius
     — see §5.
   - Installable: only on the owning account.
2. Generate a private key (GitHub issues RSA/PKCS#1); store it locally, e.g.
   `~/.config/merge-guard/approver.pem`, `chmod 600`. Never in any repo.
3. Install the App on the target repository.

The installation ID is resolved at runtime from the App JWT
(`GET /repos/{repo}/installation`) — it is not configuration.

### 3.2 Configuration contract (opt-in switch)

`project-config.toml` grows an optional block, parsed by the merge-guard resolver
(`resolve_policy.py`) and emitted in its policy JSON:

```toml
[merge-policy.approver]
type         = "github-app"                        # required; only supported value
app-id       = 123456                               # required; integer App ID
key-path-env = "MERGE_GUARD_APPROVER_KEY_PATH"      # optional; default shown
```

Resolution semantics:

| Config state | Resolved policy | Merge-time behavior |
|---|---|---|
| Block absent | `approver: null` | **Existing behavior, unchanged.** No approval attempted; a GitHub review-required rejection halts and hands to human. |
| Block present, valid | `approver: {type, app_id, key_path_env}` | Approve-then-merge path armed (see 3.4). |
| Block present, invalid (unknown `type`, missing/non-integer `app-id`) | Resolver exits 1 (`PolicyError`) | Fail loud at policy-resolution time. Invalid intent never silently downgrades to "no approver". |

The secret itself travels only via the environment variable named by
`key-path-env` (value = filesystem path to the PEM). Config carries no key
material and no absolute user paths.

The `[merge-policy]` schema documentation in
`docs/architecture/review-merge-policy/design.md` ("Resolver contract" and the
Axis-2 schema section) is amended in the same change that implements the resolver
extension — spec/code/HLD stay in agreement.

### 3.3 Approver script contract — `approve_pr.py`

New script in the merge-guard skill (deploys to user space; **stdlib-only Python
>= 3.11**, matching sibling scripts). RS256 signing uses a subprocess call to
`openssl dgst -sha256 -sign` — `openssl` is an ambient binary dependency of the
same order as `gh`/`git`, which the skill already requires. HTTP via
`urllib.request` (the JWT-authenticated calls cannot ride `gh api`'s own auth).

```
Usage:
    approve_pr.py --repo <owner/name> --pr <number> --head-sha <sha>
                  --app-id <id> --key-path <pem> [--facts <json>]

Exit codes:
    0 — approval submitted (or PR already APPROVED; idempotent no-op, says so)
    1 — refused: live PR head != --head-sha (head moved since eligibility check)
    2 — environment/API failure (key unreadable, mint failed, POST rejected);
        concise one-line diagnostic on stderr, never a raw traceback
```

Behavior:

1. Read key; build App JWT (stdlib header/claims + openssl signature;
   `iat` backdated 60s, `exp` +9 min, `iss` = app-id).
2. Exchange JWT for a short-lived installation token, scoped down at mint time to
   this single repo and `pull_requests: write` — the least privilege a review
   POST needs — so a leaked *token* cannot exercise the installation's other grants,
   including `contents: write` (see §5). Mint flow: `GET /app` →
   `GET /repos/{repo}/installation` → `POST /app/installations/{id}/access_tokens`.
3. Fetch the PR. If this App already has an APPROVED review at `--head-sha`
   (REST reviews list filtered to the App's `[bot]` login — `reviewDecision` is
   GraphQL-only) → exit 0 (idempotent).
   If live head SHA != `--head-sha` → exit 1, refuse (the approval must attest the
   exact commit the eligibility floor checked).
4. `POST /repos/{repo}/pulls/{pr}/reviews` with `event: APPROVE`,
   `commit_id: <head-sha>`, and the attestation body:

   > Automated policy attestation by merge-guard-approver[bot] — **not a human
   > review**. The merge-guard eligibility floor passed at `<sha>` and the merge
   > was authorized under this repo's merge policy. Authorizing facts:
   > `<facts JSON>`.

   The body asserts no rule-specific outcome (CI status, triage state): which
   checks constitute the floor is a property of the authorizing rule, and the
   approver never re-verifies them. `--facts` carries that detail — the
   eligibility summary (rule name, floor outputs) from the merge-guard run — so
   the review body records *why* the approval exists without the fixed prose
   claiming outcomes it did not check.

### 3.4 merge-guard wiring (the only step that changes)

In the merge-execution step, after eligibility exits 0 and merge authorization is
established (rule-based rule holding, or an explicit human "merge it"):

```
if reviewDecision == REVIEW_REQUIRED:
    if policy.approver is null:        # today's behavior
        attempt plain merge; on review-required rejection → halt, hand to human
    else:
        run approve_pr.py bound to the checked head SHA
        exit 0 → re-read reviewDecision; proceed to plain merge
        exit != 0 → HALT. Report the script's diagnostic verbatim.
                    Never retry silently. Never fall back to --admin.
                    Hand to human.
plain merge: gh pr merge --squash --match-head-commit <sha>
```

Properties: the approver is **not** an authorization source — it never runs unless
merge-guard already decided the merge is authorized; under `merge-authorization =
"never"` it never fires. `--match-head-commit` keeps the merge bound to the same
SHA the approval attested. The skill documentation additionally records, as policy:
**`--admin` is never an autonomous path** (PR #240 precedent) — it remains
available under explicit in-session human direction as the owner's emergency
bypass, which always supersedes the rule-based flow.

### 3.5 Ruleset riders (GitHub-side config, applied via `gh api`)

Applied to `main-protector` alongside this work; recorded here for
reproducibility on the work-machine fork:

1. **Required status checks**: add rule `required_status_checks` requiring check
   context `ci` (the single job of `.github/workflows/ci.yml`, which runs on every
   PR with no path filters — verified, so no PR class can be stranded). GitHub
   then enforces CI-green independent of merge-guard.
2. **`dismiss_stale_reviews_on_push: true`** on the `pull_request` rule: pushes
   invalidate stale approvals. Costs the autonomous path nothing (the App approves
   at merge time, post-quiescence) and makes external approvals strictly honest.

## 4. Failure modes (all fail-closed to human hand-off)

| Failure | Detection | Outcome |
|---|---|---|
| Approver config invalid | resolver exit 1 | Halt at policy resolution with `PolicyError` message |
| Key env var unset / file missing / unreadable | `approve_pr.py` exit 2 | Halt merge; report exact cause; no `--admin` |
| JWT mint or token exchange rejected (clock skew, revoked key, App uninstalled) | exit 2 with API status + message | Same |
| PR head moved after eligibility check | exit 1 | Halt; re-run of the merge gate re-checks the new head |
| Approval accepted but `reviewDecision` doesn't flip (e.g. App approval doesn't satisfy the rule — see §6 risk (a)) | post-approve re-read in wiring | Halt; report; escalate to owner — assumption falsified |
| Auto-mode classifier blocks approve-then-merge | tool-call denial | Owner runs the recorded command once; document precedent (§6 risk (b)) |

## 5. Security considerations

- **Blast radius of the key**: the App installation holds **`Contents: write`**
  (required for its approval to count — see §3.1), so a holder of the PEM key can
  push code to the installed repos, not just approve PRs. Guard it as a write
  credential: local file, 0600, outside all repos. Mitigation: `approve_pr.py` mints
  a token scoped down to `pull_requests: write` at run time, so the token it actually
  uses cannot push — but a holder of the key itself can mint the fuller grant.
- **No new bypass**: the ruleset's bypass list is untouched; the App *satisfies*
  the review rule. Emergency manual bypass remains the owner's, manually.
- **External PRs**: unaffected. The approver runs only inside merge-guard's
  authorized-merge path for PRs that passed the floor; fork PRs from external
  authors still require a human approving review, now with stale-approval
  dismissal and GitHub-enforced CI.
- **No secrets in Actions**: nothing is added to CI; the Actions
  `can_approve_pull_request_reviews` setting stays `false`.
- **Rogue-agent scope**: an agent with the key could approve an eligible PR early,
  but cannot merge past CI, cannot bypass, and every approval is a logged,
  attributable review event pinned to a SHA.

## 6. Assumptions to verify (tracer bullet)

Two load-bearing assumptions are verified on a real PR before this design is
declared working; both have designed fallbacks:

- **(a) An App approval counts toward `required_approving_review_count`.**
  Verified on PR #250 — **conditional on the App holding `Contents: write`**. With
  `Pull requests: write` alone the approval is recorded but does not count
  (`reviewDecision` stays `REVIEW_REQUIRED`); granting `Contents: write` flips it to
  `APPROVED` and a plain merge succeeds. `author_association` reads `NONE` either
  way — GitHub's review-counting honors the App's real repo write permission, not
  that field. Had it failed outright, the post-approve re-read would halt (see §4).
- **(b) The auto-mode classifier permits approve-then-merge.** Verified on PR #250 —
  the plain (non-`--admin`) squash merge completed. Unlike `--admin`, this exercises
  a purpose-built, human-provisioned credential to satisfy (not bypass) the rule.
  Had it been blocked, the fallback is the owner running the recorded command once;
  precedent documented in the skill.

## 7. Test plan

Unit tests follow the sibling pattern (`approve_pr_test.py` + `approve_pr_test.sh`
smoke wrapper; deployed to user space, so no repo-internal paths). Behaviors, not
plumbing — the JWT *construction decisions* are ours to pin; RSA math and GitHub's
API are not under test. HTTP and signing go behind injected callables (fakes, not
mock-call assertions).

Resolver (`resolve_policy_test.py` additions):

1. Config without `[merge-policy.approver]` resolves to `approver: null` and the
   rest of the policy JSON is unchanged from today (pin the no-regression contract).
2. Valid block resolves to the typed approver object with the default
   `key-path-env` applied when omitted.
3. Unknown `type` / missing `app-id` / non-integer `app-id` → exit 1 with a
   message naming the offending key.

Approver script (`approve_pr_test.py`):

4. JWT claims: `iss` = app-id, `iat` backdated 60s, `exp` = +9 min from injected
   clock; header/payload base64url-encoded without padding (our encoding choices).
5. Already-`APPROVED` PR (fake transport) → exit 0, no review POSTed.
6. Live head != `--head-sha` (fake transport) → exit 1, no review POSTed.
7. Review POST payload: `event: APPROVE`, `commit_id` = the given SHA, body
   contains the not-a-human-review attestation and the `--facts` JSON.
8. Missing key file / unset env → exit 2 with a one-line diagnostic (no traceback).
9. Token-exchange HTTP failure (fake transport returns 401) → exit 2, diagnostic
   includes the API status.
10. Installation-token mint is scoped: the `access_tokens` POST body requests only
    this repo and `pull_requests: write`, never an unscoped token.
11. Idempotence pagination: a prior App approval at head sitting past the first
    reviews page (full first page forces a second GET) is still found → exit 0,
    no duplicate POST.

Integration (not unit-tested; verified live): the tracer bullet in §6 on a real
PR — approve, observe `reviewDecision` flip, plain merge succeeds.

## 8. Rollout / bootstrap order

1. Owner creates + installs the App, generates the key, exports
   `MERGE_GUARD_APPROVER_KEY_PATH` (shell profile), provides the App ID.
2. Ruleset riders applied via `gh api` (config-side; no repo code).
3. Implementation lands via PR: resolver extension + `approve_pr.py` + tests +
   merge-guard SKILL.md wiring + HLD amendment + `[merge-policy.approver]` block
   in this repo's `project-config.toml`.
4. That PR (and the currently blocked PR #240) are the first customers: approved
   through the new mechanism as the live tracer bullet. Bootstrap note: until the
   implementation PR merges *and installs*, the session drives `approve_pr.py`
   from the worktree source path directly.
5. Work-machine fork: install the same App on that repo (or a sibling App at
   work), set the env var, add the config block — the pattern is per-installation.

## 9. Continuations

- **Implement merge-approver App support** (this spec): resolver extension,
  `approve_pr.py` + tests, merge-guard SKILL.md wiring, HLD amendment, ruleset
  riders, project-config block. Acceptance: PR #240-class merges complete
  autonomously on this repo with the approval attesting the floor facts; absent
  config, behavior identical to today; all §7 behaviors green.
- **Portability follow-up**: document/install the App on the work-machine fork
  once it exists (PORT track).
