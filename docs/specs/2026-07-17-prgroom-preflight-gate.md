# prgroom preflight gate — auth, reachability, repo identity, and the 5xx-misdiagnosis ruling

**Date:** 2026-07-17
**Status:** Approved (design)
**Beads:** agents-config-s0u9c (preflight gate design); agents-config-abn9.8.44 (gh-auth probe misdiagnoses GitHub 5xx incidents as auth failure) — absorbed by this spec's ruling (§3, Continuations).
**Related:** `docs/architecture/prgroom/design.md` §3.6 — the failure-tier/exit-code registry this gate raises into; `docs/architecture/prgroom/cutover-runbook.md` "Operator preflight" — the manual checklist this gate automates; agents-config-abn9.8.14 / abn9.8.20 — the cutover that retires `wait-for-pr-comments/lib.sh`, which is why that file gets no fix (§3); `2026-07-16-merge-gate-triage-aware-thread-blocker.md` — sibling amendments to the same `check-merge-eligibility.sh` this spec's merge-guard fix touches.

## 1. Problem

1. **Registered, never raised.** `PRECONDITION_NO_AUTH` and `PRECONDITION_REPO_UNREACHABLE` exist in prgroom's error registry (`errors.py`, enum + what/why/how entries) and in the design doc's §3.6 code table, but no code path constructs either — there is no `gh auth` probe and no repo probe anywhere in `packages/prgroom/src/prgroom/`. A run against a bad token or an unreachable repo fails mid-lifecycle with whatever runtime error the first API call happens to produce, after taking the lock.
2. **No repo-identity check.** The wrong-branch guard (`lifecycle/push.py`) compares branch *names* only; nothing verifies the CWD worktree's `origin` points at the PR ref's `owner/repo`. `GitClient` has no remote-inspection method at all, and `PRRef.parse`'s `default_repo` seam is never fed (`cli.py` notes the current-repo context seam as deferred) — a worktree of the *wrong repository* on a same-named branch would pass the guard and push.
3. **The misdiagnosis bug (abn9.8.44).** The shared PR-skills probe pattern — an `if ! gh auth status &>/dev/null` guard printing `Error: gh auth failed — not authenticated` to stderr and exiting 3 — exists in two independently-maintained copies: `src/user/.agents/skills/wait-for-pr-comments/lib.sh` (`preflight_checks`, consumed by the three poll scripts) and a duplicate in `src/user/.agents/skills/merge-guard/check-merge-eligibility.sh` (its file comment says "keep this copy in sync"). `gh auth status` probes GitHub's `/user` endpoint; during the 2026-07-16/17 "Degraded REST API Availability" incident that endpoint returned 503 for ~10 hours with a valid token while every functionally-needed endpoint worked — both copies deterministically reported "not authenticated" and stalled PR #291's autonomous merge leg behind a wrong diagnosis. (The bead also names `judge_merge.py` as a consumer; that is incorrect — its only `lib` match is the `hashlib` substring. Two copies, not three.)

## 2. Decision — the prgroom preflight

**A single preflight function, called once at corridor entry, that classifies by HTTP status instead of trusting a proxy probe.**

### 2.1 Placement

`preflight(gh, git, ref, *, check_identity: bool)` in a new `lifecycle/preflight.py`, invoked from `cli.py`:

- **`run`** — full preflight (`check_identity=True`), after `PRRef.parse` and **before `run_lifecycle` acquires the PR lock**: a run that cannot work must not take the lock or touch state.
- **`wait`** — auth + reachability only (`check_identity=False`): `wait` never touches the worktree.
- **Standalone verbs (`poll`/`fix`/`push`/…) — unchanged.** They are debugging/recovery tools; their existing mid-run classification already produces correct typed errors, and `push` keeps its branch guard (extended, §2.3). Wiring preflight into every verb is deliberately rejected: it would add a network round-trip to `status` (which must work offline against local state) and re-probe on every step of scripted verb sequences.

Startup-once is the contract: no re-probing mid-run. A mid-run auth expiry or repo disappearance is already handled by the existing classification — 401 (other-4xx) and vanished-404 both map to `RUNTIME_GH_TERMINAL` / tier `RUNTIME_TERMINAL_USER` (exit 77, phase → `human-gated`) — which matches the decision steer ("mid-run 401/404 is terminal → human-gated") with **no change needed**; this spec affirms that path rather than redesigning it.

### 2.2 The probe — one API call, status-classified

The probe is `gh api repos/{owner}/{repo}` against the PR ref's repo — an endpoint the run *actually needs*, never a proxy like `/user`. One call answers both preconditions:

