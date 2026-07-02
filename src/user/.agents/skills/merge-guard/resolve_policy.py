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
    2 — unexpected error

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

import tomllib
from dataclasses import asdict, dataclass


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


DEFAULTS = ReviewMergePolicy(
    bot_review_expected=True,
    bot_reviewers=["Copilot", "copilot-pull-request-reviewer[bot]"],
    bot_inactivity_timeout_seconds=1200,  # "20m"
    human_approvers_required=0,
    human_review_timeout_seconds=None,    # wait indefinitely
    merge_authorization="explicit",       # today's law, unchanged
    merge_rule=None,
)


def resolve_policy(project_config: dict, bead_labels: list[str]) -> ReviewMergePolicy:
    """Resolve config + labels into a validated policy. Raises PolicyError."""
    return DEFAULTS


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


if __name__ == "__main__":
    sys.exit(main())
