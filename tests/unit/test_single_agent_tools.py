from __future__ import annotations

import json
from typing import Any

from curriculum_agent.models import BloomLevel, StakeholderEvidence, StakeholderType
from curriculum_agent.prompts.single_agent import NeedBrief
from curriculum_agent.stages.single_agent_tools import (
    CallTool,
    SingleToolContext,
    evidence_parts,
    run_single_tool,
)
from curriculum_agent.stages.smart_agent_tools import SiblingSummary


def _ctx(text: str = "ข้อความหลักฐาน", part_chars: int = 6000) -> SingleToolContext:
    evidence = StakeholderEvidence(
        evidence_id="e1",
        program_id="p",
        stakeholder_type=StakeholderType.EMPLOYER,
        source_name="บริษัท ก",
        raw_text_th=text,
    )
    need = NeedBrief(
        need_id="N1",
        statement_th="ต้องการบัณฑิตที่แปลเอกสารธุรกิจ",
        ksec_categories=("S",),
        bloom_level="apply",
        demand_score=0.5,
        stakeholder_types=("employer",),
        evidence_ids=("e1",),
    )
    return SingleToolContext(
        evidence_by_id={"e1": evidence}, needs_by_id={"N1": need}, plos=[], part_chars=part_chars
    )


def _call(tool: str, **kwargs: Any) -> CallTool:
    return CallTool(kind="call_tool", tool=tool, **kwargs)  # type: ignore[arg-type]


def test_get_evidence_pages_through_the_whole_text() -> None:
    ctx = _ctx(text="ก" * 250 + " " + "ข" * 250, part_chars=300)
    first = run_single_tool(ctx, _call("get_evidence", evidence_id="e1", part=1))
    second = run_single_tool(ctx, _call("get_evidence", evidence_id="e1", part=2))
    assert json.loads(first.payload_json)["parts"] == 2
    assert "ข" in json.loads(second.payload_json)["text"]
    assert first.evidence_id == "e1"
    assert ctx.read_parts == {("e1", 1), ("e1", 2)}


def test_evidence_parts_lose_nothing_and_never_return_empty() -> None:
    text = "คำ " * 400
    parts = evidence_parts(text, 100)
    assert "".join(parts) == text
    assert all(len(p) <= 100 for p in parts)
    assert evidence_parts("สั้น", 100) == ["สั้น"]
    assert evidence_parts("", 100) == [""]
    hard = evidence_parts("ก" * 250, 100)
    assert "".join(hard) == "ก" * 250 and len(hard) == 3


def test_get_evidence_part_out_of_range_is_an_error() -> None:
    r = run_single_tool(_ctx(), _call("get_evidence", evidence_id="e1", part=2))
    assert r.ok is False and r.error_th


def test_get_evidence_unknown_id_is_an_error_not_an_exception() -> None:
    r = run_single_tool(_ctx(), _call("get_evidence", evidence_id="nope"))
    assert r.ok is False and r.error_th and r.evidence_id is None


def test_get_need_and_need_detail_agree() -> None:
    ctx = _ctx()
    a = run_single_tool(ctx, _call("get_need", need_id="N1"))
    b = run_single_tool(ctx, _call("need_detail", need_id="N1"))
    assert a.ok and a.payload_json == b.payload_json
    assert json.loads(a.payload_json)["evidence_ids"] == ["e1"]
    assert run_single_tool(ctx, _call("get_need", need_id="zz")).ok is False


def test_check_hard_matches_smart_rules() -> None:
    ctx = _ctx()
    good = json.loads(
        run_single_tool(
            ctx, _call("check_hard", statement_th="แปลเอกสารธุรกิจ", action_verb_th="แปล")
        ).payload_json
    )
    assert good["passed"] is True
    bad = json.loads(
        run_single_tool(
            ctx, _call("check_hard", statement_th="เข้าใจเอกสารธุรกิจ", action_verb_th="แปล")
        ).payload_json
    )
    assert set(bad["failures"]) >= {"S_verb", "M_forbidden"}
    # the citation criterion cannot fail here: wording only
    assert "R_evidence" not in bad["failures"]


def test_check_hard_and_check_verbs_need_their_arguments() -> None:
    ctx = _ctx()
    assert run_single_tool(ctx, _call("check_hard", statement_th="x")).ok is False
    assert run_single_tool(ctx, _call("check_verbs", action_verb_th="แปล")).ok is False
    assert run_single_tool(ctx, _call("bloom_lookup")).ok is False


def test_bloom_lookup_and_check_verbs() -> None:
    ctx = _ctx()
    b = json.loads(run_single_tool(ctx, _call("bloom_lookup", verb_th="วิเคราะห์")).payload_json)
    assert b["recognized"] is True and "analyze" in b["levels"]
    v = json.loads(
        run_single_tool(
            ctx, _call("check_verbs", statement_th="วิเคราะห์ข้อมูล", action_verb_th="วิเคราะห์")
        ).payload_json
    )
    assert v["opens_with_declared_verb"] is True and v["too_many_verbs"] is False


def test_list_sibling_plos_shows_saved_plos() -> None:
    ctx = _ctx()
    ctx.plos.append(
        SiblingSummary(
            plo_id="PLO1",
            statement_th="แปลเอกสาร",
            bloom_level=BloomLevel.APPLY,
            is_optional=False,
            source_need_ids=["N1"],
        )
    )
    payload = json.loads(run_single_tool(ctx, _call("list_sibling_plos")).payload_json)
    assert [p["plo_id"] for p in payload["plos"]] == ["PLO1"]
