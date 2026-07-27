from __future__ import annotations

from curriculum_agent.models import StakeholderType

# Evidence classes that carry weight in the demand score. `want` is excluded on
# purpose: a nice-to-have must not push a capability into the main PLO set.
# `unclassified` counts as `need` so an LLM classification failure degrades
# toward inclusion rather than silently dropping real evidence.
WEIGHTED_CLASSES = {"requirement", "need", "unclassified"}

FREQ_WEIGHT = 0.6
BREADTH_WEIGHT = 0.4


def compute_demand_score(
    source_evidence_ids: list[str],
    stakeholder_coverage: dict[str, int],
    total_req_need_evidence: int,
    classification_by_evidence: dict[str, str],
) -> tuple[float, bool, dict[str, int]]:
    """Score a set of evidence by weighted frequency and stakeholder breadth.

    Returns (demand_score, is_optional, classification_coverage). `is_optional`
    is True when want-evidence outnumbers requirement+need evidence, marking the
    group as supplementary rather than core.
    """
    coverage: dict[str, int] = {}
    weighted = 0
    want = 0
    for eid in set(source_evidence_ids):
        cls = classification_by_evidence.get(eid, "unclassified")
        coverage[cls] = coverage.get(cls, 0) + 1
        if cls in WEIGHTED_CLASSES:
            weighted += 1
        elif cls == "want":
            want += 1

    freq = weighted / max(total_req_need_evidence, 1)
    breadth = len(stakeholder_coverage) / max(len(StakeholderType), 1)
    score = round(min(freq * FREQ_WEIGHT + breadth * BREADTH_WEIGHT, 1.0), 4)
    return score, want > weighted, coverage
