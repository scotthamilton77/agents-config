from pathlib import Path

import pytest

from installer.core.receipt_lock import ReceiptLockBusy, receipt_lock


def test_second_acquire_while_held_raises_busy(tmp_path: Path) -> None:
    lock_path = tmp_path / "install-receipt.lock"
    with receipt_lock(lock_path), pytest.raises(ReceiptLockBusy), receipt_lock(lock_path):
        pass


def test_lock_is_released_after_context_exit(tmp_path: Path) -> None:
    lock_path = tmp_path / "install-receipt.lock"
    with receipt_lock(lock_path):
        pass
    # re-acquiring after release succeeds (no exception)
    with receipt_lock(lock_path):
        pass


def test_lock_creates_parent_dir(tmp_path: Path) -> None:
    lock_path = tmp_path / "nested" / "dir" / "install-receipt.lock"
    with receipt_lock(lock_path):
        assert lock_path.exists()
