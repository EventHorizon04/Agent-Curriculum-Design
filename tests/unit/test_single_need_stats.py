from __future__ import annotations

import pytest

from curriculum_agent.models import StakeholderType
from curriculum_agent.stages.demand import compute_demand_score
from curriculum_agent.stages.single_need_stats import derive_need_stats, scoring_corpus_for

TYPES: dict[str, StakeholderType] = {
    "e1": StakeholderType.PROFESSIONAL_COUNCIL,
    "e2": StakeholderType.EMPLOYER,
    "e3": StakeholderType.ALUMNI,
    "e4": StakeholderType.INSTITUTIONAL_DIRECTION,
    "e5": StakeholderType.EMPLOYER,
}
CORPUS = scoring_corpus_for(TYPES.keys(), TYPES)


def test_requirement_when_any_cited_item_is_council_or_institutional() -> None:
    s = derive_need_stats(["e1", "e2"], TYPES, CORPUS)
    assert s.classification == "requirement" and s.is_optional is False
    assert s.classification_coverage == {"requirement": 1}
    inst = derive_need_stats(["e4", "e2"], TYPES, CORPUS)
    assert inst.classification == "requirement"


def test_two_general_items_is_need_one_is_want_and_optional() -> None:
    two = derive_need_stats(["e2", "e3"], TYPES, CORPUS)
    assert two.classification == "need" and two.is_optional is False
    one = derive_need_stats(["e2"], TYPES, CORPUS)
    assert (one.classification, one.is_optional, one.freq) == ("want", True, 1)


def test_demand_score_equals_compute_demand_score() -> None:
    ids = ["e1", "e2", "e3"]
    s = derive_need_stats(ids, TYPES, CORPUS)
    assert s.demand_score == compute_demand_score(ids, dict(CORPUS))


def test_duplicate_ids_count_once() -> None:
    s = derive_need_stats(["e2", "e2", "e5", "e2"], TYPES, CORPUS)
    assert s.freq == 2
    assert s.stakeholder_coverage == {StakeholderType.EMPLOYER: 2}
    assert s.classification == "need"


def test_types_are_distinct_and_in_enum_order() -> None:
    s = derive_need_stats(["e4", "e3", "e2", "e5"], TYPES, CORPUS)
    cited = {
        StakeholderType.INSTITUTIONAL_DIRECTION,
        StakeholderType.ALUMNI,
        StakeholderType.EMPLOYER,
    }
    assert s.source_stakeholder_types == [t for t in StakeholderType if t in cited]
    assert s.stakeholder_coverage[StakeholderType.EMPLOYER] == 2


def test_unknown_evidence_id_raises_key_error() -> None:
    with pytest.raises(KeyError):
        derive_need_stats(["e2", "nope"], TYPES, CORPUS)


def test_empty_ids_raise_value_error() -> None:
    with pytest.raises(ValueError):
        derive_need_stats([], TYPES, CORPUS)


def test_corpus_only_holds_cited_ids() -> None:
    corpus = scoring_corpus_for(["e1", "e1", "e2"], TYPES)
    assert corpus == {"e1": "professional_council", "e2": "employer"}
