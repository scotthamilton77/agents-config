"""Per-invocation token-usage JSONL emitter (§5 token-usage logging).

The CLI logs **per-contract token usage** to ``$XDG_STATE_HOME/prgroom/usage.jsonl``
when the agent CLI emits a usage line (Claude and Codex CLIs both do). This is
**MVP baseline-capture only** — one JSON line per invocation, no aggregation, no
analysis — so future cost-optimization work has data to start from.

The XDG state directory is resolved through :func:`prgroom.prsession.file.resolve_state_dir`,
the single source of truth for ``$XDG_STATE_HOME/prgroom`` (shared with the file
Store), so usage data and state land in the same place under the same env rule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from prgroom.prsession.file import resolve_state_dir
from prgroom.prsession.pr_ref import PRRef

USAGE_FILENAME = "usage.jsonl"


@dataclass(frozen=True, slots=True)
class UsageRecord:
    """One agent invocation's usage record. The §5 JSONL line schema verbatim."""

    ts: str
    """ISO-8601 timestamp of the invocation (from the injected clock, by the caller)."""
    pr: PRRef
    contract: str
    """``cluster`` or ``fix`` — which contract dispatched."""
    provider: str
    """The agent CLI that ran (``claude`` / ``codex`` / ``opencode`` / ``ollama``)."""
    model: str
    input_tokens: int
    output_tokens: int
    duration_ms: int
    outcome: str
    """``success`` / ``timeout`` / ``error`` — the invocation's terminal disposition."""

    def to_dict(self) -> dict[str, Any]:
        """The flat JSONL line. ``pr`` renders as the ``owner/repo#n`` shorthand."""
        return {
            "ts": self.ts,
            "pr": self.pr.display(),
            "contract": self.contract,
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_ms": self.duration_ms,
            "outcome": self.outcome,
        }


def append_usage(record: UsageRecord | None) -> None:
    """Append one usage line to ``$XDG_STATE_HOME/prgroom/usage.jsonl``.

    A ``None`` record is a **no-op, not an error** (§5): the agent CLI emitted no
    parseable usage line, so there is nothing to log — the file is not even
    created. A real record is appended (never truncates prior lines); parent dirs
    are created on first write so the very first invocation succeeds.
    """
    if record is None:
        return
    path = resolve_state_dir() / USAGE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record.to_dict()) + "\n")
