#!/usr/bin/env python3
"""Refuse a bake-off run whose pricing table has a price the vendor stopped honouring.

A published price with an end date is not a price after that date. A cost figure
computed from one is wrong in a way nothing downstream can detect, so the run stops
here and a human re-verifies the table against the vendor rather than a later reader
trusting a number nobody checked.

Exit 0 the table is honourable, 3 an entry has expired, 2 the table is unusable.
Prints one JSON object either way.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

CLEAN, EXPIRED, UNUSABLE = 0, 3, 2


def check(table: dict, today: dt.date) -> list[dict]:
    """Every model whose published price stopped applying on or before `today`."""
    expired = []
    for name, m in sorted((table.get("models") or {}).items()):
        raw = m.get("expires")
        if not raw:
            continue
        try:
            ends = dt.date.fromisoformat(raw)
        except ValueError:
            expired.append({"model": name, "expires": raw, "reason": "unparseable expires date"})
            continue
        if today > ends:
            expired.append({
                "model": name,
                "expires": raw,
                "days_stale": (today - ends).days,
                "reason": m.get("expires_reason") or "dated price",
            })
    return expired


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--table", default=str(Path(__file__).with_name("pricing.json")))
    p.add_argument("--today", help="ISO date; defaults to today in UTC. For tests.")
    a = p.parse_args()

    try:
        table = json.loads(Path(a.table).read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(json.dumps({"ok": False, "errors": [f"cannot read {a.table}: {e}"]}))
        return UNUSABLE

    try:
        today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(dt.UTC).date()
    except ValueError as e:
        print(json.dumps({"ok": False, "errors": [f"bad --today: {e}"]}))
        return UNUSABLE

    expired = check(table, today)
    out = {
        "ok": not expired,
        "table": a.table,
        "verified": table.get("verified"),
        "today": today.isoformat(),
        "expired": expired,
    }
    if expired:
        names = ", ".join(f"{e['model']} (ended {e['expires']})" for e in expired)
        out["message"] = (
            f"Pricing expired for: {names}. Re-verify against the vendor's current "
            f"pricing page, update {a.table}, and move its `verified` date. Until then "
            "any cost this run reports would be computed from a price nobody honours."
        )
    print(json.dumps(out, indent=2, sort_keys=True))
    return EXPIRED if expired else CLEAN


if __name__ == "__main__":
    sys.exit(main())
