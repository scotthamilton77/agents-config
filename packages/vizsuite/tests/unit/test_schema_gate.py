"""Schema gate: `scene.assemble.assemble` rejects a Tier-2/3 fact lacking
provenance or citations, loud and typed — never a silent default (spec test
item 8, plan slice 5). An accepted fact that later becomes doubted must carry
both independent axes (verdict + freshness) through assembly unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from vizsuite.envelope import ErrorCode, VizError
from vizsuite.scene.assemble import assemble
from vizsuite.scene.model import Fact, Freshness, Provenance, ProvenanceKind

_ESTATE = {"src/a.py": "sha_a"}


def _assemble(facts: Sequence[Fact] = ()):
    return assemble(
        _ESTATE,
        pr_number=1,
        generated_at="2020-01-01T00:00:00+00:00",
        generator="vizsuite/0.1.0",
        base_oid="base000",
        head_oid="head111",
        facts=facts,
    )


def test_fact_missing_provenance_is_rejected():
    fact = Fact(id="f1", note="a drill story")  # provenance=None: unvalidated

    with pytest.raises(VizError) as exc_info:
        _assemble(facts=[fact])

    assert exc_info.value.code == ErrorCode.SCHEMA_INVALID
    assert exc_info.value.detail["fact_id"] == "f1"


def test_fact_with_provenance_but_no_citations_is_rejected():
    fact = Fact(
        id="f2",
        note="an inferred edge",
        provenance=Provenance(kind=ProvenanceKind.INFERRED, citations=()),
    )

    with pytest.raises(VizError) as exc_info:
        _assemble(facts=[fact])

    assert exc_info.value.code == ErrorCode.SCHEMA_INVALID
    assert exc_info.value.detail["fact_id"] == "f2"


def test_accepted_then_doubted_fact_carries_both_axes_through_assembly():
    fact = Fact(
        id="f3",
        note="an accepted edge later doubted by a diff",
        provenance=Provenance(
            kind=ProvenanceKind.ACCEPTED,
            freshness=Freshness.DOUBTED,
            citations=("agents-config-yf2ov.2",),
        ),
    )

    scene = _assemble(facts=[fact])

    assert len(scene.facts) == 1
    carried = scene.facts[0].provenance
    assert carried is not None
    # both axes are independent and both survive assembly unchanged.
    assert carried.kind == ProvenanceKind.ACCEPTED
    assert carried.freshness == Freshness.DOUBTED
