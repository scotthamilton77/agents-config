#!/usr/bin/env python3
"""judge_merge.py — the agent-ruling merge-judge harness.

Runs cheap deterministic pre-judge gates, then (only if all pass) the injected
judge backend, then collapses the result into a head-and-base-bound verdict
envelope on stdout. Every path that is not an affirmative, current-head,
current-base `go` with valid cross-model provenance FAILS CLOSED (abstain).

Outside-world dependencies (git, the codex subprocess, the clock-free state
dir) are injected so the logic is unit-testable without a network or the codex
CLI. Stdlib only — deploys with the merge-guard skill.

Contract: docs/specs/2026-07-03-agent-ruling-merge-judge.md (verdict envelope).
"""
from __future__ import annotations

import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_family import family_of  # noqa: E402

PROMPT_VERSION = "1"  # bump to invalidate every cached no-go on a prompt change

VERDICT_GO = "go"
VERDICT_NO_GO = "no-go"
VERDICT_ABSTAIN = "abstain"


def mint_nonce() -> str:
    """A per-run unguessable delimiter token, minted AFTER the diff is read."""
    return secrets.token_hex(16)


def build_envelope(*, head: str, base: str, diff_sha: str, verdict: str,
                   abstain_reason: str | None, judge_model: str,
                   judge_effort: str, author_families: list[str],
                   summary: str, merge_blocking_findings: list) -> dict:
    """Assemble the one JSON shape the gate reads. judge_backend is fixed codex."""
    return {
        "head_ref_oid": head,
        "base_ref_oid": base,
        "diff_sha": diff_sha,
        "verdict": verdict,
        "abstain_reason": abstain_reason,
        "judge_backend": "codex",
        "judge_model": judge_model,
        "judge_model_family": family_of(judge_model),
        "judge_effort": judge_effort,
        "author_families": author_families,
        "summary": summary,
        "merge_blocking_findings": merge_blocking_findings,
    }


import json  # noqa: E402


def state_home() -> str:
    return os.environ.get("MERGE_JUDGE_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".claude", "state")


def _attempts_path(state: str, owner: str, repo: str, pr: str, base: str) -> str:
    return os.path.join(state, "merge-judge", f"{owner}-{repo}-{pr}-{base}.attempts.json")


def _read_attempts(path: str) -> int:
    try:
        with open(path) as fh:
            return int(json.load(fh).get("count", 0))
    except (OSError, ValueError):
        return 0


def budget_exhausted(state: str, owner: str, repo: str, pr: str, base: str,
                     *, max_attempts: int) -> bool:
    """True once >= max_attempts no-go's have been recorded for this PR+base."""
    return _read_attempts(_attempts_path(state, owner, repo, pr, base)) >= max_attempts


def bump_attempts(state: str, owner: str, repo: str, pr: str, base: str) -> int:
    """Increment (and persist) the no-go counter for this PR+base; return new value."""
    path = _attempts_path(state, owner, repo, pr, base)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    count = _read_attempts(path) + 1
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump({"count": count}, fh)
    os.replace(tmp, path)
    return count


import subprocess  # noqa: E402
from protected_paths import scan_protected  # noqa: E402


def _real_git(args: list[str]) -> str:
    """Run a git command, return stdout. Raises CalledProcessError on failure."""
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          check=True, timeout=60).stdout


def changed_paths(base: str, head: str, git_runner=_real_git) -> list[str]:
    out = git_runner(["diff", "--name-only", f"{base}...{head}"])
    return [ln for ln in out.splitlines() if ln.strip()]


def protected_diff_path(base: str, head: str, git_runner=_real_git) -> str | None:
    """First protected path the diff touches, else None (structural abstain)."""
    return scan_protected(changed_paths(base, head, git_runner))


def _read_provenance(state: str, owner: str, repo: str, pr: str, head: str) -> dict | None:
    path = os.path.join(state, "pr-provenance", f"{owner}-{repo}-{pr}-{head}.provenance.json")
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _base_head_commits(base: str, head: str, git_runner) -> list[str]:
    out = git_runner(["rev-list", f"{base}..{head}"])
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def provenance_gate(state: str, owner: str, repo: str, pr: str, base: str, head: str,
                    *, judge_family: str | None, git_runner=_real_git):
    """(ok, abstain_reason|None, author_families).

    Authorizes only when: a record exists for `head`; every commit in base..head
    is first-hand attested in it; and judge_family is in NO commit's families.
    """
    record = _read_provenance(state, owner, repo, pr, head)
    if record is None or record.get("head_sha") != head:
        return (False, "no-provenance", [])
    by_sha = {c.get("sha"): c for c in record.get("commits", [])}
    fams: set[str] = set()
    for sha in _base_head_commits(base, head, git_runner):
        entry = by_sha.get(sha)
        if entry is None or entry.get("attestation") != "first-hand":
            return (False, "unattested-commit", [])
        fams.update(entry.get("author_families", []))
    ai_fams = sorted(fams - {"human"})
    if judge_family is not None and judge_family in fams:
        return (False, "same-family", ai_fams)
    return (True, None, ai_fams)


