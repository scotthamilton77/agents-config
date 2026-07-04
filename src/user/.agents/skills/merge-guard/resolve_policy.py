#!/usr/bin/env python3
"""resolve_policy.py — resolve the PR review/merge policy for a repository.

Turns project-config.toml ([review-expectations] + [merge-policy]) and
per-bead override labels into one validated policy JSON on stdout.

Contract: docs/architecture/review-merge-policy/design.md ("Resolver contract").
Precedence: per-bead label > project config > built-in default.

Usage:
    resolve_policy.py --project-config <path/to/project-config.toml> [--labels "a,b,c"]

Exit codes:
    0 — resolved; policy JSON on stdout
    1 — invalid config/labels (PolicyError; message on stderr)
    2 — unexpected/environment error (e.g. unreadable config path;
        concise one-line message on stderr, never a raw traceback)

Stdlib only (tomllib requires Python >= 3.11). No third-party deps — this
file deploys into user space with the merge-guard skill.
"""
from __future__ import annotations

import argparse
import json
import sys

if sys.version_info < (3, 11):  # tomllib is 3.11+; fail loud, never degrade
    sys.stderr.write("error: resolve_policy.py requires Python >= 3.11 (tomllib)\n")
    sys.exit(2)

import re
import tomllib
from dataclasses import asdict, dataclass, replace


class PolicyError(Exception):
    """Invalid configuration or labels. Never silently defaulted."""


@dataclass(frozen=True)
class ReviewMergePolicy:
    # Axis 1 — review expectation (drives polling)
    bot_review_expected: bool
    bot_reviewers: list[str]
    bot_inactivity_timeout_seconds: int
    human_approvers_required: int
    human_review_timeout_seconds: int | None
    # Axis 2 — merge authorization
    merge_authorization: str  # "never" | "explicit" | "rule-based"
    merge_rule: str | None    # "bot-quiescence" | "human-approvals" | "agent-ruling"
    allow_force_after_bot_timeout: bool  # opt-in escape hatch, bot-quiescence only


DEFAULTS = ReviewMergePolicy(
    bot_review_expected=True,
    bot_reviewers=["Copilot", "copilot-pull-request-reviewer[bot]"],
    bot_inactivity_timeout_seconds=1200,  # "20m"
    human_approvers_required=0,
    human_review_timeout_seconds=None,    # wait indefinitely
    merge_authorization="explicit",       # today's law, unchanged
    merge_rule=None,
    allow_force_after_bot_timeout=False,
)


_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600}

REVIEW_EXPECTATION_KEYS = {
    "bot-review-expected", "bot-reviewers", "bot-inactivity-timeout",
    "human-approvers-required", "human-review-timeout",
}
MERGE_POLICY_KEYS = {"merge-authorization", "merge-rule", "allow-force-after-bot-timeout"}


def parse_duration(value: object, key: str) -> int:
    """'20m' / '48h' / '90s' / bare int (seconds) -> seconds. Raises PolicyError."""
    if isinstance(value, bool):  # bool is an int subclass; reject explicitly
        raise PolicyError(f"{key}: expected duration, got boolean")
    if isinstance(value, int):
        if value < 0:
            raise PolicyError(f"{key}: negative duration {value}")
        return value
    if isinstance(value, str) and len(value) >= 2 and value[:-1].isdigit() \
            and value[-1] in _DURATION_UNITS:
        return int(value[:-1]) * _DURATION_UNITS[value[-1]]
    raise PolicyError(f"{key}: invalid duration {value!r} (use e.g. \"20m\", \"48h\", or seconds as int)")


def _check_keys(section: dict, allowed: set[str], name: str) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise PolicyError(f"[{name}]: unknown key(s) {', '.join(unknown)} (allowed: {', '.join(sorted(allowed))})")


def _typed(section: dict, key: str, kind: type, default):
    if key not in section:
        return default
    value = section[key]
    if kind is bool and not isinstance(value, bool):
        raise PolicyError(f"{key}: expected boolean, got {type(value).__name__}")
    if kind is int and (isinstance(value, bool) or not isinstance(value, int)):
        raise PolicyError(f"{key}: expected integer, got {type(value).__name__}")
    if kind is list and not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
        raise PolicyError(f"{key}: expected list of strings")
    if kind is str and not isinstance(value, str):
        raise PolicyError(f"{key}: expected string, got {type(value).__name__}")
    return value


MERGE_AUTHORIZATIONS = {"never", "explicit", "rule-based"}
MERGE_RULES = {"bot-quiescence", "human-approvals", "agent-ruling"}

_HUMAN_LABEL = re.compile(r"^review-exit-human-approvers-(.*)$")
_COPILOT_LABEL = "review-exit-copilot-only"


def apply_labels(policy: ReviewMergePolicy, labels: list[str]) -> ReviewMergePolicy:
    """Per-bead overrides: label > config. Unrelated labels are ignored."""
    copilot_only = _COPILOT_LABEL in labels
    counts = []
    for label in labels:
        match = _HUMAN_LABEL.match(label)
        if match:
            # isdecimal() (not isdigit()) rejects both empty <n> and unicode
            # digits (e.g. superscript "²") that isdigit() accepts but
            # int() cannot parse.
            if not match.group(1).isdecimal():
                raise PolicyError(
                    f"label {label!r}: <n> must be a non-negative integer")
            counts.append(int(match.group(1)))
    if copilot_only and counts:
        raise PolicyError(
            "labels review-exit-copilot-only and review-exit-human-approvers-<n> are mutually exclusive")
    if len(counts) > 1:
        raise PolicyError("multiple review-exit-human-approvers-<n> labels present")
    if copilot_only:
        # Purpose is to wait for the bot; must not degrade to no-review.
        return replace(policy, bot_review_expected=True, human_approvers_required=0)
    if counts:
        return replace(policy, human_approvers_required=counts[0])
    return policy


