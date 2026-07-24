"""Track derivation and vocabulary validation.

Derivation is config-free by design -- a pure function over labels -- so the
`Item.track` envelope field appears on every read verb regardless of config
state. Only *validation* (`require_known_track`) needs the vocabulary.
"""

from __future__ import annotations

from collections.abc import Sequence

from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, WorkError

TRACK_PREFIX = "track:"


def derive_track(labels: Sequence[str]) -> str | None:
    """Exactly one `track:*` label -> its name; zero or 2+ -> None."""
    names = [label[len(TRACK_PREFIX) :] for label in labels if label.startswith(TRACK_PREFIX)]
    if len(names) == 1:
        return names[0]
    return None


def track_label(name: str) -> str:
    return f"{TRACK_PREFIX}{name}"


def require_known_track(name: str, config: TrackLayerConfig) -> None:
    """Unknown names fail with E_UNKNOWN_TRACK naming the vocabulary -- never a new label."""
    if name not in config.names:
        raise WorkError(
            ErrorCode.UNKNOWN_TRACK,
            f"unknown track {name!r}; configured tracks: {', '.join(config.names)}",
            detail={"track": name, "names": list(config.names)},
        )