import hashlib  # noqa: E402
from dataclasses import dataclass  # noqa: E402

MAX_DIFF_BYTES = 400_000  # oversized diffs abstain (MVP: no chunking)


@dataclass(frozen=True)
class Diff:
    text: str
    diff_sha: str
    is_empty: bool
    is_oversized: bool


def assemble_diff(base: str, head: str, git_runner=_real_git, max_bytes: int = MAX_DIFF_BYTES) -> Diff:
    text = git_runner(["diff", f"{base}...{head}"])
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return Diff(text=text, diff_sha=sha,
                is_empty=(text.strip() == ""),
                is_oversized=(len(text.encode("utf-8")) > max_bytes))


def _real_gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True,
                          check=True, timeout=60).stdout


def refs_current(owner: str, repo: str, pr: str, head: str, base: str, gh_runner=_real_gh) -> bool:
    """Live-fetch the PR's head+base OIDs; True iff BOTH still match."""
    out = gh_runner(["pr", "view", pr, "--repo", f"{owner}/{repo}",
                     "--json", "headRefOid,baseRefOid"])
    try:
        live = json.loads(out)
    except ValueError:
        return False
    return live.get("headRefOid") == head and live.get("baseRefOid") == base


import re  # noqa: E402


def nonce_collides(nonce: str, diff_text: str) -> bool:
    """True if the run nonce already appears in the diff (must then abstain)."""
    return nonce in diff_text


def extract_verdict_block(raw_output: str, nonce: str) -> dict | None:
    """Honor ONLY the current run's nonce sentinels.

    Requires exactly one <<<JUDGE:nonce>>>...<<<END:nonce>>> block as the final
    non-whitespace content, a valid JSON object of the judge shape. Any
    deviation (zero, multiple, trailing content, bad schema) -> None (abstain).
    A static/guessed sentinel echoed from the diff carries the wrong nonce and
    is ignored.
    """
    start = re.escape(f"<<<JUDGE:{nonce}>>>")
    end = re.escape(f"<<<END:{nonce}>>>")
    matches = list(re.finditer(f"{start}(.*?){end}", raw_output, re.DOTALL))
    if len(matches) != 1:
        return None
    m = matches[0]
    if raw_output[m.end():].strip() != "":  # must be the final content
        return None
    try:
        obj = json.loads(m.group(1))
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    if not isinstance(obj.get("merge_blocking_findings"), list):
        return None
    if not isinstance(obj.get("summary"), str):
        return None
    return obj


def collapse(merge_blocking_findings: list) -> str:
    """go iff zero blocking findings; else no-go. Never trusts a model verdict string."""
    return VERDICT_GO if len(merge_blocking_findings) == 0 else VERDICT_NO_GO


def _codex_home() -> str:
    return os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.join(
        os.path.expanduser("~"),
        ".claude/plugins/marketplaces/openai-codex/plugins/codex")


def run_backend(prompt: str, model: str, effort: str, timeout_seconds: int,
                runner=None) -> str:
    """Blocking read-only codex `task` subprocess; returns the model's final
    message text (the `rawOutput` field of the `task --json` payload).

    No --write => read-only sandbox. A non-zero exit / timeout / missing CLI
    raises; the caller maps that to abstain.
    """
    if runner is not None:
        return runner(prompt, model, effort, timeout_seconds)
    companion = os.path.join(_codex_home(), "scripts", "codex-companion.mjs")
    proc = subprocess.run(
        ["node", companion, "task", "--json", "-m", model, "--effort", effort],
        input=prompt, capture_output=True, text=True,
        check=True, timeout=timeout_seconds)
    return _final_message_text(proc.stdout)


def _final_message_text(raw_stdout: str) -> str:
    """Unwrap the model's final message from `task --json` output.

    Verified against the installed runtime (`codex-companion.mjs`
    `executeTaskRun`, codex-cli 0.136.0): `task --json` emits
    `JSON.stringify({status, threadId, rawOutput, touchedFiles, reasoningSummary})`.
    The model's final message (carrying the nonce-delimited verdict block) is the
    `rawOutput` string; the nonce block is NOT scannable in the raw envelope
    because the inner object's braces/quotes are JSON-escaped there. Parse the
    envelope, require status 0, return rawOutput for nonce extraction.
    """
    payload = json.loads(raw_stdout)          # non-JSON => raises => abstain
    if payload.get("status") != 0:
        raise RuntimeError(f"codex task status {payload.get('status')!r}")
    return payload.get("rawOutput", "")


import argparse  # noqa: E402


def _config_hash(policy: dict) -> str:
    material = "|".join(str(policy.get(k)) for k in (
        "judge_backend", "judge_model", "judge_effort",
        "judge_timeout_seconds", "judge_max_attempts")) + "|" + PROMPT_VERSION
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _cache_path(state, owner, repo, pr, head, base, diff_sha, policy):
    key = f"{owner}-{repo}-{pr}-{head}-{base}-{diff_sha}-{_config_hash(policy)}.judge.json"
    return os.path.join(state, "merge-judge", key)


def no_go_cached(state, owner, repo, pr, head, base, diff_sha, policy) -> bool:
    return os.path.exists(_cache_path(state, owner, repo, pr, head, base, diff_sha, policy))