def validate(policy: ReviewMergePolicy) -> None:
    """Value-domain + combination validation. Raises PolicyError; never degrades."""
    if policy.human_approvers_required < 0:
        raise PolicyError(
            f"human-approvers-required: must be >= 0, got {policy.human_approvers_required}")
    if policy.merge_authorization not in MERGE_AUTHORIZATIONS:
        raise PolicyError(
            f"merge-authorization: {policy.merge_authorization!r} not in {sorted(MERGE_AUTHORIZATIONS)}")
    if policy.merge_rule is not None and policy.merge_rule not in MERGE_RULES:
        raise PolicyError(f"merge-rule: {policy.merge_rule!r} not in {sorted(MERGE_RULES)}")
    if policy.merge_authorization == "rule-based" and policy.merge_rule is None:
        raise PolicyError("merge-authorization=rule-based requires a merge-rule")
    if policy.merge_authorization != "rule-based" and policy.merge_rule is not None:
        raise PolicyError("merge-rule is only valid with merge-authorization=rule-based")
    if policy.merge_rule == "human-approvals" and policy.human_approvers_required < 1:
        raise PolicyError(
            "merge-rule=human-approvals requires human-approvers-required >= 1 "
            "(a zero-approval rule is vacuously true and would authorize an unreviewed merge)")
    if policy.merge_rule == "bot-quiescence":
        if not policy.bot_reviewers:
            raise PolicyError("merge-rule=bot-quiescence requires a non-empty bot-reviewers allowlist")
        if not policy.bot_review_expected:
            raise PolicyError("merge-rule=bot-quiescence requires bot-review-expected = true")
    if policy.merge_rule == "agent-ruling":
        raise PolicyError("merge-rule=agent-ruling is design-reserved and not yet implemented")
    if policy.allow_force_after_bot_timeout and policy.merge_rule != "bot-quiescence":
        raise PolicyError(
            "allow-force-after-bot-timeout is only valid with merge-rule=bot-quiescence")


def resolve_policy(project_config: dict, bead_labels: list[str]) -> ReviewMergePolicy:
    """Resolve config + labels into a validated policy. Raises PolicyError."""
    expect = project_config.get("review-expectations", {})
    merge = project_config.get("merge-policy", {})
    if not isinstance(expect, dict):
        raise PolicyError("[review-expectations] must be a table")
    if not isinstance(merge, dict):
        raise PolicyError("[merge-policy] must be a table")
    _check_keys(expect, REVIEW_EXPECTATION_KEYS, "review-expectations")
    _check_keys(merge, MERGE_POLICY_KEYS, "merge-policy")

    bot_timeout = (parse_duration(expect["bot-inactivity-timeout"], "bot-inactivity-timeout")
                   if "bot-inactivity-timeout" in expect
                   else DEFAULTS.bot_inactivity_timeout_seconds)
    human_timeout = (parse_duration(expect["human-review-timeout"], "human-review-timeout")
                     if "human-review-timeout" in expect
                     else DEFAULTS.human_review_timeout_seconds)

    policy = ReviewMergePolicy(
        bot_review_expected=_typed(expect, "bot-review-expected", bool, DEFAULTS.bot_review_expected),
        bot_reviewers=_typed(expect, "bot-reviewers", list, DEFAULTS.bot_reviewers),
        bot_inactivity_timeout_seconds=bot_timeout,
        human_approvers_required=_typed(expect, "human-approvers-required", int, DEFAULTS.human_approvers_required),
        human_review_timeout_seconds=human_timeout,
        merge_authorization=_typed(merge, "merge-authorization", str, DEFAULTS.merge_authorization),
        merge_rule=_typed(merge, "merge-rule", str, DEFAULTS.merge_rule),
        allow_force_after_bot_timeout=_typed(
            merge, "allow-force-after-bot-timeout", bool,
            DEFAULTS.allow_force_after_bot_timeout),
    )
    policy = apply_labels(policy, bead_labels)
    validate(policy)
    return policy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-config", required=True,
                        help="Path to project-config.toml (absent file = all defaults)")
    parser.add_argument("--labels", default="",
                        help="Comma-separated bead labels (per-bead overrides)")
    args = parser.parse_args()

    try:
        config: dict = {}
        try:
            with open(args.project_config, "rb") as fh:
                config = tomllib.load(fh)
        except FileNotFoundError:
            config = {}  # absent file = absent sections = defaults
        except tomllib.TOMLDecodeError as exc:
            raise PolicyError(f"unparseable {args.project_config}: {exc}") from exc

        labels = [lb.strip() for lb in args.labels.split(",") if lb.strip()]
        policy = resolve_policy(config, labels)
        json.dump(asdict(policy), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    except PolicyError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    except Exception as exc:  # noqa: BLE001 - deliberate boundary catch-all
        # Unexpected/environment error (e.g. --project-config points at a
        # directory, or a permissions/encoding failure) -> exit 2, one
        # concise line, no raw traceback. PolicyError (exit 1) is handled
        # above and never reaches here.
        sys.stderr.write(f"error: unexpected {type(exc).__name__}: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
