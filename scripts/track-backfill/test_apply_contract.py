"""Tests for apply.py's failure-classification contract.

These exist because a real regression shipped here: `set_track` was written to
inspect a failing envelope and return an error code, but the shared `work()`
helper defaults to `require_ok=True` and raises `SystemExit` first. The
E_NOT_FOUND recovery branch became unreachable dead code in the same commit that
introduced it, and every other write failure silently bypassed the run-log
summary.

Nothing caught it, because the only test coverage was of pure reconciliation
logic and the failure path needs a failing backend to exercise. So these tests
substitute the backend instead of the whole subprocess layer.
"""
import unittest

import apply


class FakeWork:
    """Stands in for context.work, recording how it was called."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, root, *argv, require_ok=True):
        self.calls.append({"argv": argv, "require_ok": require_ok})
        if require_ok and not self.payload.get("ok"):
            # Exactly what the real helper does — this is the trap.
            raise SystemExit(f"`work {' '.join(argv)}` failed")
        return self.payload


class TestSetTrackClassifiesFailures(unittest.TestCase):
    def setUp(self):
        self._real_work = apply.work

    def tearDown(self):
        apply.work = self._real_work

    def _run(self, payload):
        fake = FakeWork(payload)
        apply.work = fake
        return fake, apply.set_track("/repo", "agents-config-abc", "installer")

    def test_vanished_item_is_classified_not_raised(self):
        """The regression: this raised SystemExit instead of returning a code."""
        _, (ok, code) = self._run(
            {"ok": False, "error": {"code": "E_NOT_FOUND", "message": "gone"}}
        )
        self.assertFalse(ok)
        self.assertEqual(code, "E_NOT_FOUND")

    def test_set_track_opts_out_of_fail_loud(self):
        """Pin the require_ok=False that makes classification possible at all."""
        fake, _ = self._run({"ok": False, "error": {"code": "E_NOT_FOUND"}})
        self.assertEqual(len(fake.calls), 1)
        self.assertFalse(
            fake.calls[0]["require_ok"],
            "set_track must opt out of fail-loud or it can never classify an error",
        )

    def test_other_failures_are_classified_too(self):
        """Contention must reach the abort path with its code, not a bare exit."""
        _, (ok, code) = self._run({"ok": False, "error": {"code": "E_CONTENDED"}})
        self.assertFalse(ok)
        self.assertEqual(code, "E_CONTENDED")

    def test_error_envelope_without_a_code_degrades_to_unknown(self):
        _, (ok, code) = self._run({"ok": False, "error": {}})
        self.assertFalse(ok)
        self.assertEqual(code, "UNKNOWN")

    def test_null_error_object_does_not_crash(self):
        _, (ok, code) = self._run({"ok": False, "error": None})
        self.assertFalse(ok)
        self.assertEqual(code, "UNKNOWN")

    def test_success_returns_ok_with_no_code(self):
        _, (ok, code) = self._run({"ok": True, "data": {"track": "installer"}})
        self.assertTrue(ok)
        self.assertEqual(code, "")

    def test_it_writes_through_the_validated_gate(self):
        """Never a raw label write — the track must go through `work track set`."""
        fake, _ = self._run({"ok": True, "data": {}})
        self.assertEqual(
            fake.calls[0]["argv"],
            ("track", "set", "agents-config-abc", "installer"),
        )


if __name__ == "__main__":
    unittest.main()
