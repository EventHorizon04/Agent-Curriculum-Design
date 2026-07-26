from __future__ import annotations

from curriculum_agent.models import Need, ProgramMetadata
from curriculum_agent.prompts.stage_3_plo import build_plo_synthesis_prompt
from curriculum_agent.stages import plo_synthesis as ps


def test_plo_count_bounds():
    assert ps._MIN_PLOS == 6
    assert ps._MAX_PLOS == 10


def test_draft_list_enforces_bounds():
    fields = ps._PLODraftList.model_fields["plos"]
    metadata = {m.__class__.__name__: m for m in fields.metadata}
    assert metadata["MinLen"].min_length == 6
    assert metadata["MaxLen"].max_length == 10


def test_synthesis_prompt_asks_for_6_to_10(
    sample_metadata: ProgramMetadata, sample_needs: list[Need]
):
    msgs = build_plo_synthesis_prompt(sample_metadata, sample_needs)
    assert "6-10" in msgs[0]["content"]
    assert "4-6" not in msgs[0]["content"] + msgs[1]["content"]
