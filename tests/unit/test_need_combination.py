from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from curriculum_agent.models import BloomLevel, ExtractedSkill, KSECCategory, StakeholderType
from curriculum_agent.stages import need_combination as nc
from curriculum_agent.stages.demand import (
    MANDATE_WEIGHT,
    OTHER_VOICE_WEIGHT,
    PRACTITIONER_WEIGHT,
)
from tests.support.needs import RATIONALE_TH


def _skill(
    name: str,
    ksec: KSECCategory,
    sid: str,
    eid: str,
    stype: StakeholderType = StakeholderType.EMPLOYER,
    classification: str = "need",
) -> ExtractedSkill:
    return ExtractedSkill(
        skill_id=sid,
        program_id="cs-test",
        skill_name_th=name,
        ksec_category=ksec,
        bloom_level=BloomLevel.APPLY,
        evidence_span_th=name,
        source_evidence_id=eid,
        source_stakeholder_type=stype,
        classification=classification,
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.5,
    )


@pytest.fixture
def skills() -> list[ExtractedSkill]:
    return [
        _skill("เขียนโปรแกรมเว็บ", KSECCategory.S, "S1", "E1"),
        _skill("ออกแบบฐานข้อมูล", KSECCategory.S, "S2", "E1"),
        _skill("ทำงานเป็นทีม", KSECCategory.S, "S3", "E2"),
        _skill("ยึดถือจรรยาบรรณ", KSECCategory.E, "S4", "E3"),
    ]


async def _fake_summarize(model, messages, **kw):  # noqa: ANN001, ANN003
    return nc._NeedStatement(
        statement_th="ตลาดแรงงานต้องการผู้ที่ออกแบบและดูแลระบบสารสนเทศขององค์กรให้ใช้งานได้จริง",
        statement_en="The market needs people who maintain corporate information systems",
        rationale_th=RATIONALE_TH,
    )


def _patch_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cluster each bucket into singletons; summarize echoes the first skill name."""

    async def fake_cluster(
        names: list[str], target: int | None = None, program_context: str | None = None
    ) -> list[list[int]]:
        return [[i] for i in range(len(names))]

    monkeypatch.setattr(nc, "cluster_skill_names", fake_cluster)
    monkeypatch.setattr(nc, "complete_need_combination", _fake_summarize)


def _patch_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub every persistence call the stage makes.

    `run` clears the program's previous Needs before inserting the new set, so a
    test stubbing only bulk_insert leaves the delete reaching a real database.
    """
    monkeypatch.setattr(nc.NeedRepository, "delete_by_program", AsyncMock())
    monkeypatch.setattr(nc.NeedRepository, "bulk_insert", AsyncMock())


async def test_every_need_holds_exactly_one_ksec_tag(
    skills: list[ExtractedSkill], monkeypatch: pytest.MonkeyPatch
):
    _patch_llm(monkeypatch)
    _patch_repo(monkeypatch)

    state = await nc.run(
        {
            "program_id": "cs-test",
            "extracted_skills": [s.model_dump(mode="json") for s in skills],
        }
    )

    needs = state["needs"]
    assert needs, "expected at least one Need"
    skills_by_id = {s.skill_id: s for s in skills}
    for need in needs:
        tags = {skills_by_id[sid].ksec_category.value for sid in need["member_skill_ids"]}
        assert len(tags) == 1
        assert tags == {need["ksec_category"]}


async def test_ethics_and_character_skills_form_one_ec_need(monkeypatch: pytest.MonkeyPatch):
    skills = [
        _skill("จรรยาบรรณวิชาชีพ", KSECCategory.E, "S1", "E1"),
        _skill("ความรับผิดชอบต่อหน้าที่", KSECCategory.C, "S2", "E2"),
    ]

    async def one_cluster(
        names: list[str], target: int | None = None, program_context: str | None = None
    ) -> list[list[int]]:
        return [list(range(len(names)))]

    monkeypatch.setattr(nc, "cluster_skill_names", one_cluster)
    monkeypatch.setattr(nc, "complete_need_combination", _fake_summarize)
    _patch_repo(monkeypatch)

    state = await nc.run(
        {
            "program_id": "cs-test",
            "extracted_skills": [s.model_dump(mode="json") for s in skills],
        }
    )

    assert [n["ksec_category"] for n in state["needs"]] == ["EC"]


