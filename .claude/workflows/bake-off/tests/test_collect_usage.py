"""collect_usage reads both harnesses' transcripts, dedupes streamed usage, and
prices from the four-way table without ever blending rates."""

import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("collect_usage", HERE / "collect_usage.py")
cu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cu)

TABLE = {
    "verified": "2026-08-22",
    "models": {
        "claude-sonnet-5": {"input": 2.0, "cache_write_5m": 2.5, "cache_write_1h": 4.0, "cache_read": 0.2, "output": 10.0},
        "gpt-5.6-luna": {"input": 0.2, "cache_write": None, "cache_read": 0.02, "output": 1.2},
    },
    "multipliers": {"anthropic_inference_geo_us": 1.1, "anthropic_fast_mode": {"claude-sonnet-5": {"input": 4.0, "output": 20.0}}},
}
WT = "/w/exp-X"


def claude_line(mid, usage, ts, model="claude-sonnet-5"):
    return json.dumps({"type": "assistant", "timestamp": ts, "message": {"id": mid, "model": model, "usage": usage}})


def write_claude(root: Path, lines, worktree=WT):
    d = root / "slug" / "sess" / "subagents" / "workflows" / "wf_1"
    d.mkdir(parents=True)
    first = json.dumps({"type": "user", "timestamp": "2026-01-01T00:00:00Z",
                        "message": {"content": f"Dispatch preamble (run tag 1): your working root is {worktree}. Your report path is /r."}})
    (d / "agent-a1.jsonl").write_text("\n".join([first, *lines]) + "\n")
    return d / "agent-a1.jsonl"


def test_claude_usage_is_taken_once_per_message_id_last_entry_wins(tmp_path):
    u0 = {"input_tokens": 2, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 0, "output_tokens": 5,
          "cache_creation": {"ephemeral_5m_input_tokens": 100, "ephemeral_1h_input_tokens": 0}}
    u1 = dict(u0, output_tokens=80)
    write_claude(tmp_path, [claude_line("m1", u0, "2026-01-01T00:00:10Z"), claude_line("m1", u1, "2026-01-01T00:01:00Z")])
    rows = cu.collect(tmp_path, [{"label": "X", "kind": "claude", "worktree": WT}], TABLE, tmp_path, tmp_path)
    t = rows[0]["tokens"]
    assert t == {"input": 2, "cache_read": 0, "output": 80, "cache_write_5m": 100, "cache_write_1h": 0}
    assert rows[0]["requests"] == 1
    assert rows[0]["wall_seconds"] == 60


def test_claude_cost_uses_four_rates_not_a_blend(tmp_path):
    u = {"input_tokens": 1_000_000, "cache_creation_input_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000, "output_tokens": 1_000_000,
         "cache_creation": {"ephemeral_5m_input_tokens": 500_000, "ephemeral_1h_input_tokens": 500_000}}
    write_claude(tmp_path, [claude_line("m1", u, "2026-01-01T00:00:10Z")])
    cost = cu.collect(tmp_path, [{"label": "X", "kind": "claude", "worktree": WT}], TABLE, tmp_path, tmp_path)[0]["cost"]
    assert cost["parts"] == {"input": 2.0, "cache_write_5m": 1.25, "cache_write_1h": 2.0, "cache_read": 0.2, "output": 10.0}
    assert cost["usd"] == pytest.approx(15.45)


def test_fast_mode_and_us_geo_are_read_from_the_usage_block(tmp_path):
    u = {"input_tokens": 1_000_000, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 1_000_000,
         "speed": "fast", "inference_geo": "us"}
    write_claude(tmp_path, [claude_line("m1", u, "2026-01-01T00:00:10Z")])
    cost = cu.collect(tmp_path, [{"label": "X", "kind": "claude", "worktree": WT}], TABLE, tmp_path, tmp_path)[0]["cost"]
    assert cost["parts"]["input"] == pytest.approx(4.4)   # fast 4.0 × geo 1.1
    assert cost["parts"]["output"] == pytest.approx(22.0)
    assert len(cost["notes"]) == 2


def test_claude_join_is_the_dispatch_preamble_not_a_prefix_match(tmp_path):
    write_claude(tmp_path, [claude_line("m1", {"input_tokens": 1, "output_tokens": 1}, "2026-01-01T00:00:10Z")], worktree=WT + "1")
    rows = cu.collect(tmp_path, [{"label": "X", "kind": "claude", "worktree": WT}], TABLE, tmp_path, tmp_path)
    assert "error" in rows[0] and "cost" not in rows[0]