def _cache_no_go(state, owner, repo, pr, head, base, diff_sha, policy, envelope):
    path = _cache_path(state, owner, repo, pr, head, base, diff_sha, policy)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(envelope, fh)
    os.replace(tmp, path)


def _load_prompt() -> str:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "merge_judge_prompt.md")) as fh:
        return fh.read()


def _abstain(head, base, diff_sha, reason, policy, families):
    return build_envelope(head=head, base=base, diff_sha=diff_sha, verdict=VERDICT_ABSTAIN,
                          abstain_reason=reason, judge_model=policy["judge_model"],
                          judge_effort=policy["judge_effort"], author_families=families,
                          summary="", merge_blocking_findings=[])


def run_judge(*, owner, repo, pr, head, base, base_ref, policy, state,
              nonce_fn=mint_nonce, git_runner=_real_git, gh_runner=_real_gh,
              backend_runner=None) -> dict:
    """Full harness: pre-judge gates -> backend -> collapse -> cache. Returns the envelope."""
    judge_family = family_of(policy["judge_model"])
    max_attempts = int(policy["judge_max_attempts"])

    # Gate 0: attempt budget (checked FIRST — never pay for a run past budget)
    if budget_exhausted(state, owner, repo, pr, base, max_attempts=max_attempts):
        return _abstain(head, base, "", "attempt-budget-exhausted", policy, [])

    # Gate 1: protected-path scan
    if protected_diff_path(base, head, git_runner) is not None:
        return _abstain(head, base, "", "protected-path", policy, [])

    # Gate 2: cross-model provenance
    ok, reason, families = provenance_gate(state, owner, repo, pr, base, head,
                                           judge_family=judge_family, git_runner=git_runner)
    if not ok:
        return _abstain(head, base, "", reason, policy, families)

    # Gate 3: head+base currency
    if not refs_current(owner, repo, pr, head, base, gh_runner):
        return _abstain(head, base, "", "base-or-head-moved", policy, families)

    # Gate 4: diff assembly + size
    diff = assemble_diff(base, head, git_runner)
    if diff.is_empty:
        return _abstain(head, base, diff.diff_sha, "empty-diff", policy, families)
    if diff.is_oversized:
        return _abstain(head, base, diff.diff_sha, "oversized-diff", policy, families)

    # No-go cache: an identical (head,base,diff) no-go is terminal
    if no_go_cached(state, owner, repo, pr, head, base, diff.diff_sha, policy):
        bump_attempts(state, owner, repo, pr, base)
        return _abstain(head, base, diff.diff_sha, "prior-no-go", policy, families)

    # Nonce mint (AFTER reading the diff) + collision guard
    nonce = nonce_fn()
    if nonce_collides(nonce, diff.text):
        return _abstain(head, base, diff.diff_sha, "nonce-collision", policy, families)

    prompt = _load_prompt().replace("{nonce}", nonce).replace(
        "{base}", base).replace("{head}", head).replace("{diff}", diff.text)

    try:
        raw = run_backend(prompt, policy["judge_model"], policy["judge_effort"],
                          int(policy["judge_timeout_seconds"]), runner=backend_runner)
    except subprocess.TimeoutExpired:
        return _abstain(head, base, diff.diff_sha, "judge-timeout", policy, families)
    except Exception:  # noqa: BLE001 - any backend failure fails closed
        return _abstain(head, base, diff.diff_sha, "judge-error", policy, families)

    obj = extract_verdict_block(raw, nonce)
    if obj is None:
        return _abstain(head, base, diff.diff_sha, "extraction-failed", policy, families)

    findings = obj["merge_blocking_findings"]
    verdict = collapse(findings)
    envelope = build_envelope(head=head, base=base, diff_sha=diff.diff_sha, verdict=verdict,
                              abstain_reason=None, judge_model=policy["judge_model"],
                              judge_effort=policy["judge_effort"], author_families=families,
                              summary=obj.get("summary", ""), merge_blocking_findings=findings)
    if verdict == VERDICT_NO_GO:
        _cache_no_go(state, owner, repo, pr, head, base, diff.diff_sha, policy, envelope)
        bump_attempts(state, owner, repo, pr, base)
    # a `go` is NEVER cached — always freshly computed
    return envelope


_EXIT = {VERDICT_GO: 0, VERDICT_NO_GO: 1, VERDICT_ABSTAIN: 2}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    for flag in ("--owner", "--repo", "--pr", "--head-ref-oid", "--base-ref-oid",
                 "--base-ref", "--policy-json"):
        ap.add_argument(flag, required=True)
    args = ap.parse_args()
    try:
        policy = json.loads(args.policy_json)
        env = run_judge(owner=args.owner, repo=args.repo, pr=args.pr,
                        head=args.head_ref_oid, base=args.base_ref_oid,
                        base_ref=args.base_ref, policy=policy, state=state_home())
        json.dump(env, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return _EXIT[env["verdict"]]
    except Exception as exc:  # noqa: BLE001 - never crash into a merge; abstain
        sys.stderr.write(f"error: unexpected {type(exc).__name__}: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