async def test_an_all_ethics_group_keeps_the_standalone_e_tag(monkeypatch: pytest.MonkeyPatch):
    skills = [
        _skill("จรรยาบรรณวิชาชีพ", KSECCategory.E, "S1", "E1"),
        _skill("ความซื่อสัตย์ในวิชาชีพ", KSECCategory.E, "S2", "E2"),
    ]

    async def one_cluster(
        names: list[str], target: int | None = None, program_context: str | None = None
    ) -> list[list[int]]:
        return [list(range(len(names)))]

    monkeypatch.setattr(nc, "cluster_skill_names", one_cluster)
    monkeypatch.setattr(nc, "complete_need_combination", _fake_summarize)
    _patch_repo(monkeypatch)

    state = await nc.run(
        {
            "program_id": "cs-test",
            "extracted_skills": [s.model_dump(mode="json") for s in skills],
        }
    )

    assert [n["ksec_category"] for n in state["needs"]] == ["E"]


async def test_needs_carry_their_source_stakeholder_types(monkeypatch: pytest.MonkeyPatch):
    skills = [
        _skill(
            "วิเคราะห์ข้อมูล", KSECCategory.S, "S1", "E1", stype=StakeholderType.PROFESSIONAL_COUNCIL
        ),
        _skill("วิเคราะห์ข้อมูล", KSECCategory.S, "S2", "E2", stype=StakeholderType.ALUMNI),
    ]

    async def one_cluster(
        names: list[str], target: int | None = None, program_context: str | None = None
    ) -> list[list[int]]:
        return [list(range(len(names)))]

    monkeypatch.setattr(nc, "cluster_skill_names", one_cluster)
    monkeypatch.setattr(nc, "complete_need_combination", _fake_summarize)
    _patch_repo(monkeypatch)

    state = await nc.run(
        {
            "program_id": "cs-test",
            "extracted_skills": [s.model_dump(mode="json") for s in skills],
        }
    )

    assert state["needs"][0]["source_stakeholder_types"] == ["professional_council", "alumni"]


async def test_a_want_only_group_is_optional(monkeypatch: pytest.MonkeyPatch):
    skills = [
        _skill("เล่นดนตรีไทย", KSECCategory.S, "S1", "E3", classification="want"),
        _skill("จัดนิทรรศการ", KSECCategory.S, "S2", "E3", classification="want"),
    ]
    _patch_llm(monkeypatch)
    _patch_repo(monkeypatch)

    state = await nc.run(
        {
            "program_id": "cs-test",
            "extracted_skills": [s.model_dump(mode="json") for s in skills],
        }
    )

    assert all(n["is_optional"] for n in state["needs"])


async def test_freq_counts_mentions_not_unique_names(monkeypatch: pytest.MonkeyPatch):
    # Same capability named twice in one bucket, clustered together.
    dupes = [
        _skill("วิเคราะห์ข้อมูล", KSECCategory.S, "S1", "E1"),
        _skill("วิเคราะห์ข้อมูล", KSECCategory.S, "S2", "E2"),
    ]

    async def one_cluster(
        names: list[str], target: int | None = None, program_context: str | None = None
    ) -> list[list[int]]:
        return [list(range(len(names)))]

    async def fake_summarize(model, messages, **kw):  # noqa: ANN001, ANN003
        return nc._NeedStatement(
            statement_th="ตลาดแรงงานต้องการผู้ที่วิเคราะห์ข้อมูลยอดขายเพื่อสนับสนุนการตัดสินใจของผู้บริหาร",
            statement_en="The market needs people who analyse sales data for management decisions",
            rationale_th=RATIONALE_TH,
        )

    monkeypatch.setattr(nc, "cluster_skill_names", one_cluster)
    monkeypatch.setattr(nc, "complete_need_combination", fake_summarize)
    _patch_repo(monkeypatch)

    state = await nc.run(
        {
            "program_id": "cs-test",
            "extracted_skills": [s.model_dump(mode="json") for s in dupes],
        }
    )

    assert len(state["needs"]) == 1
    assert state["needs"][0]["freq"] == 2  # two mentions, one name


