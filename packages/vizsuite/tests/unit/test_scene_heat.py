"""Cross-axis heat fusion (spec §6.2/§4.5): the weighted average over
complexity, load-bearing, and consequence, plus PR-membership and
self-describing metadata.

Tests pin the *invariants* the spec cares about — the weighted-average
formula, share-of-importance cooling, renormalization when the load-bearing
axis is unavailable, and the real-zero-vs-unavailable distinction — never the
tunable `DEFAULT_WEIGHTS` values themselves.
"""

from __future__ import annotations

import pytest

from vizsuite.extract.centrality import CentralityAxis
from vizsuite.scene.heat import DEFAULT_WEIGHTS, combine

_ESTATE = {"a.py": "sha_a", "b.py": "sha_b", "c.py": "sha_c"}
_COMPLEXITY = {"a.py": 0.2, "b.py": 0.8, "c.py": 0.5}
_CONSEQUENCE = {"a.py": 0.0, "b.py": 1.0, "c.py": 0.5}


def _available_centrality() -> CentralityAxis:
    return CentralityAxis(scores={"a.py": 0.5, "b.py": 1.0, "c.py": 0.0})


def test_combine_computes_the_weighted_average_at_default_weights() -> None:
    model = combine(_ESTATE, _COMPLEXITY, _CONSEQUENCE, _available_centrality(), pr_files=set())

    weight_total = sum(DEFAULT_WEIGHTS.values())
    load_bearing = {"a.py": 0.5, "b.py": 1.0, "c.py": 0.0}
    for path in _ESTATE:
        expected = (
            DEFAULT_WEIGHTS["complexity"] * _COMPLEXITY[path]
            + DEFAULT_WEIGHTS["load_bearing"] * load_bearing[path]
            + DEFAULT_WEIGHTS["consequence"] * _CONSEQUENCE[path]
        ) / weight_total
        assert model.attributes[path]["heat"] == pytest.approx(expected)


def test_raising_weight_on_a_weak_axis_cools_the_file_weak_on_it() -> None:
    # a.py is weak on complexity (0.2) but strong on load-bearing/consequence.
    # Weighting heavily toward complexity must pull its heat DOWN toward 0.2 —
    # share-of-importance, not a volume knob (spec §4.5).
    weights_favoring_strong_axes = {"complexity": 0.1, "load_bearing": 0.45, "consequence": 0.45}
    weights_favoring_weak_axis = {"complexity": 0.8, "load_bearing": 0.1, "consequence": 0.1}

    model_low = combine(
        _ESTATE,
        _COMPLEXITY,
        _CONSEQUENCE,
        _available_centrality(),
        pr_files=set(),
        weights=weights_favoring_strong_axes,
    )
    model_high = combine(
        _ESTATE,
        _COMPLEXITY,
        _CONSEQUENCE,
        _available_centrality(),
        pr_files=set(),
        weights=weights_favoring_weak_axis,
    )

    heat_low = model_low.attributes["a.py"]["heat"]
    heat_high = model_high.attributes["a.py"]["heat"]
    assert isinstance(heat_low, float)
    assert isinstance(heat_high, float)
    assert heat_high < heat_low


def test_unavailable_centrality_drops_load_bearing_and_renormalizes() -> None:
    centrality = CentralityAxis.unavailable("graphify-out absent")
    estate = {"a.py": "sha_a"}
    complexity = {"a.py": 0.4}
    consequence = {"a.py": 0.6}

    model = combine(estate, complexity, consequence, centrality, pr_files=set())

    assert model.unavailable_axes == ("load_bearing",)
    weight_total = DEFAULT_WEIGHTS["complexity"] + DEFAULT_WEIGHTS["consequence"]
    expected = (
        DEFAULT_WEIGHTS["complexity"] * 0.4 + DEFAULT_WEIGHTS["consequence"] * 0.6
    ) / weight_total
    assert model.attributes["a.py"]["heat"] == pytest.approx(expected)
    # the attribute value is still a real zero — only the WEIGHT is excluded,
    # never silently reported as stale-as-fresh centrality.
    assert model.attributes["a.py"]["load_bearing"] == 0.0


def test_file_absent_from_available_centrality_scores_gets_a_real_zero() -> None:
    # Axis IS available; this file simply has no qualifying in-edges. Distinct
    # from axis-unavailable: the weight still counts, the value is a real 0.0.
    centrality = CentralityAxis(scores={"a.py": 0.9})  # b.py absent from scores
    estate = {"a.py": "sha_a", "b.py": "sha_b"}
    complexity = {"a.py": 0.5, "b.py": 0.5}
    consequence = {"a.py": 0.5, "b.py": 0.5}

    model = combine(estate, complexity, consequence, centrality, pr_files=set())

    assert model.unavailable_axes == ()
    assert model.attributes["b.py"]["load_bearing"] == 0.0
    weight_total = sum(DEFAULT_WEIGHTS.values())
    expected_b_heat = (
        DEFAULT_WEIGHTS["complexity"] * 0.5
        + DEFAULT_WEIGHTS["load_bearing"] * 0.0
        + DEFAULT_WEIGHTS["consequence"] * 0.5
    ) / weight_total
    assert model.attributes["b.py"]["heat"] == pytest.approx(expected_b_heat)


def test_in_pr_membership_reflects_the_net_file_set() -> None:
    estate = {"a.py": "sha_a", "b.py": "sha_b"}
    complexity = {"a.py": 0.5, "b.py": 0.5}
    consequence = {"a.py": 0.5, "b.py": 0.5}
    centrality = CentralityAxis.unavailable("no graph")

    model = combine(estate, complexity, consequence, centrality, pr_files={"a.py"})

    assert model.attributes["a.py"]["in_pr"] is True
    assert model.attributes["b.py"]["in_pr"] is False


def test_descriptors_name_all_four_heat_axes_not_in_pr() -> None:
    estate = {"a.py": "sha_a"}
    model = combine(
        estate, {"a.py": 0.5}, {"a.py": 0.5}, CentralityAxis.unavailable("x"), pr_files=set()
    )

    names = {descriptor.name for descriptor in model.descriptors}
    assert names == {"complexity", "load_bearing", "consequence", "heat"}


def test_default_weights_reflects_the_effective_weights_used() -> None:
    estate = {"a.py": "sha_a"}
    custom_weights = {"complexity": 0.5, "load_bearing": 0.3, "consequence": 0.2}

    model = combine(
        estate,
        {"a.py": 0.5},
        {"a.py": 0.5},
        CentralityAxis.unavailable("x"),
        pr_files=set(),
        weights=custom_weights,
    )

    assert model.default_weights == custom_weights
