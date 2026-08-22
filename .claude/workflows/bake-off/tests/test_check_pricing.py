"""The expiry gate: a dated price is honoured through its last day and not after."""

import datetime as dt
import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "check_pricing", Path(__file__).resolve().parents[1] / "check_pricing.py"
)
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)

TABLE = json.loads((Path(__file__).resolve().parents[1] / "pricing.json").read_text())


def _table(expires):
    return {"models": {"m": {"input": 1.0, "expires": expires}}}


def test_last_honoured_day_is_not_expired():
    # "available at least through 2026-11-21" means the 21st still bills at that price.
    assert cp.check(_table("2026-11-21"), dt.date(2026, 11, 21)) == []


def test_day_after_is_expired():
    out = cp.check(_table("2026-11-21"), dt.date(2026, 11, 22))
    assert [e["model"] for e in out] == ["m"]
    assert out[0]["days_stale"] == 1


def test_entry_without_an_expiry_never_expires():
    assert cp.check({"models": {"m": {"input": 1.0}}}, dt.date(2099, 1, 1)) == []


def test_unparseable_expiry_is_reported_not_ignored():
    # A typo must not read as "no expiry" — that would silently disarm the gate.
    out = cp.check(_table("not-a-date"), dt.date(2026, 1, 1))
    assert out and out[0]["reason"] == "unparseable expires date"


def test_shipped_table_is_clean_on_its_own_verified_date():
    verified = dt.date.fromisoformat(TABLE["verified"])
    assert cp.check(TABLE, verified) == []


def test_shipped_table_expires_sol_after_its_published_window():
    out = cp.check(TABLE, dt.date(2026, 11, 22))
    assert [e["model"] for e in out] == ["gpt-5.6-sol"]


def test_every_model_carries_the_rates_a_cost_calculation_needs():
    for name, m in TABLE["models"].items():
        assert m["vendor"] in {"anthropic", "openai"}, name
        for field in ("input", "output", "cache_read"):
            assert isinstance(m[field], (int, float)), f"{name}.{field}"