async def test_empty_skills_stops_the_run_instead_of_yielding_no_needs(
    monkeypatch: pytest.MonkeyPatch,
):
    """An empty extraction is reported here, not carried forward.

    It used to return `needs == []`, which walked on through the shared
    checkpoint to plo_synthesis — the stage that then failed, naming this one.
    The stored Needs still survive: the raise happens before delete_by_program.
    """
    delete = AsyncMock()
    monkeypatch.setattr(nc.NeedRepository, "delete_by_program", delete)
    monkeypatch.setattr(nc.NeedRepository, "bulk_insert", AsyncMock())

    with pytest.raises(ValueError, match="skill_extraction"):
        await nc.run({"program_id": "cs-test", "extracted_skills": []})

    delete.assert_not_awaited()


async def test_no_upper_cap_on_core_needs(monkeypatch: pytest.MonkeyPatch):
    """One KSEC bucket producing more than the old 10-Need cap must not be merged down.

    Project policy dropped MAX_NEEDS: every core group clustering finds becomes its
    own Need, regardless of how many that is.
    """
    many_skills = [_skill(f"ทักษะที่ {i}", KSECCategory.S, f"S{i}", "E1") for i in range(15)]

    _patch_llm(monkeypatch)  # clusters each name into its own singleton
    _patch_repo(monkeypatch)

    state = await nc.run(
        {
            "program_id": "cs-test",
            "extracted_skills": [s.model_dump(mode="json") for s in many_skills],
        }
    )

    assert len(state["needs"]) == 15


# --- the generated sentence must not carry code tokens ---------------------


def test_need_statement_model_rejects_a_leaked_code_token() -> None:
    """Instructor retries on a validator error, so rejecting here is what makes
    the model re-answer instead of the token reaching a stored Need."""
    with pytest.raises(ValidationError) as exc:
        nc._NeedStatement(
            statement_th="ตลาดแรงงานต้องการบุคคลที่สามารถเป็นผู้ประกอบการ หน.getDefault รับฟังผู้บริหาร",
            rationale_th=RATIONALE_TH,
        )
    assert "getDefault" in str(exc.value)


def test_need_statement_model_accepts_ordinary_thai_with_industry_terms() -> None:
    written = nc._NeedStatement(
        statement_th="ตลาดแรงงานต้องการผู้ที่ประยุกต์ AI และ Data Science กับงานธุรกิจได้",
        rationale_th=RATIONALE_TH,
    )
    assert written.statement_en is None


def test_summarize_is_asked_to_retry_on_a_rejected_statement() -> None:
    """The retry budget has to reach Instructor — without max_retries the
    validator would turn a recoverable leak into a fallback sentence."""
    assert nc._STATEMENT_ATTEMPTS >= 2


# --- the stage reads skills and nothing else --------------------------------


async def test_the_written_statement_reaches_the_stored_need(
    skills: list[ExtractedSkill], monkeypatch: pytest.MonkeyPatch
):
    """Guards every other test in this file as much as the stage.

    `run` wraps the summarize call in a try/except that falls back to a marked
    skill list, so a fake statement that trips _NeedStatement's validators would
    make the suite pass while exercising the fallback path instead of the one each
    test names. Asserting the sentence survives is what keeps that honest.
    """
    _patch_llm(monkeypatch)
    _patch_repo(monkeypatch)

    state = await nc.run(
        {
            "program_id": "cs-test",
            "extracted_skills": [s.model_dump(mode="json") for s in skills],
        }
    )

    expected = (await _fake_summarize(None, [])).statement_th
    assert all(n["statement_th"] == expected for n in state["needs"])


