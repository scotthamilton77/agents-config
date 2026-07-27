"""Suite-wide guards.

S9T1-A6's strongest claim is not about one command: it is that *across the
whole suite* the fake tracker's mutation log contains no run-local slug. A
per-test assertion would only cover the tests that remembered to make it, so
the guard runs after every test instead.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from executor.state import RUN_LOCAL_SLUG
from tests.unit.fakes import LIVE_TRACKERS


@pytest.fixture(autouse=True)
def no_run_local_tracker_writes() -> Iterator[None]:
    LIVE_TRACKERS.clear()
    yield
    offenders = [
        mutation
        for tracker in LIVE_TRACKERS
        for mutation in tracker.mutations
        if len(mutation) > 1 and RUN_LOCAL_SLUG.match(mutation[1])
    ]
    LIVE_TRACKERS.clear()
    assert offenders == [], f"tracker mutations issued against run-local slugs: {offenders}"
