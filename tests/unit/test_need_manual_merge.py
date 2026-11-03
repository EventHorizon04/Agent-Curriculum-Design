"""`POST /programs/{id}/needs/merge`: the designer folds 2-5 Needs into one."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from curriculum_agent.api import jobs as jobs_mod
from curriculum_agent.api.main import app
from curriculum_agent.api.routes import needs as needs_route
from curriculum_agent.graph import review_needs
from curriculum_agent.models import (
    BloomLevel,
    ExtractedSkill,
    JobInfo,
    KSECCategory,
    Need,
    ProgramMetadata,
    StakeholderType,
)
from curriculum_agent.stages import need_merge as nm
from curriculum_agent.stages.need_combination import NeedStatement
from curriculum_agent.stages.need_grouping import REVIEW_MARKER_TH
from tests.support.jobs import InMemoryJobs
from tests.support.needs import RATIONALE_TH

client = TestClient(app)
_REAL_RUNNING_SESSION = jobs_mod._running_session
_NOW = datetime(2026, 11, 3, 3, 0, 0)
_SENTENCE = "ต้องการบัณฑิตที่แปลและตรวจสอบเอกสารธุรกิจไทย-จีนโดยใช้ AI ช่วยตรวจคุณภาพ"
_METADATA = ProgramMetadata.model_validate(
    {
        "program_id": "p",
        "field": "ภาษาจีน",
        "degree_level": "bachelor",
        "duration_years": 4,
        "faculty": "มนุษยศาสตร์",
        "university": "Test University",
    }
)


def _need(nid: str, demand: float = 0.5, **extra: Any) -> Need:
    fields: dict[str, Any] = {
        "need_id": nid,
        "program_id": "p",
        "statement_th": f"ต้องการบัณฑิตที่ทำงาน {nid} ในสถานประกอบการจริงได้",
        "ksec_categories": [KSECCategory.S],
        "bloom_level": BloomLevel.APPLY,
        "member_skill_ids": [f"S-{nid}"],
        "source_evidence_ids": [f"E-{nid}"],
        "freq": 1,
        "demand_score": demand,
        "in_field_skill_count": 1,
        "graduate_capability_skill_count": 1,
    }
    fields.update(extra)
    return Need(**fields)


def _skill(sid: str) -> ExtractedSkill:
    return ExtractedSkill(
        skill_id=sid,
        program_id="p",
        skill_name_th=f"ทักษะ {sid}",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.APPLY,
        evidence_span_th=sid,
        source_evidence_id=f"E-{sid[2:]}",
        source_stakeholder_type=StakeholderType.EMPLOYER,
        classification="need",
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.5,
    )


class _Store:
    """The Need table as the route sees it, with the writes it uses."""

    def __init__(self, needs: list[Need]) -> None:
        self.rows = {n.need_id: n for n in needs}
        self.write_merge = AsyncMock(side_effect=self._write_merge)

    async def list_by_program(self, program_id: str) -> list[Need]:
        return list(self.rows.values())

    async def _write_merge(self, program_id: str, originals: list[Need], merged: Need) -> Need:
        for o in originals:
            self.rows[o.need_id] = self.rows[o.need_id].model_copy(
                update={"merged_into": merged.need_id}
            )
        self.rows[merged.need_id] = merged
        return merged

    async def split(self, program_id: str, need_id: str) -> list[Need]:
        del self.rows[need_id]
        freed = []
        for nid, n in list(self.rows.items()):
            if n.merged_into == need_id:
                self.rows[nid] = n.model_copy(update={"merged_into": None})
                freed.append(self.rows[nid])
        return freed


class _Sentence:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, model: type[NeedStatement], messages: object, **kw: object) -> Any:
        self.calls += 1
        return NeedStatement(statement_th=_SENTENCE, rationale_th=RATIONALE_TH)


def _install(
    monkeypatch: pytest.MonkeyPatch, needs: list[Need], plos: list[object] | None = None
) -> tuple[_Store, _Sentence]:
    store = _Store(needs)
    sentence = _Sentence()
    skills = [_skill(sid) for n in needs for sid in n.member_skill_ids]
    monkeypatch.setattr(needs_route.NeedRepository, "list_by_program", store.list_by_program)
    monkeypatch.setattr(needs_route.NeedRepository, "write_merge", store.write_merge)
    monkeypatch.setattr(needs_route.NeedRepository, "split", store.split)
    monkeypatch.setattr(
        needs_route.PLORepository, "list_by_program", AsyncMock(return_value=plos or [])
    )
    monkeypatch.setattr(
        needs_route.SkillRepository, "list_by_program", AsyncMock(return_value=skills)
    )
    monkeypatch.setattr(needs_route.ProgramRepository, "get", AsyncMock(return_value=_METADATA))
    monkeypatch.setattr(nm, "complete_need_combination", sentence)
    return store, sentence


def _pool(extra: int = 4) -> list[Need]:
    return [
        _need("A", 0.9),
        _need("B", 0.7),
        _need("C", 0.8),
        *[_need(f"F{i}") for i in range(extra)],
    ]


def _merge(ids: list[str], reason: str | None = None) -> Any:
    return client.post("/programs/p/needs/merge", json={"need_ids": ids, "reason_th": reason})


def test_manual_merge_success(monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs) -> None:
    store, sentence = _install(monkeypatch, _pool())

    response = _merge(["B", "A"], "งานเดียวกัน")

    assert response.status_code == 200
    body = response.json()
    assert body["merged_by"] == "designer"
    assert body["merged_from"] == ["A", "B"]  # demand order
    assert body["merge_reason_th"] == "งานเดียวกัน"
    assert body["statement_th"] == _SENTENCE
    assert store.rows["A"].merged_into == body["need_id"]
    assert store.rows["B"].merged_into == body["need_id"]
    assert sentence.calls == 1


def test_manual_merge_blank_reason_uses_fallback(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs
) -> None:
    _install(monkeypatch, _pool())

    body = _merge(["A", "B"], "   ").json()

    assert body["merge_reason_th"] == "ผู้ออกแบบหลักสูตรเลือกรวม Need เหล่านี้"


def test_manual_merge_duplicate_ids_422(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs
) -> None:
    _, sentence = _install(monkeypatch, _pool())

    response = _merge(["A", "A"])

    assert response.status_code == 422
    assert response.json()["detail"] == "เลือก Need ซ้ำ"
    assert sentence.calls == 0


@pytest.mark.parametrize("ids", [["A"], ["A", "B", "C", "F0", "F1", "F2"]])
def test_manual_merge_wrong_count_422(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs, ids: list[str]
) -> None:
    _, sentence = _install(monkeypatch, _pool())

    response = _merge(ids)

    assert response.status_code == 422
    assert response.json()["detail"] == "เลือก Need 2-5 ข้อเพื่อรวม"
    assert sentence.calls == 0


def test_manual_merge_unknown_422(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs
) -> None:
    _, sentence = _install(monkeypatch, _pool())

    response = _merge(["A", "NOPE"])

    assert response.status_code == 422
    assert response.json()["detail"] == "ไม่พบ Need: NOPE"
    assert sentence.calls == 0


@pytest.mark.parametrize(
    "extra", [{"merged_into": "M"}, {"excluded_at": _NOW}], ids=["merged-away", "excluded"]
)
def test_manual_merge_inactive_422(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs, extra: dict[str, Any]
) -> None:
    _, sentence = _install(monkeypatch, [*_pool(), _need("X", **extra)])

    response = _merge(["A", "X"])

    assert response.status_code == 422
    assert response.json()["detail"] == "Need X ไม่อยู่ในชุดที่ใช้งาน"
    assert sentence.calls == 0


def test_manual_merge_unwritten_422(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs
) -> None:
    unwritten = _need("U", statement_th=f"{REVIEW_MARKER_TH} ทักษะ ก, ทักษะ ข")
    _, sentence = _install(monkeypatch, [*_pool(), unwritten])

    response = _merge(["A", "U"])

    assert response.status_code == 422
    assert "ยังไม่ได้เขียนประโยคสำหรับ Need: U" in response.json()["detail"]
    assert sentence.calls == 0


def test_manual_merge_plo_cited_409(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs
) -> None:
    plo = SimpleNamespace(source_need_ids=["B"])
    store, sentence = _install(monkeypatch, _pool(), [plo])

    response = _merge(["A", "B"])

    assert response.status_code == 409
    assert response.json()["detail"] == "มี PLO อ้างถึง Need: B — ลบหรือรวม PLO ก่อนรวม Need"
    assert sentence.calls == 0
    store.write_merge.assert_not_awaited()


def test_manual_merge_floor_422(monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs) -> None:
    # Four core Needs: merging two leaves three, below the floor of four.
    _, sentence = _install(monkeypatch, [_need(n) for n in "ABCD"])

    response = _merge(["A", "B"])

    assert response.status_code == 422
    assert response.json()["detail"] == "การรวมนี้จะเหลือ Need หลัก 3 ข้อ ต่ำกว่าขั้นต่ำ 4 ข้อ"
    assert sentence.calls == 0


def test_manual_merge_optional_pair_not_blocked_by_floor(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs
) -> None:
    """Merging two optional Needs leaves the core count where it was."""
    needs = [_need(n) for n in "ABC"]
    needs += [_need("O1", is_optional=True), _need("O2", is_optional=True)]
    _install(monkeypatch, needs)

    assert _merge(["O1", "O2"]).status_code == 200


def test_manual_merge_busy_409(monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs) -> None:
    jobs_store.rows["j1"] = JobInfo(
        job_id="j1", program_id="p", kind="plo_synthesis", status="running", created_at=_NOW
    )
    _, sentence = _install(monkeypatch, _pool())

    response = _merge(["A", "A"])  # would be a 422 if the guard did not come first

    assert response.status_code == 409
    assert sentence.calls == 0


def test_manual_merge_second_request_while_first_registered_409(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs
) -> None:
    _, sentence = _install(monkeypatch, _pool())
    monkeypatch.setitem(jobs_mod._SYNC_WRITERS, "p", "กำลังรวม Need อยู่")

    response = _merge(["A", "B"])

    assert response.status_code == 409
    assert sentence.calls == 0


def test_manual_merge_missing_metadata_422_before_llm(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs
) -> None:
    _, sentence = _install(monkeypatch, _pool())
    monkeypatch.setattr(needs_route.ProgramRepository, "get", AsyncMock(return_value=None))

    response = _merge(["A", "B"])

    assert response.status_code == 422
    assert sentence.calls == 0


def test_manual_merge_sentence_failure_502_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs
) -> None:
    store, _ = _install(monkeypatch, _pool())
    monkeypatch.setattr(
        nm, "complete_need_combination", AsyncMock(side_effect=RuntimeError("down"))
    )

    response = _merge(["A", "B"])

    assert response.status_code == 502
    assert response.json()["detail"] == "เขียนประโยค Need ที่รวมแล้วไม่สำเร็จ ลองใหม่อีกครั้ง"
    store.write_merge.assert_not_awaited()
    assert all(n.merged_into is None for n in store.rows.values())


def test_manual_merge_of_needs_with_reextracted_skills_409(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs
) -> None:
    """After /needs/skills/run the Needs cite skill ids that no longer exist; a
    retry can never succeed, so the answer is 409 pointing at Agent 2, not 502."""
    store, sentence = _install(monkeypatch, _pool())
    monkeypatch.setattr(
        needs_route.SkillRepository, "list_by_program", AsyncMock(return_value=[_skill("S-new")])
    )

    response = _merge(["A", "B"])

    assert response.status_code == 409
    assert response.json()["detail"] == "ทักษะของ Need ที่เลือกถูกสกัดใหม่แล้ว — รัน Agent 2 ใหม่ก่อนรวม Need"
    assert sentence.calls == 0
    store.write_merge.assert_not_awaited()


def test_manual_merge_nests_merged_need(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs
) -> None:
    m1 = _need("M1", 0.95, merged_from=["O1", "O2"], merge_reason_th="เดิม")
    m1 = m1.model_copy(update={"member_skill_ids": ["S-O1", "S-O2"]})
    needs = [
        m1,
        _need("O1", merged_into="M1"),
        _need("O2", merged_into="M1"),
        _need("N3", 0.6),
        *[_need(f"F{i}") for i in range(4)],
    ]
    store, _ = _install(monkeypatch, needs)

    merged = _merge(["M1", "N3"]).json()

    assert merged["merged_from"] == ["M1", "N3"]
    assert store.rows["M1"].merged_into == merged["need_id"]
    assert store.rows["M1"].merged_from == ["O1", "O2"]  # keeps its own trail

    first = client.post(f"/programs/p/needs/{merged['need_id']}/split").json()
    assert [n["need_id"] for n in first] == ["M1", "N3"]
    assert store.rows["M1"].merged_into is None and store.rows["M1"].is_merged

    second = client.post("/programs/p/needs/M1/split").json()
    assert [n["need_id"] for n in second] == ["O1", "O2"]


async def test_manual_merge_while_session_paused(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs
) -> None:
    """A suspended session is not a running writer, and the resume reload sees the merge."""
    store, _ = _install(monkeypatch, _pool())
    suspended = SimpleNamespace(status="suspended")
    sessions = SimpleNamespace(list_by_program=AsyncMock(return_value=[suspended]))
    monkeypatch.setattr(jobs_mod, "SessionRepository", lambda: sessions)
    monkeypatch.setattr(jobs_mod, "_running_session", _REAL_RUNNING_SESSION)

    response = _merge(["A", "B"])

    assert response.status_code == 200
    merged_id = response.json()["need_id"]

    async def active(_self: object, program_id: str) -> list[Need]:
        return [n for n in store.rows.values() if n.merged_into is None]

    monkeypatch.setattr(needs_route.NeedRepository, "list_active_by_program", active)
    with patch("curriculum_agent.graph.interrupt", return_value={}):
        result = await review_needs({"program_id": "p", "needs": []})  # type: ignore[typeddict-item]
    ids = [n["need_id"] for n in result["needs"]]
    assert merged_id in ids
    assert "A" not in ids and "B" not in ids