async def test_evidence_text_in_the_state_never_reaches_the_prompt(
    skills: list[ExtractedSkill], monkeypatch: pytest.MonkeyPatch
):
    """The stage sees the extracted skills only.

    A caller may still hand it `classified_evidence` — `run` for the first pass of
    a program builds one state for both stages. Nothing in that key may travel
    into the summarize prompt: the skills already carry what extraction found.
    """
    secret = "ข้อความหลักฐานที่ต้องไม่ปรากฏในพรอมต์"
    seen: list[list[dict[str, str]]] = []

    async def capture(model, messages, **kw):  # noqa: ANN001, ANN003
        seen.append(messages)
        return await _fake_summarize(model, messages)

    async def fake_cluster(
        names: list[str], target: int | None = None, program_context: str | None = None
    ) -> list[list[int]]:
        return [[i] for i in range(len(names))]

    monkeypatch.setattr(nc, "cluster_skill_names", fake_cluster)
    monkeypatch.setattr(nc, "complete_need_combination", capture)
    _patch_repo(monkeypatch)

    await nc.run(
        {
            "program_id": "cs-test",
            "classified_evidence": [
                {"evidence_id": "E1", "stakeholder_type": "employer", "raw_text_th": secret}
            ],
            "extracted_skills": [s.model_dump(mode="json") for s in skills],
        }
    )

    assert seen, "the summarize call never happened"
    assert all(secret not in m["content"] for messages in seen for m in messages)


async def test_demand_score_is_weighted_by_the_skills_own_stakeholder_types(
    monkeypatch: pytest.MonkeyPatch,
):
    """Scoring survives the loss of `classified_evidence`.

    Every block of the score comes off `ExtractedSkill.source_stakeholder_type`
    and `source_evidence_id` now. The council is a practitioner voice and the
    student is not, so each Need is the whole of its own block's audience — and
    only the council Need collects the mandate block on top.
    """
    council = _skill(
        "ออกแบบระบบฐานข้อมูล",
        KSECCategory.S,
        "S1",
        "E1",
        stype=StakeholderType.PROFESSIONAL_COUNCIL,
    )
    student = _skill("จัดกิจกรรมนักศึกษา", KSECCategory.S, "S2", "E2", stype=StakeholderType.STUDENT)
    _patch_llm(monkeypatch)
    _patch_repo(monkeypatch)

    state = await nc.run(
        {
            "program_id": "cs-test",
            "extracted_skills": [s.model_dump(mode="json") for s in (council, student)],
        }
    )

    by_skill = {n["member_skill_ids"][0]: n["demand_score"] for n in state["needs"]}
    assert by_skill["S1"] == pytest.approx(MANDATE_WEIGHT + PRACTITIONER_WEIGHT)
    assert by_skill["S2"] == pytest.approx(OTHER_VOICE_WEIGHT)


async def test_a_group_whose_sentence_cannot_be_written_is_marked_for_review(
    skills: list[ExtractedSkill], monkeypatch: pytest.MonkeyPatch
):
    """The fallback must not pass for a usable Need.

    A comma-joined skill list is exactly what _require_plo_ready rejects, so
    shipping one unmarked would hand plo_synthesis a Need it can only guess from.
    The marker is what puts it in front of the designer at the checkpoint.

    Which marker depends on why the sentence is missing — this simulates a
    provider that never answered, so the Need says so and re-running the stage is
    the fix. test_need_statement_failure_kind.py covers the split itself.
    """

    async def always_fails(model, messages, **kw):  # noqa: ANN001, ANN003
        raise RuntimeError("model unavailable")

    async def fake_cluster(
        names: list[str], target: int | None = None, program_context: str | None = None
    ) -> list[list[int]]:
        return [list(range(len(names)))]

    monkeypatch.setattr(nc, "cluster_skill_names", fake_cluster)
    monkeypatch.setattr(nc, "complete_need_combination", always_fails)
    _patch_repo(monkeypatch)

    state = await nc.run(
        {
            "program_id": "cs-test",
            "extracted_skills": [s.model_dump(mode="json") for s in skills],
        }
    )

    assert state["needs"]
    assert all(n["statement_th"].startswith(nc._PROVIDER_MARKER_TH) for n in state["needs"])


