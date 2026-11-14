"""Need statistics derived from the evidence a Need cites (single-agent mode).

A single-mode Need has no skill rows, so everything the multi pipeline reads off
skills (demand score, stakeholder types, requirement/need/want, optional) comes
from the cited evidence items here. Pure code: no DB, no LLM, no settings.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Literal

from pydantic import BaseModel

from curriculum_agent.models import StakeholderType
from curriculum_agent.stages.demand import (
    build_scoring_corpus,
    compute_demand_score,
    is_optional_group,
)
from curriculum_agent.stages.stakeholder_needs import classify_evidence_type


class EvidenceNeedStats(BaseModel):
    source_stakeholder_types: list[StakeholderType]
    stakeholder_coverage: dict[StakeholderType, int]
    freq: int
    demand_score: float
    classification: Literal["requirement", "need", "want"]
    classification_coverage: dict[str, int]
    is_optional: bool


def scoring_corpus_for(
    cited_ids: Iterable[str], type_by_evidence: Mapping[str, StakeholderType]
) -> dict[str, str]:
    """The demand-score corpus: every evidence id cited by any Need of the run."""
    return build_scoring_corpus((eid, type_by_evidence[eid].value) for eid in set(cited_ids))


def derive_need_stats(
    evidence_ids: Sequence[str],
    type_by_evidence: Mapping[str, StakeholderType],
    corpus: Mapping[str, str],
) -> EvidenceNeedStats:
    """Score one Need from the evidence items it cites.

    An id missing from `type_by_evidence` is a caller bug (`KeyError`); callers
    validate ids first. Duplicate ids count once.
    """
    ids = list(dict.fromkeys(evidence_ids))
    if not ids:
        raise ValueError("a Need must cite at least one evidence item")
    types = [type_by_evidence[eid] for eid in ids]

    coverage: dict[StakeholderType, int] = {}
    for t in types:
        coverage[t] = coverage.get(t, 0) + 1
    present = set(types)

    freq = len(ids)
    if any(classify_evidence_type(t) == "requirement" for t in types):
        classification: Literal["requirement", "need", "want"] = "requirement"
    elif freq > 1:
        classification = "need"
    else:
        classification = "want"
    class_coverage: dict[str, int] = {classification: 1}

    return EvidenceNeedStats(
        source_stakeholder_types=[t for t in StakeholderType if t in present],
        stakeholder_coverage=coverage,
        freq=freq,
        demand_score=compute_demand_score(ids, dict(corpus)),
        classification=classification,
        classification_coverage=class_coverage,
        is_optional=is_optional_group(class_coverage, freq),
    )
