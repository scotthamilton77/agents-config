"""Config surface + loader for prgroom (§3.5, §4.3).

Settings resolve with precedence **CLI flag > env var > per-repo TOML >
built-in default** (§3.5). Durations are written in TOML as strings
(``"5m"``, ``"1h30m"``) and parsed into :class:`~datetime.timedelta`. The TOML
file is the per-repo ``.prgroom.toml``; a missing file is not an error (every
setting has a default).

:class:`ApproverConfig` reads a different file — the *project* config, whose
``[merge-policy.approver]`` table names the GitHub App identity the ``approve``
verb posts under. It shares this module's parse helpers and its uniform
``ValueError`` on malformed input, and nothing about it is defaulted or resolved
from the environment: absence is an error, not a fallback.

Two TOML scopes (§3.5, §4.3): the PR-review retry budget ``pr_review_retries`` is a
top-level key; the §4.3 quiescence knobs live under a ``[quiescence]`` table
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

DEFAULT_PR_REVIEW_RETRIES = 5
DEFAULT_REVIEW_START_TIMEOUT = timedelta(minutes=3)
DEFAULT_REVIEW_FINISH_TIMEOUT = timedelta(minutes=15)
DEFAULT_IDLE_THRESHOLD = timedelta(minutes=10)
DEFAULT_POLL_INTERVAL = timedelta(seconds=30)
DEFAULT_AUTO_REQUEST_HUMAN_REVIEW = True
DEFAULT_APPROVER_KEY_PATH_ENV = "MERGE_GUARD_APPROVER_KEY_PATH"

_QUIESCENCE_TABLE = "quiescence"
_MERGE_POLICY_TABLE = "merge-policy"
_APPROVER_TABLE = "approver"
_APPROVER_TYPE = "github-app"
_APPROVER_KEYS: frozenset[str] = frozenset({"type", "app-id", "key-path-env"})

# The value names an environment variable, so it must be a legal one — rejected
# here rather than left to fail cryptically at lookup time.
_ENV_VAR_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

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

    pr_review_retries: int = DEFAULT_PR_REVIEW_RETRIES
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
        pr_review_retries_flag: int | None = None,
        idle_threshold_flag: timedelta | None = None,
        poll_interval_flag: timedelta | None = None,
        review_start_timeout_flag: timedelta | None = None,
        review_finish_timeout_flag: timedelta | None = None,
        auto_request_human_review_flag: bool | None = None,
    ) -> PrgroomConfig:
        """Resolve config with CLI > env > TOML > default precedence (§3.5, §4.3)."""
        table = read_toml(repo_config)
        quiescence = subtable(table, _QUIESCENCE_TABLE)

        return cls(
            pr_review_retries=cls._resolve_pr_review_retries(table, pr_review_retries_flag),
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
    def _resolve_pr_review_retries(table: dict[str, Any], flag: int | None) -> int:
        if flag is not None:
            return flag
        env = os.environ.get("PRGROOM_PR_REVIEW_RETRIES")
        if env is not None:
            try:
                return int(env)
            except ValueError as exc:
                msg = (
                    f"PRGROOM_PR_REVIEW_RETRIES (pr_review_retries) must be an integer, got {env!r}"
                )
                raise ValueError(msg) from exc
        if "pr_review_retries" in table:
            return _coerce_int(table["pr_review_retries"], key="pr_review_retries")
        return DEFAULT_PR_REVIEW_RETRIES


@dataclass(frozen=True, slots=True)
class ApproverConfig:
    """The GitHub App identity that authors an approving review.

    A mechanical review-satisfaction identity, never an authorization source.
    ``key_path_env`` names the environment variable holding the private key's
    path, so the key's location never enters a committed file.
    """

    app_id: int
    key_path_env: str = DEFAULT_APPROVER_KEY_PATH_ENV

    @classmethod
    def load(cls, path: Path) -> ApproverConfig:
        """Read the approver block out of the project config at ``path``.

        Raises :class:`ValueError` — the loader's uniform type — when the block is
        absent, mistyped, or carries a key this reader does not know. Absence is an
        error rather than a default: there is no App identity to fall back to, and
        a silent default would post reviews as the wrong actor. An unknown key
        fails loud for the same reason a typo'd one must not be ignored.
        """
        merge_policy = subtable(read_toml(path), _MERGE_POLICY_TABLE)
        if _APPROVER_TABLE not in merge_policy:
            msg = f"no [{_MERGE_POLICY_TABLE}.{_APPROVER_TABLE}] block in {path}"
            raise ValueError(msg)
        section = subtable(merge_policy, _APPROVER_TABLE)
        unknown = sorted(set(section) - _APPROVER_KEYS)
        if unknown:
            msg = (
                f"[{_MERGE_POLICY_TABLE}.{_APPROVER_TABLE}] has unknown key(s) "
                f"{', '.join(unknown)} (allowed: {', '.join(sorted(_APPROVER_KEYS))})"
            )
            raise ValueError(msg)
        approver_type = section.get("type")
        if approver_type != _APPROVER_TYPE:
            msg = f"approver type must be {_APPROVER_TYPE!r}, got {approver_type!r}"
            raise ValueError(msg)
        app_id = _coerce_int(section.get("app-id"), key="app-id")
        if app_id <= 0:
            msg = f"app-id must be a positive integer, got {app_id}"
            raise ValueError(msg)
        key_path_env = section.get("key-path-env", DEFAULT_APPROVER_KEY_PATH_ENV)
        if not isinstance(key_path_env, str) or not _ENV_VAR_NAME_RE.fullmatch(key_path_env):
            msg = f"key-path-env must be a valid environment variable name, got {key_path_env!r}"
            raise ValueError(msg)
        return cls(app_id=app_id, key_path_env=key_path_env)


def read_toml(path: Path | None) -> dict[str, Any]:
    """Parse the per-repo ``.prgroom.toml`` (missing file -> ``{}``).

    The single parse path for the config file — :class:`PrgroomConfig` and the
    agent chain loader both read through here, so the file is interpreted one way.
    """
    if path is None or not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def subtable(table: dict[str, Any], key: str) -> dict[str, Any]:
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