# --- the generated sentence must be usable as a PLO ------------------------


@pytest.mark.parametrize(
    ("statement", "reason"),
    [
        ("ตลาดต้องการคนเก่ง", "สั้นเกินไป"),
        (
            "ตลาดแรงงานต้องการผู้ที่มีทักษะที่จำเป็นต่อการทำงานในองค์กรยุคใหม่ได้อย่างเหมาะสม",
            "คำกว้าง",
        ),
        (
            "ตลาดแรงงานต้องการผู้ที่มีสมรรถนะด้านต่างๆ ในการทำงานร่วมกับผู้อื่นในองค์กรได้ดี",
            "คำกว้าง",
        ),
        (
            "ตลาดแรงงานต้องการบุคลากรที่มีความสามารถตามที่ตลาดต้องการในการทำงานยุคดิจิทัล",
            "วนกลับมาพูดถึงตัวเอง",
        ),
        (
            "เขียนโปรแกรมเว็บ, ออกแบบฐานข้อมูล, ทดสอบระบบ, เขียนเอกสาร, ดูแลเซิร์ฟเวอร์",
            "เป็นลิสต์ชื่อทักษะ",
        ),
    ],
)
def test_a_statement_that_cannot_become_a_plo_is_rejected(statement: str, reason: str) -> None:
    """Instructor re-asks on a validator error, so rejecting here is what makes the
    model write a usable sentence instead of the placeholder reaching plo_synthesis."""
    with pytest.raises(ValidationError):
        nc._NeedStatement(statement_th=statement, rationale_th=RATIONALE_TH)


@pytest.mark.parametrize(
    "statement",
    [
        "ตลาดแรงงานต้องการผู้ที่ออกแบบระบบฐานข้อมูลสำหรับงานธุรกิจให้รองรับปริมาณข้อมูลจริงได้",
        # A real object modified by "ที่จำเป็น" is specific — only a generic head
        # noun in front of it makes the phrase empty.
        "ตลาดแรงงานต้องการผู้ที่คัดกรองข้อมูลที่จำเป็นต่อการตัดสินใจของผู้บริหารได้",
        # Two commas is prose, not a list.
        "ตลาดแรงงานต้องการผู้ที่ออกแบบ, พัฒนา และดูแลระบบสารสนเทศขององค์กรได้",
    ],
)
def test_a_specific_market_sentence_passes(statement: str) -> None:
    assert (
        nc._NeedStatement(statement_th=statement, rationale_th=RATIONALE_TH).statement_th
        == statement
    )


def _flagged(
    name: str,
    sid: str,
    eid: str,
    *,
    in_field: bool = True,
    graduate: bool = True,
    classification: str = "need",
) -> ExtractedSkill:
    return _skill(name, KSECCategory.S, sid, eid, classification=classification).model_copy(
        update={"is_field_relevant": in_field, "is_graduate_capability": graduate}
    )


async def _needs_from(
    skills: list[ExtractedSkill], monkeypatch: pytest.MonkeyPatch
) -> list[dict[str, object]]:
    _patch_llm(monkeypatch)
    _patch_repo(monkeypatch)
    state = await nc.run(
        {
            "program_id": "cs-test",
            "extracted_skills": [s.model_dump(mode="json") for s in skills],
        }
    )
    return state["needs"]


