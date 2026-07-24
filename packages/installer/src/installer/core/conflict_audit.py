"""The deploy-time conflict audit (S3, charter D16 / AC2).

A deployed artifact may declare a ``claims`` mapping in its front matter —
``<claim-key>: <value>`` — where a claim-key names a fact about the live
workflow (e.g. ``pr-review-medium: verdict-artifact``). The audit reconciles
every admitted artifact's claims: if two artifacts assert *distinct* values for
the same key, that pair is a conflict and the deploy aborts.

This is the deliberately simple first implementation the charter sanctioned —
a pairwise key/value lint, not semantic (NLI) conflict detection over prose.
With zero admitted claimants (the zero-base state) the audit is vacuously
green.
"""

from __future__ import annotations


def conflict_violations(claims_by_artifact: list[tuple[str, dict[str, str]]]) -> list[str]:
    """Violation messages for claim-keys asserted with conflicting values.

    ``claims_by_artifact`` is ``(label, claims)`` per admitted artifact. For
    each claim-key carrying more than one distinct value across artifacts, emit
    one message naming the key, each value, and the artifact(s) asserting it.
    The scan is deterministic: keys and values are reported in sorted order so
    the message is stable across runs.
    """
    # key -> value -> sorted labels asserting it
    by_key: dict[str, dict[str, list[str]]] = {}
    for label, claims in claims_by_artifact:
        for key, value in claims.items():
            by_key.setdefault(key, {}).setdefault(value, []).append(label)

    out: list[str] = []
    for key in sorted(by_key):
        values = by_key[key]
        if len(values) > 1:
            rendered = "; ".join(
                f"{value!r} ({', '.join(sorted(values[value]))})" for value in sorted(values)
            )
            out.append(f"conflicting claim '{key}': {rendered}")
    return out
