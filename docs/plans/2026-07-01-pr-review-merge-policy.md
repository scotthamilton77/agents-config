# PR Review / Merge Policy Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the two-axis PR review/merge policy from `docs/specs/2026-06-30-pr-review-merge-policy.md` — a tested policy resolver, a rebuilt eligibility gate, and live wiring so a repo's config (not a hardcoded law) decides who reviews and who merges.

**Architecture:** Axis 1 (review expectation) drives polling; Axis 2 (merge authorization: `never`/`explicit`/`rule-based`) decides who presses merge; between them a no-blocker eligibility floor is computed live at merge time. A stdlib-only Python resolver (`resolve_policy.py`, bundled in the merge-guard skill) turns `project-config.toml` + bead labels into one typed policy JSON; `check-merge-eligibility.sh` is rebuilt to compute the floor + positive facts against that policy; merge-guard SKILL.md applies Axis 2 to the script's output. Scripts own determinism, skills own judgment (M0).

**Tech Stack:** Bash + jq + `gh` (eligibility gate, PATH-shim `gh` stub for tests); Python ≥3.11 stdlib only — `tomllib`, `unittest` (resolver; no uv, no PEP-723, matching existing skill-bundled Python); Markdown (SKILL.md wiring, HLD, law amendment).

**Execution context:** worktree `.claude/worktrees/wgclw14-review-merge-policy`, branch `worktree-wgclw14-review-merge-policy`, bead `agents-config-wgclw.14`. Spec: `docs/specs/2026-06-30-pr-review-merge-policy.md` (approved 2026-07-01).

---

## Ground truth (verified 2026-07-01 — trust these over assumptions)