| Outcome | Classification | Tier / exit |
|---|---|---|
| 2xx | auth valid, repo reachable — proceed | — |
| gh's own no-token failure (no HTTP status, stderr contains `gh auth login` — gh's stable login instruction) | `PRECONDITION_NO_AUTH` | user-error / 2 |
| HTTP 401 | `PRECONDITION_NO_AUTH` (token invalid/expired) | user-error / 2 |
| HTTP 404 | `PRECONDITION_REPO_UNREACHABLE` (absent, private-without-access — GitHub deliberately conflates these; the registered `how` covers both) | user-error / 2 |
| HTTP 403 rate-limited | `RUNTIME_GH_TRANSIENT` | transient / 75 |
| HTTP 403 otherwise | `PRECONDITION_REPO_UNREACHABLE` (token lacks scope/SSO authorization) | user-error / 2 |
| HTTP 5xx, network failure, unparseable | `RUNTIME_GH_TRANSIENT` — **a server incident is never diagnosed as an auth failure** | transient / 75 |

**The status-surfacing seam (new, required).** `_classify_gh_failure` cannot serve the preflight as-is: it collapses 401, other-4xx, and unparseable-stderr into one `RUNTIME_GH_TERMINAL` bucket, and `GhCli`'s methods swallow the status into mapped exceptions. The implementation extracts the existing `(HTTP nnn)` stderr parsing into a small structured helper in `gh/client.py` — parse once, return `{status: int | None, stderr: str}` — consumed by *both* the unchanged `_classify_gh_failure` mapping (mid-run behavior byte-identical) and the preflight, which applies its own table above to the parsed status. The two discriminators for status-less failures: stderr containing `gh auth login` → `PRECONDITION_NO_AUTH`; anything else without a status (network failure, unparseable output) → `RUNTIME_GH_TRANSIENT`. That default direction is deliberate and is the inverse of the bug being fixed: an unrecognizable failure is never diagnosed as auth.

A transient probe outcome raises `RUNTIME_GH_TRANSIENT` and exits 75 immediately — single-shot, matching the shipped adapter's behavior (the design doc's §3.6 in-process retry budget is not implemented anywhere today; the preflight does not build it, and inherits it automatically if it ever lands). The scheduler's cadence is the retry loop — a 10-hour GitHub incident thus reads as "GitHub degraded, retrying on cadence," which is the truthful diagnosis the 2026-07-16 outage lacked.

### 2.3 Repo identity

`GitClient` gains `remote_url(remote: str = "origin") -> str | None` — None when CWD is not a git repo or the remote is absent. Implementation note: `GitCli._run` raises on both cases ("not a git repository" is a terminal marker; "No such remote" classifies transient), so `remote_url` must catch its adapter's failure and map it to None rather than let either classification escape — the preflight's response to every None is the same `PRECONDITION_WRONG_REPO`. The preflight parses owner/repo out of both SSH (`git@github.com:owner/repo.git`) and HTTPS (`https://github.com/owner/repo[.git]`) forms and compares case-insensitively against the ref:

- Mismatch, no remote, or not a git repo → **`PRECONDITION_WRONG_REPO`** (new registry code, user-error / 2; what: "CWD's origin does not point at the PR's repository", why: "run mutates the worktree and pushes — a same-named branch in the wrong clone would pass the branch guard", how: "cd into a worktree of {owner}/{repo} or pass the right PR ref"). Adding a code is non-breaking per §3.6's registry discipline.
- The identity check runs **before** the network probe (local, free, fails fastest); probe order is identity → repo route.
- `push`'s standalone branch guard additionally adopts the same identity comparison (one shared helper), closing the wrong-repo hole on the recovery path too.

The same `remote_url` seam is what the deferred bare-`<n>` PR-ref resolution needs (`PRRef.parse(default_repo=…)`); that feature stays out of scope but its enabling method ships here (Continuations).

## 3. Ruling — where the abn9.8.44 fix lands

**Primary: prgroom's preflight (§2.2) — the future owns the fix.** The poll scripts' `lib.sh` is retired wholesale at the Phase-1 cutover (abn9.8.20 → abn9.8.14); patching it now is spec'ing a corpse. **`lib.sh` gets no fix**; until cutover, the misdiagnosis there is an accepted, documented interim limitation (fail-closed direction correct, message wrong — operators have the incident-recognition rule).

**Except: merge-guard's copy outlives the cutover and is fixed under this spec.** `check-merge-eligibility.sh`'s duplicated preflight is not retired by anything on the roadmap. Its fix is narrow, per the bead's direction — *diagnosis and message change; fail-closed behavior preserved*:

