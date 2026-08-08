"""Pin that both `work show` reply shapes still parse.

These scripts shell out to whichever `work` is on PATH, which is not
necessarily the one built in this checkout. Protocol 2.0 made `work show ID`
answer `{"items": [...]}`, where every earlier version answered a single id
with the item object directly — so a helper written for either shape alone
breaks against half the installations that exist right now. `context.show`
reads both, and that is the whole of what is tested here.

The same hazard, one verb over, is recorded in verify.py's C1 comment: a
default that MOVED between protocol versions, read by a script that does not
control which version it gets.
"""

import pathlib
import unittest
from unittest import mock

import context

_ITEM = {
    "id": "agents-config-x1",
    "status": "open",
    "parent": None,
    "labels": ["track:workcli"],
    "track": "workcli",
}

_OLD_SHAPE = {"protocol": "1.13", "ok": True, "data": dict(_ITEM), "error": None}
_NEW_SHAPE = {"protocol": "2.0", "ok": True, "data": {"items": [dict(_ITEM)]}, "error": None}
_NOT_FOUND = {
    "protocol": "2.0",
    "ok": False,
    "data": None,
    "error": {"code": "E_NOT_FOUND", "message": "no such item", "detail": None},
}


class TestShowReadsBothShapes(unittest.TestCase):
    def _shown(self, envelope, **kwargs):
        with mock.patch.object(context, "work", return_value=envelope) as ran:
            got = context.show(pathlib.Path("/repo"), "agents-config-x1", **kwargs)
        self.assertEqual(ran.call_args.args[1:], ("show", "agents-config-x1"))
        return got

    def test_the_pre_2_0_singular_shape_still_parses(self):
        """The installed `work` may predate the bump; it must keep working."""
        self.assertEqual(self._shown(_OLD_SHAPE)["data"], _ITEM)

    def test_the_2_0_items_shape_parses_to_the_same_item(self):
        self.assertEqual(self._shown(_NEW_SHAPE)["data"], _ITEM)

    def test_both_shapes_hand_the_caller_the_identical_payload(self):
        # The point of the helper: a caller reads one thing and never learns
        # which facade answered it.
        self.assertEqual(self._shown(_OLD_SHAPE), {**self._shown(_NEW_SHAPE), "protocol": "1.13"})

    def test_a_failing_envelope_is_returned_intact_for_the_caller_to_read(self):
        # verify.py's C6 asks whether the groom-state item exists at all, so a
        # failure is its finding rather than an abort.
        got = self._shown(_NOT_FOUND, require_ok=False)
        self.assertIs(got["ok"], False)
        self.assertIsNone(got["data"])

    def test_a_reply_carrying_more_than_one_row_aborts_rather_than_taking_the_first(self):
        many = {"protocol": "2.0", "ok": True, "data": {"items": [_ITEM, _ITEM]}, "error": None}
        with self.assertRaises(SystemExit):
            self._shown(many)


if __name__ == "__main__":
    unittest.main()