async def test_two_rows_sharing_a_skill_name_are_counted_separately(
    monkeypatch: pytest.MonkeyPatch,
):
    """The counters are over member *rows*, not distinct skill names.

    Clustering works on deduplicated names, so it is tempting to count the same
    way — and `classification` genuinely does, ORed across every row sharing a
    name. Doing that here would push the number to the total whenever a name
    recurs across evidence items, and the fraction the designer reads at the
    checkpoint would be 8/8 for every Need ever produced.
    """
    skills = [
        _flagged("การแปลเอกสารธุรกิจ", "S1", "E1", in_field=True),
        _flagged("การแปลเอกสารธุรกิจ", "S2", "E2", in_field=False),
    ]

    needs = await _needs_from(skills, monkeypatch)

    (need,) = needs
    assert sorted(need["member_skill_ids"]) == ["S1", "S2"]
    assert need["in_field_skill_count"] == 1
    assert need["graduate_capability_skill_count"] == 2


async def test_neither_counter_can_exceed_the_member_count(monkeypatch: pytest.MonkeyPatch):
    """The denominator the designer sees is len(member_skill_ids), which is why
    these are plain ints rather than a coverage dict. A count taken over anything
    but that list would read as "9 of 8"."""
    skills = [
        _flagged("การแปลเอกสารธุรกิจ", "S1", "E1"),
        _flagged("การแปลเอกสารธุรกิจ", "S2", "E2", graduate=False),
        _flagged("การล่ามการเจรจา", "S3", "E1", in_field=False),
        _flagged("การตรวจแก้งานแปล", "S4", "E3"),
    ]

    needs = await _needs_from(skills, monkeypatch)

    assert needs
    for need in needs:
        total = len(need["member_skill_ids"])
        assert 0 <= need["in_field_skill_count"] <= total
        assert 0 <= need["graduate_capability_skill_count"] <= total


async def test_a_requirement_skill_judged_off_field_still_counts_as_off_field(
    monkeypatch: pytest.MonkeyPatch,
):
    """The two axes are read straight off the row and never through
    `classification`.

    A rule routed through classification would be dead on exactly the cases it
    was written for: a skill named by a professional council or by the
    institution's own vision comes out `requirement` no matter what either flag
    says, because requirement wins. That precedence is not the thing to change —
    selection has to read the flags directly instead.
    """
    skills = [
        _flagged(
            "การบริหารจัดการและพัฒนาแหล่งรายได้",
            "S1",
            "E1",
            in_field=False,
            graduate=False,
            classification="requirement",
        )
    ]

    needs = await _needs_from(skills, monkeypatch)

    (need,) = needs
    assert need["classification_coverage"] == {"requirement": 1}
    assert need["in_field_skill_count"] == 0
    assert need["graduate_capability_skill_count"] == 0


def test_a_statement_without_supporting_indices_is_still_accepted() -> None:
    """The coverage field is a measurement, and a measurement must not cost a Need.

    A validator that raised on a missing or malformed list would send Instructor
    round again and, three misses later, turn a well-written sentence into a
    `[ต้องทบทวน]` fallback for the designer to rewrite by hand.
    """
    written = nc._NeedStatement(
        statement_th="ต้องการบัณฑิตที่แปลและตรวจสอบเอกสารสัญญาทางธุรกิจไทย-จีนได้อย่างถูกต้อง",
        rationale_th=RATIONALE_TH,
    )
    assert written.supporting_indices is None


