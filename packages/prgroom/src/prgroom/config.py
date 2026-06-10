"""Config surface + loader for prgroom (§3.5, §4.3, §7).

Settings resolve with precedence **CLI flag > env var > per-repo TOML >
built-in default** (§3.5). Durations are written in TOML as strings
(``"5m"``, ``"1h30m"``) and parsed into :class:`~datetime.timedelta`. The TOML
file is the per-repo ``.prgroom.toml``; a missing file is not an error (every
setting has a default).

Two TOML scopes (§3.5, §4.3): the hard-cap ``max_rounds`` is a top-level key; the
§4.3 quiescence knobs live under a ``[quiescence]`` table
(``quiescence.idle_threshold``, ``quiescence.poll_interval``, etc.). Each knob also
honors a ``PRGROOM_<UPPER>`` env var and an optional CLI flag passed to
:meth:`PrgroomConfig.load`.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

DEFAULT_MAX_ROUNDS = 3
DEFAULT_REVIEW_START_TIMEOUT = timedelta(minutes=3)
DEFAULT_REVIEW_FINISH_TIMEOUT = timedelta(minutes=15)
DEFAULT_IDLE_THRESHOLD = timedelta(minutes=10)
DEFAULT_POLL_INTERVAL = timedelta(seconds=30)
DEFAULT_AUTO_REQUEST_HUMAN_REVIEW = True

_QUIESCENCE_TABLE = "quiescence"

# Accepted boolean spellings for the §4.3 ``auto_request_human_review`` env var.
_TRUE_TOKENS: frozenset[str] = frozenset({"true", "1", "yes", "on"})
_FALSE_TOKENS: frozenset[str] = frozenset({"false", "0", "no", "off"})

_DURATION_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")


def parse_duration(text: str) -> timedelta:
    """Parse a duration string (``30s`` / ``10m`` / ``1h30m``) into a timedelta.

    Units must appear in descending order (h, m, s), each at most once, with at
    least one unit present. Raises :class:`ValueError` on any malformed input.
    """
    match = _DURATION_RE.fullmatch(text)
    if match is None or not any(match.groups()):
        msg = f"invalid duration string: {text!r} (expected e.g. '30s', '10m', '1h30m')"
        raise ValueError(msg)
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


def _parse_bool(value: str, *, key: str) -> bool:
    lowered = value.strip().lower()
    if lowered in _TRUE_TOKENS:
        return True
    if lowered in _FALSE_TOKENS:
        return False
    msg = f"{key} must be a boolean (true/false), got {value!r}"
    raise ValueError(msg)


def _coerce_int(value: object, *, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{key} must be an integer, got {value!r}"
        raise ValueError(msg)  # noqa: TRY004  # config-domain validation error; ValueError is the loader's uniform type
    return value


def _resolve_duration(
    *,
    flag: timedelta | None,
    env_var: str,
    table: dict[str, Any],
    table_key: str,
    default: timedelta,
) -> timedelta:
    """CLI flag > env var > ``[quiescence]`` table > default for a duration knob."""
    if flag is not None:
        return flag
    env = os.environ.get(env_var)
    if env is not None:
        try:
            return parse_duration(env)
        except ValueError as exc:
            msg = f"{table_key} ({env_var}) must be a duration string, got {env!r}"
            raise ValueError(msg) from exc
    raw = table.get(table_key)
    if raw is None:
        return default
    if not isinstance(raw, str):
        msg = f"{table_key} must be a duration string, got {raw!r}"
        raise ValueError(msg)  # noqa: TRY004  # config-domain validation error; ValueError is the loader's uniform type
    try:
        return parse_duration(raw)
    except ValueError as exc:
        msg = f"{table_key} must be a duration string, got {raw!r}"
        raise ValueError(msg) from exc


def _resolve_bool(
    *,
    flag: bool | None,
    env_var: str,
    table: dict[str, Any],
    table_key: str,
    default: bool,  # internal resolver; the public surface uses keyword-only flags
) -> bool:
    """CLI flag > env var > ``[quiescence]`` table > default for a boolean knob."""
    if flag is not None:
        return flag
    env = os.environ.get(env_var)
    if env is not None:
        return _parse_bool(env, key=f"{table_key} ({env_var})")
    raw = table.get(table_key)
    if raw is None:
        return default
    if not isinstance(raw, bool):
        msg = f"{table_key} must be a boolean, got {raw!r}"
        raise ValueError(msg)  # noqa: TRY004  # config-domain validation error; ValueError is the loader's uniform type
    return raw


@dataclass(frozen=True, slots=True)
class PrgroomConfig:
    """Resolved runtime configuration."""

    max_rounds: int = DEFAULT_MAX_ROUNDS
    review_start_timeout: timedelta = DEFAULT_REVIEW_START_TIMEOUT
    review_finish_timeout: timedelta = DEFAULT_REVIEW_FINISH_TIMEOUT
    idle_threshold: timedelta = DEFAULT_IDLE_THRESHOLD
    poll_interval: timedelta = DEFAULT_POLL_INTERVAL
    auto_request_human_review: bool = DEFAULT_AUTO_REQUEST_HUMAN_REVIEW

    @classmethod
    def load(
        cls,
        *,
        repo_config: Path | None = None,
        max_rounds_flag: int | None = None,
        idle_threshold_flag: timedelta | None = None,
        poll_interval_flag: timedelta | None = None,
        review_start_timeout_flag: timedelta | None = None,
        review_finish_timeout_flag: timedelta | None = None,
        auto_request_human_review_flag: bool | None = None,
    ) -> PrgroomConfig:
        """Resolve config with CLI > env > TOML > default precedence (§3.5, §4.3)."""
        table = _read_toml(repo_config)
        quiescence = _subtable(table, _QUIESCENCE_TABLE)

        return cls(
            max_rounds=cls._resolve_max_rounds(table, max_rounds_flag),
            review_start_timeout=_resolve_duration(
                flag=review_start_timeout_flag,
                env_var="PRGROOM_REVIEW_START_TIMEOUT",
                table=quiescence,
                table_key="review_start_timeout",
                default=DEFAULT_REVIEW_START_TIMEOUT,
            ),
            review_finish_timeout=_resolve_duration(
                flag=review_finish_timeout_flag,
                env_var="PRGROOM_REVIEW_FINISH_TIMEOUT",
                table=quiescence,
                table_key="review_finish_timeout",
                default=DEFAULT_REVIEW_FINISH_TIMEOUT,
            ),
            idle_threshold=_resolve_duration(
                flag=idle_threshold_flag,
                env_var="PRGROOM_IDLE_THRESHOLD",
                table=quiescence,
                table_key="idle_threshold",
                default=DEFAULT_IDLE_THRESHOLD,
            ),
            poll_interval=_resolve_duration(
                flag=poll_interval_flag,
                env_var="PRGROOM_POLL_INTERVAL",
                table=quiescence,
                table_key="poll_interval",
                default=DEFAULT_POLL_INTERVAL,
            ),
            auto_request_human_review=_resolve_bool(
                flag=auto_request_human_review_flag,
                env_var="PRGROOM_AUTO_REQUEST_HUMAN_REVIEW",
                table=quiescence,
                table_key="auto_request_human_review",
                default=DEFAULT_AUTO_REQUEST_HUMAN_REVIEW,
            ),
        )

    @staticmethod
    def _resolve_max_rounds(table: dict[str, Any], flag: int | None) -> int:
        if flag is not None:
            return flag
        env = os.environ.get("PRGROOM_MAX_ROUNDS")
        if env is not None:
            try:
                return int(env)
            except ValueError as exc:
                msg = f"PRGROOM_MAX_ROUNDS (max_rounds) must be an integer, got {env!r}"
                raise ValueError(msg) from exc
        if "max_rounds" in table:
            return _coerce_int(table["max_rounds"], key="max_rounds")
        return DEFAULT_MAX_ROUNDS


def _read_toml(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _subtable(table: dict[str, Any], key: str) -> dict[str, Any]:
    """Return the named sub-table; ``{}`` if absent, raise if present-but-not-a-table.

    An absent key falls through to per-setting defaults. A present-but-wrong-typed key
    (e.g. ``quiescence = "..."``) is a config error — failing fast keeps the loader's
    type validation consistent rather than silently ignoring a malformed override.
    """
    raw = table.get(key)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        msg = f"{key} must be a table, got {raw!r}"
        raise ValueError(msg)  # noqa: TRY004  # config-domain validation error; ValueError is the loader's uniform type
    return raw
