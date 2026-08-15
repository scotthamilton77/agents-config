#!/usr/bin/env python3
"""Session hook: terminate Codex broker processes nothing can reach any more.

The Codex plugin runs one long-lived broker per workspace, fronting a `codex
app-server` child, and records it in a `broker.json` under its state directory.
Two paths leave a broker running with that record gone or never written:
concurrent launches all spawn one and only the last writer of `broker.json`
survives, and a session that dies without its shutdown hook never reaps the one
it owns. Neither leaves anything able to reach the process, and the broker has
no idle timeout, so it holds itself and its child until the machine restarts.

A broker is only terminated here when both proofs hold:

  1. No `broker.json` under any state root names both its pid and its own
     endpoint socket. `broker.json` is the sole route to a broker — nothing
     sets the endpoint environment variable — so a broker no record names
     this way is unreachable by construction. Pid alone is not enough: pids recycle, and a
     record long dead can still name the pid a live, unrelated broker now
     holds. The endpoint is the part that can't coincide by accident, so a
     record only protects the broker whose live socket it actually names.
  2. Nothing is connected to its socket. A listening socket with no peer shows
     one holder; each connected client adds one. This matters because a broker
     that lost the race is still handed back to the caller that spawned it, in
     memory, and can be serving a live task while absent from every record.

Anything that cannot be proved is left alone and the process survives. The hook
never fails a session: it exits 0 whatever happens, and says nothing unless it
terminated something.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

BROKER_SCRIPT = "app-server-broker.mjs"
BROKER_SUBCOMMAND = "serve"

# Excludes the window between a broker being spawned and its caller connecting,
# where it is legitimately unreferenced and has no peer yet. Milliseconds wide
# in practice; a minute of margin costs nothing, since the processes this hook
# exists to remove are hours or days old.
DEFAULT_MIN_AGE_SECONDS = 60

# Narrows the hook to brokers whose command line contains this string. Empty
# considers every broker. Point it at one workspace to limit the sweep to it —
# which is also how the tests keep themselves to their own fixtures.
SCOPE_ENV = "CODEX_BROKER_REAPER_SCOPE"
MIN_AGE_ENV = "CODEX_BROKER_REAPER_MIN_AGE_SECONDS"

TIMEOUT_SECONDS = 5
ENDPOINT_RE = re.compile(r"--endpoint\s+(\S+)")
ETIME_RE = re.compile(r"^(?:(?:(\d+)-)?(\d+):)?(\d+):(\d+)$")


def _run(argv: list[str]) -> str | None:
    """Return stdout, or None if the command is missing, failed, or hung."""
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode in (0, 1) else None


def parse_etime(value: str) -> int | None:
    """Seconds from ps elapsed time: ``[[DD-]HH:]MM:SS``."""
    match = ETIME_RE.match(value.strip())
    if not match:
        return None
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


def endpoint_socket(cmdline: str) -> str | None:
    match = ENDPOINT_RE.search(cmdline)
    if not match:
        return None
    endpoint = match.group(1)
    # Endpoints are `unix:/path` on POSIX and a named pipe on Windows, which has
    # no socket file to inspect and no lsof to inspect it with.
    return endpoint[len("unix:") :] if endpoint.startswith("unix:") else None


def min_age_seconds() -> int:
    try:
        return max(int(os.environ[MIN_AGE_ENV]), 0)
    except (KeyError, ValueError):
        return DEFAULT_MIN_AGE_SECONDS


def live_brokers() -> list[dict]:
    """Every running plugin broker, with its age and socket path."""
    output = _run(["ps", "-axo", "pid=,etime=,command="])
    if not output:
        return []

    scope = os.environ.get(SCOPE_ENV, "")
    brokers = []
    for line in output.splitlines():
        parts = line.split(None, 2)
        if len(parts) != 3:
            continue
        pid_text, etime_text, cmdline = parts
        if BROKER_SCRIPT not in cmdline or BROKER_SUBCOMMAND not in cmdline.split():
            continue
        if scope and scope not in cmdline:
            continue
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        age = parse_etime(etime_text)
        if pid <= 1 or age is None:
            continue
        brokers.append(
            {"pid": pid, "age": age, "socket": endpoint_socket(cmdline), "cmdline": cmdline}
        )
    return brokers


def state_roots() -> list[Path]:
    """Directories the plugin may keep its per-workspace state under."""
    roots = []
    configured = os.environ.get("CLAUDE_PLUGIN_DATA")
    if configured:
        roots.append(Path(configured) / "state")
    roots.extend(sorted(Path.home().glob(".claude/plugins/data/*/state")))
    roots.append(Path(os.environ.get("TMPDIR", "/tmp")) / "codex-companion")

    seen, unique = set(), []
    for root in roots:
        resolved = root.expanduser()
        if resolved not in seen and resolved.is_dir():
            seen.add(resolved)
            unique.append(resolved)
    return unique


def referenced_sockets(roots: list[Path]) -> dict[int, set[str | None]]:
    """Every (pid, endpoint socket) pair named by a session record.

    Keyed by pid rather than a flat pair set so a lookup by a live broker's
    pid is O(1) instead of a scan. A bare pid is not proof of reachability —
    pids recycle — so callers must also check the live broker's own socket
    against this pid's recorded set before trusting the record.
    """
    by_pid: dict[int, set[str | None]] = {}
    for root in roots:
        for record in root.glob("*/broker.json"):
            try:
                data = json.loads(record.read_text(encoding="utf8"))
            except (OSError, ValueError):
                # A record that will not parse confers no reachability. The
                # plugin loads these the same way and treats a parse failure as
                # no session at all, so it will never reuse the broker such a
                # record describes — it spawns a replacement and abandons it.
                # That broker is therefore exactly what this hook removes.
                #
                # The one case where skipping could be wrong is a record caught
                # mid-write for a broker someone is about to use. Records are
                # written within milliseconds of a spawn, and nothing rewrites
                # one later, so the minimum-age gate already covers that window.
                continue
            pid = data.get("pid")
            if not isinstance(pid, int):
                continue
            endpoint = data.get("endpoint")
            # Same unix-prefix transform as endpoint_socket() applies to a live
            # process's cmdline, so a record's value compares equal to what a
            # live broker's own socket resolves to.
            socket_path = endpoint[len("unix:") :] if isinstance(endpoint, str) and endpoint.startswith("unix:") else None
            by_pid.setdefault(pid, set()).add(socket_path)
    return by_pid


def socket_holders(socket_path: str) -> int | None:
    """Processes holding this socket, or None when that cannot be determined."""
    output = _run(["lsof", "--", socket_path])
    if output is None:
        return None
    lines = [line for line in output.splitlines() if line.strip()]
    return max(len(lines) - 1, 0)  # drop the header


def is_group_leader(pid: int) -> bool:
    """Terminating a group is only safe when the process leads its own."""
    try:
        return os.getpgid(pid) == pid
    except OSError:
        return False


def should_reap(broker: dict, referenced: dict[int, set[str | None]]) -> tuple[bool, str]:
    if broker["socket"] in referenced.get(broker["pid"], ()):
        return False, "named by a session record"
    if broker["age"] < min_age_seconds():
        return False, "too young to judge"
    if not is_group_leader(broker["pid"]):
        return False, "not its own process group leader"

    socket_path = broker["socket"]
    if socket_path is None:
        return False, "no inspectable socket"
    if not Path(socket_path).exists():
        # The socket is gone, so no client can reach it and none can arrive.
        return True, "unreferenced, socket removed"

    holders = socket_holders(socket_path)
    if holders is None:
        return False, "could not determine socket holders"
    if holders > 1:
        return False, f"{holders - 1} client(s) connected"
    return True, "unreferenced, no client connected"


def reap(pid: int) -> bool:
    """Signal the broker's process group, which is what takes its child too.

    A signal to the broker alone leaves it hung: its shutdown path waits on a
    `codex app-server` child that never gets asked to stop.
    """
    try:
        os.killpg(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="codex-broker-reaper",
        description="Terminate unreachable Codex plugin brokers.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would be terminated."
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Report every broker and its verdict."
    )
    parser.add_argument("event", nargs="?", help="Hook event name (ignored).")
    args = parser.parse_args(argv)

    # Hook payloads arrive on stdin. Nothing here needs them, but leaving the
    # pipe unread can hand the caller a broken pipe.
    if not sys.stdin.isatty():
        try:
            sys.stdin.read()
        except OSError:
            pass

    brokers = live_brokers()
    referenced = referenced_sockets(state_roots())

    reaped = []
    for broker in brokers:
        verdict, reason = should_reap(broker, referenced)
        if args.verbose:
            action = "REAP" if verdict else "keep"
            print(f"{action} {broker['pid']}: {reason}", file=sys.stderr)
        if not verdict:
            continue
        if args.dry_run or reap(broker["pid"]):
            reaped.append(broker["pid"])

    if reaped:
        verb = "would terminate" if args.dry_run else "terminated"
        print(
            f"codex-broker-reaper: {verb} {len(reaped)} unreachable broker(s): "
            f"{', '.join(str(pid) for pid in reaped)}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - a hook must never break the session
        sys.exit(0)