async def test_names_reach_the_prompt_most_mentioned_first(monkeypatch: pytest.MonkeyPatch):
    """The listing cap cuts from the end, so the end has to be the rarest names.

    Ordered as clustering returned them, a cap could drop the name the group is
    mostly made of and keep one extracted once; coverage would then be measured
    against a list the sentence was never shown the core of.
    """
    rows = [
        _skill("ล่ามการประชุม", KSECCategory.S, "S1", "E1"),
        _skill("แปลเอกสารสัญญา", KSECCategory.S, "S2", "E1"),
        _skill("แปลเอกสารสัญญา", KSECCategory.S, "S3", "E2"),
        _skill("แปลเอกสารสัญญา", KSECCategory.S, "S4", "E3"),
    ]

    async def one_cluster(
        names: list[str], target: int | None = None, program_context: str | None = None
    ) -> list[list[int]]:
        return [list(range(len(names)))]

    seen: list[str] = []

    async def capture(model, messages, **kw):  # noqa: ANN001, ANN003
        seen.append(messages[1]["content"])
        return await _fake_summarize(model, messages, **kw)

    monkeypatch.setattr(nc, "cluster_skill_names", one_cluster)
    monkeypatch.setattr(nc, "complete_need_combination", capture)
    _patch_repo(monkeypatch)

    await nc.run(
        {"program_id": "cs-test", "extracted_skills": [r.model_dump(mode="json") for r in rows]}
    )

    assert "0 | แปลเอกสารสัญญา" in seen[0]
    assert "1 | ล่ามการประชุม" in seen[0]


@pytest.mark.parametrize(
    ("answer", "kept"),
    [
        ("0,1,2", None),
        ({"0": True}, None),
        (["1", "x", 2, 2.0, None], [1, 2]),
        ([], []),
    ],
)
def test_a_malformed_supporting_list_degrades_instead_of_failing_the_call(
    answer: object, kept: list[int] | None
) -> None:
    """No validator of ours raises here, and that is not enough on its own.

    Pydantic still type-checks `list[int]`, so a model answering "0,1,2" as a
    string would fail the call, send Instructor round again, and could end in a
    `[ต้องทบทวน]` fallback over a field the stage only logs. Whatever arrives is
    reduced to the integers in it, or to None when there is no list at all.
    """
    written = nc._NeedStatement(
        statement_th="ต้องการบัณฑิตที่แปลและตรวจสอบเอกสารสัญญาทางธุรกิจไทย-จีนได้อย่างถูกต้อง",
        rationale_th=RATIONALE_TH,
        supporting_indices=answer,  # type: ignore[arg-type]
    )
    assert written.supporting_indices == kept


async def test_one_create_member_does_not_make_the_need_create(monkeypatch: pytest.MonkeyPatch):
    """The level reaches the summarize prompt as "สร้างและออกแบบสิ่งใหม่ได้", which
    is why five stored Needs and the PLOs copied from them all opened with
    ออกแบบ. The level has to be the group's, or the sentence and the outcome
    inherit a demand only one member made."""
    rows = [
        _skill("แปลเอกสารสัญญา", KSECCategory.S, "S1", "E1"),
        _skill("ตรวจทานคำแปล", KSECCategory.S, "S2", "E2"),
        _skill("แปลเอกสารธุรกิจ", KSECCategory.S, "S3", "E3"),
        _skill("ออกแบบเครื่องมือแปล", KSECCategory.S, "S4", "E4"),
    ]
    rows[3] = rows[3].model_copy(update={"bloom_level": BloomLevel.CREATE})

    async def one_cluster(
        names: list[str], target: int | None = None, program_context: str | None = None
    ) -> list[list[int]]:
        return [list(range(len(names)))]

    seen: list[str] = []

    async def capture(model, messages, **kw):  # noqa: ANN001, ANN003
        seen.append(messages[1]["content"])
        return await _fake_summarize(model, messages, **kw)

    monkeypatch.setattr(nc, "cluster_skill_names", one_cluster)
    monkeypatch.setattr(nc, "complete_need_combination", capture)
    _patch_repo(monkeypatch)

    state = await nc.run(
        {"program_id": "cs-test", "extracted_skills": [r.model_dump(mode="json") for r in rows]}
    )

    assert state["needs"][0]["bloom_level"] == "apply"
    assert "(apply)" in seen[0]
