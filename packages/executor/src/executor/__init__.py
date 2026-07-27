"""executor — the decision layer above the grind runtime and the work facade.

grind reports facts; the work facade records tracker outcomes. This package is
the only place that pairs the two: one executor verb appends one grind event
and enacts at most one tracker verb (the S9T1-D12 pairing table).

The envelope is protocol-versioned from birth (S9T1-D11). `"1"` is the shape
`{"protocol", "ok", "data", "error"}` with `error` as
`{code, message, retryable, data?}`.
"""

from __future__ import annotations

PROTOCOL_VERSION = "1"
