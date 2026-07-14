"""Cross-axis heat fusion — the §6.2 weighted average over complexity,
load-bearing, and consequence (distinct from the per-axis extractors, which
stay untouched here).

`combine()` fuses the three finished axes into one per-file heat via a
user-tunable weighted average (slider semantics per §4.5: share-of-importance,
not a volume knob — a file weak on an axis cools as that axis gains weight).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from vizsuite.envelope import JsonValue
from vizsuite.extract.centrality import CentralityAxis
from vizsuite.scene.model import AttributeDescriptor

# Tunable cross-axis mix (spec §6.2). The tested invariants are share-of-
# importance cooling and renormalization-on-unavailable — never these specific
# numbers.
DEFAULT_WEIGHTS: Mapping[str, float] = {
    "complexity": 0.4,
    "load_bearing": 0.35,
    "consequence": 0.25,
}

_HEAT_AXES = ("complexity", "load_bearing", "consequence", "heat")
_AXIS_UNIT = "0-1"
_AXIS_DIRECTION = "higher_is_hotter"


@dataclass(frozen=True)
class HeatModel:
    """The combined cross-axis fusion result for one estate (spec §6.2/§4.4).

    `attributes` maps each estate path to its per-axis values, combined heat,
    and PR membership (`in_pr`). `descriptors` self-describes the four
    heat-bearing attributes only — `in_pr` is a membership flag, not a 0-1
    heat axis. `default_weights` is the effective weight mix this `combine()`
    call used (the UI's slider starting positions); `unavailable_axes` lists
    axes to render disabled.
    """

    attributes: dict[str, dict[str, JsonValue]]
    descriptors: tuple[AttributeDescriptor, ...]
    default_weights: dict[str, float]
    unavailable_axes: tuple[str, ...]


def combine(
    estate: Mapping[str, str],
    complexity_scores: Mapping[str, float],
    consequence_scores: Mapping[str, float],
    centrality: CentralityAxis,
    pr_files: Collection[str],
    *,
    weights: Mapping[str, float] | None = None,
) -> HeatModel:
    """Fuse the three §6.2 axes into one per-file heat, weighted-average style.

    ``heat = Σ(wᵢ·vᵢ) / Σ(wᵢ)``. A file absent from a per-file score map
    (complexity/consequence/load-bearing alike) contributes a real zero.
    """
    effective_weights = dict(weights) if weights is not None else dict(DEFAULT_WEIGHTS)
    # Load-bearing drops out of the mix entirely — weight excluded, not just
    # zeroed — exactly when the axis itself is unavailable; the remaining two
    # axes renormalize over their own weight sum (spec §6.2: "weight controls
    # exclude it; never report a stale graph as post-PR centrality").
    unavailable_axes = () if centrality.is_available else ("load_bearing",)
    active_weights = {
        axis: weight for axis, weight in effective_weights.items() if axis not in unavailable_axes
    }
    weight_total = sum(active_weights.values())
    centrality_scores = centrality.scores or {}

    attributes: dict[str, dict[str, JsonValue]] = {}
    for path in estate:
        values = {
            "complexity": complexity_scores.get(path, 0.0),
            "load_bearing": centrality_scores.get(path, 0.0),
            "consequence": consequence_scores.get(path, 0.0),
        }
        weighted_sum = sum(active_weights[axis] * values[axis] for axis in active_weights)
        heat_value = weighted_sum / weight_total if weight_total > 0 else 0.0
        attributes[path] = {**values, "heat": heat_value, "in_pr": path in pr_files}

    descriptors = tuple(
        AttributeDescriptor(name=name, unit=_AXIS_UNIT, direction=_AXIS_DIRECTION)
        for name in _HEAT_AXES
    )
    return HeatModel(
        attributes=attributes,
        descriptors=descriptors,
        default_weights=effective_weights,
        unavailable_axes=unavailable_axes,
    )
