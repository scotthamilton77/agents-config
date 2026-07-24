"""Leading YAML front-matter split, shared by the admission bar and the surface
budget (S3).

A markdown artifact optionally opens with a ``---`` fenced YAML block. The
admission gate reads the ``admission``/``claims`` mappings out of it; the
surface budget measures the *body* (everything after the block) against the
per-skill cap. Both need the same split, so it lives here once.

Deliberately hand-rolled rather than pulling a front-matter library: the split
is a three-line-fence scan and the payload goes through ``yaml.safe_load``
(already a dependency). A parse failure or a non-mapping payload is treated as
"no front matter" — the caller then sees no ``admission`` key and drops the
artifact, which is the safe default (an unparseable artifact never silently
earns admission).
"""

from __future__ import annotations

from typing import Any

import yaml

_FENCE = "---"


def split_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    """Split ``text`` into ``(frontmatter_mapping_or_None, body)``.

    The front matter is a leading line equal to ``---`` followed by YAML up to
    the next ``---`` line. Returns the parsed mapping and the body text after
    the closing fence. When there is no leading fence, no closing fence, the
    YAML fails to parse, or the payload is not a mapping, returns
    ``(None, text)`` — the full text is the body and there is no record.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _FENCE:
        return None, text
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FENCE:
            block = "".join(lines[1:idx])
            body = "".join(lines[idx + 1 :])
            try:
                loaded: Any = yaml.safe_load(block)
            except yaml.YAMLError:
                return None, text
            if isinstance(loaded, dict):
                return loaded, body
            return None, text
    # Opening fence with no close: not front matter.
    return None, text
