"""This adapter's own names for its backend, and the scrubber that removes them.

Everything the facade publishes -- `error.message`, `error.detail`, `data` --
is read by consumers who are promised they will never learn which tracker is
behind the seam. Authored text is easy to keep that promise in: the adapter
simply writes facade vocabulary. Passed-through text is not, because the
backend writes it and the backend names itself: a missing workspace, for
instance, is reported by this backend with its own binary name, its own
environment variable, and its own storage directory in one sentence.

Dropping that text would be the safe move and the wrong one -- it is the
entire content of an unrecognized failure, the one case where the adapter has
no answer of its own. So it travels, scrubbed. This module is where the
scrubbing lives because this module is inside the adapter, which is the only
layer permitted to know what its backend is called. A scrubber one layer up
would have to learn the same vocabulary to strip it, which is the knowledge
the seam exists to withhold.

The scrub is deliberately narrow: it removes the backend's *identity*, not
its diagnosis. "no <X> database found" still says a database is missing.
"""

from __future__ import annotations

import re

# The tokens that identify this backend: the binary, the project it belongs
# to (which names its environment variable and its storage directory too), and
# the storage engine underneath it. Word edges are spelled out rather than
# left to `\b` so that `BEADS_DIR` and `.beads` are matched -- `_` and a
# leading `.` are word characters to `\b`, which would let both through.
_BACKEND_IDENTITY = re.compile(
    r"(?<![A-Za-z0-9])\.?(?:beads|bd|dolt)(?![A-Za-z0-9])",
    re.IGNORECASE,
)

# Reads as a redaction rather than as a word, so nobody mistakes the scrubbed
# sentence for something the backend actually said.
_PLACEHOLDER = "[tracker]"


def redact(text: str) -> str:
    """Return `text` with every mention of this backend's identity replaced.

    Applied to backend-authored text on its way into a published field. Not
    applied to adapter-authored text: an authored message that needs this is
    a message written in the wrong vocabulary, and scrubbing it would hide
    that rather than fix it.
    """
    return _BACKEND_IDENTITY.sub(_PLACEHOLDER, text)
