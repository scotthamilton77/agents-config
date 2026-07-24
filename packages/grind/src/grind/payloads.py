"""Per-type payload shape validation -- the CLI boundary (spec: "validated
per-type at the CLI boundary ... parse once, trust inward").

This is the malformed/illegal seam: a payload failing these checks is a
command error (nothing appended); a payload that passes but is illegal from
the entity's current status still appends and folds as an anomaly
(accept-and-flag, `grind.fold`'s job, not this module's). Required-field sets
are taken from the event taxonomy table in the event-sourced grind runtime
spec -- no field is invented here that the spec doesn't name.
"""

from __future__ import annotations

from collections.abc import Callable

from grind.model import PARK_REASONS, RawEvent

Validator = Callable[[RawEvent], list[str]]

_REVIEW_KINDS = {"codex", "copilot", "ralf", "human"}
_VERDICTS = {"clean", "findings", "stalemate"}
_DISPOSITIONS = {"fixed", "wont-fix", "deferred", "escalated"}
# One vocabulary, one definition: `grind.model.PARK_REASONS` is the source and
# both the enum check and its error text derive from it, so the boundary can't
# drift from the fold's idea of a legal reason.
_PARK_REASONS: set[str] = set(PARK_REASONS)
_PARK_REASONS_HELP = "|".join(PARK_REASONS)
_PR_CLOSED_NEXT = {"in-progress", "queued", "parked"}
_OBSERVATION_LEVELS = {"INFO", "WARN", "ERROR", "LESSON"}
_WORK_DISPOSITIONS = {"parked", "enqueued"}


def _is_str(payload: RawEvent, key: str) -> bool:
    value = payload.get(key)
    return isinstance(value, str) and value != ""


def _is_int(payload: RawEvent, key: str) -> bool:
    value = payload.get(key)
    return isinstance(value, int) and not isinstance(value, bool)


def _is_dict(payload: RawEvent, key: str) -> bool:
    return isinstance(payload.get(key), dict)


def _is_list_of_str(payload: RawEvent, key: str) -> bool:
    value = payload.get(key)
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_enum(payload: RawEvent, key: str, choices: set[str]) -> bool:
    return payload.get(key) in choices


def _require(errors: list[str], ok: bool, message: str) -> None:
    if not ok:
        errors.append(message)


def _require_str(errors: list[str], payload: RawEvent, key: str) -> None:
    _require(errors, _is_str(payload, key), f"{key} is required and must be a non-empty string")


def _optional_str(errors: list[str], payload: RawEvent, key: str) -> None:
    if key in payload and payload[key] is not None:
        _require(errors, isinstance(payload[key], str), f"{key} must be a string when present")


def _optional_nested_str(errors: list[str], container: RawEvent, key: str, prefix: str) -> None:
    if container.get(key) is not None:
        _require(
            errors,
            isinstance(container[key], str),
            f"{prefix}.{key} must be a string when present",
        )


def _optional_nested_list_of_str(
    errors: list[str], container: RawEvent, key: str, prefix: str
) -> None:
    if container.get(key) is not None:
        _require(
            errors,
            _is_list_of_str(container, key),
            f"{prefix}.{key} must be an array of strings when present",
        )


def _validate_grind_created(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "title")
    _require_str(errors, payload, "repo")
    _require(errors, _is_dict(payload, "mission"), "mission is required and must be an object")
    _require(errors, _is_dict(payload, "protocols"), "protocols is required and must be an object")
    if "config" in payload and payload["config"] is not None:
        _require(errors, _is_dict(payload, "config"), "config must be an object when present")

    lanes = payload.get("lanes")
    if not isinstance(lanes, list):
        errors.append("lanes is required and must be an array")
        return errors
    for lane_index, lane in enumerate(lanes):
        if not isinstance(lane, dict) or not _is_str(lane, "id"):
            errors.append(f"lanes[{lane_index}] must be an object with a non-empty string id")
            continue
        lane_prefix = f"lanes[{lane_index}]"
        for field in ("name", "agent", "model", "effort"):
            _optional_nested_str(errors, lane, field, lane_prefix)
        if "queue" not in lane:
            continue
        queue = lane.get("queue")
        if not isinstance(queue, list):
            errors.append(f"{lane_prefix}.queue must be an array when present")
            continue
        for item_index, item in enumerate(queue):
            item_prefix = f"{lane_prefix}.queue[{item_index}]"
            if not isinstance(item, dict) or not _is_str(item, "id"):
                errors.append(f"{item_prefix} must be an object with a non-empty string id")
                continue
            _optional_nested_str(errors, item, "title", item_prefix)
            _optional_nested_list_of_str(errors, item, "on", item_prefix)
    return errors


def _validate_grind_paused(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "reason")
    if "resume_checklist" in payload:
        _require(
            errors,
            _is_list_of_str(payload, "resume_checklist"),
            "resume_checklist must be an array of strings when present",
        )
    return errors


def _validate_grind_resumed(_payload: RawEvent) -> list[str]:
    return []


def _validate_grind_finished(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "summary")
    return errors


def _validate_lane_standing_down(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "lane")
    return errors


def _validate_lane_handover(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "lane")
    _require_str(errors, payload, "from_agent")
    _require_str(errors, payload, "to_agent")
    _require_str(errors, payload, "reason")
    _optional_str(errors, payload, "to_model")
    _optional_str(errors, payload, "to_effort")
    return errors


def _validate_item_started(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "item")
    return errors


def _validate_pr_opened(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "item")
    _require(errors, _is_int(payload, "pr"), "pr is required and must be an integer")
    _optional_str(errors, payload, "url")
    return errors


