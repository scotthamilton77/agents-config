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
