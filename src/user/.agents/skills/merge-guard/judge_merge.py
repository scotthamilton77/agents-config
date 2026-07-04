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
