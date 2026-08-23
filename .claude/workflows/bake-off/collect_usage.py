#!/usr/bin/env python3
"""Per-arm wall time, exact token usage and priced cost for a bake-off run.

Both harnesses write the exact token split of every request into their own
transcripts; nothing in the run reads them. This reads them after the arms
finish and prices the result from the committed table. The output is for the
run's final result only — price tracks model tier, so a seat holding it is
partly unblinded. Never hand this to a judge, checker or reconciler.

Claude arms: the arm's transcript is the `agent-*.jsonl` under the session's
`subagents/workflows/<run>/` whose first user message is the dispatch preamble
naming the arm's worktree. Its `cwd` is the session root, not the worktree, so
the preamble is the join. Streaming writes the same `message.id` more than
once, the last entry carrying the final `output_tokens`; usage is taken once
per id from the last entry, or the totals roughly double.

Codex arms: the session id the ladder recorded names the rollout under
`~/.codex/sessions`. Its `token_count` events carry a cumulative
`total_token_usage`; the last one is the run. `input_tokens` there already
includes `cached_input_tokens`, and `reasoning_output_tokens` is the reasoning
subset of `output_tokens` — OpenAI bills reasoning as output, once.

Usage: collect_usage.py --dir RUN_DIR --arm LABEL,KIND,WORKTREE[,MODEL] ...
                        [--pricing TABLE] [--claude-root DIR] [--codex-root DIR]
One --arm per contestant, comma-separated so the workflow can embed it in a shell
command without quoting; MODEL is the codex model for codex arms. Exit 0 with a
JSON report on stdout; an arm whose transcript cannot be found is reported with
`error` set rather than priced from nothing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRICING = HERE / "pricing.json"
CLAUDE_ROOT = Path.home() / ".claude" / "projects"
CODEX_ROOT = Path.home() / ".codex" / "sessions"
PER_M = 1_000_000


def parse_ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


# ---------------------------------------------------------------- claude


def find_claude_transcript(worktree: str, root: Path) -> Path | None:
    needle = f"your working root is {worktree}."
    hits = []
    for f in root.glob("*/*/subagents/workflows/*/agent-*.jsonl"):
        try:
            with f.open() as fh:
                first = fh.readline()
        except OSError:
            continue
        if needle in first:
            hits.append(f)
    if not hits:
        return None
    return max(hits, key=lambda p: p.stat().st_mtime)  # a re-run supersedes


def read_claude(path: Path) -> dict:
    by_id: dict[str, dict] = {}
    models: set[str] = set()
    speeds: set[str] = set()
    geos: set[str] = set()
    ts: list[str] = []
    with path.open() as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("timestamp"):
                ts.append(d["timestamp"])
            m = d.get("message")
            if not isinstance(m, dict) or not m.get("usage"):
                continue
            u = m["usage"]
            by_id[m.get("id") or d.get("uuid")] = u  # last entry wins
            models.add(m.get("model") or "")
            speeds.add(str(u.get("speed")))
            geos.add(str(u.get("inference_geo")))
    cc5 = cc1h = 0
    t = {"input": 0, "cache_read": 0, "output": 0}
    for u in by_id.values():
        t["input"] += u.get("input_tokens", 0)
        t["cache_read"] += u.get("cache_read_input_tokens", 0)
        t["output"] += u.get("output_tokens", 0)
        cc = u.get("cache_creation") or {}
        if cc:
            cc5 += cc.get("ephemeral_5m_input_tokens", 0)
            cc1h += cc.get("ephemeral_1h_input_tokens", 0)
        else:  # older entries carry only the undifferentiated total; bill as 5m
            cc5 += u.get("cache_creation_input_tokens", 0)
    t["cache_write_5m"] = cc5
    t["cache_write_1h"] = cc1h
    wall = int((parse_ts(ts[-1]) - parse_ts(ts[0])).total_seconds()) if len(ts) > 1 else 0
    return {
        "transcript": str(path),
        "models": sorted(m for m in models if m),
        "requests": len(by_id),
        "wall_seconds": wall,
        "tokens": t,
        "speed": sorted(speeds),
        "inference_geo": sorted(geos),
    }


def price_claude(info: dict, table: dict) -> dict:
    models = info["models"]
    if len(models) != 1:
        return {"error": f"expected one model in the arm transcript, saw {models}"}
    m = table["models"].get(models[0])
    if not m:
        return {"error": f"no price for {models[0]} in the table"}
    t = info["tokens"]
    mult = table.get("multipliers", {})
    notes = []
    rates = dict(m)
    if "fast" in info["speed"]:
        fast = mult.get("anthropic_fast_mode", {}).get(models[0])
        if not fast:
            return {"error": f"{models[0]} ran in fast mode and the table has no fast rate for it"}
        rates.update(fast)
        notes.append("fast-mode rates applied")
    geo = 1.0
    if "us" in info["inference_geo"]:
        geo = mult.get("anthropic_inference_geo_us", 1.0)
        notes.append(f"inference_geo=us multiplier {geo} applied to every category")
    parts = {
        "input": t["input"] * rates["input"],
        "cache_write_5m": t["cache_write_5m"] * rates["cache_write_5m"],
        "cache_write_1h": t["cache_write_1h"] * rates["cache_write_1h"],
        "cache_read": t["cache_read"] * rates["cache_read"],
        "output": t["output"] * rates["output"],
    }
    parts = {k: round(v * geo / PER_M, 4) for k, v in parts.items()}
    return {"usd": round(sum(parts.values()), 4), "parts": parts, "notes": notes}


# ----------------------------------------------------------------- codex


def codex_sessions(dir_: Path, label: str) -> list[str]:
    ladder = dir_ / f"{label}.ladder.jsonl"
    ids: list[str] = []
    if not ladder.exists():
        return ids
    for line in ladder.read_text().splitlines():
        try:
            sid = json.loads(line).get("session_id") or ""
        except ValueError:
            continue
        if sid and sid not in ids:
            ids.append(sid)
    return ids


def read_codex(session_id: str, root: Path) -> dict | None:
    paths = glob.glob(str(root / "*" / "*" / "*" / f"rollout-*{session_id}*.jsonl"))
    if not paths:
        return None
    path = Path(paths[0])
    last = None
    models: set[str] = set()
    ts: list[str] = []
    cwd = None
    with path.open() as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("timestamp"):
                ts.append(d["timestamp"])
            p = d.get("payload") or {}
            if d.get("type") == "session_meta":
                cwd = p.get("cwd")
            if p.get("model"):
                models.add(p["model"])
            if p.get("type") == "token_count" and (p.get("info") or {}).get("total_token_usage"):
                last = p["info"]["total_token_usage"]
    if last is None:
        return None
    return {
        "transcript": str(path),
        "cwd": cwd,
        "models": sorted(models),
        "wall_seconds": int((parse_ts(ts[-1]) - parse_ts(ts[0])).total_seconds()) if len(ts) > 1 else 0,
        "tokens": {
            "input": last.get("input_tokens", 0) - last.get("cached_input_tokens", 0),
            "cache_read": last.get("cached_input_tokens", 0),
            "cache_write": last.get("cache_write_input_tokens", 0),
            "output": last.get("output_tokens", 0),
            "reasoning_output": last.get("reasoning_output_tokens", 0),
        },
    }


def merge_codex(sessions: list[dict]) -> dict:
    out = dict(sessions[0])
    out["transcript"] = [s["transcript"] for s in sessions]
    out["models"] = sorted({m for s in sessions for m in s["models"]})
    out["wall_seconds"] = sum(s["wall_seconds"] for s in sessions)
    out["tokens"] = {k: sum(s["tokens"][k] for s in sessions) for k in sessions[0]["tokens"]}
    return out


def price_codex(info: dict, table: dict, arm_model: str | None) -> dict:
    model = arm_model or (info["models"][0] if len(info["models"]) == 1 else None)
    if not model:
        return {"error": f"cannot tell which model to price: {info['models']}"}
    m = table["models"].get(model)
    if not m:
        return {"error": f"no price for {model} in the table"}
    t = info["tokens"]
    parts = {
        "input": t["input"] * m["input"],
        "cache_read": t["cache_read"] * m["cache_read"],
        "output": t["output"] * m["output"],
    }
    notes = ["reasoning_output_tokens are a subset of output_tokens; priced once"]
    if t["cache_write"]:
        if m.get("cache_write") is None:
            notes.append(f"{t['cache_write']} cache-write tokens UNPRICED: the table has no vendor rate (null = undetermined, not free)")
        else:
            parts["cache_write"] = t["cache_write"] * m["cache_write"]
    parts = {k: round(v / PER_M, 4) for k, v in parts.items()}
    return {"usd": round(sum(parts.values()), 4), "parts": parts, "notes": notes}


# ------------------------------------------------------------------ main


def collect(dir_: Path, arms: list[dict], table: dict, claude_root: Path, codex_root: Path) -> list[dict]:
    rows = []
    for a in arms:
        row = {"label": a["label"], "kind": a["kind"]}
        if a["kind"] == "claude":
            path = find_claude_transcript(a["worktree"], claude_root)
            if not path:
                row["error"] = f"no agent transcript under {claude_root} carries the dispatch preamble for {a['worktree']}"
            else:
                info = read_claude(path)
                row.update(info)
                row["cost"] = price_claude(info, table)
        elif a["kind"] == "codex":
            sids = codex_sessions(dir_, a["label"])
            found = [s for s in (read_codex(s, codex_root) for s in sids) if s]
            if not sids:
                row["error"] = f"{dir_ / (a['label'] + '.ladder.jsonl')} records no session id"
            elif not found:
                row["error"] = f"no rollout under {codex_root} for session(s) {sids}"
            else:
                info = merge_codex(found)
                row.update(info)
                row["sessions"] = sids
                row["cost"] = price_codex(info, table, a.get("codexModel"))
        else:
            row["skipped"] = f"kind {a['kind']} has no transcript"
        rows.append(row)
    return rows


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="per-arm wall time, tokens and priced cost for a bake-off run")
    ap.add_argument("--dir", required=True, type=Path, help="the run directory (ladder files live here)")
    ap.add_argument("--arm", action="append", required=True, metavar="LABEL,KIND,WORKTREE[,MODEL]")
    ap.add_argument("--pricing", type=Path, default=PRICING)
    ap.add_argument("--claude-root", type=Path, default=CLAUDE_ROOT)
    ap.add_argument("--codex-root", type=Path, default=CODEX_ROOT)
    args = ap.parse_args(argv)
    arms = []
    for spec in args.arm:
        parts = spec.split(",")
        if len(parts) not in (3, 4):
            ap.error(f"--arm wants LABEL,KIND,WORKTREE[,MODEL]: {spec!r}")
        arms.append({"label": parts[0], "kind": parts[1], "worktree": parts[2], "codexModel": parts[3] if len(parts) == 4 else None})
    table = json.loads(args.pricing.read_text())
    rows = collect(args.dir, arms, table, args.claude_root, args.codex_root)
    print(json.dumps({"pricing_verified": table.get("verified"), "arms": rows}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