def _validate_review_round(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "item")
    _require(
        errors,
        _is_enum(payload, "kind", _REVIEW_KINDS),
        "kind must be one of codex|copilot|ralf|human",
    )
    _require(errors, _is_int(payload, "round"), "round is required and must be an integer")
    _require_str(errors, payload, "head_sha")
    _optional_str(errors, payload, "detail")
    return errors


def _validate_findings(errors: list[str], payload: RawEvent) -> None:
    if "findings" not in payload:
        return
    findings = payload.get("findings")
    if not isinstance(findings, list):
        errors.append("findings must be an array when present")
        return
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            errors.append(f"findings[{index}] must be an object")
            continue
        if not _is_str(finding, "severity"):
            errors.append(f"findings[{index}].severity is required and must be a non-empty string")
        if not _is_str(finding, "summary"):
            errors.append(f"findings[{index}].summary is required and must be a non-empty string")
        if not _is_enum(finding, "disposition", _DISPOSITIONS):
            errors.append(
                f"findings[{index}].disposition must be one of fixed|wont-fix|deferred|escalated"
            )


def _validate_review_verdict(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "item")
    _require(
        errors,
        _is_enum(payload, "kind", _REVIEW_KINDS),
        "kind must be one of codex|copilot|ralf|human",
    )
    _require(errors, _is_int(payload, "round"), "round is required and must be an integer")
    _require_str(errors, payload, "head_sha")
    _require(
        errors,
        _is_enum(payload, "verdict", _VERDICTS),
        "verdict must be one of clean|findings|stalemate",
    )
    _validate_findings(errors, payload)
    return errors


def _validate_pr_closed(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "item")
    _require(errors, _is_int(payload, "pr"), "pr is required and must be an integer")
    _require_str(errors, payload, "reason")
    _require(
        errors,
        _is_enum(payload, "next", _PR_CLOSED_NEXT),
        "next must be one of in-progress|queued|parked",
    )
    return errors


def _validate_item_blocked(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "item")
    _require(
        errors, _is_list_of_str(payload, "on"), "on is required and must be an array of strings"
    )
    _optional_str(errors, payload, "note")
    return errors


def _validate_item_waiting_human(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "item")
    _require_str(errors, payload, "why")
    return errors


def _validate_item_resumed(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "item")
    _require_str(errors, payload, "ruling")
    return errors


def _validate_item_merged(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "item")
    _require(errors, _is_int(payload, "pr"), "pr is required and must be an integer")
    _require_str(errors, payload, "sha")
    return errors


def _validate_item_done(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "item")
    return errors


def _validate_item_parked(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "item")
    _require(
        errors,
        _is_enum(payload, "reason", _PARK_REASONS),
        f"reason must be one of {_PARK_REASONS_HELP}",
    )
    _require_str(errors, payload, "note")
    return errors


def _validate_item_enqueued(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "item")
    _require_str(errors, payload, "lane")
    if "position" in payload:
        _require(errors, _is_int(payload, "position"), "position must be an integer when present")
    return errors


def _validate_discovered_work(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "item")
    _require_str(errors, payload, "description")
    _require_str(errors, payload, "source")
    _require_str(errors, payload, "rationale")
    _optional_str(errors, payload, "bead")
    disposition = payload.get("disposition")
    if disposition not in _WORK_DISPOSITIONS:
        errors.append("disposition must be one of parked|enqueued")
        return errors
    if disposition == "parked":
        _require(
            errors,
            _is_enum(payload, "reason", _PARK_REASONS),
            f"reason is required when disposition is parked, and must be one of "
            f"{_PARK_REASONS_HELP}",
        )
    else:
        _require_str(errors, payload, "lane")
    return errors


def _validate_observation(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require(
        errors,
        _is_enum(payload, "level", _OBSERVATION_LEVELS),
        "level must be one of INFO|WARN|ERROR|LESSON",
    )
    _require_str(errors, payload, "message")
    _optional_str(errors, payload, "item")
    _optional_str(errors, payload, "lane")
    return errors


def _validate_attention_raised(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require_str(errors, payload, "text")
    return errors


def _validate_attention_cleared(payload: RawEvent) -> list[str]:
    errors: list[str] = []
    _require(
        errors,
        _is_str(payload, "text") or _is_str(payload, "item"),
        "attention_cleared requires a text or item to match",
    )
    return errors


_VALIDATORS: dict[str, Validator] = {
    "grind_created": _validate_grind_created,
    "grind_paused": _validate_grind_paused,
    "grind_resumed": _validate_grind_resumed,
    "grind_finished": _validate_grind_finished,
    "lane_standing_down": _validate_lane_standing_down,
    "lane_handover": _validate_lane_handover,
    "item_started": _validate_item_started,
    "pr_opened": _validate_pr_opened,
    "review_round": _validate_review_round,
    "review_verdict": _validate_review_verdict,
    "pr_closed": _validate_pr_closed,
    "item_blocked": _validate_item_blocked,
    "item_waiting_human": _validate_item_waiting_human,
    "item_resumed": _validate_item_resumed,
    "item_merged": _validate_item_merged,
    "item_done": _validate_item_done,
    "item_parked": _validate_item_parked,
    "item_enqueued": _validate_item_enqueued,
    "discovered_work": _validate_discovered_work,
    "observation": _validate_observation,
    "attention_raised": _validate_attention_raised,
    "attention_cleared": _validate_attention_cleared,
}


def validate_payload(event_type: str, payload: RawEvent) -> list[str]:
    """Shape-validate `payload` for `event_type`, returning error strings (empty = valid).

    An unrecognized `event_type` has no validator -- it is forward-compatible
    per spec ("unknown types append fine and fold as anomalies"), so shape is
    never checked and this always returns `[]` for one.
    """
    validator = _VALIDATORS.get(event_type)
    if validator is None:
        return []
    return validator(payload)
