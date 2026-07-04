#!/usr/bin/env python3
"""record_provenance.py — emit the out-of-band authorship attestation.

Invoked by the delivery workflow (finishing-a-development-branch) right after
push, once owner/repo/PR/head-SHA are known. Writes
  <state>/pr-provenance/<owner>~<repo>~<pr>~<head_sha>.provenance.json
where <state> = $MERGE_JUDGE_STATE_HOME (tests) or ~/.claude/state (prod).

The delivery session attests FIRST-HAND the families it knows it produced this
session; commits it did not produce are marked trailer-derived (not trusted
for authorization). This file is NEVER part of the diff — its trust boundary
is the operator host that both writes and reads it.

--commit format: <sha>:<fam1[+fam2...]>:<first-hand|trailer-derived>

Exit: 0 ok; 1 invalid input (message on stderr); 2 unexpected error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_FAMILIES = {"anthropic", "openai", "google", "human"}
_ATTESTATIONS = {"first-hand", "trailer-derived"}


def _safe_component(value: str, name: str) -> str:
    """Reject path-traversal / separator chars in a filename component (fail closed)."""
    if not value or any(c in value for c in ("/", "\\", "\x00")) or ".." in value or "~" in value:
        raise ValueError(f"--{name} contains illegal path characters: {value!r}")
    return value


def _state_dir() -> str:
    base = os.environ.get("MERGE_JUDGE_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".claude", "state")
    return os.path.join(base, "pr-provenance")


def _parse_commit(spec: str) -> dict:
    parts = spec.split(":")
    if len(parts) != 3:
        raise ValueError(f"--commit must be <sha>:<families>:<attestation>, got {spec!r}")
    sha, fams, attestation = parts
    families = [f for f in fams.split("+") if f]
    if not sha or not families:
        raise ValueError(f"--commit missing sha or families: {spec!r}")
    bad = [f for f in families if f not in _FAMILIES]
    if bad:
        raise ValueError(f"--commit unknown family/families {bad} (allowed: {sorted(_FAMILIES)})")
    if attestation not in _ATTESTATIONS:
        raise ValueError(f"--commit attestation must be one of {sorted(_ATTESTATIONS)}, got {attestation!r}")
    return {"sha": sha, "author_families": families, "attestation": attestation}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--owner", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pr", required=True)
    ap.add_argument("--head-sha", required=True)
    ap.add_argument("--commit", action="append", required=True,
                    help="<sha>:<fam1[+fam2]>:<first-hand|trailer-derived> (repeatable)")
    ap.add_argument("--recorded-by", required=True)
    args = ap.parse_args()

    try:
        commits = [_parse_commit(c) for c in args.commit]
        record = {"head_sha": args.head_sha, "commits": commits, "recorded_by": args.recorded_by}
        out_dir = _state_dir()
        os.makedirs(out_dir, exist_ok=True)
        for _name, _val in (("owner", args.owner), ("repo", args.repo),
                            ("pr", args.pr), ("head-sha", args.head_sha)):
            _safe_component(_val, _name)
        # provenance filename format is shared with judge_merge.py's _read_provenance; keep in sync
        path = os.path.join(out_dir, f"{args.owner}~{args.repo}~{args.pr}~{args.head_sha}.provenance.json")
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(record, fh, indent=2)
        os.replace(tmp, path)  # atomic
        return 0
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    except Exception as exc:  # noqa: BLE001 - deliberate boundary catch-all
        sys.stderr.write(f"error: unexpected {type(exc).__name__}: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