- **Test harness**: `project-config.toml` `[gates].test` runs every `*_test.sh` under `src/user/.agents/skills` + `src/user/.claude/hooks`. There is NO Python test harness outside `packages/` and NO pytest for skills. New Python tests must be wrapped in a `*_test.sh` file to be discovered. Run a single test file directly: `bash src/user/.agents/skills/merge-guard/<name>_test.sh`.
- **Skill-bundled Python precedent**: `whats-next/collect.py` — `#!/usr/bin/env python3`, stdlib only, invoked as `python3 "${CLAUDE_SKILL_DIR}/collect.py"`. `optimize-my-skill/scripts/*.py` uses snake_case filenames. No PEP-723, no `uv run`, no requirements files anywhere in skills.
- **Installer**: copies each skill dir verbatim (`shutil.copytree`); `.installignore` matches only direct children of namespace dirs, so nested `*.py` / `*_test.sh` inside a skill deploy fine. Cross-skill relative references exist today only for `.md` docs (e.g. `../wait-for-pr-comments/references/handling-feedback.md`) — this plan adds the first cross-skill *script* reference (`../merge-guard/resolve_policy.py`), mechanically identical.
- **`check-merge-eligibility.sh` today**: 263 lines; REST-only; exit 0/1/2/3; Copilot matched by substring `test("copilot"; "i")`; "review complete" = state `COMMENTED` only; Check 3 counts top-level inline comments vs `--comments-seen`. Its `_test.sh` uses a PATH-shim `gh` stub with per-endpoint canned JSON (`FIXTURE_*` env vars) — extend that pattern.
- **Inventory (wait-for-pr-comments)**: lives at `~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha12>.json` (12-char head SHA), `schema_version: 1`. Item kinds `review_thread` / `review_summary` / `issue_comment`; `review_summary` items carry NO GitHub IDs (guard 3 in `validate-inventory.sh:106-108` forbids them). Deleted on success at Phase 9 (`A/SKILL.md:449-459` `rm -f`) and silently unlinked for completed prior runs in Phase 1 concurrency handling (`A/SKILL.md:863-867`). Pruning >30 days lives in `write-inventory.sh:77-84` and stays.
- **`review_summary` has NO script producer**: `poll-copilot-review.sh` returns raw REST `reviews[]` (each with numeric `id`, `node_id`, `user.login`, `body`, `state`, `submitted_at`, `commit_id`); the Phase-3 orchestrator hand-builds `review_summary` items from them. (`A/SKILL.md:202`'s "GraphQL `reviews.nodes`" claim is unimplemented prose.)
- **Replies**: `post-replies.sh` posts via `gh api --method POST` and **discards the response JSON** (`>/dev/null`); the `.posted` sidecar records the replied-TO comment id (idempotency), never the created reply's id. `resolve-threads.sh` uses GraphQL `resolveReviewThread`.
- **The merge law lives in** (verbatim locations): `src/user/.agents/INSTRUCTIONS.md.template:59` ("No unauthorized merges" constraint), `src/user/.agents/rules/completion-gate.md:15` (HARD STOP), `merge-guard/SKILL.md:71-93`, `monitor-pr/SKILL.md:10-13` + `:99-101`, `reply-and-resolve-pr-threads/SKILL.md:28`. **`delivery.md` does NOT exist in src/** (archive only) — the spec's reference to "the delivery rule" is stale; amend the five real locations.
- **Old config keys have zero live code consumers** — only `project-config.toml:74-79`, the spec, archive, and bead JSONL data records.
- **prgroom `status --json` envelope**: `merge_gates.{phase_is_quiesced,last_error_clear,no_blocker_items,human_review_satisfied}` + `auto_merge_eligible` (never consume the rollup) + `human_review`. It does NOT expose per-item dispositions, so the spec's "or prgroom's persisted item disposition" alternative for non-thread triage is not implementable from the envelope — the durable-inventory union is the implemented source (spec's "or" permits this; `no_blocker_items` is still consumed as the separate internal-blocker atom).

## Spec-deviation ledger (decided here, documented for review)

1. **Law amendment targets** — spec names "the delivery and completion-gate rules"; `delivery.md` has no source file. Targets adjusted to the five real locations above. The orphaned *installed* `~/.claude/rules/delivery.md` is filed as discovered work (Task 22), not resurrected.
2. **Default `bot-reviewers`** — spec says "the implementation resolves the precise login". Decided: `["Copilot", "copilot-pull-request-reviewer[bot]"]` — two exact literals (GitHub surfaces Copilot's reviewer identity as either depending on API), still no substring matching. Operators verify theirs via `gh api repos/<o>/<r>/pulls/<n>/reviews --jq '.[].user.login'`.
3. **Timeout defaults** — spec doesn't pin values. Decided: `bot-inactivity-timeout = "20m"`, `human-review-timeout` unset (= wait indefinitely).
4. **Exit-code redesign** — old 0/1/2/3 becomes 0 (eligible) / 1 (blocked — JSON `blockers[]` carries every reason) / 3 (error). The JSON is the interface; merge-guard SKILL.md is rewritten in the same plan.
5. **`--comments-seen` retired** — the count-vs-seen heuristic (old Check 3) is superseded by the live unresolved-threads + untriaged-non-thread-feedback gates, which check actual triage state instead of a count the agent self-reports.
6. **Poll-side Copilot substring filter** (`poll-copilot-review.sh` `COPILOT_REVIEW_FILTER`) stays permissive — Axis 1 polling is detection, not a trust boundary; worst case it waits for an untrusted bot's review, which then gets triaged. The trust boundary (exact identity) is enforced where merges happen. Filed as optional follow-up (Task 22).
7. **Guard numbering** — the same rule is "guard 3" in `validate-inventory.sh` (authoritative) and "#4" in A/SKILL.md's narrative list. This plan edits by script numbering and does NOT fix the narrative off-by-one (minimal edits; filed as discovered work).

## File structure

```
docs/architecture/review-merge-policy/
  index.md                                  # NEW — orientation (Task 1)
  design.md                                 # NEW — two-axis model, eligibility, resolver contract, rules (Task 1)
src/user/.agents/skills/merge-guard/
  resolve_policy.py                         # NEW — policy resolver CLI, stdlib-only (Tasks 2-5)
  resolve_policy_test.py                    # NEW — unittest suite (Tasks 2-5)
  resolve_policy_test.sh                    # NEW — thin wrapper so [gates].test discovers the Python tests (Task 2)
  check-merge-eligibility.sh                # REWRITE — policy-driven floor + facts (Tasks 7-13, 17-18)
  check-merge-eligibility_test.sh           # EXTEND — stub grows GraphQL/branch-protection/check-runs fixtures (Tasks 7-13, 17-18)
  SKILL.md                                  # REWRITE — Axis 2 branching, force-merge exception (Task 19)
src/user/.agents/skills/wait-for-pr-comments/
  SKILL.md                                  # EDIT — Phase-1 policy entry, retention, review_id schema, concurrency table (Tasks 14-15, 20)
  validate-inventory.sh                     # EDIT — guard 3 relaxation (Task 15)
  validate-inventory_test.sh                # EXTEND — guard 3 cases (Task 15)
src/user/.agents/skills/reply-and-resolve-pr-threads/
  post-replies.sh                           # EDIT — capture created reply id → posted_reply_id (Task 16)
  post-replies_test.sh                      # EXTEND — reply-id recording case (Task 16)
  SKILL.md                                  # EDIT — MERGE PROHIBITION pointer (Task 21)
src/user/.agents/skills/monitor-pr/SKILL.md # EDIT — law pointer x2 (Task 21)
src/user/.agents/INSTRUCTIONS.md.template   # EDIT — constraint rewrite (Task 21)
src/user/.agents/rules/completion-gate.md   # EDIT — HARD STOP wording (Task 21)
project-config.toml                         # EDIT — [review-expectations] + [merge-policy] replace [review-requirements] (Task 6)
```

Dependency order: Task 1 (docs) → 2-5 (resolver) → 6 (toml) → 7-13 (eligibility gates that need only GitHub) → 14-16 (inventory durability + reply ids — prerequisites for the non-thread gate) → 17-18 (non-thread gate + final assembly) → 19-20 (skill wiring) → 21 (law) → 22 (verify + housekeeping).

---

### Task 1: HLD — `docs/architecture/review-merge-policy/`

**Files:**
- Create: `docs/architecture/review-merge-policy/index.md`
- Create: `docs/architecture/review-merge-policy/design.md`

No code — evergreen reference distilled from the spec (undated filenames per `docs/architecture/` conventions). The spec remains the point-in-time rationale; design.md is the current-state contract that `project-config.toml` will cite instead of the quarantined `bead-pipeline-architecture.md §5.1`.

- [x] **Step 1: Write `index.md`**

```markdown
# Review / Merge Policy — architecture

High-level design for the two-axis PR review/merge policy subsystem: what
reviews a repo expects (Axis 1, drives polling) and who is authorized to
merge (Axis 2), joined by a live no-blocker eligibility floor.

- [design.md](design.md) — the policy model: axes, merge-rule vocabulary,
  eligibility predicate, freshness invariant, resolver contract, config schema.

Source spec: `docs/specs/2026-06-30-pr-review-merge-policy.md` (dated
rationale; this folder is the evergreen contract).

Consumers: `merge-guard` (enforcement point), `wait-for-pr-comments`
(polling), `resolve_policy.py` (resolver, bundled in merge-guard).
```

- [x] **Step 2: Write `design.md`**

Distill these spec sections, in this order, adapting prose to present tense (this is the current contract, not a proposal). Copy the tables verbatim from the spec; do not invent new fields:

1. `## Core model` — the two axes + eligibility definition (spec "Core model: two orthogonal axes", including the merge iff `eligible AND authorized` invariant and the force-merge carve-out sentence).
2. `## Axis 1 — Review expectation` — the 5-setting table (spec Axis 1 table) + the "timeout means stop waiting, not satisfied" paragraph.
3. `## Axis 2 — Merge authorization` — the 3-value table + merge-rule vocabulary table (`bot-quiescence`, `human-approvals`, `agent-ruling` marked design-reserved) + the AI-reviewer-vs-merge-judge distinction + the no-zero-review-auto-merge safety property.
4. `## Eligibility predicate` — the blocker-fact table (8 rows) + the prgroom-sourcing caveats.
5. `## Freshness invariant` — the 3 numbered points (head-binding positive facts only, recompute live, `--match-head-commit`).
6. `## Machine-checkable predicates` — CI-green and bot clean-review definitions verbatim.
7. `## Resolver contract` — the `resolve_policy` signature + `ReviewMergePolicy` shape + validation rules + precedence (`per-bead label > project config > built-in default`) + built-in defaults, **updated with the decided values from this plan's deviation ledger** (dual Copilot logins, 20m bot timeout, indefinite human timeout).
8. `## Config schema` — the `[review-expectations]` / `[merge-policy]` TOML keys with types and defaults (matching Task 6's file exactly), plus the two per-bead override labels.
9. `## Consumers` — one paragraph each: merge-guard (Axis 2 enforcement), wait-for-pr-comments (Axis 1 polling + durable triage inventories), reply-and-resolve-pr-threads (posted-reply-ID recording).

- [x] **Step 3: Commit**

```bash
git add docs/architecture/review-merge-policy/
git commit -m "docs(architecture): review-merge-policy HLD — two-axis model, eligibility, resolver contract (wgclw.14)"
```

---

### Task 2: Resolver scaffold + built-in defaults

**Files:**
- Create: `src/user/.agents/skills/merge-guard/resolve_policy.py`
- Create: `src/user/.agents/skills/merge-guard/resolve_policy_test.py`
- Create: `src/user/.agents/skills/merge-guard/resolve_policy_test.sh`

Behavior under test: **with no config file and no labels, the resolver emits the built-in default policy as JSON on stdout, exit 0.**

- [x] **Step 1: Write the failing test**

`resolve_policy_test.py`:

```python
#!/usr/bin/env python3
"""Unit tests for resolve_policy.py (stdlib unittest; run via resolve_policy_test.sh)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "resolve_policy.py")


def run_resolver(*args):
    """Run the resolver CLI; return (exit_code, stdout, stderr)."""
    proc = subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True, text=True, timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


class TestDefaults(unittest.TestCase):
    def test_no_config_file_yields_builtin_defaults(self):
        missing = os.path.join(tempfile.mkdtemp(), "absent.toml")
        code, out, err = run_resolver("--project-config", missing)
        self.assertEqual(code, 0, err)
        policy = json.loads(out)
        self.assertEqual(policy, {
            "bot_review_expected": True,
            "bot_reviewers": ["Copilot", "copilot-pull-request-reviewer[bot]"],
            "bot_inactivity_timeout_seconds": 1200,
            "human_approvers_required": 0,
            "human_review_timeout_seconds": None,
            "merge_authorization": "explicit",
            "merge_rule": None,
        })


if __name__ == "__main__":
    unittest.main()
```

`resolve_policy_test.sh` (the wrapper that makes `[gates].test` discover the Python suite):

```bash
#!/usr/bin/env bash
# Smoke wrapper: runs the Python unittest suite for resolve_policy.py.
# The [gates].test glob only discovers *_test.sh, hence this shim.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "[resolve_policy_test]"

if ! command -v python3 >/dev/null 2>&1; then
    echo "  SKIP: python3 not found on PATH" >&2
    exit 0
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "  SKIP: python3 < 3.11 (tomllib unavailable)" >&2
    exit 0
fi

python3 "$HERE/resolve_policy_test.py" -v
```

```bash
chmod +x src/user/.agents/skills/merge-guard/resolve_policy_test.sh
```

- [x] **Step 2: Run test to verify it fails**

Run: `bash src/user/.agents/skills/merge-guard/resolve_policy_test.sh`
Expected: FAIL — `resolve_policy.py` does not exist (subprocess exits nonzero / FileNotFoundError).

- [x] **Step 3: Write minimal implementation**

`resolve_policy.py`:

```python
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
```

```bash
chmod +x src/user/.agents/skills/merge-guard/resolve_policy.py
```

- [x] **Step 4: Run test to verify it passes**

Run: `bash src/user/.agents/skills/merge-guard/resolve_policy_test.sh`
Expected: PASS (`test_no_config_file_yields_builtin_defaults ... ok`).

- [x] **Step 5: Commit**

```bash
git add src/user/.agents/skills/merge-guard/resolve_policy.py src/user/.agents/skills/merge-guard/resolve_policy_test.py src/user/.agents/skills/merge-guard/resolve_policy_test.sh
git commit -m "feat(merge-guard): resolve_policy.py scaffold — built-in default policy (wgclw.14)"
```

---

### Task 3: Resolver — config-section parsing

Behavior: **`[review-expectations]` and `[merge-policy]` values override defaults; unknown keys and bad types fail loud.**

**Files:**
- Modify: `src/user/.agents/skills/merge-guard/resolve_policy.py`
- Modify: `src/user/.agents/skills/merge-guard/resolve_policy_test.py`

- [x] **Step 1: Write the failing tests** (append to `resolve_policy_test.py`; keep `run_resolver` helper)

```python
def write_toml(content: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".toml")
    with os.fdopen(fd, "w") as fh:
        fh.write(content)
    return path


class TestConfigParsing(unittest.TestCase):
    def test_config_values_override_defaults(self):
        path = write_toml(
            '[review-expectations]\n'
            'bot-review-expected = false\n'
            'bot-reviewers = ["my-bot[bot]"]\n'
            'bot-inactivity-timeout = "45m"\n'
            'human-approvers-required = 2\n'
            'human-review-timeout = "48h"\n'
            '[merge-policy]\n'
            'merge-authorization = "never"\n'
        )
        code, out, err = run_resolver("--project-config", path)
        self.assertEqual(code, 0, err)
        policy = json.loads(out)
        self.assertFalse(policy["bot_review_expected"])
        self.assertEqual(policy["bot_reviewers"], ["my-bot[bot]"])
        self.assertEqual(policy["bot_inactivity_timeout_seconds"], 2700)
        self.assertEqual(policy["human_approvers_required"], 2)
        self.assertEqual(policy["human_review_timeout_seconds"], 172800)
        self.assertEqual(policy["merge_authorization"], "never")

    def test_integer_duration_is_seconds(self):
        path = write_toml('[review-expectations]\nbot-inactivity-timeout = 900\n')
        code, out, _ = run_resolver("--project-config", path)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["bot_inactivity_timeout_seconds"], 900)

    def test_unknown_key_fails_loud(self):
        path = write_toml('[review-expectations]\nbot-reviewer = ["typo"]\n')
        code, _, err = run_resolver("--project-config", path)
        self.assertEqual(code, 1)
        self.assertIn("unknown key", err)
        self.assertIn("bot-reviewer", err)

    def test_bad_duration_fails_loud(self):
        path = write_toml('[review-expectations]\nbot-inactivity-timeout = "soon"\n')
        code, _, err = run_resolver("--project-config", path)
        self.assertEqual(code, 1)
        self.assertIn("duration", err)

    def test_wrong_type_fails_loud(self):
        path = write_toml('[review-expectations]\nbot-review-expected = "yes"\n')
        code, _, err = run_resolver("--project-config", path)
        self.assertEqual(code, 1)

    def test_unparseable_toml_fails_loud_not_defaults(self):
        path = write_toml('[review-expectations\nbroken')
        code, _, err = run_resolver("--project-config", path)
        self.assertEqual(code, 1)
        self.assertIn("unparseable", err)
```

- [x] **Step 2: Run to verify the new tests fail**

Run: `bash src/user/.agents/skills/merge-guard/resolve_policy_test.sh`
Expected: FAIL — override/unknown-key/duration tests fail (resolver still returns pure defaults / exits 0).

- [x] **Step 3: Implement parsing** (replace the stub `resolve_policy` body; add helpers above it)

```python
_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600}

REVIEW_EXPECTATION_KEYS = {
    "bot-review-expected", "bot-reviewers", "bot-inactivity-timeout",
    "human-approvers-required", "human-review-timeout",
}
MERGE_POLICY_KEYS = {"merge-authorization", "merge-rule"}


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

    return ReviewMergePolicy(
        bot_review_expected=_typed(expect, "bot-review-expected", bool, DEFAULTS.bot_review_expected),
        bot_reviewers=_typed(expect, "bot-reviewers", list, DEFAULTS.bot_reviewers),
        bot_inactivity_timeout_seconds=bot_timeout,
        human_approvers_required=_typed(expect, "human-approvers-required", int, DEFAULTS.human_approvers_required),
        human_review_timeout_seconds=human_timeout,
        merge_authorization=_typed(merge, "merge-authorization", str, DEFAULTS.merge_authorization),
        merge_rule=_typed(merge, "merge-rule", str, DEFAULTS.merge_rule),
    )
```

- [x] **Step 4: Run to verify all tests pass**

Run: `bash src/user/.agents/skills/merge-guard/resolve_policy_test.sh`
Expected: PASS (7 tests).

- [x] **Step 5: Commit**

```bash
git add src/user/.agents/skills/merge-guard/resolve_policy.py src/user/.agents/skills/merge-guard/resolve_policy_test.py
git commit -m "feat(merge-guard): resolver parses [review-expectations]/[merge-policy] fail-loud (wgclw.14)"
```

---

### Task 4: Resolver — validation rules

Behavior: **invalid values and invalid combinations are rejected with exit 1 — never a silent fallback to merging or to a different rule.** These are the spec's "Invalid combinations fail loud" rules verbatim.

**Files:**
- Modify: `src/user/.agents/skills/merge-guard/resolve_policy.py`
- Modify: `src/user/.agents/skills/merge-guard/resolve_policy_test.py`

- [x] **Step 1: Write the failing tests** (append)

```python
class TestValidation(unittest.TestCase):
    def _resolve(self, toml_body: str):
        return run_resolver("--project-config", write_toml(toml_body))

    def test_negative_approvers_rejected_in_every_mode(self):
        code, _, err = self._resolve('[review-expectations]\nhuman-approvers-required = -1\n')
        self.assertEqual(code, 1)
        self.assertIn("human-approvers-required", err)

    def test_bad_merge_authorization_enum(self):
        code, _, err = self._resolve('[merge-policy]\nmerge-authorization = "auto"\n')
        self.assertEqual(code, 1)
        self.assertIn("merge-authorization", err)

    def test_rule_based_without_rule(self):
        code, _, err = self._resolve('[merge-policy]\nmerge-authorization = "rule-based"\n')
        self.assertEqual(code, 1)
        self.assertIn("merge-rule", err)

    def test_rule_set_while_not_rule_based(self):
        code, _, err = self._resolve(
            '[merge-policy]\nmerge-authorization = "explicit"\nmerge-rule = "bot-quiescence"\n')
        self.assertEqual(code, 1)

    def test_bad_rule_enum(self):
        code, _, err = self._resolve(
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "vibes"\n')
        self.assertEqual(code, 1)
        self.assertIn("merge-rule", err)

    def test_human_approvals_rule_requires_at_least_one(self):
        code, _, err = self._resolve(
            '[review-expectations]\nhuman-approvers-required = 0\n'
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "human-approvals"\n')
        self.assertEqual(code, 1)
        self.assertIn("human-approvals", err)

    def test_bot_quiescence_requires_trusted_bot(self):
        code, _, err = self._resolve(
            '[review-expectations]\nbot-reviewers = []\n'
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "bot-quiescence"\n')
        self.assertEqual(code, 1)
        self.assertIn("bot-reviewers", err)

    def test_bot_quiescence_requires_bot_expected(self):
        code, _, err = self._resolve(
            '[review-expectations]\nbot-review-expected = false\n'
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "bot-quiescence"\n')
        self.assertEqual(code, 1)
        self.assertIn("bot-review-expected", err)

    def test_agent_ruling_not_implemented(self):
        code, _, err = self._resolve(
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "agent-ruling"\n')
        self.assertEqual(code, 1)
        self.assertIn("not yet implemented", err)

    def test_valid_rule_based_bot_quiescence_resolves(self):
        code, out, err = self._resolve(
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "bot-quiescence"\n')
        self.assertEqual(code, 0, err)
        policy = json.loads(out)
        self.assertEqual(policy["merge_authorization"], "rule-based")
        self.assertEqual(policy["merge_rule"], "bot-quiescence")
```

- [x] **Step 2: Run to verify the new tests fail**

Run: `bash src/user/.agents/skills/merge-guard/resolve_policy_test.sh`
Expected: FAIL — every TestValidation case except `test_valid_rule_based_bot_quiescence_resolves` (no validation yet).

- [x] **Step 3: Implement validation** (add constants + `validate()`; call it at the end of `resolve_policy` before `return` — restructure so the constructed policy is validated then returned)

```python
MERGE_AUTHORIZATIONS = {"never", "explicit", "rule-based"}
MERGE_RULES = {"bot-quiescence", "human-approvals", "agent-ruling"}


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
```

In `resolve_policy`, change the tail to:

```python
    policy = ReviewMergePolicy(
        ...  # unchanged construction from Task 3
    )
    validate(policy)
    return policy
```

- [x] **Step 4: Run to verify all tests pass**

Run: `bash src/user/.agents/skills/merge-guard/resolve_policy_test.sh`
Expected: PASS (17 tests).

- [x] **Step 5: Commit**

```bash
git add src/user/.agents/skills/merge-guard/resolve_policy.py src/user/.agents/skills/merge-guard/resolve_policy_test.py
git commit -m "feat(merge-guard): resolver validation — no vacuous rules, no silent fallbacks (wgclw.14)"
```

---

### Task 5: Resolver — per-bead label overrides

Behavior: **`review-exit-copilot-only` forces `bot_review_expected=true` + `human_approvers_required=0` regardless of config; `review-exit-human-approvers-<n>` sets the count; both together (or a malformed `<n>`) fail loud; validation runs on the post-override policy.**

**Files:**
- Modify: `src/user/.agents/skills/merge-guard/resolve_policy.py`
- Modify: `src/user/.agents/skills/merge-guard/resolve_policy_test.py`

- [x] **Step 1: Write the failing tests** (append)

```python
class TestLabelOverrides(unittest.TestCase):
    def test_copilot_only_overrides_config(self):
        path = write_toml(
            '[review-expectations]\nbot-review-expected = false\nhuman-approvers-required = 3\n')
        code, out, err = run_resolver("--project-config", path,
                                      "--labels", "misc,review-exit-copilot-only")
        self.assertEqual(code, 0, err)
        policy = json.loads(out)
        self.assertTrue(policy["bot_review_expected"])
        self.assertEqual(policy["human_approvers_required"], 0)

    def test_human_approvers_label_sets_count(self):
        code, out, err = run_resolver("--project-config", "/nonexistent.toml",
                                      "--labels", "review-exit-human-approvers-3")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["human_approvers_required"], 3)

    def test_both_labels_conflict(self):
        code, _, err = run_resolver("--project-config", "/nonexistent.toml",
                                    "--labels", "review-exit-copilot-only,review-exit-human-approvers-2")
        self.assertEqual(code, 1)
        self.assertIn("mutually exclusive", err)

    def test_malformed_count_label_rejected(self):
        code, _, err = run_resolver("--project-config", "/nonexistent.toml",
                                    "--labels", "review-exit-human-approvers-lots")
        self.assertEqual(code, 1)

    def test_unrelated_labels_ignored(self):
        code, out, _ = run_resolver("--project-config", "/nonexistent.toml",
                                    "--labels", "install,formula-implement-feature")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["human_approvers_required"], 0)

    def test_label_override_still_validated(self):
        # copilot-only forces humans=0 — combined with human-approvals rule that must fail
        path = write_toml(
            '[review-expectations]\nhuman-approvers-required = 1\n'
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "human-approvals"\n')
        code, _, err = run_resolver("--project-config", path,
                                    "--labels", "review-exit-copilot-only")
        self.assertEqual(code, 1)
        self.assertIn("human-approvals", err)
```

- [x] **Step 2: Run to verify the new tests fail**

Run: `bash src/user/.agents/skills/merge-guard/resolve_policy_test.sh`
Expected: FAIL — all six TestLabelOverrides cases (labels currently unused).

- [x] **Step 3: Implement label handling** (add helper; apply between construction and `validate()` in `resolve_policy` — use `dataclasses.replace`)

```python
import re
from dataclasses import replace  # merge into the existing dataclasses import

_HUMAN_LABEL = re.compile(r"^review-exit-human-approvers-(.+)$")
_COPILOT_LABEL = "review-exit-copilot-only"


def apply_labels(policy: ReviewMergePolicy, labels: list[str]) -> ReviewMergePolicy:
    """Per-bead overrides: label > config. Unrelated labels are ignored."""
    copilot_only = _COPILOT_LABEL in labels
    counts = []
    for label in labels:
        match = _HUMAN_LABEL.match(label)
        if match:
            if not match.group(1).isdigit():
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
```

In `resolve_policy`, the tail becomes:

```python
    policy = ReviewMergePolicy(
        ...  # unchanged construction
    )
    policy = apply_labels(policy, bead_labels)
    validate(policy)
    return policy
```

- [x] **Step 4: Run to verify all tests pass**

Run: `bash src/user/.agents/skills/merge-guard/resolve_policy_test.sh`
Expected: PASS (23 tests).

- [x] **Step 5: Commit**

```bash
git add src/user/.agents/skills/merge-guard/resolve_policy.py src/user/.agents/skills/merge-guard/resolve_policy_test.py
git commit -m "feat(merge-guard): per-bead label overrides with post-override validation (wgclw.14)"
```

---

### Task 6: `project-config.toml` restructure (this repo's own policy)

Behavior: **agents-config's config expresses its intent with the new sections and the resolver accepts it** — `rule-based`/`bot-quiescence` auto-merge on a clean Copilot review, deliberately named.

**Files:**
- Modify: `project-config.toml` (lines 7 and 74-79)
- Modify: `src/user/.agents/skills/merge-guard/resolve_policy_test.py`

- [x] **Step 1: Write the failing test** (append — a fixture mirroring the intended agents-config settings; tests the resolver against the real shape, not the live file)

```python
class TestAgentsConfigSettings(unittest.TestCase):
    def test_agents_config_policy_resolves(self):
        path = write_toml(
            '[review-expectations]\n'
            'bot-review-expected = true\n'
            'bot-reviewers = ["Copilot", "copilot-pull-request-reviewer[bot]"]\n'
            'human-approvers-required = 0\n'
            '[merge-policy]\n'
            'merge-authorization = "rule-based"\n'
            'merge-rule = "bot-quiescence"\n'
        )
        code, out, err = run_resolver("--project-config", path)
        self.assertEqual(code, 0, err)
        policy = json.loads(out)
        self.assertEqual(policy["merge_rule"], "bot-quiescence")
        self.assertEqual(policy["human_approvers_required"], 0)
```

- [x] **Step 2: Run — expect PASS already** (Tasks 3-4 built this behavior; this test pins the repo's own shape against regressions)

Run: `bash src/user/.agents/skills/merge-guard/resolve_policy_test.sh`
Expected: PASS (24 tests). If it fails, a Task 3-4 regression exists — fix before proceeding.

- [x] **Step 3: Replace `[review-requirements]` in `project-config.toml`**

Replace lines 74-79:

```toml
# ---------------------------------------------------------------------------
# [review-requirements] — PR review defaults
# Read by: review-cycle
# ---------------------------------------------------------------------------
[review-requirements]
copilot-required         = true
human-approvers-required = 0     # copilot-only by default; override per bead
```

with:

```toml
# ---------------------------------------------------------------------------
# [review-expectations] — Axis 1: what reviews do we expect (drives polling)
# [merge-policy]        — Axis 2: who is authorized to merge
# Read by: resolve_policy.py (merge-guard skill), consumed by merge-guard and
# wait-for-pr-comments. Schema: docs/architecture/review-merge-policy/design.md
# ---------------------------------------------------------------------------
[review-expectations]
bot-review-expected      = true
bot-reviewers            = ["Copilot", "copilot-pull-request-reviewer[bot]"]  # exact identities, never substrings
human-approvers-required = 0     # override per bead: review-exit-human-approvers-<n>

[merge-policy]
# This repo auto-merges on a clean Copilot review — a deliberate, named choice.
merge-authorization = "rule-based"
merge-rule          = "bot-quiescence"
```

- [x] **Step 4: Fix the stale schema reference at line 7**

Replace:

```toml
# Schema defined in: docs/specs/bead-pipeline-architecture.md §5.1
```

with:

```toml
# Review/merge policy schema: docs/architecture/review-merge-policy/design.md
# (other sections' schema origin: archive/docs/specs/bead-pipeline-architecture.md)
```

- [x] **Step 5: Verify the live file resolves**

Run: `python3 src/user/.agents/skills/merge-guard/resolve_policy.py --project-config project-config.toml`
Expected: exit 0; JSON with `"merge_rule": "bot-quiescence"`.

- [x] **Step 6: Commit**

```bash
git add project-config.toml src/user/.agents/skills/merge-guard/resolve_policy_test.py
git commit -m "feat(config): [review-expectations] + [merge-policy] replace overloaded [review-requirements] (wgclw.14)"
```

---

### Task 7: Eligibility script — new contract skeleton (`--policy-json`, headRefOid, blockers/facts JSON)

The old script's three checks are superseded; this task rewrites the skeleton so every later gate is an append. After this task the script is honest but empty: it fetches PR + head, parses the policy, emits the new JSON with **no blockers yet**, exits 0/3.

**Files:**
- Rewrite: `src/user/.agents/skills/merge-guard/check-merge-eligibility.sh`
- Rewrite: `src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh`

- [x] **Step 1: Rewrite the test file** — full replacement of `check-merge-eligibility_test.sh`:

```bash
#!/usr/bin/env bash
# Smoke test for check-merge-eligibility.sh (policy-driven rewrite).
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/check-merge-eligibility.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAIL=0

assert() {
  if eval "$2"; then
    echo "  ok: $1"
  else
    echo "  FAIL: $1"
    FAIL=1
  fi
}

echo "[check-merge-eligibility_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -40 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --policy-json flag" "grep -q -- '--policy-json' '$SCRIPT'"
assert "no --comments-seen flag (retired)" "! grep -q -- '--comments-seen' '$SCRIPT'"
assert "no substring copilot matching" "! grep -q 'test(\"copilot\"' '$SCRIPT'"

# ── gh + prgroom stubs ────────────────────────────────────────────────────────
STUB_DIR="$TMP/bin"
mkdir -p "$STUB_DIR"
cat > "$STUB_DIR/gh" <<'STUB'
#!/usr/bin/env bash
[ "$1" = "auth" ] && exit 0
if [ "$1" = "api" ]; then
  shift
  if [ "$1" = "graphql" ]; then
    printf '%s' "${FIXTURE_GRAPHQL_THREADS:-{\"data\":{\"repository\":{\"pullRequest\":{\"reviewThreads\":{\"pageInfo\":{\"hasNextPage\":false,\"endCursor\":null},\"nodes\":[]}}}}}}"
    exit 0
  fi
  path="$1"; shift
  filter=""
  while [ $# -gt 0 ]; do
    case "$1" in --jq) filter="$2"; shift 2 ;; *) shift ;; esac
  done
  case "$path" in
    */requested_reviewers)  body="${FIXTURE_REQUESTED_REVIEWERS:-'{\"users\":[],\"teams\":[]}'}" ;;
    */issues/*/events*)     body="${FIXTURE_EVENTS:-[]}" ;;
    */issues/*/comments*)   body="${FIXTURE_ISSUE_COMMENTS:-[]}" ;;
    */pulls/*/reviews*)     body="${FIXTURE_REVIEWS:-[]}" ;;
    */protection/required_status_checks*)
        if [ "${FIXTURE_PROTECTION_404:-1}" = 1 ]; then
          echo "gh: Not Found (HTTP 404)" >&2; exit 1
        fi
        body="${FIXTURE_REQUIRED_CHECKS}" ;;
    */check-runs*)          body="${FIXTURE_CHECK_RUNS:-'{\"check_runs\":[]}'}" ;;
    */commits/*/status*)    body="${FIXTURE_COMMIT_STATUS:-'{\"statuses\":[]}'}" ;;
    */pulls/*)              body="${FIXTURE_PR:-'{\"state\":\"open\",\"head\":{\"sha\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"},\"base\":{\"ref\":\"main\"},\"created_at\":\"2026-01-01T00:00:00Z\"}'}" ;;
    *)                      body='{}' ;;
  esac
  body="${body#\'}"; body="${body%\'}"
  if [ -n "$filter" ]; then printf '%s' "$body" | jq -r "$filter"; else printf '%s' "$body"; fi
  exit 0
fi
exit 0
STUB
chmod +x "$STUB_DIR/gh"
# prgroom stub: emits FIXTURE_PRGROOM when set, else fails (= no prgroom state)
cat > "$STUB_DIR/prgroom" <<'STUB'
#!/usr/bin/env bash
[ -n "${FIXTURE_PRGROOM:-}" ] && { printf '%s' "$FIXTURE_PRGROOM"; exit 0; }
exit 1
STUB
chmod +x "$STUB_DIR/prgroom"

# Isolated HOME so inventory globs never see the real ~/.claude/state
FAKE_HOME="$TMP/home"
mkdir -p "$FAKE_HOME/.claude/state/pr-inventory"

run_script() {  # run_script <policy-json> [env VAR=... pairs]
  local policy="$1"; shift
  env HOME="$FAKE_HOME" PATH="$STUB_DIR:$PATH" "$@" \
    "$SCRIPT" --owner o --repo r --pr 1 --policy-json "$policy" 2>/dev/null
}

# Base policy: nothing expected on Axis 1 → in-flight atom vacuously clear
BASE_POLICY='{"bot_review_expected":false,"bot_reviewers":["trusted-bot[bot]"],"bot_inactivity_timeout_seconds":1200,"human_approvers_required":0,"human_review_timeout_seconds":null,"merge_authorization":"explicit","merge_rule":null}'
HEAD_SHA="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

# ── Arg validation (exit 3) ───────────────────────────────────────────────────
"$SCRIPT" 2>/dev/null;                                       assert "exits 3 with no flags" "[ \$? -eq 3 ]"
"$SCRIPT" --owner o --repo r --pr 1 2>/dev/null;             assert "exits 3 when --policy-json missing" "[ \$? -eq 3 ]"
"$SCRIPT" --owner o --repo r --pr x --policy-json "$BASE_POLICY" 2>/dev/null
assert "exits 3 for non-integer --pr" "[ \$? -eq 3 ]"
"$SCRIPT" --owner o --repo r --pr 1 --policy-json 'not-json' 2>/dev/null
assert "exits 3 for unparseable policy" "[ \$? -eq 3 ]"
"$SCRIPT" --owner o --repo r --pr 1 --policy-json '{}' 2>/dev/null
assert "exits 3 for policy missing required keys" "[ \$? -eq 3 ]"

# ── Skeleton behavior: empty fixtures + nothing expected → eligible ──────────
out=$(run_script "$BASE_POLICY"); rc=$?
assert "empty PR with nothing expected → exit 0" "[ \$rc -eq 0 ]"
assert "status is eligible" "[ \"\$(jq -r '.status' <<<\"\$out\")\" = eligible ]"
assert "head_ref_oid echoed" "[ \"\$(jq -r '.head_ref_oid' <<<\"\$out\")\" = \"$HEAD_SHA\" ]"
assert "blockers array empty" "[ \"\$(jq '.blockers | length' <<<\"\$out\")\" = 0 ]"
assert "merge hint binds head" "jq -r '.merge_command_hint' <<<\"\$out\" | grep -q -- \"--match-head-commit $HEAD_SHA\""

exit $FAIL
```

- [x] **Step 2: Run to verify it fails**

Run: `bash src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh`
Expected: FAIL — old script still accepts `--comments-seen`, lacks `--policy-json`, emits the old JSON shape.

- [x] **Step 3: Rewrite the script skeleton** — full replacement of `check-merge-eligibility.sh`:

```bash
#!/usr/bin/env bash
# check-merge-eligibility.sh — compute the no-blocker eligibility floor and the
# positive review facts for a PR, against a resolved review/merge policy.
#
# Contract: docs/architecture/review-merge-policy/design.md
#   - eligibility = the no-blocker floor (blockers[] empty)
#   - positive facts (bot clean review at head, distinct current approvers) are
#     emitted for merge-rule evaluation in merge-guard SKILL.md — they are
#     facts here, never blockers.
#
# Usage:
#   check-merge-eligibility.sh --owner <o> --repo <r> --pr <n> --policy-json '<json>'
#
# Inputs:
#   --policy-json   resolve_policy.py output (required — run the resolver first)
#
# Exit codes:
#   0 — eligible (no blockers)
#   1 — blocked (see .blockers[] in the JSON)
#   3 — error (auth, invalid args, network, invalid policy)
#
# Stdout (JSON):
#   { "status": "eligible|blocked", "head_ref_oid": "<sha>",
#     "blockers": [ {"code": "...", "details": "..."} ],
#     "facts": { ... }, "merge_command_hint": "gh pr merge <n> --squash --match-head-commit <sha>" }

set -euo pipefail

usage() {
    echo "Usage: $0 --owner <owner> --repo <repo> --pr <pr-number> --policy-json '<json>'" >&2
    exit 3
}

OWNER=""; REPO=""; PR=""; POLICY_JSON=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --owner)       [[ $# -ge 2 ]] || usage; OWNER="${2:-}";       shift 2 ;;
        --repo)        [[ $# -ge 2 ]] || usage; REPO="${2:-}";        shift 2 ;;
        --pr)          [[ $# -ge 2 ]] || usage; PR="${2:-}";          shift 2 ;;
        --policy-json) [[ $# -ge 2 ]] || usage; POLICY_JSON="${2:-}"; shift 2 ;;
        *) usage ;;
    esac
done
[[ -n "$OWNER" && -n "$REPO" && -n "$PR" && -n "$POLICY_JSON" ]] || usage
[[ "$PR" =~ ^[0-9]+$ ]] || { echo "Error: --pr must be a positive integer" >&2; exit 3; }

# ── Policy parsing (fail loud on malformed/missing keys) ─────────────────────
if ! jq -e . >/dev/null 2>&1 <<<"$POLICY_JSON"; then
    echo "Error: --policy-json is not valid JSON" >&2; exit 3
fi
for key in bot_review_expected bot_reviewers bot_inactivity_timeout_seconds \
           human_approvers_required human_review_timeout_seconds \
           merge_authorization merge_rule; do
    jq -e --arg k "$key" 'has($k)' >/dev/null 2>&1 <<<"$POLICY_JSON" || {
        echo "Error: policy JSON missing key: $key (run resolve_policy.py)" >&2; exit 3; }
done
BOT_EXPECTED=$(jq -r '.bot_review_expected' <<<"$POLICY_JSON")
BOT_REVIEWERS=$(jq -c '.bot_reviewers' <<<"$POLICY_JSON")
BOT_TIMEOUT=$(jq -r '.bot_inactivity_timeout_seconds' <<<"$POLICY_JSON")
HUMANS_REQUIRED=$(jq -r '.human_approvers_required' <<<"$POLICY_JSON")
HUMAN_TIMEOUT=$(jq -r '.human_review_timeout_seconds' <<<"$POLICY_JSON")   # "null" = indefinite

# ── Helpers ──────────────────────────────────────────────────────────────────
gh_api() {
    local result exit_code=0
    result=$(gh api "$@" 2>/dev/null) || exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        echo "gh api failed (exit $exit_code): $*" >&2
        return 1
    fi
    printf '%s' "$result"
}

BLOCKERS='[]'
add_blocker() {  # add_blocker <code> <details>
    BLOCKERS=$(jq --arg c "$1" --arg d "$2" '. + [{code: $c, details: $d}]' <<<"$BLOCKERS")
}
FACTS='{}'
set_fact() {     # set_fact <key> <json-value>
    FACTS=$(jq --arg k "$1" --argjson v "$2" '.[$k] = $v' <<<"$FACTS")
}

# ── Pre-flight ───────────────────────────────────────────────────────────────
if ! gh auth status &>/dev/null; then
    echo "Error: gh auth failed — not authenticated" >&2; exit 3
fi
command -v jq &>/dev/null || { echo "Error: jq is required but not found" >&2; exit 3; }

PR_JSON=$(gh_api "repos/${OWNER}/${REPO}/pulls/${PR}") || {
    echo "Error: failed to fetch PR #${PR}" >&2; exit 3; }
pr_state=$(jq -r '.state' <<<"$PR_JSON")
[[ "$pr_state" == "open" ]] || { echo "Error: PR #${PR} is ${pr_state}, not open" >&2; exit 3; }

# The head every positive fact binds to (Freshness invariant pt. 1) and the
# SHA the merge must be issued against (pt. 3).
HEAD_OID=$(jq -r '.head.sha' <<<"$PR_JSON")
[[ -n "$HEAD_OID" && "$HEAD_OID" != "null" ]] || { echo "Error: no head SHA on PR" >&2; exit 3; }
PR_CREATED=$(jq -r '.created_at' <<<"$PR_JSON")
BASE_REF=$(jq -r '.base.ref' <<<"$PR_JSON")

# Shared fetches (each gate filters this once-fetched data)
ALL_REVIEWS=$(gh_api "repos/${OWNER}/${REPO}/pulls/${PR}/reviews?per_page=100" --paginate | jq -s 'add // []') || {
    echo "Error: failed to fetch reviews" >&2; exit 3; }

# Informational: pending requested reviewers (never a blocker by itself)
pending_json=$(gh_api "repos/${OWNER}/${REPO}/pulls/${PR}/requested_reviewers") || pending_json='{"users":[],"teams":[]}'
set_fact pending_reviewers "$(jq '[(.users[].login), (.teams[].slug)]' <<<"$pending_json")"

# ── Gates (appended by later tasks) ──────────────────────────────────────────
# GATE: bot-clean-review        (Task 8)
# GATE: requested-changes       (Task 9)
# GATE: distinct-approvers      (Task 10)
# GATE: unresolved-threads      (Task 11)
# GATE: ci-green                (Task 12)
# GATE: review-in-flight        (Task 13)
# GATE: non-thread-feedback     (Task 17)
# GATE: prgroom-internal        (Task 18)

# ── Decision ─────────────────────────────────────────────────────────────────
blocker_count=$(jq 'length' <<<"$BLOCKERS")
status="eligible"; exit_code=0
if [[ "$blocker_count" -gt 0 ]]; then status="blocked"; exit_code=1; fi

jq -n \
    --arg status "$status" \
    --arg head "$HEAD_OID" \
    --argjson blockers "$BLOCKERS" \
    --argjson facts "$FACTS" \
    --arg hint "gh pr merge ${PR} --squash --match-head-commit ${HEAD_OID}" \
    '{status: $status, head_ref_oid: $head, blockers: $blockers, facts: $facts, merge_command_hint: $hint}'
exit "$exit_code"
```

- [x] **Step 4: Run to verify it passes**

Run: `bash src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh`
Expected: PASS (all asserts ok, exit 0).

- [x] **Step 5: Commit**

```bash
git add src/user/.agents/skills/merge-guard/check-merge-eligibility.sh src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh
git commit -m "feat(merge-guard): policy-driven eligibility skeleton — blockers/facts contract, head binding (wgclw.14)"
```

---

### Task 8: Gate — trusted-bot clean review **fact** (exact identity)

Behavior: **`facts.bot_clean_review_at_head` is true iff the latest non-DISMISSED review from an allowlisted identity has `commit_id == head` and state `APPROVED`/`COMMENTED`.** Substring matching is gone; a stale-head or missing-`commit_id` review never counts (fail closed). This is a fact, not a blocker.

**Files:**
- Modify: `src/user/.agents/skills/merge-guard/check-merge-eligibility.sh` (replace the `# GATE: bot-clean-review` line)
- Modify: `src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh` (append before `exit $FAIL`)

- [x] **Step 1: Append the failing tests**

```bash
# ── Task 8: trusted-bot clean review fact ─────────────────────────────────────
mk_review() {  # mk_review <login> <state> <commit> <ts> [type]
  jq -n --arg l "$1" --arg s "$2" --arg c "$3" --arg t "$4" --arg ty "${5:-Bot}" \
    '{user: {login: $l, type: $ty}, state: $s, commit_id: $c, submitted_at: $t, body: ""}'
}

# clean: trusted bot, APPROVED at head
revs=$(jq -n --argjson a "$(mk_review 'trusted-bot[bot]' APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z)" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "trusted APPROVED at head → fact true" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = true ]"

# COMMENTED at head is also clean (triage completeness is the floor's job)
revs=$(jq -n --argjson a "$(mk_review 'trusted-bot[bot]' COMMENTED "$HEAD_SHA" 2026-01-01T01:00:00Z)" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "trusted COMMENTED at head → fact true" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = true ]"

# stale head → not satisfied
revs=$(jq -n --argjson a "$(mk_review 'trusted-bot[bot]' APPROVED bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 2026-01-01T01:00:00Z)" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "stale-head review → fact false" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# missing commit_id → fail closed
revs='[{"user":{"login":"trusted-bot[bot]","type":"Bot"},"state":"APPROVED","submitted_at":"2026-01-01T01:00:00Z","body":""}]'
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "missing commit_id → fact false (fail closed)" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# untrusted bot (would match a substring filter) → ignored
revs=$(jq -n --argjson a "$(mk_review 'evil-copilot-clone[bot]' APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z)" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "untrusted bot ignored (exact identity)" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# latest wins: APPROVED then CHANGES_REQUESTED at head → not clean
revs=$(jq -n \
  --argjson a "$(mk_review 'trusted-bot[bot]' APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z)" \
  --argjson b "$(mk_review 'trusted-bot[bot]' CHANGES_REQUESTED "$HEAD_SHA" 2026-01-01T02:00:00Z)" '[$a,$b]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "latest CHANGES_REQUESTED → fact false" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"
```

- [x] **Step 2: Run to verify the new asserts fail**

Run: `bash src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh`
Expected: FAIL — `.facts.bot_clean_review_at_head` is `null` (gate not implemented).

- [x] **Step 3: Implement** — replace the line `# GATE: bot-clean-review        (Task 8)` with:

```bash
# ── Fact: trusted-bot clean review at current head (bot-quiescence input) ────
# Exact-identity allowlist — never substring. Missing commit_id fails closed.
bot_fact=$(jq --argjson trusted "$BOT_REVIEWERS" --arg head "$HEAD_OID" '
    [ .[]
      | select(.user.login as $l | ($trusted | index($l)) != null)
      | select(.state != "DISMISSED")
      | select((.commit_id // "") == $head) ]
    | sort_by(.submitted_at) | last
    | if . == null then {clean: false, by: null}
      elif (.state == "APPROVED" or .state == "COMMENTED") then {clean: true, by: .user.login}
      else {clean: false, by: .user.login}
      end' <<<"$ALL_REVIEWS")
set_fact bot_clean_review_at_head "$(jq '.clean' <<<"$bot_fact")"
set_fact bot_reviewed_by "$(jq '.by' <<<"$bot_fact")"
```

- [x] **Step 4: Run to verify all asserts pass**

Run: `bash src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/user/.agents/skills/merge-guard/check-merge-eligibility.sh src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh
git commit -m "feat(merge-guard): trusted-bot clean-review fact — exact identity, head-bound, fail-closed (wgclw.14)"
```

---

### Task 9: Gate — requested-changes sticky blocker

Behavior: **an active `CHANGES_REQUESTED` verdict blocks every non-force path, across ALL commits (deliberately not head-scoped).** Cleared only by dismissal (the review's state becomes `DISMISSED` in the API — natural exclusion) or a later `APPROVED` from the same reviewer. A later `COMMENTED` does NOT clear it.

**Files:** same two as Task 8.

- [x] **Step 1: Append the failing tests**

```bash
# ── Task 9: requested-changes sticky blocker ─────────────────────────────────
# CR on an OLD commit still blocks (not head-scoped)
revs=$(jq -n --argjson a "$(mk_review reviewer1 CHANGES_REQUESTED bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 2026-01-01T01:00:00Z Human)" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs"); rc=$?
assert "stale-commit CR still blocks" "[ \$rc -eq 1 ]"
assert "blocker code requested_changes_active" "jq -r '.blockers[].code' <<<\"\$out\" | grep -q requested_changes_active"

# later COMMENTED from same reviewer does NOT clear it
revs=$(jq -n \
  --argjson a "$(mk_review reviewer1 CHANGES_REQUESTED "$HEAD_SHA" 2026-01-01T01:00:00Z Human)" \
  --argjson b "$(mk_review reviewer1 COMMENTED "$HEAD_SHA" 2026-01-01T02:00:00Z Human)" '[$a,$b]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs"); rc=$?
assert "later COMMENTED does not clear CR" "[ \$rc -eq 1 ]"

# later APPROVED from same reviewer DOES clear it
revs=$(jq -n \
  --argjson a "$(mk_review reviewer1 CHANGES_REQUESTED "$HEAD_SHA" 2026-01-01T01:00:00Z Human)" \
  --argjson b "$(mk_review reviewer1 APPROVED "$HEAD_SHA" 2026-01-01T02:00:00Z Human)" '[$a,$b]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs"); rc=$?
assert "superseding APPROVED clears CR" "[ \$rc -eq 0 ]"

# dismissed CR (state=DISMISSED in API) does not block
revs=$(jq -n --argjson a "$(mk_review reviewer1 DISMISSED "$HEAD_SHA" 2026-01-01T01:00:00Z Human)" '[$a]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs"); rc=$?
assert "dismissed review does not block" "[ \$rc -eq 0 ]"
```

- [x] **Step 2: Run to verify the new asserts fail** (CR cases currently exit 0)

- [x] **Step 3: Implement** — replace `# GATE: requested-changes       (Task 9)` with:

```bash
# ── Blocker: active requested-changes verdict (sticky; never head-scoped) ────
# GitHub does not clear CHANGES_REQUESTED on push; only dismissal (state
# becomes DISMISSED) or a later APPROVED from the same reviewer clears it.
# COMMENTED is not a verdict change.
cr_logins=$(jq '
    group_by(.user.login)
    | map({
        login: .[0].user.login,
        cr: ([ .[] | select(.state == "CHANGES_REQUESTED") ] | sort_by(.submitted_at) | last),
        ok: ([ .[] | select(.state == "APPROVED") ] | sort_by(.submitted_at) | last)
      })
    | map(select(.cr != null and (.ok == null or .ok.submitted_at < .cr.submitted_at)))
    | map(.login)' <<<"$ALL_REVIEWS")
if [[ $(jq 'length' <<<"$cr_logins") -gt 0 ]]; then
    add_blocker requested_changes_active \
        "active CHANGES_REQUESTED from: $(jq -r 'join(", ")' <<<"$cr_logins") (cleared only by dismissal or a superseding APPROVED from the same reviewer)"
fi
```

- [x] **Step 4: Run to verify all asserts pass**

- [x] **Step 5: Commit**

```bash
git add src/user/.agents/skills/merge-guard/check-merge-eligibility.sh src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh
git commit -m "feat(merge-guard): sticky requested-changes floor blocker — survives pushes, COMMENTED never clears (wgclw.14)"
```

---

### Task 10: Gate — distinct current approvers **fact**

Behavior: **`facts.distinct_current_approvers` counts non-bot logins whose LATEST review is `APPROVED` with `commit_id == head`** — deduped by login, latest-state-wins, stale/missing `commit_id` never counts.

**Files:** same two.

- [ ] **Step 1: Append the failing tests**

```bash
# ── Task 10: distinct current approvers ──────────────────────────────────────
# same login twice = 1; bot approval excluded; stale-head approval excluded
revs=$(jq -n \
  --argjson a "$(mk_review alice APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z Human)" \
  --argjson b "$(mk_review alice APPROVED "$HEAD_SHA" 2026-01-01T02:00:00Z Human)" \
  --argjson c "$(mk_review bot-x[bot] APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z Bot)" \
  --argjson d "$(mk_review carol APPROVED bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 2026-01-01T01:00:00Z Human)" \
  '[$a,$b,$c,$d]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "dedup by login, bots and stale heads excluded (==1)" "[ \"\$(jq '.facts.distinct_current_approvers' <<<\"\$out\")\" = 1 ]"

# APPROVED superseded by later CHANGES_REQUESTED = 0 approvers (and CR blocks)
revs=$(jq -n \
  --argjson a "$(mk_review alice APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z Human)" \
  --argjson b "$(mk_review alice CHANGES_REQUESTED "$HEAD_SHA" 2026-01-01T02:00:00Z Human)" '[$a,$b]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs")
assert "approval superseded by CR counts 0" "[ \"\$(jq '.facts.distinct_current_approvers' <<<\"\$out\")\" = 0 ]"
```

- [ ] **Step 2: Run to verify the new asserts fail** (`.facts.distinct_current_approvers` is `null`)

- [ ] **Step 3: Implement** — replace `# GATE: distinct-approvers      (Task 10)` with:

```bash
# ── Fact: distinct current approvers (human-approvals rule input) ────────────
# One entry per non-bot login, latest review wins, APPROVED at current head
# only. Missing commit_id fails closed (does not count).
approvers=$(jq --arg head "$HEAD_OID" '
    [ .[] | select(.user.type != "Bot") ]
    | group_by(.user.login)
    | map(sort_by(.submitted_at) | last)
    | map(select(.state == "APPROVED" and (.commit_id // "") == $head))
    | map(.user.login)' <<<"$ALL_REVIEWS")
set_fact distinct_current_approvers "$(jq 'length' <<<"$approvers")"
set_fact approver_logins "$approvers"
APPROVER_COUNT=$(jq 'length' <<<"$approvers")
```

- [ ] **Step 4: Run to verify all asserts pass**

- [ ] **Step 5: Commit**

```bash
git add src/user/.agents/skills/merge-guard/check-merge-eligibility.sh src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh
git commit -m "feat(merge-guard): distinct-current-approver fact — dedup, latest-wins, head-bound (wgclw.14)"
```

---

### Task 11: Gate — live unresolved review threads

Behavior: **any unresolved review thread blocks, read live from GraphQL at merge time** (never prgroom state). Cursor-paginates.

**Files:** same two.

- [ ] **Step 1: Append the failing tests**

```bash
# ── Task 11: unresolved threads ──────────────────────────────────────────────
export_threads() {  # export_threads <resolved-bools...>  e.g. export_threads true false
  local nodes; nodes=$(printf '%s\n' "$@" | jq -R 'fromjson? // . | {isResolved: (. == "true" or . == true)}' | jq -s .)
  jq -n --argjson n "$nodes" '{data:{repository:{pullRequest:{reviewThreads:{pageInfo:{hasNextPage:false,endCursor:null},nodes:$n}}}}}'
}

out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads true false)"); rc=$?
assert "unresolved thread blocks" "[ \$rc -eq 1 ]"
assert "blocker code unresolved_threads" "jq -r '.blockers[].code' <<<\"\$out\" | grep -q unresolved_threads"

out=$(run_script "$BASE_POLICY" FIXTURE_GRAPHQL_THREADS="$(export_threads true true)"); rc=$?
assert "all threads resolved → eligible" "[ \$rc -eq 0 ]"
```

- [ ] **Step 2: Run to verify the new asserts fail** (unresolved thread currently exits 0)

- [ ] **Step 3: Implement** — replace `# GATE: unresolved-threads      (Task 11)` with:

```bash
# ── Blocker: unresolved review threads (always live; prgroom is never a
#    substitute — a thread opened after prgroom quiesced is absent from state) ─
fetch_threads_page() {  # fetch_threads_page [cursor]
    if [[ $# -eq 0 ]]; then
        gh api graphql \
          -f query='query($owner:String!,$repo:String!,$pr:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$pr){reviewThreads(first:100){pageInfo{hasNextPage endCursor}nodes{isResolved}}}}}' \
          -f owner="$OWNER" -f repo="$REPO" -F pr="$PR" 2>/dev/null
    else
        gh api graphql \
          -f query='query($owner:String!,$repo:String!,$pr:Int!,$cursor:String!){repository(owner:$owner,name:$repo){pullRequest(number:$pr){reviewThreads(first:100,after:$cursor){pageInfo{hasNextPage endCursor}nodes{isResolved}}}}}' \
          -f owner="$OWNER" -f repo="$REPO" -F pr="$PR" -f cursor="$1" 2>/dev/null
    fi
}
unresolved_threads=0
page=$(fetch_threads_page) || { echo "Error: reviewThreads query failed" >&2; exit 3; }
while :; do
    count=$(jq '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)] | length' <<<"$page")
    unresolved_threads=$((unresolved_threads + count))
    has_next=$(jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.hasNextPage' <<<"$page")
    [[ "$has_next" == "true" ]] || break
    cursor=$(jq -r '.data.repository.pullRequest.reviewThreads.pageInfo.endCursor' <<<"$page")
    page=$(fetch_threads_page "$cursor") || { echo "Error: reviewThreads pagination failed" >&2; exit 3; }
done
if [[ "$unresolved_threads" -gt 0 ]]; then
    add_blocker unresolved_threads "${unresolved_threads} unresolved review thread(s) on the PR"
fi
```

- [ ] **Step 4: Run to verify all asserts pass**

- [ ] **Step 5: Commit**

```bash
git add src/user/.agents/skills/merge-guard/check-merge-eligibility.sh src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh
git commit -m "feat(merge-guard): always-live unresolved-thread blocker with pagination (wgclw.14)"
```

---

### Task 12: Gate — required-CI-green

Behavior per the spec's CI-green predicate: **required set fetched from branch protection (never derived from the rollup); a required check absent or unconcluded = not green; a source-pinned requirement is only satisfied by a `SUCCESS` from that app; `SKIPPED`/`NEUTRAL` pass; empty required set = vacuously green.**

**Files:** same two.

- [ ] **Step 1: Append the failing tests**

```bash
# ── Task 12: CI-green ────────────────────────────────────────────────────────
REQ_ONE='{"strict":false,"contexts":["ci/build"],"checks":[{"context":"ci/build","app_id":15368}]}'
run_ok()   { jq -n '{check_runs:[{name:"ci/build",status:"completed",conclusion:"success",app:{id:15368}}]}'; }
run_wrong_app() { jq -n '{check_runs:[{name:"ci/build",status:"completed",conclusion:"success",app:{id:99999}}]}'; }
run_pending()   { jq -n '{check_runs:[{name:"ci/build",status:"in_progress",conclusion:null,app:{id:15368}}]}'; }
run_failed()    { jq -n '{check_runs:[{name:"ci/build",status:"completed",conclusion:"failure",app:{id:15368}}]}'; }

# no branch protection (stub default 404) → vacuously green
out=$(run_script "$BASE_POLICY"); rc=$?
assert "no protection → ci_state none, eligible" "[ \$rc -eq 0 ] && [ \"\$(jq -r '.facts.ci_state' <<<\"\$out\")\" = none ]"

# required + success from the pinned app → green
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_404=0 FIXTURE_REQUIRED_CHECKS="$REQ_ONE" FIXTURE_CHECK_RUNS="$(run_ok)"); rc=$?
assert "pinned success → green, eligible" "[ \$rc -eq 0 ] && [ \"\$(jq -r '.facts.ci_state' <<<\"\$out\")\" = green ]"

# same-named success from a DIFFERENT app → not green (spoofed integration)
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_404=0 FIXTURE_REQUIRED_CHECKS="$REQ_ONE" FIXTURE_CHECK_RUNS="$(run_wrong_app)"); rc=$?
assert "wrong-app success → blocked" "[ \$rc -eq 1 ]"
assert "blocker code ci_not_green (wrong app)" "jq -r '.blockers[].code' <<<\"\$out\" | grep -q ci_not_green"

# required check never started (absent from rollup) → not green
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_404=0 FIXTURE_REQUIRED_CHECKS="$REQ_ONE" FIXTURE_CHECK_RUNS='{"check_runs":[]}'); rc=$?
assert "required check never started → blocked" "[ \$rc -eq 1 ]"

# in-progress → not green; failure → not green
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_404=0 FIXTURE_REQUIRED_CHECKS="$REQ_ONE" FIXTURE_CHECK_RUNS="$(run_pending)"); rc=$?
assert "in-progress required check → blocked" "[ \$rc -eq 1 ]"
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_404=0 FIXTURE_REQUIRED_CHECKS="$REQ_ONE" FIXTURE_CHECK_RUNS="$(run_failed)"); rc=$?
assert "failed required check → blocked" "[ \$rc -eq 1 ]"

# unpinned requirement satisfied by legacy commit status
REQ_UNPINNED='{"strict":false,"contexts":["legacy/lint"],"checks":[{"context":"legacy/lint","app_id":null}]}'
out=$(run_script "$BASE_POLICY" FIXTURE_PROTECTION_404=0 FIXTURE_REQUIRED_CHECKS="$REQ_UNPINNED" \
      FIXTURE_COMMIT_STATUS='{"statuses":[{"context":"legacy/lint","state":"success"}]}'); rc=$?
assert "unpinned req satisfied by legacy status → eligible" "[ \$rc -eq 0 ]"
```

- [ ] **Step 2: Run to verify the new asserts fail** (`.facts.ci_state` is `null`; nothing blocks)

- [ ] **Step 3: Implement** — replace `# GATE: ci-green                (Task 12)` with:

```bash
# ── Blocker: required CI checks not green ────────────────────────────────────
# Required set from branch protection — NEVER derived from the rollup (the
# rollup lists only contexts that already reported; filtering it would hide a
# required check that never started). 404 / no protection = empty set =
# vacuously green. A source-pinned (app_id) requirement is only satisfied by
# a run from that app — name alone is not a trust boundary.
prot=""
prot_stderr=$(mktemp)
if prot=$(gh api "repos/${OWNER}/${REPO}/branches/${BASE_REF}/protection/required_status_checks" 2>"$prot_stderr"); then
    :
else
    if grep -qiE 'HTTP 404|Not Found|Branch not protected' "$prot_stderr"; then
        prot=""   # no protection → empty required set
    else
        echo "Error: failed to fetch branch protection: $(cat "$prot_stderr")" >&2
        rm -f "$prot_stderr"; exit 3
    fi
fi
rm -f "$prot_stderr"
required_checks=$(jq -c '[.checks[]? | {context, app_id}]' <<<"${prot:-null}" 2>/dev/null || echo '[]')
[[ "$required_checks" == "null" ]] && required_checks='[]'

check_runs=$(gh_api "repos/${OWNER}/${REPO}/commits/${HEAD_OID}/check-runs?per_page=100" --paginate \
    | jq -s '[.[] | .check_runs[]? | {name, status, conclusion, app_id: (.app.id // null)}]') || {
    echo "Error: failed to fetch check runs" >&2; exit 3; }
legacy_statuses=$(gh_api "repos/${OWNER}/${REPO}/commits/${HEAD_OID}/status" \
    | jq '[.statuses[]? | {context, state}]') || legacy_statuses='[]'

ci_eval=$(jq -n --argjson req "$required_checks" --argjson runs "$check_runs" --argjson legacy "$legacy_statuses" '
    def red_conclusions: ["failure","cancelled","timed_out","action_required","startup_failure","stale"];
    def eval_one(r):
      ( [ $runs[] | select(.name == r.context and (r.app_id == null or .app_id == r.app_id)) ]
        + ( if r.app_id == null
            then [ $legacy[] | select(.context == r.context)
                   | { name: .context, status: "legacy",
                       conclusion: (if .state == "success" then "success"
                                    elif (.state == "failure" or .state == "error") then "failure"
                                    else "pending" end) } ]
            else [] end) ) as $cands
      | if ($cands | length) == 0 then "pending"
        elif any($cands[]; (.conclusion // "") as $c | red_conclusions | index($c)) then "red"
        elif all($cands[]; ((.status == "completed") or (.status == "legacy"))
                           and ((["success","skipped","neutral"]) | index(.conclusion // ""))) then "green"
        else "pending" end;
    if ($req | length) == 0 then {state: "none", not_green: []}
    else ([ $req[] | {context, result: eval_one(.)} ]) as $per
      | { state: (if any($per[]; .result == "red") then "red"
                  elif all($per[]; .result == "green") then "green"
                  else "pending" end),
          not_green: [ $per[] | select(.result != "green") | "\(.context) (\(.result))" ] }
    end')
set_fact ci_state "$(jq '.state' <<<"$ci_eval")"
ci_state=$(jq -r '.state' <<<"$ci_eval")
if [[ "$ci_state" != "green" && "$ci_state" != "none" ]]; then
    add_blocker ci_not_green \
        "required checks not green: $(jq -r '.not_green | join(", ")' <<<"$ci_eval") (pending/absent fails closed)"
fi
```

- [ ] **Step 4: Run to verify all asserts pass**

- [ ] **Step 5: Commit**

```bash
git add src/user/.agents/skills/merge-guard/check-merge-eligibility.sh src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh
git commit -m "feat(merge-guard): CI-green gate — branch-protection sourced, app-pinned, pending fails closed (wgclw.14)"
```

---

### Task 13: Gate — expected review still in flight

Behavior: **when Axis 1 expects a review that has neither arrived at the current head nor timed out, block — an explicit "merge it" must not race a pending review.** Bot side: reference time = latest of (trusted-bot review request event, `copilot_work_started`, latest trusted-bot review, PR creation); age ≥ `bot_inactivity_timeout_seconds` → wait over. Human side: approvals ≥ required → satisfied; `null` timeout → block indefinitely; else age vs timeout from PR creation. Timeout NEVER satisfies the positive fact — it only ends the wait.

**Files:** same two.

- [ ] **Step 1: Append the failing tests**

```bash
# ── Task 13: review still in flight ──────────────────────────────────────────
BOT_POLICY=$(jq -c '.bot_review_expected = true' <<<"$BASE_POLICY")
TS_RECENT=$(jq -rn 'now - 60 | todate')      # 1 min ago  < 1200s timeout
TS_OLD=$(jq -rn 'now - 7200 | todate')       # 2 h ago    > 1200s timeout

# bot expected, requested recently, no review yet → blocked (in flight)
ev=$(jq -n --arg t "$TS_RECENT" '[{event:"review_requested", requested_reviewer:{login:"trusted-bot[bot]"}, created_at:$t}]')
out=$(run_script "$BOT_POLICY" FIXTURE_EVENTS="$ev"); rc=$?
assert "pending bot review blocks explicit merge" "[ \$rc -eq 1 ]"
assert "blocker code review_in_flight" "jq -r '.blockers[].code' <<<\"\$out\" | grep -q review_in_flight"
assert "review_wait.bot is waiting" "[ \"\$(jq -r '.facts.review_wait.bot' <<<\"\$out\")\" = waiting ]"

# bot expected, silence past timeout → wait over (timed_out), not blocked
ev=$(jq -n --arg t "$TS_OLD" '[{event:"review_requested", requested_reviewer:{login:"trusted-bot[bot]"}, created_at:$t}]')
old_pr=$(jq -n --arg t "$TS_OLD" '{state:"open", head:{sha:"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}, base:{ref:"main"}, created_at:$t}')
out=$(run_script "$BOT_POLICY" FIXTURE_EVENTS="$ev" FIXTURE_PR="$old_pr"); rc=$?
assert "bot silence past timeout → eligible (timed_out)" "[ \$rc -eq 0 ]"
assert "review_wait.bot is timed_out" "[ \"\$(jq -r '.facts.review_wait.bot' <<<\"\$out\")\" = timed_out ]"
assert "timeout does NOT satisfy the positive fact" "[ \"\$(jq '.facts.bot_clean_review_at_head' <<<\"\$out\")\" = false ]"

# bot review arrived at head → satisfied
revs=$(jq -n --argjson a "$(mk_review 'trusted-bot[bot]' COMMENTED "$HEAD_SHA" 2026-01-01T01:00:00Z)" '[$a]')
out=$(run_script "$BOT_POLICY" FIXTURE_REVIEWS="$revs" FIXTURE_PR="$old_pr"); rc=$?
assert "arrived bot review → satisfied, eligible" "[ \$rc -eq 0 ] && [ \"\$(jq -r '.facts.review_wait.bot' <<<\"\$out\")\" = satisfied ]"

# humans required, none yet, no timeout → blocks indefinitely
H_POLICY=$(jq -c '.human_approvers_required = 1' <<<"$BASE_POLICY")
out=$(run_script "$H_POLICY" FIXTURE_PR="$old_pr"); rc=$?
assert "missing human approval with null timeout blocks" "[ \$rc -eq 1 ]"
assert "review_wait.human is waiting" "[ \"\$(jq -r '.facts.review_wait.human' <<<\"\$out\")\" = waiting ]"

# humans required, timeout elapsed → wait over
H_TIMEOUT_POLICY=$(jq -c '.human_approvers_required = 1 | .human_review_timeout_seconds = 1200' <<<"$BASE_POLICY")
out=$(run_script "$H_TIMEOUT_POLICY" FIXTURE_PR="$old_pr"); rc=$?
assert "human timeout elapsed → eligible (timed_out)" "[ \$rc -eq 0 ]"

# humans required and enough current approvals → satisfied
revs=$(jq -n --argjson a "$(mk_review alice APPROVED "$HEAD_SHA" 2026-01-01T01:00:00Z Human)" '[$a]')
out=$(run_script "$H_POLICY" FIXTURE_REVIEWS="$revs" FIXTURE_PR="$old_pr"); rc=$?
assert "enough approvals → satisfied, eligible" "[ \$rc -eq 0 ] && [ \"\$(jq -r '.facts.review_wait.human' <<<\"\$out\")\" = satisfied ]"
```

- [ ] **Step 2: Run to verify the new asserts fail** (`.facts.review_wait` is `null`; pending cases exit 0)

- [ ] **Step 3: Implement** — replace `# GATE: review-in-flight        (Task 13)` with:

```bash
# ── Blocker: expected review still in flight ─────────────────────────────────
# A review that hasn't happened YET is otherwise indistinguishable from one
# that concluded clean — both read "no blocker" on every other row. Block
# until the expected review arrives at the current head or its wait window
# closes. Timing out ends the wait; it never satisfies the positive fact.
EVENTS=$(gh_api "repos/${OWNER}/${REPO}/issues/${PR}/events?per_page=100" --paginate | jq -s 'add // []') || EVENTS='[]'

review_wait_bot="not_expected"
if [[ "$BOT_EXPECTED" == "true" ]]; then
    arrived=$(jq --argjson trusted "$BOT_REVIEWERS" --arg head "$HEAD_OID" '
        [ .[] | select((.user.login as $l | ($trusted | index($l)) != null)
                       and ((.commit_id // "") == $head)
                       and .state != "DISMISSED") ] | length' <<<"$ALL_REVIEWS")
    if [[ "$arrived" -gt 0 ]]; then
        review_wait_bot="satisfied"
    else
        latest_ref=$(jq -rn --argjson ev "$EVENTS" --argjson rv "$ALL_REVIEWS" \
            --argjson trusted "$BOT_REVIEWERS" --arg pr_created "$PR_CREATED" '
            ( [ $ev[] | select(.event == "review_requested"
                               and (((.requested_reviewer.login // "") as $l | ($trusted | index($l)) != null)))
                      | .created_at ]
            + [ $ev[] | select(.event == "copilot_work_started") | .created_at ]
            + [ $rv[] | select((.user.login as $l | ($trusted | index($l)) != null)) | .submitted_at ]
            + [ $pr_created ] ) | max')
        bot_age=$(jq -rn --arg ts "$latest_ref" '(now - ($ts | fromdateiso8601)) | floor')
        if [[ "$bot_age" -ge "$BOT_TIMEOUT" ]]; then
            review_wait_bot="timed_out"
        else
            review_wait_bot="waiting"
            add_blocker review_in_flight \
                "bot review expected but not arrived at head; last activity ${bot_age}s ago < inactivity timeout ${BOT_TIMEOUT}s"
        fi
    fi
fi

review_wait_human="not_expected"
if [[ "$HUMANS_REQUIRED" -gt 0 ]]; then
    if [[ "$APPROVER_COUNT" -ge "$HUMANS_REQUIRED" ]]; then
        review_wait_human="satisfied"
    elif [[ "$HUMAN_TIMEOUT" == "null" ]]; then
        review_wait_human="waiting"
        add_blocker review_in_flight \
            "waiting for ${HUMANS_REQUIRED} human approval(s), have ${APPROVER_COUNT}; no human-review-timeout — waits indefinitely"
    else
        human_age=$(jq -rn --arg ts "$PR_CREATED" '(now - ($ts | fromdateiso8601)) | floor')
        if [[ "$human_age" -ge "$HUMAN_TIMEOUT" ]]; then
            review_wait_human="timed_out"
        else
            review_wait_human="waiting"
            add_blocker review_in_flight \
                "waiting for ${HUMANS_REQUIRED} human approval(s), have ${APPROVER_COUNT}; ${human_age}s elapsed < timeout ${HUMAN_TIMEOUT}s"
        fi
    fi
fi
set_fact review_wait "$(jq -n --arg b "$review_wait_bot" --arg h "$review_wait_human" '{bot: $b, human: $h}')"
```

Placement note: this block must sit AFTER the Task-10 block (it reads `APPROVER_COUNT`).

- [ ] **Step 4: Run to verify all asserts pass**

- [ ] **Step 5: Commit**

```bash
git add src/user/.agents/skills/merge-guard/check-merge-eligibility.sh src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh
git commit -m "feat(merge-guard): review-in-flight floor blocker — explicit merge cannot race a pending review (wgclw.14)"
```

---

### Task 14: Retain completed inventories (durable triage record)

The non-thread-feedback gate (Task 17) reads completed inventories as its durable triage record — but today Skill A deletes them on success (Phase 9 `rm -f`) and silently unlinks completed prior-run files in the Phase-1 concurrency check. Both deletion sites go; the >30-day pruning in `write-inventory.sh` stays as the only hygiene.

**Files:**
- Modify: `src/user/.agents/skills/wait-for-pr-comments/SKILL.md` (Phase 9 step 4 ~lines 449-459; concurrency branch table row ~line 867; cleanup-timing note ~lines 893-901)

Prose-only edits (the deletion is instructed in SKILL.md code blocks, not in a script), so no failing-test step — verification is by grep.

- [ ] **Step 1: Rewrite Phase 9 step 4** — replace:

```markdown
4. **If count == 0**: write final completion state and clean up:
   ```bash
   ${CLAUDE_SKILL_DIR}/write-inventory.sh \
     --state complete \
     --phase 9-final-check-done \
     --output ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
     < ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json

   rm -f ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json
   ```
   Skill A is the file's lifecycle owner — Skill B never unlinks.
```

with:

```markdown
4. **If count == 0**: write final completion state and RETAIN the file:
   ```bash
   ${CLAUDE_SKILL_DIR}/write-inventory.sh \
     --state complete \
     --phase 9-final-check-done \
     --output ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json \
     < ~/.claude/state/pr-inventory/<owner>-<repo>-<n>-<sha>.json
   ```
   Do NOT delete the inventory. Completed inventories are the durable triage
   record the merge-eligibility floor's untriaged-non-thread-feedback check
   unions across pushes (`check-merge-eligibility.sh` globs
   `<owner>-<repo>-<n>-*.json`) — possibly in a later session. The >30-day
   pruning in `write-inventory.sh` is the only deletion. Skill A remains the
   file's lifecycle owner — Skill B never unlinks.
```

- [ ] **Step 2: Rewrite the branch-table row** — replace:

```markdown
| `true` | `8-skill-b-done`, `9-final-check-done` | **Silent unlink** (orphan from prior crash); proceed normally |
```

with:

```markdown
| `true` | `8-skill-b-done`, `9-final-check-done` | **Retained triage record** (completed run) — do NOT unlink; proceed normally. The eligibility floor reads these files. |
```

- [ ] **Step 3: Rewrite the cleanup-timing note** — replace:

```markdown
**Inventory cleanup timing:**

- At Skill A startup: housekeeping ONLY (delete files >30 days, handled
  inline by `write-inventory.sh`). Never touch the inventory currently
  being recovered.
- At Phase 9 success (after final unresolved-threads check passes): Skill A updates
  `last_completed_phase="9-final-check-done"` then `unlink`s.
- Never at Phase 1 (the concurrency check refuses before any cleanup of the
  current PR's files).
```

with:

```markdown
**Inventory cleanup timing:**

- At Skill A startup: housekeeping ONLY (delete files >30 days, handled
  inline by `write-inventory.sh`). Never touch the inventory currently
  being recovered.
- At Phase 9 success (after final unresolved-threads check passes): Skill A
  updates `last_completed_phase="9-final-check-done"` and **retains the
  file** — completed inventories are the durable triage record consumed by
  `check-merge-eligibility.sh`'s non-thread-feedback check, unioned across
  the PR's full push history.
- Never at Phase 1 (the concurrency check refuses before any cleanup of the
  current PR's files; completed files found there are retained records, not
  orphans).
- The only deletion anywhere is the >30-day pruning.
```

- [ ] **Step 4: Verify by grep**

Run: `grep -n "rm -f ~/.claude/state/pr-inventory" src/user/.agents/skills/wait-for-pr-comments/SKILL.md; grep -cn "Silent unlink" src/user/.agents/skills/wait-for-pr-comments/SKILL.md`
Expected: no `rm -f` hit; 0 `Silent unlink` hits.

- [ ] **Step 5: Commit**

```bash
git add src/user/.agents/skills/wait-for-pr-comments/SKILL.md
git commit -m "feat(wait-for-pr-comments): retain completed inventories as durable triage record (wgclw.14)"
```

---

### Task 15: `review_summary` items gain a stable `review_id`

Behavior: **guard 3 now requires `review_summary` items to carry `review_id` (the REST review's numeric `id`) and still forbids the other three IDs** — so summaries can be matched across inventory files by stable identity. Loud at write time, not silently blocking at merge time.

**Files:**
- Modify: `src/user/.agents/skills/wait-for-pr-comments/validate-inventory.sh` (guard 3, lines 106-108)
- Modify: `src/user/.agents/skills/wait-for-pr-comments/validate-inventory_test.sh` (append cases before final `exit $FAIL`, reusing its `assert` helper)
- Modify: `src/user/.agents/skills/wait-for-pr-comments/SKILL.md` (schema: item-fields block ~667-685, `review_summary` note ~695-699, Phase-3 sourcing line ~202)

- [ ] **Step 1: Append the failing tests** to `validate-inventory_test.sh` (self-contained fixtures; invocation per its usage: `validate-inventory.sh --inventory <path> --phase 0`):

```bash
# ── review_id on review_summary (guard 3, wgclw.14) ──────────────────────────
T15="$(mktemp -d)"
mk_inv() {  # mk_inv <items-json>
  jq -n --argjson items "$1" '{schema_version: 1, pr: {}, polling: {}, items: $items,
    crash_recovery: {skill_a_completed: false, last_completed_phase: "7-write-inventory"}}'
}
good_summary='[{"kind":"review_summary","review_id":301,"thread_id":null,"reply_to_comment_id":null,"issue_comment_id":null,"author":"copilot","body_excerpt":"x","classification":"SKIP","rationale":"noise","fix_outcome":null}]'
no_id_summary='[{"kind":"review_summary","thread_id":null,"reply_to_comment_id":null,"issue_comment_id":null,"author":"copilot","body_excerpt":"x","classification":"SKIP","rationale":"noise","fix_outcome":null}]'
wrong_id_summary='[{"kind":"review_summary","review_id":301,"thread_id":null,"reply_to_comment_id":null,"issue_comment_id":88,"author":"copilot","body_excerpt":"x","classification":"SKIP","rationale":"noise","fix_outcome":null}]'

mk_inv "$good_summary" > "$T15/good.json"
mk_inv "$no_id_summary" > "$T15/noid.json"
mk_inv "$wrong_id_summary" > "$T15/wrongid.json"

"$HERE/validate-inventory.sh" --inventory "$T15/good.json" --phase 0 >/dev/null 2>&1
assert "review_summary with review_id passes guard 3" "[ \$? -eq 0 ]"
"$HERE/validate-inventory.sh" --inventory "$T15/noid.json" --phase 0 >/dev/null 2>&1
assert "review_summary without review_id fails guard 3" "[ \$? -eq 1 ]"
"$HERE/validate-inventory.sh" --inventory "$T15/wrongid.json" --phase 0 >/dev/null 2>&1
assert "review_summary with issue_comment_id still fails guard 3" "[ \$? -eq 1 ]"
rm -rf "$T15"
```

- [ ] **Step 2: Run to verify the new asserts fail**

Run: `bash src/user/.agents/skills/wait-for-pr-comments/validate-inventory_test.sh`
Expected: FAIL — "with review_id passes" fails today only if the guard rejects unknown fields (it does not — select-based guards pass extra fields), so the failing assert is "without review_id fails" (currently passes guard 3).

- [ ] **Step 3: Update guard 3** in `validate-inventory.sh` — replace:

```bash
# Guard 3: review_summary items must have null thread_id, reply_to_comment_id, issue_comment_id
run_guard "review_summary-null-ids" \
    '[.items[] | select(.kind == "review_summary" and ((.thread_id != null) or (.reply_to_comment_id != null) or (.issue_comment_id != null)))]' || FAIL=1
```

with:

```bash
# Guard 3: review_summary items carry review_id (their stable identity for the
# cross-push triage union in check-merge-eligibility.sh) and none of the other
# three IDs. review_id is the REST review's numeric .id.
run_guard "review_summary-ids" \
    '[.items[] | select(.kind == "review_summary" and ((.thread_id != null) or (.reply_to_comment_id != null) or (.issue_comment_id != null) or (.review_id == null)))]' || FAIL=1
```

- [ ] **Step 4: Run to verify all asserts pass**

Run: `bash src/user/.agents/skills/wait-for-pr-comments/validate-inventory_test.sh`
Expected: PASS.

- [ ] **Step 5: Update the SKILL.md schema docs** (three edits):

(a) In the per-item fields block (~lines 667-685), after the `"issue_comment_id"` line, add:

```jsonc
"review_id": 301 | null,                 // review_summary only: REST review .id — its stable cross-inventory identity
```

(b) Replace the `review_summary` note (~lines 695-699):

> `review_summary` items have only `kind`, `body_excerpt`, `author`, `classification`, `rationale`, `fix_outcome`, `fix_commit_sha`, `fix_summary`, `fix_gate_variant`. **No** `thread_id`, `reply_to_comment_id`, `issue_comment_id` (validation guard 3 enforces this).

with:

> `review_summary` items have `kind`, `review_id`, `body_excerpt`, `author`, `classification`, `rationale`, `fix_outcome`, `fix_commit_sha`, `fix_summary`, `fix_gate_variant`. `review_id` is **required** — it is the REST review's numeric `.id`, the item's stable identity for the cross-push triage union in `check-merge-eligibility.sh`. **No** `thread_id`, `reply_to_comment_id`, `issue_comment_id` (validation guard 3 enforces both).

(c) At the Phase-3 `review_summary` sourcing line (~line 202 — currently claims the items come from "GraphQL `reviews.nodes`", which no script implements), replace that sentence with:

> `review_summary` items are built by the orchestrator from `poll-copilot-review.sh`'s `reviews[]` output (raw REST review objects): set `review_id` from the review's numeric `.id`, `author` from `.user.login`, `body_excerpt` from the first 200 chars of `.body`. One item per review with a non-empty body.

- [ ] **Step 6: Commit**

```bash
git add src/user/.agents/skills/wait-for-pr-comments/validate-inventory.sh src/user/.agents/skills/wait-for-pr-comments/validate-inventory_test.sh src/user/.agents/skills/wait-for-pr-comments/SKILL.md
git commit -m "feat(wait-for-pr-comments): review_summary items carry stable review_id (guard 3) (wgclw.14)"
```

---

### Task 16: Record created reply IDs (`posted_reply_id`)

Behavior: **when `post-replies.sh` successfully posts a reply, it captures the created comment's numeric `.id` from the API response and records it on the matching inventory item as `posted_reply_id`** — the exclusion set the eligibility floor uses instead of author-login filtering (the agent commonly posts through its human operator's own GitHub account).

**Files:**
- Modify: `src/user/.agents/skills/reply-and-resolve-pr-threads/post-replies.sh`
- Modify: `src/user/.agents/skills/reply-and-resolve-pr-threads/post-replies_test.sh` (append before final `exit $FAIL`, reusing its `assert` helper and stub conventions)

- [ ] **Step 1: Append the failing test**

```bash
# ── posted_reply_id recording (wgclw.14) ─────────────────────────────────────
T16="$(mktemp -d)"
cat > "$T16/gh" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "api" ]; then
  # POST returns the created comment object, like the real API
  printf '{"id": 777001, "html_url": "https://example.invalid/c/777001"}'
  exit 0
fi
exit 0
STUB
chmod +x "$T16/gh"
jq -n '{schema_version: 1, pr: {}, polling: {}, items: [
  {kind: "issue_comment", issue_comment_id: 4242, thread_id: null, reply_to_comment_id: null,
   author: "reviewer", body_excerpt: "x", classification: "SKIP", rationale: "noise",
   fix_outcome: null, reply_body: "Acknowledged — skipping as cosmetic."}
], crash_recovery: {skill_a_completed: true, last_completed_phase: "7-write-inventory"}}' > "$T16/inv.json"

out16=$(PATH="$T16:$PATH" "$HERE/post-replies.sh" --inventory "$T16/inv.json" --owner o --repo r --pr 1 2>&1)
rc16=$?
assert "post succeeds against stub" "[ \$rc16 -eq 0 ]"
assert "POSTED line emitted" "grep -q 'POSTED 4242' <<<\"\$out16\""
assert "posted_reply_id recorded on the item" \
  "[ \"\$(jq -r '.items[0].posted_reply_id' \"$T16/inv.json\")\" = 777001 ]"
rm -rf "$T16"
```

- [ ] **Step 2: Run to verify the new asserts fail**

Run: `bash src/user/.agents/skills/reply-and-resolve-pr-threads/post-replies_test.sh`
Expected: FAIL — `posted_reply_id` assert (the script discards the API response today).

- [ ] **Step 3: Implement.** Two edits to `post-replies.sh`:

(a) Insert this helper directly after the `jq -c '.items[]?' "$INV" > "$TMP"` line (line ~140):

```bash
# Record the CREATED reply's id on the matching inventory item — the
# eligibility floor excludes agent replies by exact recorded id, never by
# author login (the agent commonly posts through its human operator's own
# GitHub account, so a login filter would hide that human's real comments).
record_reply_id() {  # record_reply_id <item-key> <match-value> <reply-id>
  local key="$1" val="$2" rid="$3" tmp_inv
  tmp_inv="$(mktemp)"
  if jq --arg k "$key" --arg v "$val" --argjson rid "$rid" \
       '.items |= map(if ((.[$k] // "") | tostring) == $v then . + {posted_reply_id: $rid} else . end)' \
       "$INV" > "$tmp_inv" && mv "$tmp_inv" "$INV"; then
    :
  else
    rm -f "$tmp_inv"
    echo "WARNING $val reply-id-record-failed: reply $rid posted to GitHub but not recorded in $INV; the eligibility check will treat it as incoming feedback until triaged" >&2
  fi
}
```

(b) Replace the POST block (lines ~221-243). The `if printf '%s' "$body" | gh api ... >/dev/null 2>"$ERR"; then` opener becomes a response-capturing form, and the success branch gains the recording call after the sidecar append (all existing sidecar comments and logic stay verbatim):

```bash
  : > "$ERR"
  if resp="$(printf '%s' "$body" | gh api "$post_url" \
      --method POST --field body=@- 2>"$ERR")"; then
    echo "POSTED $cid"
    # [ ... keep the existing sidecar-append block (comments included) verbatim ... ]
    reply_id="$(printf '%s' "$resp" | jq -r '.id // empty' 2>/dev/null)"
    if [ -n "$reply_id" ]; then
      case "$kind" in
        issue_comment)  record_reply_id issue_comment_id "$cid" "$reply_id" ;;
        review_summary)
          rsid="$(echo "$item" | jq -r '.review_id // empty')"
          if [ -n "$rsid" ]; then
            record_reply_id review_id "$rsid" "$reply_id"
          else
            echo "WARNING $cid reply-id-not-recorded: legacy review_summary item lacks review_id" >&2
          fi
          ;;
        *)              record_reply_id reply_to_comment_id "$reply_to" "$reply_id" ;;
      esac
    else
      echo "WARNING $cid reply-id-not-recorded: API response carried no .id" >&2
    fi
  else
```

(The `else` branch and everything after it are unchanged.) Note the `review_thread`/fallback arm records too — harmless and consistent; the floor's exclusion set only consults it for non-thread kinds.

- [ ] **Step 4: Run both suites to verify**

Run: `bash src/user/.agents/skills/reply-and-resolve-pr-threads/post-replies_test.sh`
Expected: PASS (new asserts and all pre-existing ones — the capture change must not break the pipe-isolation behavior the header comments describe).

- [ ] **Step 5: Commit**

```bash
git add src/user/.agents/skills/reply-and-resolve-pr-threads/post-replies.sh src/user/.agents/skills/reply-and-resolve-pr-threads/post-replies_test.sh
git commit -m "feat(reply-and-resolve): record created reply IDs on inventory items (wgclw.14)"
```

---

### Task 17: Gate — untriaged non-thread reviewer feedback

Behavior: **every `issue_comment` and non-empty-body review (`review_summary`) currently visible on the PR must be excluded (its id durably recorded as an agent reply) or terminally triaged (`SKIP`, or `FIX` with `committed`/`already_addressed`) in the union of ALL retained inventories for the PR — else it blocks.** Not head-scoped; `ESCALATE`/`failed`/absent = blocker; empty set vacuously clear; exclusion by exact ID, never author login.

**Files:**
- Modify: `src/user/.agents/skills/merge-guard/check-merge-eligibility.sh` (replace `# GATE: non-thread-feedback     (Task 17)`)
- Modify: `src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh` (append)

- [ ] **Step 1: Append the failing tests**

```bash
# ── Task 17: untriaged non-thread feedback ───────────────────────────────────
INV_DIR="$FAKE_HOME/.claude/state/pr-inventory"
write_inv() {  # write_inv <filename> <items-json>
  jq -n --argjson items "$2" '{schema_version: 1, pr: {}, polling: {}, items: $items,
    crash_recovery: {skill_a_completed: true, last_completed_phase: "9-final-check-done"}}' \
    > "$INV_DIR/$1"
}
clean_invs() { rm -f "$INV_DIR"/*.json; }

IC='[{"id": 900, "user": {"login": "reviewer"}, "body": "please fix the naming"}]'

# untriaged issue comment blocks
clean_invs
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC"); rc=$?
assert "untriaged issue comment blocks" "[ \$rc -eq 1 ]"
assert "blocker code untriaged_feedback" "jq -r '.blockers[].code' <<<\"\$out\" | grep -q untriaged_feedback"

# terminal triage in a retained inventory clears it — recorded against a
# DIFFERENT head SHA than current (union across pushes, never head-scoped)
write_inv "o-r-1-oldsha0001.json" '[{"kind":"issue_comment","issue_comment_id":900,"classification":"SKIP","rationale":"cosmetic","fix_outcome":null}]'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC"); rc=$?
assert "triage from an older-head inventory still clears (union)" "[ \$rc -eq 0 ]"

# ESCALATE triage still blocks
clean_invs
write_inv "o-r-1-oldsha0001.json" '[{"kind":"issue_comment","issue_comment_id":900,"classification":"ESCALATE","escalation_filed":true,"rationale":"needs human","fix_outcome":null}]'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC"); rc=$?
assert "ESCALATE disposition still blocks" "[ \$rc -eq 1 ]"

# a recorded agent reply is excluded by exact ID…
clean_invs
write_inv "o-r-1-oldsha0002.json" '[{"kind":"issue_comment","issue_comment_id":444,"classification":"SKIP","rationale":"r","fix_outcome":null,"posted_reply_id":900}]'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC"); rc=$?
assert "recorded posted_reply_id excluded → eligible" "[ \$rc -eq 0 ]"

# …but a manual comment from the same account with a DIFFERENT id still blocks
IC2='[{"id": 900, "user": {"login": "operator"}, "body": "agent reply"}, {"id": 901, "user": {"login": "operator"}, "body": "actually, one more thing"}]'
out=$(run_script "$BASE_POLICY" FIXTURE_ISSUE_COMMENTS="$IC2"); rc=$?
assert "same-account manual comment (unrecorded id) blocks" "[ \$rc -eq 1 ]"

# an APPROVED bot review with a non-empty body needs triage too
clean_invs
revs=$(jq -n '[{user: {login: "trusted-bot[bot]", type: "Bot"}, state: "APPROVED",
  commit_id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", submitted_at: "2026-01-01T01:00:00Z",
  id: 301, body: "LGTM but consider renaming this module"}]')
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs"); rc=$?
assert "APPROVED review with body blocks until triaged" "[ \$rc -eq 1 ]"

# triaged by review_id in a retained inventory → clears
write_inv "o-r-1-oldsha0003.json" '[{"kind":"review_summary","review_id":301,"classification":"FIX","rationale":"renamed","fix_outcome":"already_addressed","fix_commit_sha":"abc"}]'
out=$(run_script "$BASE_POLICY" FIXTURE_REVIEWS="$revs"); rc=$?
assert "review_summary triaged by review_id clears" "[ \$rc -eq 0 ]"
clean_invs
```

- [ ] **Step 2: Run to verify the new asserts fail** (untriaged cases currently exit 0)

- [ ] **Step 3: Implement** — replace `# GATE: non-thread-feedback     (Task 17)` with:

```bash
# ── Blocker: untriaged non-thread reviewer feedback ──────────────────────────
# review_summary / issue_comment items are disjoint GitHub objects from review
# threads — the thread check does not cover them, and prgroom's
# no_blocker_items must never stand in (an item prgroom has not polled has no
# disposition). Deliberately NOT head-scoped: an issue_comment carries no
# commit reference and a summary's feedback does not become moot on push —
# only an actual triage decision clears it. Exclusion is by exact recorded
# reply ID, never author login. No durable record anywhere = blocker (fail
# closed). Empty current set = vacuously clear.
ISSUE_COMMENTS=$(gh_api "repos/${OWNER}/${REPO}/issues/${PR}/comments?per_page=100" --paginate | jq -s 'add // []') || {
    echo "Error: failed to fetch issue comments" >&2; exit 3; }

inventory_items='[]'
while IFS= read -r -d '' inv_file; do
    file_items=$(jq '[.items[]?]' "$inv_file" 2>/dev/null) || continue
    inventory_items=$(jq -n --argjson a "$inventory_items" --argjson b "$file_items" '$a + $b')
done < <(find "${HOME}/.claude/state/pr-inventory" -maxdepth 1 \
         -name "${OWNER}-${REPO}-${PR}-*.json" -print0 2>/dev/null)

untriaged=$(jq -n \
    --argjson live_issue "$(jq '[.[] | {id, author: .user.login}]' <<<"$ISSUE_COMMENTS")" \
    --argjson live_summaries "$(jq '[.[] | select((.body // "") != "") | {review_id: .id, author: .user.login}]' <<<"$ALL_REVIEWS")" \
    --argjson recorded "$inventory_items" '
    def terminal_ok:
        (.classification == "SKIP")
        or (.classification == "FIX"
            and (.fix_outcome == "committed" or .fix_outcome == "already_addressed"));
    ([ $recorded[] | .posted_reply_id // empty ] | unique) as $agent_replies
    | ([ $recorded[] | select(.kind == "issue_comment" and terminal_ok) | .issue_comment_id ] | unique) as $done_issue
    | ([ $recorded[] | select(.kind == "review_summary" and terminal_ok) | .review_id // empty ] | unique) as $done_review
    | ([ $live_issue[]
         | select((.id as $i | $agent_replies | index($i)) == null)
         | select((.id as $i | $done_issue | index($i)) == null)
         | "issue_comment #\(.id) by \(.author)" ])
    + ([ $live_summaries[]
         | select((.review_id as $i | $done_review | index($i)) == null)
         | "review_summary #\(.review_id) by \(.author)" ])')
untriaged_count=$(jq 'length' <<<"$untriaged")
set_fact untriaged_feedback_count "$untriaged_count"
if [[ "$untriaged_count" -gt 0 ]]; then
    add_blocker untriaged_feedback \
        "untriaged non-thread feedback (no terminal disposition in any retained inventory): $(jq -r 'join("; ")' <<<"$untriaged")"
fi
```

- [ ] **Step 4: Run to verify all asserts pass** — including re-running the FULL file: earlier tasks' fixtures (e.g. Task 8/13's `mk_review` bodies) use `body: ""`, so they do not trip this gate.

- [ ] **Step 5: Commit**

```bash
git add src/user/.agents/skills/merge-guard/check-merge-eligibility.sh src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh
git commit -m "feat(merge-guard): untriaged non-thread-feedback blocker — durable union, ID-based exclusion (wgclw.14)"
```

---

### Task 18: Gate — prgroom internal atoms (+ never the rollup)

Behavior: **when prgroom state exists, `merge_gates.no_blocker_items == false` or `merge_gates.last_error_clear == false` each block; the rolled-up `auto_merge_eligible` is NEVER consumed; absent prgroom = n/a, not a blocker.**

**Files:** same two as Task 17.

- [ ] **Step 1: Append the failing tests**

```bash
# ── Task 18: prgroom internal atoms ──────────────────────────────────────────
PG_BLOCKED='{"merge_gates":{"phase_is_quiesced":true,"last_error_clear":true,"no_blocker_items":false,"human_review_satisfied":true},"auto_merge_eligible":false}'
PG_ERROR='{"merge_gates":{"phase_is_quiesced":true,"last_error_clear":false,"no_blocker_items":true,"human_review_satisfied":true},"auto_merge_eligible":false}'
# rollup says GO but an atom says NO — proves the rollup is never consumed
PG_ROLLUP_LIES='{"merge_gates":{"phase_is_quiesced":true,"last_error_clear":true,"no_blocker_items":false,"human_review_satisfied":true},"auto_merge_eligible":true}'

out=$(run_script "$BASE_POLICY" FIXTURE_PRGROOM="$PG_BLOCKED"); rc=$?
assert "prgroom no_blocker_items=false blocks" "[ \$rc -eq 1 ]"
assert "blocker code prgroom_blocker" "jq -r '.blockers[].code' <<<\"\$out\" | grep -q prgroom_blocker"

out=$(run_script "$BASE_POLICY" FIXTURE_PRGROOM="$PG_ERROR"); rc=$?
assert "prgroom last_error_clear=false blocks" "[ \$rc -eq 1 ]"

out=$(run_script "$BASE_POLICY" FIXTURE_PRGROOM="$PG_ROLLUP_LIES"); rc=$?
assert "auto_merge_eligible=true never overrides an atom" "[ \$rc -eq 1 ]"

out=$(run_script "$BASE_POLICY"); rc=$?
assert "no prgroom state → n/a, eligible" "[ \$rc -eq 0 ]"
assert "prgroom_available false" "[ \"\$(jq '.facts.prgroom_available' <<<\"\$out\")\" = false ]"
```

- [ ] **Step 2: Run to verify the new asserts fail** (prgroom fixtures currently ignored)

- [ ] **Step 3: Implement** — replace `# GATE: prgroom-internal        (Task 18)` with:

```bash
# ── Blockers: prgroom internal state (ADDITIONAL sources, never substitutes
#    for the live thread / non-thread checks; the rolled-up auto_merge_eligible
#    is never consumed — two of its four gates are unsuitable here) ───────────
prgroom_available=false
if command -v prgroom >/dev/null 2>&1; then
    if pg_status=$(prgroom status --json 2>/dev/null) && [[ -n "$pg_status" ]] \
       && jq -e '.merge_gates' >/dev/null 2>&1 <<<"$pg_status"; then
        prgroom_available=true
        [[ "$(jq -r '.merge_gates.no_blocker_items' <<<"$pg_status")" == "false" ]] \
            && add_blocker prgroom_blocker "prgroom reports escalated/failed item(s) (merge_gates.no_blocker_items=false)"
        [[ "$(jq -r '.merge_gates.last_error_clear' <<<"$pg_status")" == "false" ]] \
            && add_blocker prgroom_error "prgroom reports a terminal lifecycle error (merge_gates.last_error_clear=false)"
    fi
fi
set_fact prgroom_available "$prgroom_available"
```

- [ ] **Step 4: Run the FULL suite to verify everything passes together**

Run: `bash src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh`
Expected: PASS — every assert from Tasks 7-18.

- [ ] **Step 5: Commit**

```bash
git add src/user/.agents/skills/merge-guard/check-merge-eligibility.sh src/user/.agents/skills/merge-guard/check-merge-eligibility_test.sh
git commit -m "feat(merge-guard): prgroom atomic blockers — rollup never consumed (wgclw.14)"
```

---

### Task 19: merge-guard SKILL.md rewrite — Axis 2 enforcement

The script now owns every deterministic fact; the skill owns the authorization judgment. This task replaces the SKILL.md body. (`finishing-a-development-branch` needs **no change** — it already stops at PR creation and hands merge decisions here; that satisfies the spec's third live-wiring consumer.)

**Files:**
- Rewrite: `src/user/.agents/skills/merge-guard/SKILL.md`

- [ ] **Step 1: Replace the file body** (keep the existing frontmatter's `model:`/`effort:` lines; update `description:`):

````markdown
---
name: merge-guard
description: >
  Pre-merge enforcement point for the repo's review/merge policy. Resolves the
  policy (resolve_policy.py), computes the live eligibility floor + review
  facts (check-merge-eligibility.sh), then applies the merge-authorization
  axis: never / explicit (default) / rule-based. Invoke proactively before
  any `gh pr merge`, `git merge`, or merge action.
model: sonnet[1m]
effort: low
---

# Merge Guard

Enforces the two-axis review/merge policy at the merge boundary. A merge
happens **iff the PR is eligible (no blockers) AND the action is authorized
(Axis 2)**. Contract: `docs/architecture/review-merge-policy/design.md`.

**Triggers:** any action that merges a PR — `gh pr merge`, merge buttons,
`git merge` of a PR branch.

**Don't use when:** merging local branches unrelated to a PR.

## The Process

### Step 1: Determine PR context

Identify `owner`, `repo`, PR number (explicit argument, conversation context,
or `gh pr view --json number,url`), and the repo root.

### Step 2: Resolve the policy

```bash
POLICY_JSON=$(python3 "${CLAUDE_SKILL_DIR}/resolve_policy.py" \
  --project-config "<repo-root>/project-config.toml" \
  --labels "<comma-separated bead labels, or empty>")
```

- Labels: when working a bead, `bd label list <bead-id> --json | jq -r 'join(",")'`;
  otherwise pass `--labels ""`.
- Resolver exit 1 = invalid policy config. **Stop. Report the error verbatim.
  Do not merge, do not fall back to defaults** — a repo that misconfigured its
  merge policy must not get a silently different one.
- python3 (>= 3.11) unavailable → treat as the built-in default policy
  (`explicit`) and say so: that is exactly today's law, the safe floor.

### Step 3: Run the eligibility check

```bash
${CLAUDE_SKILL_DIR}/check-merge-eligibility.sh \
  --owner <owner> --repo <repo> --pr <n> --policy-json "$POLICY_JSON"
```

| Exit | Meaning |
|------|---------|
| 0 | Eligible — no blockers; facts populated |
| 1 | Blocked — every reason in `.blockers[]` |
| 3 | Error — unknown state. Report it. **Do not merge.** |

The JSON carries: `head_ref_oid` (the SHA every fact was computed against),
`blockers[]` (`{code, details}`), `facts` (`bot_clean_review_at_head`,
`distinct_current_approvers`, `ci_state`, `review_wait`, ...), and
`merge_command_hint`.

### Step 4: Apply Axis 2 (`merge_authorization` from the policy JSON)

**`never`** — the agent never merges, not even on an in-session instruction.
If the user says "merge it", refuse with: this repo's policy is human-manual
merge; share the eligibility summary so they can merge in the GitHub UI.
Force-merge is NOT available.

**`explicit`** (default) — merge iff **eligible AND the human gave an explicit
in-session instruction**. Authorized phrases: "go ahead and merge", "merge
it", "ship it", "yes merge". "ok"/"sure" are not sufficient.
- Eligible + no instruction → present the summary and wait:
  > "PR #N is eligible to merge — no blockers. `review_wait`: <facts>. Ready
  > when you are. Just say the word."
- Instructed + blocked → **fail closed.** Report every `blockers[]` entry and
  offer:
  > 1. **Wait** — invoke `wait-for-pr-comments` (poll, classify, fix, push,
  >    reply, resolve), then re-run this guard.
  > 2. **Force merge** — see below.
- **Force-merge (the ONE eligibility-bypass path):** valid only in `explicit`
  mode, only on a fresh in-session instruction that (a) uses the words "force
  merge" and (b) names the blocker being overridden (e.g. "force merge past
  the pending Copilot review"). A bare "force merge" → ask which blocker they
  are overriding, then proceed and log both the blockers bypassed and the
  instruction into the merge commit context / PR comment. Never available to
  `never`, `rule-based`, or any autonomous path.

**`rule-based`** — merge autonomously iff **eligible AND the configured
`merge_rule` holds** (evaluated from `facts`):

| Rule | Holds when |
|------|-----------|
| `bot-quiescence` | `facts.bot_clean_review_at_head == true` (a trusted `bot-reviewers` identity actually reviewed the current head clean) |
| `human-approvals` | `facts.distinct_current_approvers >= human_approvers_required` |
| `agent-ruling` | Never (design-reserved) — the resolver already rejects it; if somehow reached, report "not implemented" and hand off |

- Rule holds + eligible → merge now (Step 5). Announce what authorized it:
  > "Merging PR #N under rule-based policy (`bot-quiescence`): Copilot
  > reviewed head <sha> clean, no blockers."
- Rule not (yet) satisfied or blocked → report status and stop. NO
  force-merge in this mode. A timed-out bot (`review_wait.bot ==
  "timed_out"`) never satisfies the rule — hand off to the human with the
  facts.

### Step 5: Merge, bound to the checked head

```bash
gh pr merge <n> --squash --match-head-commit "<head_ref_oid from the JSON>"
```

- Use `merge_command_hint` from the JSON — it already carries the SHA.
- GitHub rejects the merge if the head moved since evaluation → **re-run from
  Step 3** against the new head. Never retry blind.
- `gh pr merge` can exit 0 while printing a rejection. Confirm:
  `gh pr view <n> --json state` (expect `MERGED`).

## Decision Matrix

| Axis 2 | Eligible | Rule holds | Human instructed | Action |
|---|---|---|---|---|
| never | any | n/a | any (even "merge it") | Refuse; human merges in UI |
| explicit | yes | n/a | no | Summarize; wait for the word |
| explicit | yes | n/a | yes | **Merge** |
| explicit | no | n/a | yes | **Fail closed**; offer wait / named force-merge |
| rule-based | yes | yes | n/a | **Merge autonomously** |
| rule-based | yes | no | any | Report; wait or hand off (no force-merge) |
| rule-based | no | any | any | Report blockers (no force-merge) |

## Red Flags

| Thought | Reality |
|---------|---------|
| "Copilot is slow, just merge" | The in-flight blocker exists precisely for this. Wait or get a named force-merge. |
| "The user said 'ok', close enough" | Not an authorized phrase. Ask plainly. |
| "auto_merge_eligible was true" | prgroom's rollup is never consumed. Only this guard's own gates count. |
| "The rule held five minutes ago" | Facts bind to `head_ref_oid`. Re-run Step 3; merge with `--match-head-commit`. |
| "It's blocked but rule-based says merge" | Rule-based NEVER bypasses the floor. Eligible AND rule — both. |
| "The script errored, probably fine" | Exit 3 = unknown state. Do not merge. Report. |
| "`gh pr merge` exited 0, so it merged" | It can exit 0 on rejection. Confirm state == MERGED. |
````

- [ ] **Step 2: Verify internal consistency**

Run: `grep -c "comments-seen\|Comments Seen" src/user/.agents/skills/merge-guard/SKILL.md`
Expected: 0 (the retired heuristic is gone from the skill too).

- [ ] **Step 3: Commit**

```bash
git add src/user/.agents/skills/merge-guard/SKILL.md
git commit -m "feat(merge-guard): SKILL.md enforces Axis 2 — never/explicit/rule-based, named force-merge (wgclw.14)"
```

---

### Task 20: wait-for-pr-comments — policy entry (Axis 1 drives polling)

**Files:**
- Modify: `src/user/.agents/skills/wait-for-pr-comments/SKILL.md` (Phase 1, after the concurrency-check step ~line 107)

- [ ] **Step 1: Insert a new Phase-1 step 5** immediately after the concurrency-check step (step 4, ending "If none found, proceed."):

```markdown
5. **Resolve the review policy** (Axis 1 decides whether and what to poll):
   ```bash
   POLICY_JSON=$(python3 "${CLAUDE_SKILL_DIR}/../merge-guard/resolve_policy.py" \
     --project-config "<repo-root>/project-config.toml" \
     --labels "<comma-separated bead labels, or empty>")
   ```
   (`--labels`: in `--mode autonomous`, `bd label list <bead-id> --json | jq -r 'join(",")'`;
   interactive without a bead → `""`.)
   - Resolver exit 1 → fatal startup error; report the resolver's stderr
     verbatim. A repo with an invalid review policy must not silently poll
     under a different one.
   - python3 (>= 3.11) or the resolver missing → proceed with the built-in
     default policy (bot expected / explicit merge) and say so — identical to
     this skill's historical behavior.
   - **`bot_review_expected == false` and `human_approvers_required == 0`**:
     nothing is expected — SKIP Phase 2 entirely (no polling) and proceed
     directly to Phase 3 to inventory any already-present feedback. Do NOT
     emit a human-handoff status: nothing human is expected; whether a merge
     may proceed is merge-guard's question, not this skill's.
   - **`bot_review_expected == false` but `human_approvers_required > 0`**:
     skip Copilot polling (Phase 2); inventory + triage existing feedback
     (Phases 3-8); at Phase 9, end with the terminal status
     "awaiting human review (<n> approval(s) required)" — parked, not
     blocking, not an error.
   - **`bot_review_expected == true`**: run Phase 2 as written. On
     `copilot_review_timeout`, the timeout ends the wait — it never counts as
     a review having happened (merge-guard's in-flight gate makes the same
     call independently at merge time).
```

- [ ] **Step 2: Update the Phase-9 completion messaging.** In Phase 9, after the (Task-14-rewritten) step 4, add:

```markdown
5. **Terminal status:** if the resolved policy has `human_approvers_required > 0`
   and that many distinct current approvals have not arrived, report
   "awaiting human review (<n> required)" as the terminal status. Otherwise
   report the normal completion summary. Never report a human-handoff status
   when nothing human is expected.
```

- [ ] **Step 3: Verify by grep**

Run: `grep -n "resolve_policy.py" src/user/.agents/skills/wait-for-pr-comments/SKILL.md`
Expected: the Phase-1 insertion (one hit, `../merge-guard/` path).

- [ ] **Step 4: Commit**

```bash
git add src/user/.agents/skills/wait-for-pr-comments/SKILL.md
git commit -m "feat(wait-for-pr-comments): Axis-1 policy entry — poll iff a review is expected (wgclw.14)"
```

---

### Task 21: The merge-authorization law amendment

Five real locations (the spec's "delivery rule" has no source file — see deviation ledger #1). Each edit preserves `explicit` as the default so no repo silently gains merge autonomy.

**Files:**
- Modify: `src/user/.agents/INSTRUCTIONS.md.template:59`
- Modify: `src/user/.agents/rules/completion-gate.md:15`
- Modify: `src/user/.agents/skills/monitor-pr/SKILL.md:10-13` and `:99-101`
- Modify: `src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md:28`

- [ ] **Step 1: `INSTRUCTIONS.md.template:59`** — replace:

```markdown
- **No unauthorized merges**: Creating a PR is not authorization to merge. Merge only when the user explicitly says so ("go ahead and merge", "merge it", etc.). When in doubt, they have not authorized it.
```

with:

```markdown
- **Merge authorization policy**: The agent's merge authority for a repository is set by its merge-authorization policy: `never` (the agent never merges), `explicit` (default — merge only on an explicit in-session human instruction: "go ahead and merge", "merge it", etc.), or `rule-based` (autonomous merge only when the repo's configured merge-rule AND the eligibility predicate both hold — a deliberate, named opt-in enforced by merge-guard). Absent configuration, `explicit` applies unchanged: creating a PR is not authorization to merge, and when in doubt, the user has not authorized it.
```

- [ ] **Step 2: `completion-gate.md:15`** — in the HARD STOP paragraph, replace the final sentence fragment:

```markdown
Pause only at the merge step: merging needs explicit authorization ("merge it" / "ship it" / "go ahead and merge"); everything up to and including PR creation is automatic.
```

with:

```markdown
Pause only at the merge step: merging follows the repo's merge-authorization policy via merge-guard — `explicit` (default) needs a human instruction ("merge it" / "ship it" / "go ahead and merge"); `rule-based` repos merge autonomously when the configured rule and eligibility both hold; `never` repos hand off to the human. Everything up to and including PR creation is automatic.
```

- [ ] **Step 3: `monitor-pr/SKILL.md`** — two edits:

(a) Frontmatter description (lines 10-13), replace:

```yaml
  merge gate. Do NOT use to merge a PR — merge authorization stays with the
  human.
```

with:

```yaml
  merge gate. Do NOT use to merge a PR — merge authorization is governed by
  the repo's merge-authorization policy, enforced by the merge-guard skill
  (default: explicit human instruction).
```

(b) Lines 99-101, replace:

```markdown
- **Do not merge on `auto_merge_eligible: true`.** That flag is a handoff signal
  for a future merge gate, not a license to merge. Merge authorization is the
  human's.
```

with:

```markdown
- **Do not merge on `auto_merge_eligible: true`.** That rollup is never
  consumed — merge-guard recomputes its own atomic gates live. Merge
  authorization is governed by the repo's merge-authorization policy via the
  merge-guard skill (default: explicit human instruction).
```

- [ ] **Step 4: `reply-and-resolve-pr-threads/SKILL.md:28`** — replace:

```markdown
**MERGE PROHIBITION:** Resolving threads is NOT authorization to merge. The orchestrator never merges; the user does, on explicit say-so.
```

with:

```markdown
**MERGE PROHIBITION:** Resolving threads is NOT authorization to merge. This skill never merges; merge authority belongs to the merge-guard skill under the repo's merge-authorization policy (default: explicit human say-so).
```

- [ ] **Step 5: Sweep for stragglers** (per the sweep-all-refs rule):

Run: `grep -rn "authorization stays with the human\|Merge authorization is the human's\|No unauthorized merges" src/`
Expected: no hits.

- [ ] **Step 6: Commit**

```bash
git add src/user/.agents/INSTRUCTIONS.md.template src/user/.agents/rules/completion-gate.md src/user/.agents/skills/monitor-pr/SKILL.md src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md
git commit -m "feat(rules): merge-authorization law names its two opt-outs; explicit stays the default (wgclw.14)"
```

---

### Task 22: Full verification + housekeeping

- [ ] **Step 1: Run the complete smoke suite** (the `[gates].test` command):

```bash
find src/user/.agents/skills src/user/.claude/hooks -name '*_test.sh' -print0 | sort -z | xargs -0 -I{} sh -c 'echo "[TEST] $1"; bash "$1" || exit 1' _ {}
```

Expected: every suite passes, including the three new/extended ones. Any failure = fix before proceeding.

- [ ] **Step 2: Resolver sanity against the live repo config**

Run: `python3 src/user/.agents/skills/merge-guard/resolve_policy.py --project-config project-config.toml`
Expected: exit 0, `merge_rule: "bot-quiescence"`.

- [ ] **Step 3: Update the knowledge graph** (code files changed):

```bash
graphify update .
```

- [ ] **Step 4: Bead housekeeping**

```bash
# Label-authoring dependency named by the spec (7bk.12 authors the labels this resolver consumes)
bd dep add agents-config-wgclw.14 agents-config-7bk.12 --type related-to

# Discovered work — orphans with provenance (sibling test: none were in wgclw.14's original scope)
bd create --title="agent-ruling merge-rule: independent AI merge-judge harness" \
  --description="Implement the design-reserved agent-ruling merge-rule from docs/architecture/review-merge-policy/design.md: an independent cross-model agent renders a merge go/no-go verdict at the merge gate (reuses RALF/codex-review machinery). The resolver currently rejects agent-ruling as not-implemented." \
  --type=feature --priority=P2
bd dep add <new-id> agents-config-wgclw.14 --type discovered-from

bd create --title="Installed ~/.claude/rules/delivery.md is orphaned (no source in src/)" \
  --description="The installed delivery.md (Action Categories, REQUIRES EXPLICIT AUTHORIZATION) has no source under src/ — only archive/. It now also states the OLD merge law. Decide: re-home a source, or remove from installs. Found while amending the merge-authorization law (wgclw.14)." \
  --type=task --priority=P2
bd dep add <new-id> agents-config-wgclw.14 --type discovered-from

bd create --title="wait-for-pr-comments SKILL.md guard-numbering off-by-one vs validate-inventory.sh" \
  --description="A/SKILL.md's narrative guard list (~819-852) numbers guards off-by-one vs the authoritative script labels (script guard 3 = narrative #4). Align the narrative list to script numbering." \
  --type=task --priority=P3
bd dep add <new-id> agents-config-wgclw.14 --type discovered-from

bd create --title="poll-copilot-review.sh: consider bot-reviewers-driven filter" \
  --description="Polling still matches Copilot by substring (COPILOT_REVIEW_FILTER). Harmless (detection, not a trust boundary — merge enforcement uses the exact-identity allowlist), but aligning the poll filter to the policy's bot-reviewers list would generalize polling to non-Copilot bots. Optional." \
  --type=task --priority=P3
bd dep add <new-id> agents-config-wgclw.14 --type discovered-from
```

- [ ] **Step 5: Update the bead and close out the plan**

```bash
bd update agents-config-wgclw.14 --append-notes "Implementation plan executed: docs/plans/2026-07-01-pr-review-merge-policy.md. All 22 tasks complete; full smoke suite green."
```

Then run the completion gate (quality-reviewer → address → simplify → address → verify-checklist) and deliver per the delivery rules (PR creation is automatic; **merging this PR follows the very policy it implements — agents-config is `rule-based`/`bot-quiescence` only AFTER this lands and is installed; until then today's explicit law applies**).

---

## Self-review (per writing-plans)

**Spec coverage** — Deliverable 1 (HLD) → Task 1; 2 (resolver + tests) → Tasks 2-5; 3 (eligibility extension: in-flight, exact bot identity, distinct approvers, sticky requested-changes, live threads, non-thread feedback + durable union + schema `review_id`, freshness + `--match-head-commit`, prgroom atoms, CI-green from branch protection with source pins) → Tasks 7-13 + 15 + 17-18; 4 (live wiring: wait-for-pr-comments → Task 20 + 14, merge-guard → Task 19, finishing-a-development-branch → no-change verified in Task 19 prose) → done; 5 (label parsing) → Task 5; 6 (law amendment) → Task 21; 7 (toml restructure + stale §5.1 fix) → Task 6. Freshness invariant → Tasks 7 (head fetch + hint), 8/10 (head-bound facts), 19 Step 5 (re-eval on rejection). Reply-ID recording → Task 16. Testing-section behaviors → mapped across task test blocks.

**Known gaps (accepted, documented):** GraphQL thread pagination has a cursor loop but no multi-page test fixture (stub is single-page); prgroom per-item-disposition fallback not implementable from the status envelope (ground truth) — inventory union is the durable source; `review_wait` human reference time uses PR `created_at` (not per-request-event time) — conservative in the blocking direction.

**Placeholder scan** — no TBD/TODO/"similar to Task N"; every code step carries the code. Task 16 Step 3(b) contains one bracketed keep-verbatim marker for the pre-existing sidecar block — that block is quoted in full in this plan's Ground Truth source (post-replies.sh:224-238) and must be preserved byte-for-byte, not rewritten.

**Type consistency** — policy JSON keys (`bot_review_expected`, `bot_reviewers`, `bot_inactivity_timeout_seconds`, `human_approvers_required`, `human_review_timeout_seconds`, `merge_authorization`, `merge_rule`) identical across resolver output (Task 2), script parsing (Task 7), and SKILL.md wiring (Tasks 19-20). Eligibility JSON keys (`status`, `head_ref_oid`, `blockers[].code/details`, `facts.*`, `merge_command_hint`) identical across Tasks 7-18 and Task 19's tables. Blocker codes: `requested_changes_active`, `unresolved_threads`, `untriaged_feedback`, `review_in_flight`, `ci_not_green`, `prgroom_blocker`, `prgroom_error` — each defined once, referenced consistently. Inventory fields `review_id` (Task 15) and `posted_reply_id` (Task 16) match Task 17's union exactly.



