"""Remote-less sync against real embedded-dolt: honest ok=true, incl. a real
pending change through the commit path."""

from __future__ import annotations


def test_sync_remote_less_is_ok(driver):
    env = driver(["sync"])
    assert env["ok"] is True
    assert env["data"]["mode"] == "push"


def test_sync_after_a_real_mutation_commits(driver):
    # A real pending change drives `dolt commit` down its with-content path; ok=True
    # confirms that path completes without error. The remote-less envelope
    # ({synced, mode}) does not distinguish a real commit from the nothing-pending
    # no-op, so that is the extent of what this asserts — it guards the path
    # against regressions/exceptions, not the commit's byte-level effect.
    driver(["create", "--raw", "--title", "sync-content", "--type", "task", "--priority", "2"])
    env = driver(["sync"])
    assert env["ok"] is True
