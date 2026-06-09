"""Schema-migration registry for persisted state (§2, §3.7).

A migrator upgrades a serialized state blob from one ``schema_version`` to the
current one. The registry is keyed by the **from** version. It is EMPTY in the
MVP — ``schema_version`` is 1 and there is nothing older to upgrade — but the
seam exists so a future schema bump ships its upgrade path here without touching
the read path. :meth:`~prgroom.prsession.file.FileStore.read` consults this dict
on a version mismatch: a registered migrator runs and the file is rewritten in
place; an absent one trips ``STATE_SCHEMA_UNKNOWN`` (exit 78).
"""

from __future__ import annotations

from collections.abc import Callable

# Upgrades a raw JSON state blob from the keyed (from-)version toward the current
# SCHEMA_VERSION. Must be pure w.r.t. the filesystem — the caller owns the atomic
# rewrite. A migrator that cannot convert MUST raise (never return corrupt bytes);
# the read path maps the raise to STATE_CORRUPT.
Migrator = Callable[[bytes], bytes]

# Keyed by the from-version. EMPTY in MVP (schema_version == 1, nothing older).
MIGRATIONS: dict[int, Migrator] = {}
