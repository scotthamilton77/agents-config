"""Append every hook payload this process receives to one JSONL file, verbatim.

Claude Code runs this as a hook command, once per event, in its own process. It is
deliberately free of imports from the rest of the package so it can be invoked by path
from a session that knows nothing about this project.
"""

from __future__ import annotations

import json
import os
import sys
import time

SECRET_MARKERS = ("TOKEN", "KEY", "SECRET", "PASSWORD")


def team_snapshot(session_id: str) -> dict[str, object] | None:
    """Return the team config Claude Code keeps for this session, or None when there is none."""
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    path = os.path.join(config_dir, "teams", f"session-{session_id[:8]}", "config.json")
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {"_unparsed": raw}
    # The hook process's own CLAUDE* variables say which session and team it belongs to,
    # which is how a payload that omits the agent identity can still be attributed.
    env = {
        key: ("<redacted>" if any(marker in key for marker in SECRET_MARKERS) else value)
        for key, value in os.environ.items()
        if key.startswith("CLAUDE")
    }
    record: dict[str, object] = {
        "t": time.time(),
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "env": env,
        "payload": payload,
        "team": team_snapshot(payload.get("session_id", "")),
    }
    path = os.environ.get("AGENTPROBE_EVENTS")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


if __name__ == "__main__":
    main()
