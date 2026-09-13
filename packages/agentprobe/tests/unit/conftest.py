"""Shared access to the recorded runs the detectors are tested against."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentprobe.events import Run, load_run

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def run2() -> Run:
    """The teammate-child-messaging recording used as the reference for every detector."""
    return load_run(FIXTURES / "run2")


@pytest.fixture
def guard_run() -> Run:
    """A recording of the report-file-guard scenario, where the guard actually fired."""
    return load_run(FIXTURES / "guard-run")


@pytest.fixture
def packaged_run() -> Run:
    """The first recording the package made of itself driving a session end to end."""
    return load_run(FIXTURES / "packaged-run")


@pytest.fixture
def run3() -> Run:
    """A second recording of the same scenario, for the rate a report prints across runs."""
    return load_run(FIXTURES / "run3")
