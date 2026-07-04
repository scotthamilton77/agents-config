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