- Replace `gh auth status` with a status-classified probe of `repos/${OWNER}/${REPO}` (the same endpoint discipline as §2.2, in shell: capture stderr, parse the `HTTP nnn` token).
- 401/403 → `"gh auth/access failed for ${OWNER}/${REPO} — check token"`; 5xx/network/unparseable → `"GitHub API degraded (HTTP nnn) — not an auth failure; retry when the incident clears"`.
- **Both paths still exit 3.** The gate stays fail-closed during incidents; only the lie in the message dies. (Distinct exit codes for transient-vs-auth are deliberately rejected: merge-guard's callers treat any non-zero as "not eligible now," and a new exit code would ripple through the merge-guard skill contract for no behavioral gain.)
- The sync-note comment in `check-merge-eligibility.sh` is updated to state that the copies have deliberately diverged: `lib.sh` is frozen awaiting retirement.

abn9.8.44 is thereby **absorbed**: its prgroom-side remedy is §2.2, its surviving-consumer remedy is this section, its `judge_merge.py` claim is corrected in §1. The bead closes as absorbed when this spec's continuations are minted (see Continuations).

## 4. Test plan

Preflight (pytest, `packages/prgroom`, fake gh runner + fake git):

1. 2xx → no error, lifecycle entered; probe called exactly once (startup-once pinned).
2. Each classification row of §2.2 → the mapped code, tier, and exit; 5xx and network failures produce `RUNTIME_GH_TRANSIENT` and **never** `PRECONDITION_NO_AUTH` (the regression pin for the 2026-07-16 incident).
3. Transient probe failure (5xx, network, status-less non-auth stderr) exits 75 single-shot — no in-process retry, no state mutation.
4. Preflight failure on `run` leaves no lock held and no state write (probe-before-lock pinned).
5. Identity: SSH form, HTTPS form, `.git`-suffixed, case-mismatch → parsed and compared correctly; wrong owner/repo, missing remote, non-repo CWD → `PRECONDITION_WRONG_REPO`; `wait` never runs the identity check.
6. `push`'s guard rejects a same-named branch in a wrong-origin worktree.

merge-guard (`check-merge-eligibility_test.sh`, existing stub harness): stubbed probe returning 401 → auth message, exit 3; returning 503 → degraded message naming the status, exit 3; 2xx → gate proceeds. Existing suite stays green.

## Assumption ledger

- `gh api repos/{owner}/{repo}` requires no scope beyond what every subsequent call needs, and succeeds for public repos with any valid token — the probe can only under-claim (403/404 on a repo the run could actually read is not a reachable failure mode for tokens that can groom its PRs).
- Verified at HEAD: no preflight exists in `packages/prgroom/src/prgroom/`; `PRECONDITION_NO_AUTH`/`PRECONDITION_REPO_UNREACHABLE` have no raise sites; `GitClient` has no remote-inspection method; mid-run 401→`RUNTIME_GH_TERMINAL` and vanished-404→terminal are current behavior; exactly two copies of the `gh auth status` probe pattern exist (`lib.sh`, `check-merge-eligibility.sh`) and `judge_merge.py` is not one of them.
- Exit codes and tiers cite the §3.6 table at HEAD (`design.md`): user-error 2, transient 75, `RUNTIME_TERMINAL_USER` 77.
- The Phase-1 cutover retires `lib.sh` and its poll scripts (abn9.8.14 scope); if that retirement is descoped, the lib.sh no-fix ruling must be revisited.
- merge-guard's callers key on exit-code-nonzero, not exit-code identity — verified against the merge-guard skill's invocation contract before rejecting a distinct transient exit code.

## Continuations

- task: implement the prgroom preflight gate — AC: `lifecycle/preflight.py` per §2 (probe table, status-surfacing seam, identity check, `PRECONDITION_WRONG_REPO` registry entry, `GitClient.remote_url`, probe-before-lock, `wait` without identity, `push` guard extension); the stale `NO_AUTH`/`REPO_UNREACHABLE` registry what/why/how texts rewritten to describe the repo-route probe (they currently describe a `gh auth status` probe that never existed in prgroom and a 404-only reachability story); §4 preflight tests green; `make ci-prgroom` green; design.md §1/§3.6 amended in the implementation PR to document the raise sites.
- task: merge-guard probe diagnosis fix — AC: `check-merge-eligibility.sh` per §3 (status-classified repo-route probe, split messages, exit 3 preserved, sync-note updated); §4 merge-guard tests green; closes the surviving-consumer half of abn9.8.44.
- task (deferred): bare `<n>` PR-ref resolution via the current-repo seam — AC: `PRRef.parse` receives `default_repo` derived from `GitClient.remote_url` so `prgroom run 123` works from a PR's worktree; gated on the preflight task landing `remote_url`.
- disposition: agents-config-abn9.8.44 closes as **absorbed by this spec** once the two non-deferred tasks above are minted (its remedies are §2.2 and §3; no residual scope remains).