def write_codex(root: Path, sid, totals, cwd=WT, model="gpt-5.6-luna"):
    d = root / "2026" / "01" / "01"
    d.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"timestamp": "2026-01-01T00:00:00Z", "type": "session_meta", "payload": {"id": sid, "cwd": cwd}}),
        json.dumps({"timestamp": "2026-01-01T00:00:01Z", "type": "turn_context", "payload": {"model": model}}),
        json.dumps({"timestamp": "2026-01-01T00:00:02Z", "type": "event_msg",
                    "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 10, "cached_input_tokens": 5, "output_tokens": 1},
                                                                "last_token_usage": {"input_tokens": 10}}}}),
        json.dumps({"timestamp": "2026-01-01T00:02:00Z", "type": "event_msg",
                    "payload": {"type": "token_count", "info": {"total_token_usage": totals, "last_token_usage": {"input_tokens": 1}}}}),
    ]
    (d / f"rollout-2026-01-01T00-00-00-{sid}.jsonl").write_text("\n".join(lines) + "\n")


def test_codex_takes_the_last_cumulative_total_and_separates_cached_input(tmp_path):
    run = tmp_path / "run"; run.mkdir()
    (run / "X.ladder.jsonl").write_text(json.dumps({"session_id": "sid-1"}) + "\n")
    write_codex(tmp_path, "sid-1", {"input_tokens": 1_000_000, "cached_input_tokens": 900_000, "cache_write_input_tokens": 0,
                                    "output_tokens": 100_000, "reasoning_output_tokens": 40_000, "total_tokens": 1_100_000})
    row = cu.collect(run, [{"label": "X", "kind": "codex", "worktree": WT, "codexModel": "gpt-5.6-luna"}], TABLE, tmp_path, tmp_path)[0]
    assert row["tokens"]["input"] == 100_000 and row["tokens"]["cache_read"] == 900_000
    assert row["wall_seconds"] == 120
    assert row["cost"]["parts"] == {"input": 0.02, "cache_read": 0.018, "output": 0.12}
    assert row["cost"]["usd"] == pytest.approx(0.158)


def test_codex_cache_writes_are_reported_unpriced_when_the_table_has_no_rate(tmp_path):
    run = tmp_path / "run"; run.mkdir()
    (run / "X.ladder.jsonl").write_text(json.dumps({"session_id": "sid-2"}) + "\n")
    write_codex(tmp_path, "sid-2", {"input_tokens": 10, "cached_input_tokens": 0, "cache_write_input_tokens": 7, "output_tokens": 1})
    cost = cu.collect(run, [{"label": "X", "kind": "codex", "worktree": WT, "codexModel": "gpt-5.6-luna"}], TABLE, tmp_path, tmp_path)[0]["cost"]
    assert "cache_write" not in cost["parts"]
    assert any("UNPRICED" in n and "7" in n for n in cost["notes"])


def test_codex_resumed_sessions_are_summed(tmp_path):
    run = tmp_path / "run"; run.mkdir()
    (run / "X.ladder.jsonl").write_text(json.dumps({"session_id": "s-a"}) + "\n" + json.dumps({"session_id": "s-b"}) + "\n")
    for s in ("s-a", "s-b"):
        write_codex(tmp_path, s, {"input_tokens": 10, "cached_input_tokens": 0, "cache_write_input_tokens": 0, "output_tokens": 3})
    row = cu.collect(run, [{"label": "X", "kind": "codex", "worktree": WT, "codexModel": "gpt-5.6-luna"}], TABLE, tmp_path, tmp_path)[0]
    assert row["tokens"]["input"] == 20 and row["tokens"]["output"] == 6 and row["wall_seconds"] == 240


def test_missing_transcripts_are_errors_not_zero_cost(tmp_path):
    run = tmp_path / "run"; run.mkdir()
    rows = cu.collect(run, [{"label": "X", "kind": "codex", "worktree": WT}, {"label": "Y", "kind": "claude", "worktree": WT}], TABLE, tmp_path, tmp_path)
    assert all("error" in r and "cost" not in r for r in rows)


def test_shipped_table_keys_are_the_ones_the_calculator_reads():
    table = json.loads((HERE / "pricing.json").read_text())
    info = {"models": ["claude-sonnet-5"], "speed": ["standard"], "inference_geo": ["not_available"],
            "tokens": {"input": 1, "cache_write_5m": 1, "cache_write_1h": 1, "cache_read": 1, "output": 1}}
    assert "usd" in cu.price_claude(info, table)
    assert "usd" in cu.price_codex({"models": [], "tokens": {"input": 1, "cache_read": 1, "cache_write": 0, "output": 1}}, table, "gpt-5.6-sol")
    for name, m in table["models"].items():
        if m["vendor"] == "openai":
            assert "cache_write" in m, name  # null there means unpriced, not absent
