"""Render every prompt this pipeline sends, as one markdown inventory.

The prompts are Python literals returned by builders in
`curriculum_agent.prompts`, so a hand-written inventory of them starts drifting
the first time a rule is edited - `.claude/skills/.../references/prompts.md`
already did. This calls the builders and writes what they actually return.

    uv run python scripts/dump_prompts.py            # rewrite docs/prompt-inventory.md
    uv run python scripts/dump_prompts.py --check    # fail if it is out of date

The sample arguments below are placeholders in angle brackets. Everything
outside them - every rule, every schema line - is the live prompt text.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from curriculum_agent.models import (
    BloomHistogram,
    BloomLevel,
    KSECCategory,
    KsecCoverage,
    Need,
    ProgramMetadata,
    UnusedNeedFinding,
)
from curriculum_agent.prompts.cluster_skills import (
    build_cluster_skills_prompt,
    build_merge_clusters_prompt,
)
from curriculum_agent.prompts.designer_note import NOTE_HEADER_TH, NOTE_POLICY_TH
from curriculum_agent.prompts.extract_skills import build_extract_skills_prompt
from curriculum_agent.prompts.merged_need import build_merged_need_prompt
from curriculum_agent.prompts.need_dedup import build_need_dedup_prompt
from curriculum_agent.prompts.plo_feedback import build_bloom_redraft_note_th
from curriculum_agent.prompts.plo_review import (
    ReviewItem,
    build_plo_review_prompt,
    build_review_observation,
    build_review_refusal,
)
from curriculum_agent.prompts.program_context import build_program_context_th
from curriculum_agent.prompts.smart_agent import (
    build_agent_repair_prompt,
    build_refusal_observation,
    build_smart_agent_prompt,
    build_vote_repair_instruction_th,
)
from curriculum_agent.prompts.stage_3_plo import build_plo_from_need_prompt
from curriculum_agent.prompts.summarize_need import (
    MAX_RATIONALE_CHARS,
    MIN_RATIONALE_CHARS,
    MIN_STATEMENT_CHARS,
    build_summarize_need_prompt,
)
from curriculum_agent.stages.plo_review_facts import ReviewDossier

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "prompt-inventory.md"

_METADATA = ProgramMetadata(
    program_id="demo",
    university="<มหาวิทยาลัย>",
    faculty="<คณะ>",
    field="<สาขาวิชา>",
    degree_level="bachelor",
    duration_years=4,
)
_NEED = Need(
    need_id="<need_id>",
    program_id="demo",
    statement_th="<ประโยคความต้องการ>",
    ksec_category=KSECCategory.S,
    bloom_level=BloomLevel.APPLY,
    freq=3,
    demand_score=0.72,
    member_skill_ids=["<skill_id>"],
    source_skill_ids=["<skill_id>"],
    source_evidence_ids=["<evidence_id>"],
)


def _render(messages: list[dict[str, str]]) -> str:
    """One builder's messages as fenced blocks, one per role."""
    parts = []
    for message in messages:
        parts.append(f"**`{message['role']}`**\n\n```text\n{message['content']}\n```")
    return "\n\n".join(parts)


def _build() -> str:
    extract = _render(
        build_extract_skills_prompt(
            "<ข้อความ evidence หนึ่ง window>",
            "requirement",
            field_th="<สาขาวิชา>",
            program_name_th="<ชื่อหลักสูตร>",
            scope_th="<ขอบเขตหลักสูตรที่ผู้ออกแบบเขียน>",
        )
    )
    cluster = _render(
        build_cluster_skills_prompt(["<skill 0>", "<skill 1>"], 4, "<program context>")
    )
    merge = _render(build_merge_clusters_prompt(["<label 0>", "<label 1>"], 4))
    summarize = _render(
        build_summarize_need_prompt(
            ["<skill a>", "<skill b>"],
            "S",
            "apply",
            note_th="<ข้อความจากผู้ออกแบบหลักสูตร>",
            program_context="<program context>",
        )
    )
    plo = _render(
        build_plo_from_need_prompt(_METADATA, [_NEED], note_th="<ข้อความจากผู้ออกแบบหลักสูตร>")
    )
    dedup = _render(
        build_need_dedup_prompt(
            [("N1", "S", "<ประโยคความต้องการ 1>"), ("N2", "S", "<ประโยคความต้องการ 2>")],
            program_context="<program context>",
        )
    )
    merged_need = _render(
        build_merged_need_prompt(
            ["<skill a>", "<skill b>"],
            ["K", "S"],
            "apply",
            "<เหตุผลที่ตรวจพบว่าซ้ำกัน>",
            program_context="<program context>",
            skill_frequencies=[3, 1],
        )
    )
    review = _render(
        build_plo_review_prompt(
            ReviewDossier(
                program_context="<program context>",
                degree_level="bachelor",
                items=(
                    ReviewItem(
                        plo_id="<PLO1>",
                        is_optional=False,
                        statement_th="<ประโยค PLO หลัก>",
                        action_verb_th="<กริยา>",
                        bloom_level="apply",
                        current_ksec=("S",),
                        need_statements_th=("<ประโยคความต้องการ>",),
                    ),
                    ReviewItem(
                        plo_id="<OPT1>",
                        is_optional=True,
                        statement_th="<ประโยค PLO เสริม>",
                        action_verb_th="<กริยา>",
                        bloom_level="analyze",
                        current_ksec=("E", "C"),
                        need_statements_th=("<ประโยคความต้องการ>",),
                    ),
                ),
                ksec_coverage=KsecCoverage(
                    counts={"K": 0, "S": 1, "E": 1, "C": 1},
                    missing=["K"],
                    flags=[],
                ),
                bloom_histogram=BloomHistogram(
                    counts={"apply": 1, "analyze": 1},
                    degree_level="bachelor",
                    flags=[],
                ),
                core_count=1,
                unused_needs=(
                    UnusedNeedFinding(
                        need_id="<need_id>",
                        statement_th="<ประโยคความต้องการที่ไม่ได้เป็น PLO>",
                        demand_score=0.62,
                        ksec_category="K",
                        stakeholder_types=["professional_council"],
                        exclusion="lost_on_demand",
                    ),
                ),
            )
        )
    )
    review_observation = build_review_observation(
        "check_verbs", {"plo_id": "<PLO1>", "opens_with_declared_verb": True}
    )
    review_refusal = build_review_refusal("<เหตุผลที่ระบบปฏิเสธ>")
    smart = _render(
        build_smart_agent_prompt(
            statement_th="<ประโยค PLO ที่ร่างไว้>",
            bloom_level="apply",
            action_verb_th="<กริยา>",
            degree_level="bachelor",
            duration_years=4,
            cited_needs=[("<need_id>", "<ประโยคความต้องการ>")],
            cited_evidence_ids=["<evidence_id>"],
            sibling_count=5,
        )
    )
    repair = _render(
        build_agent_repair_prompt(
            statement_th="<ประโยค PLO เดิม>",
            bloom_level="apply",
            action_verb_th="<กริยา>",
            degree_level="bachelor",
            instruction_th="<คำสั่งแก้จาก validation agent>",
            criteria=["M_forbidden"],
            keep_th="<สาระที่ต้องคงไว้>",
        )
    )
    bloom_note = build_bloom_redraft_note_th(BloomLevel.ANALYZE, "<เหตุผลของผู้ตรวจ>")
    context_line = build_program_context_th({"field": "<สาขาวิชา>", "degree_level": "bachelor"})
    repair_instruction = build_vote_repair_instruction_th(
        ["<คำแนะนำของเกณฑ์ที่โค้ดตรวจไม่ผ่าน>"],
        [("M_assessable", "<หมายเหตุของผู้ตรวจที่เป็นตัวแทนเสียงข้างมาก>")],
        "<repair_hint_th ของผู้ตรวจที่เป็นตัวแทน>",
    )
    refusal_observation = build_refusal_observation("<เหตุผลที่ระบบปฏิเสธ>")

    return TEMPLATE.format(
        extract=extract,
        cluster=cluster,
        merge=merge,
        summarize=summarize,
        plo=plo,
        dedup=dedup,
        merged_need=merged_need,
        bloom_note=bloom_note,
        review=review,
        review_observation=review_observation,
        review_refusal=review_refusal,
        smart=smart,
        repair=repair,
        note_policy=NOTE_POLICY_TH,
        note_header=NOTE_HEADER_TH,
        context_line=context_line,
        repair_instruction=repair_instruction,
        refusal_observation=refusal_observation,
        min_statement=MIN_STATEMENT_CHARS,
        min_rationale=MIN_RATIONALE_CHARS,
        max_rationale=MAX_RATIONALE_CHARS,
    )


TEMPLATE = """# คลัง prompt ทั้งหมดในระบบ

> **สร้างด้วยเครื่อง — ห้ามแก้ไฟล์นี้ด้วยมือ**
> `uv run python scripts/dump_prompts.py` เขียนทับไฟล์นี้ · `--check` บอกว่าล้าสมัยหรือยัง
> ข้อความ prompt ทุกก้อนด้านล่าง render มาจาก builder จริง ไม่ได้คัดลอกมา
> ค่าที่อยู่ในวงเล็บแหลม `<...>` คือ argument ตัวอย่าง ที่เหลือคือข้อความจริงที่โมเดลได้อ่าน

## กติกาที่ prompt ทุกก้อนอยู่ใต้

- **หนึ่ง prompt หนึ่งไฟล์** ใน `src/curriculum_agent/prompts/` คืนค่าจาก builder ที่มี type hint ครบ
  — ห้ามเขียน prompt inline ใน stage
- builder คืน `list[dict[str, str]]` คือ messages แบบ OpenAI (`system` + `user`) ไม่ใช่ string เดียว
- ผลลัพธ์ผ่าน **Instructor → Pydantic** เสมอ ไม่มีการ parse JSON เอง
- ข้อความที่ผู้เรียนและผู้ออกแบบหลักสูตรอ่านเป็นภาษาไทย · โค้ด คอมเมนต์ log เป็นภาษาอังกฤษ

## สรุปทั้งระบบ

| # | prompt | builder | ผู้เรียก | LLM slot | response model | cache |
|---|---|---|---|---|---|---|
| 1 | สกัดทักษะจาก evidence | `build_extract_skills_prompt` | `stages/skill_extraction.py` → `run._extract_chunk` | `extraction` | `_ExtractedSkillsResponse` | ✅ `llm_cache` kind `extraction` |
| 2 | จัดกลุ่มชื่อทักษะ | `build_cluster_skills_prompt` | `stages/llm_clustering.py` → `_cluster_pass` | `clustering` | `ClusterAssignmentsResponse` | ✅ kind `clustering` (cache อยู่ที่ `cluster_skill_names`) |
| 3 | ยุบกลุ่มที่ซ้ำความหมาย | `build_merge_clusters_prompt` | `stages/llm_clustering.py` → `_cluster_map_reduce` | `clustering` | `MergeGroupsResponse` | ✅ ผ่าน key เดียวกับข้อ 2 |
| 4 | เขียนประโยค Need | `build_summarize_need_prompt` | `stages/need_combination.py` → `run` | `need_combination` | `_NeedStatement` | ❌ ไม่มี cache |
| 5 | แปลง Need เป็น PLO | `build_plo_from_need_prompt` | `stages/plo_synthesis.py` → `draft_from_needs` | `plo_synthesis` | `_SingleDraftResponse` | ❌ |
| 6 | SMART validation agent | `build_smart_agent_prompt` | `stages/smart_agent.py` → `_judge_once` (รัน `VALIDATION_RUNS` ครั้งต่อรอบ) | `validation` | `JudgeStep` | ❌ |
| 7 | สั่งแก้ประโยค PLO | `build_agent_repair_prompt` | `stages/smart_agent.py` → `_repair` | `plo_synthesis` | `_SingleDraftResponse` | ❌ |
| 8 | หา Need ที่ซ้ำกันก่อนร่าง PLO | `build_need_dedup_prompt` | `stages/need_dedup.py` → `find_duplicate_groups` | `need_dedup` | `DedupAnswer` | ❌ |
| 9 | ตรวจคุณภาพชุด PLO (QA agent ขั้นที่ 06) | `build_plo_review_prompt` | `stages/plo_review_agent.py` → `run_review_agent` | `plo_review` | `ReviewStep` | ❌ |
| 10 | เขียนประโยค Need ที่รวมจากหลายข้อ | `build_merged_need_prompt` | `stages/need_merge.py` → `_write_merged` | `need_combination` | `NeedStatement` | ❌ |
| 11 | โน้ตสั่งเขียน PLO ใหม่ตามระดับ Bloom ที่ผู้ตรวจเสนอ | `build_bloom_redraft_note_th` | `stages/plo_feedback.py` → `_send_bloom` | `plo_synthesis` (ผ่าน `note_th` ของข้อ 5) | `_SingleDraftResponse` | ❌ |

**หนึ่ง slot ต่อหนึ่ง stage** — ยกเว้น `plo_synthesis` ที่มีผู้เรียกสองราย (ข้อ 5 และ 7) โดยตั้งใจ:
การซ่อมประโยคต้องไม่ถูกตอบด้วยโมเดลคนละตัวกับที่เขียนร่างแรก

**stage ที่ไม่เรียก LLM เลย:** `intake` และ `stakeholder_needs` · การจัดประเภท evidence
(`requirement` / `general`) เป็นการ lookup จาก `StakeholderType` ด้วยโค้ดล้วน (`classify_evidence_type`)
ส่วน `need` / `want` / `unclassified` ตัดสินระดับทักษะใน `skill_extraction.classify_skills`
หลังสกัดครบทั้ง corpus เพราะความถี่เป็นสมบัติข้าม evidence

---

## 1. สกัดทักษะจาก evidence หนึ่ง window

| | |
|---|---|
| **builder** | `prompts/extract_skills.py` → `build_extract_skills_prompt(evidence_text, classification, field_th="", program_name_th="", scope_th="")` |
| **ผู้เรียก** | `stages/skill_extraction.py` → `run` → `_extract_chunk` |
| **slot / wrapper** | `extraction` → `complete_extraction` |
| **response model** | `_ExtractedSkillsResponse` (`skill_extraction.py`) |
| **cache** | key = window + `extraction_model` + `_EXTRACTION_CONTRACT` + `field_th` + `program_name_th` + `scope_th` |

ยิงหนึ่ง call ต่อหนึ่ง **window** ของ evidence แต่ละชิ้น (ไม่ใช่ prefix) จึงเป็น stage ที่เผา quota
หนักที่สุด

จุดที่ตั้งใจไว้และห้ามย้าย:

- `scope_th` อยู่ใน **system** message ไม่ใช่ user — วางไว้ข้าง evidence เมื่อไหร่ โมเดลอ่านมันเป็น
  evidence แล้วคัดลอกถ้อยคำในขอบเขตออกมาเป็นทักษะ พร้อม `evidence_span_th` ที่ quote ผิดเอกสาร
- prompt ไม่เคยรู้ว่ากำลังอ่าน stakeholder ประเภทไหน รู้แค่ `requirement` / `general`
- ทักษะนอกสาขา **ห้ามตัดทิ้ง** ให้ตั้ง flag — เวอร์ชันที่ยอมให้โมเดลตัดเองพาทักษะหลัก 3 รายการหายไปด้วย

⚠️ ข้อความ system ทั้งก้อนอยู่ใน `_extraction_contract_fingerprint` แก้อักษรเดียว = ทุกแถวใน
`llm_cache` ที่เขียนก่อนหน้ากลายเป็น `stale-contract` และต้องสกัดใหม่ทั้ง corpus

{extract}

---

## 2. จัดกลุ่มชื่อทักษะภายในหนึ่ง KSEC bucket

| | |
|---|---|
| **builder** | `prompts/cluster_skills.py` → `build_cluster_skills_prompt(skill_names, target_clusters=None, program_context=None)` |
| **ผู้เรียก** | `stages/llm_clustering.py` → `_cluster_pass` |
| **slot / wrapper** | `clustering` → `complete_clustering` (`temperature=0`) |
| **response model** | `ClusterAssignmentsResponse` |
| **cache** | ที่ `cluster_skill_names`: ชื่อทักษะทั้งชุด + `clustering_model` + `_CLUSTERING_CONTRACT` + `target_clusters` + `program_context` |

ทำงานด้วย **index** ไม่ใช่ชื่อ — โมเดลตอบเป็นเลขลำดับ `validate_assignments` จึงบังคับ
"ทุก index ปรากฏครั้งเดียว" ได้ด้วยโค้ดหลังจากนั้น

`target_clusters` มาจาก `need_grouping.allocate_cluster_targets` คือส่วนแบ่งของ bucket นี้จาก
เพดาน `MAX_CORE_PLOS` · ก่อนมีค่านี้ prompt สั่ง "4–12 กลุ่ม" ต่อ bucket โดยไม่รู้ว่ามีกี่ bucket
สามกลุ่มจึงขอมา 12–36 Need ชนเพดาน 10

`program_context` (จาก `build_program_context_th`) ใช้ **ตีความ** ชื่อทักษะเท่านั้น ห้ามใช้กรอง —
กฎใน prompt พูดตรง ๆ ว่าทักษะที่ดูนอกสาขาก็ยังคือความต้องการของตลาด และยังต้องอยู่ในกลุ่มใดกลุ่มหนึ่ง

{cluster}

---

## 3. ยุบกลุ่มที่ความหมายซ้ำกันข้าม batch

| | |
|---|---|
| **builder** | `prompts/cluster_skills.py` → `build_merge_clusters_prompt(cluster_labels, target_groups=None)` |
| **ผู้เรียก** | `stages/llm_clustering.py` → `_cluster_map_reduce` (เฉพาะเมื่อชื่อทักษะเกิน `SINGLE_PASS_MAX`) |
| **slot / wrapper** | `clustering` → `complete_clustering` (`temperature=0`) |
| **response model** | `MergeGroupsResponse` |

เพดานจำนวนกลุ่มบังคับที่ **ขั้น merge** ไม่ใช่ราย batch — batch เห็นแค่ส่วนหนึ่งของ bucket และตั้งใจให้
ผลิตเกิน ส่วนจำนวน Need สุดท้ายตัดสินกันตรงนี้

{merge}

---

## 4. เขียนประโยคความต้องการ (Need) จากหนึ่งกลุ่มทักษะ

| | |
|---|---|
| **builder** | `prompts/summarize_need.py` → `build_summarize_need_prompt(skill_names, ksec, bloom_level, *, note_th=None, program_context=None)` |
| **ผู้เรียก** | `stages/need_combination.py` → `run` |
| **slot / wrapper** | `need_combination` → `complete_need_combination` (`max_retries=_STATEMENT_ATTEMPTS`) |
| **response model** | `_NeedStatement` (`statement_th` / `statement_en` / `rationale_th`) |
| **cache** | ไม่มี — เป็น prompt เดียวที่แก้ได้โดยไม่ทำ cache ตาย |

**เห็นแค่ชื่อทักษะ ไม่เห็นข้อความ evidence** เคยแปะตัวอย่าง evidence เข้าไป แล้วถอดออก: ทักษะพกสิ่งที่
extraction อ่านได้มาแล้ว ส่วน quote ดิบมีแต่ทำให้โมเดลมีภาษาไทยให้ไหลออกนอกเรื่องยาวขึ้น ·
traceability ไม่กระทบ เพราะ `Need.source_evidence_ids` ประกอบจากทักษะสมาชิกด้วยโค้ด

แรงสองทางที่ prompt นี้ต้องคุมพร้อมกัน:

- **กันกว้าง** — ห้ามคำลอย ห้ามลดทอนทักษะเฉพาะทางเป็นสมรรถนะทั่วไป ต้องมีครบ 3 ส่วน
  ยาวไม่ต่ำกว่า {min_statement} ตัวอักษร และมีคำถามทดสอบท้าย prompt ("ลบชื่อสาขาออกแล้วยังบอกได้ไหมว่า
  เป็นความต้องการของสายวิชาชีพใด")
- **กันแคบ** — หนึ่งประโยคกินสล็อต PLO ไป 1 ใน 10 จึงต้องครอบ *ประเภทของงาน* ไม่ใช่ภารกิจย่อยชิ้นเดียว
  และข้อนี้เขียนกำกับไว้ว่าไม่ได้อนุญาตให้เขียนกว้างลอย ๆ แทน

**ห้ามเขียนเป็น PLO เสร็จรูป** — `plo_synthesis` ได้รับแค่ประโยคนี้ ถ้ามันเป็น PLO อยู่แล้ว
stage ถัดไปเหลือแค่คัดลอก และรายงานจะแสดงขั้นจาก "ตลาดขออะไร" ไป "บัณฑิตจึงต้องทำอะไรได้" ไม่ได้

`rationale_th` ({min_rationale}-{max_rationale} ตัวอักษร) ขอมาพร้อมประโยคในคอลเดียว เพราะเหตุผลว่าทำไม
ทักษะกลุ่มนี้เป็นความต้องการเดียวคือสิ่งที่โมเดลกำลังตัดสินอยู่ตอนเขียน · **ไม่ใช่ร่องรอยหลักฐาน** เป็น
free text ที่ตรวจกับ evidence ไม่ได้ prompt จึงห้ามอ้างอะไรนอกรายชื่อทักษะที่ให้มา

{summarize}

---

## 5. แปลงความต้องการเป็น PLO

| | |
|---|---|
| **builder** | `prompts/stage_3_plo.py` → `build_plo_from_need_prompt(metadata, needs, *, note_th=None)` |
| **ผู้เรียก** | `stages/plo_synthesis.py` → `draft_from_needs` |
| **slot / wrapper** | `plo_synthesis` → `complete_plo_synthesis` |
| **response model** | `_SingleDraftResponse` |

รับเป็น **list** เพราะผู้ออกแบบรวมหลาย Need เป็น PLO เดียวได้ผ่าน `POST /programs/{{id}}/plos/from-needs` ·
เส้นทางปกติของ stage ส่ง list ความยาว 1 — ฟังก์ชันเดียว กฎชุดเดียว ไม่ว่าจะ 1 Need หรือหลาย Need
prompt สลับประโยคสั่งและเพิ่มกฎ "ห้ามละข้อใดข้อหนึ่ง" เมื่อมีมากกว่าหนึ่ง

ชื่อย่อกระทรวงสะกดเต็มเป็นภาษาไทย ไม่ใช่ `MHESI` สี่ตัวอักษร — โมเดลที่ไม่รู้ว่าเขียนตามมาตรฐานของใคร
จะถอยไปใช้สำนวนผลลัพธ์การเรียนรู้แบบทั่วไป

**ไม่ถาม evidence จากโมเดลเลย** — ระบบผูก `source_evidence_ids` จาก Need ที่ให้มาเองด้วยโค้ด
(immutable rule 2)

{plo}

---

## 6. SMART validation agent (loop ที่ใช้เครื่องมือ)

| | |
|---|---|
| **builder** | `prompts/smart_agent.py` → `build_smart_agent_prompt(...)` (system คงที่ `_SYSTEM_TH` + user หนึ่งก้อน) |
| **ผู้เรียก** | `stages/smart_agent.py` → `_judge_once` (หนึ่ง judge run) ภายใต้ `_voted_loop` |
| **slot / wrapper** | `validation` → `complete_validation` (`temperature=0`, `max_tokens=_MAX_STEP_TOKENS`) |
| **response model** | `JudgeStep` = `CallTool` \\| `Finish` (ไม่มี action สั่งซ่อมแล้ว) |
| **งบ** | `VALIDATION_RUNS` judge run ต่อรอบ (ค่าเริ่มต้น 5, โหวตเสียงข้างมาก) · `VALIDATION_MAX_TURNS` รอบต่อ run · `VALIDATION_MAX_REPAIRS` ครั้งซ่อมต่อ PLO · `VALIDATION_TIMEOUT_SECONDS` ครอบทั้ง loop |

slot เดียวที่รัน multi-turn loop แบบมีเครื่องมือ · PLO หนึ่งข้อถูกตรวจหลายรอบพร้อมกัน (judge run) แล้ว `smart_vote` นับเสียงข้างมากต่อเกณฑ์ soft · run ไม่สั่งซ่อมเอง: มันรายงานผลตรวจ คำวินิจฉัย และ `repair_hint_th` สั้น ๆ แล้ว `_voted_loop` เป็นผู้ตัดสินใจซ่อมจากเสียงข้างมากกับ `hard_failures` · เครื่องมือที่เรียกได้: `check_hard`,
`bloom_lookup`, `get_need`, `get_evidence` (ไม่เกิน 3 รายการ), `list_sibling_plos`

**agent ประกาศว่าเกณฑ์ที่ตัดสินด้วยโค้ดผ่านเองไม่ได้** — `Finish` ไม่มี field ที่ล้างข้อผิดพลาดชนิดนั้น
และ `validate_and_build` รัน `hard_failures` กับประโยคสุดท้ายซ้ำเสมอทุกทางออก อิทธิพลของ agent จึงเป็น
monotone: หดรายการที่ไม่ผ่านได้ ประกาศว่าว่างเปล่าไม่ได้

**ไม่มี `note_th`** และไม่ควรมี — ข้อความจากผู้ออกแบบไปถึง prompt ร่างเท่านั้น validator ที่อ่านมันได้
จะส่งถ้อยคำนั้นต่อเข้าคำสั่งซ่อม แล้ว note จะไปโผล่ที่ prompt ซ่อมแบบมือสอง

`cited_needs` ส่งเป็นคู่ `(need_id, statement_th)` เพราะ id คือ argument ที่ `get_need` รับ · ตอนที่ส่ง
เฉพาะประโยค agent เอา *ประโยค* ของ Need ไปเป็น `need_id` ถูกปฏิเสธ อ่านคำปฏิเสธเป็นร่องรอยหลักฐานพัง
แล้วเผาโควตาซ่อมสองครั้งไปกับการสั่งให้ประโยคภาษาไทยอ้าง UUID

{smart}

### ข้อความที่ต่อเข้า loop ระหว่างทาง

ไม่ใช่ prompt เต็ม แต่เป็น user turn ที่ `_judge_once` ต่อท้ายหลังทุก action:

| builder | ใช้เมื่อ |
|---|---|
| `build_tool_observation(observation)` | ผลของเครื่องมือหนึ่งตัว — สำเร็จส่ง JSON, ล้มเหลวส่ง `ผลของ <tool>: ปฏิเสธ — <เหตุผล>` |
| `build_refusal_observation(reason_th)` | ระบบปฏิเสธคำสั่งล่าสุด เช่น รูปแบบคำตอบผิด หรือเรียกเครื่องมือด้วยอาร์กิวเมนต์เดิมซ้ำ |
| `build_vote_repair_instruction_th(...)` | คำสั่งซ่อมเดียวที่ส่งให้ slot `plo_synthesis` สร้างจากคำแนะนำของเกณฑ์ที่โค้ดตรวจไม่ผ่าน + ข้อที่ผู้ตรวจเสียงข้างมากไม่ผ่าน (ไม่รวม A_actor/A_scope) + hint ของผู้ตรวจตัวแทน ยาวไม่เกิน 800 ตัวอักษร |

```text
{repair_instruction}
```

```text
{refusal_observation}
```

หลังซ่อม ประโยคใหม่ถูกตรวจรอบใหม่ทั้งรอบ และโค้ดเทียบ `hard_failures` ของประโยคก่อน/หลัง — ถ้าประโยคใหม่มีข้อผิดพลาดชนิด
ที่ประโยคเดิมไม่มี (decision 20) จะทิ้งประโยคใหม่ ใช้ประโยคเดิมต่อ และนับว่าใช้สิทธิ์ซ่อมไปแล้ว

---

## 7. สั่งเขียนประโยค PLO ใหม่ตามคำสั่งของ validator

| | |
|---|---|
| **builder** | `prompts/smart_agent.py` → `build_agent_repair_prompt(...)` |
| **ผู้เรียก** | `stages/smart_agent.py` → `_repair` |
| **slot / wrapper** | `plo_synthesis` → `complete_plo_synthesis` (`max_retries=2`) |
| **response model** | `_SingleDraftResponse` (โครงเดียวกับร่างแรก) |

**นี่คือ invariant กลางของ SMART loop:** เสียงข้างมากของ judge run กับ `hard_failures` ตัดสินใจ *ว่าจะซ่อมไหม* และออกคำสั่ง ส่วนภาษาไทยที่
ผู้ออกแบบจะยื่นต่อ อว. เขียนโดย slot `plo_synthesis` เสมอ · `Finish` จึงไม่มี field
`statement_th` เลย (มีแค่ `repair_hint_th` สั้น ๆ) — ถ้ามี "การซ่อมไม่เคยถูกตอบด้วยโมเดลคนละตัวกับที่เขียนร่าง" จะห่างจากเท็จอยู่ field เดียว

prompt ซ่อมพกแค่คำสั่ง + ประโยคเดิม ไม่มีผลเครื่องมือ ไม่มี PLO พี่น้อง ไม่มีการท่องเกณฑ์ซ้ำ เพราะโมเดลที่
เขียนคำวินิจฉัยไม่ใช่โมเดลที่เขียนคำแก้ `instruction_th` จึงต้องอยู่ได้ด้วยตัวเอง

{repair}

---

## 8. หา Need ที่ถามหาสมรรถนะเดียวกันก่อนร่าง PLO

| | |
|---|---|
| **builder** | `prompts/need_dedup.py` → `build_need_dedup_prompt(rows, *, program_context=None)` |
| **ผู้เรียก** | `stages/need_dedup.py` → `find_duplicate_groups` (ครั้งเดียวต่อการรัน `need_combination` โดย `stages/need_merge.py`) |
| **slot / wrapper** | `need_dedup` → `complete_need_dedup` · ปิดได้ด้วย `NEED_DEDUP_PROVIDER=` |
| **response model** | `DedupAnswer` (`groups: [{{labels, reason_th}}]`) |
| **cache** | ไม่มี |

ส่งป้าย `N1`, `N2`, ... แทน `need_id` เพราะ UUID ยาว 36 ตัวที่โมเดลต้องคัดลอกให้ตรง · กฎโครงสร้างทุกข้อ
(2-5 ข้อต่อกลุ่ม · หมวด KSEC ต่างกันได้ · หนึ่ง Need หนึ่งกลุ่ม) โค้ดตรวจซ้ำใน `accept_groups` และทิ้งทั้งกลุ่มที่ผิด
ไม่ตัดสมาชิกออก · กฎข้อ 1 นิยาม "ซ้ำ" ว่างานหลักและวัตถุหลักเหมือนกัน และบอกชัดว่าหัวข้อ เครื่องมือ หรือแหล่งที่มาเดียวกันยังไม่พอ เพราะ Need ที่มาจาก
เอกสารชุดเดียวกันใช้ evidence ร่วมกันสูงถึง 55% ทั้งที่ขอคนละเรื่อง

{dedup}

---

## 9. ตรวจคุณภาพชุด PLO ทั้งหมด (QA agent ขั้นที่ 06)

| | |
|---|---|
| **builder** | `prompts/plo_review.py` → `build_plo_review_prompt(dossier)` · `build_review_observation(tool, payload)` · `build_review_refusal(reason_th)` |
| **ผู้เรียก** | `stages/plo_review_agent.py` → `run_review_agent` (orchestration ที่ `stages/plo_review.py` → `review_plo_set`) |
| **slot / wrapper** | `plo_review` → `complete_plo_review` · ปิดได้ด้วย `PLO_REVIEW_PROVIDER=` (ปิดแล้วยังเก็บข้อเท็จจริงที่โค้ดนับเป็น `code_only`) |
| **response model** | `ReviewStep` (`reasoning_th` + `action` แบบ `call_tool` / `finish`) |
| **cache** | ไม่มี |

เป็นด่านเดียวที่อ่าน **ทั้งชุด** PLO พร้อมกัน และเป็นด่านสุดท้ายของ pipeline — ทำงานหลังรายงาน
ไม่มี checkpoint คั่น ความซ้ำซ้อนระหว่างร่าง โดเมน KSEC ทั้งชุด การกระจายระดับ Bloom และ Need ที่ไม่ได้เป็น PLO
เป็นสมบัติของชุด ไม่ใช่ของ PLO ข้อใดข้อหนึ่ง

**เป็น agent ที่มีเครื่องมือ แต่ได้ข้อมูลน้อยโดยตั้งใจ** — โค้ดสร้าง dossier ให้ครั้งเดียว (ชุด PLO, ประโยค Need
ที่แต่ละข้ออ้าง, ตัวเลข KSEC/Bloom ที่โค้ดนับ, Need ที่ไม่ได้เป็น PLO) แล้ว agent เรียกเครื่องมือได้รวมไม่เกิน 4 ครั้ง
(`bloom_lookup`, `check_verbs`, `need_detail`) ใน 6 step · ไม่มี evidence ชื่อทักษะสมาชิก สัดส่วน evidence ร่วม
ผล SMART หรือผลตรวจครั้งก่อน เพราะยิ่งอ่านรายละเอียดต้นน้ำมาก ยิ่งยึดถ้อยคำเดิมและไปตัดสินขั้นก่อนหน้าซ้ำ
แทนที่จะอ่านชุดตามที่เขียนไว้อย่างที่กรรมการหลักสูตรอ่าน (สัดส่วน evidence ร่วมวัดแล้วหลอก:
คู่ที่ไม่เกี่ยวกันร่วม 55% คู่ซ้ำจริงต่ำกว่า 20%)

**เป็นคำแนะนำล้วน ไม่มีการเขียนทับอะไร** — prompt บอกตรง ๆ ว่ากรรมการคนนี้ไม่ได้แก้ PLO
ห้ามเขียนประโยคใหม่ ผลตรวจไปที่ตาราง `plo_reviews` และคำตอบ API เท่านั้น ไม่กระทบ PLO, Need, KSEC
tag หรือระดับ Bloom ที่เก็บไว้จริง และไม่เข้า Excel export · ตัวเลขทุกตัวโค้ดเป็นผู้นับ `finish` ไม่มี field
สำหรับตัวเลข

ข้อเสนอ KSEC เป็น**เซ็ตที่เลือกได้มากกว่าหนึ่งหมวด** — ประโยคหนึ่งอาจเป็นได้ทั้ง S และ E พร้อมกัน
ต่างจาก `current_ksec` ที่ PLO ถืออยู่จริงซึ่งเป็นหมวดเดียวเสมอ (`EC` อ่านเป็น E และ C)
`current`/`agrees`/`declared` คำนวณด้วยโค้ดจากสองเซ็ตนี้เทียบกัน ไม่ใช่สิ่งที่ขอจากโมเดล

กฎ "อยู่สาขาเดียวกันไม่ถือว่าซ้ำ" กันไม่ให้หลักสูตรที่ทุกข้อเกี่ยวกับงานเดียวกันโดยธรรมชาติ
(เช่นหลักสูตรการแปล ทุกข้อมีการแปล) ถูกตีว่าซ้ำกันหมด — ต้องงานหลักและวัตถุหลักเดียวกันจริง

หนึ่ง run ใช้ reasoning ซ่อนไม่เกิน 1024 token ต่อ step และเวลารวมไม่เกิน `plo_review_timeout_seconds`
(300 วินาที) · เกินหรือตอบผิดรูปแบบ = เก็บผลแบบ `code_only` ไม่มี finding ของ agent

{review}

ผลของเครื่องมือกลับไปเป็น user turn ถัดไป:

```text
{review_observation}
```

ถ้าเรียกเครื่องมือเกิน 4 ครั้ง หรือเรียก `need_detail` กับ Need นอกรายการ ระบบตอบกลับด้วยการปฏิเสธ
(และการเรียกนั้นยังนับ):

```text
{review_refusal}
```

---

## 10. เขียนประโยค Need ที่รวมจากหลายข้อ

| | |
|---|---|
| **builder** | `prompts/merged_need.py` → `build_merged_need_prompt(top_skill_names, ksec_tags, bloom_level, reason_th, *, program_context, skill_frequencies)` |
| **ผู้เรียก** | `stages/need_merge.py` → `_write_merged` (หนึ่งครั้งต่อกลุ่มที่ขั้น dedup รับ) |
| **slot / wrapper** | `need_combination` → `complete_need_combination` (`max_retries=3`) |
| **response model** | `NeedStatement` (เดียวกับข้อ 4) |
| **cache** | ไม่มี |

กฎการเขียนประโยคใช้ชุดเดียวกับข้อ 4 (`NEED_SENTENCE_RULES_HEAD_TH` / `NEED_SENTENCE_RULES_TAIL_TH` /
`NEED_SENTENCE_CONTEXT_RULE_TH` / `NEED_SPECIFICITY_CHECK_TH` / `NEED_SUPPORTING_INDICES_RULE_TH` ใน
`prompts/summarize_need.py`) เพราะคำตอบถูกตรวจด้วย `NeedStatement` ตัวเดียวกัน · ที่ต่างคือ input: ไม่ใช่ชื่อสมาชิกทั้งกลุ่ม
แต่เป็น**ทักษะเด่น** (คะแนน importance สูงสุด ไม่เกิน 7) พร้อมความถี่ของแต่ละทักษะ (จำนวนแถวสมาชิกที่รวมเป็นชื่อนั้น) และเหตุผลที่ขั้น dedup ให้ไว้ · หมวด KSEC ส่งเป็นรายการ
เพราะความต้องการเดิมอยู่คนละหมวดได้ · ถ้าเขียนประโยคไม่สำเร็จ กลุ่มนั้นไม่ถูกรวม ความต้องการเดิมยังใช้งานอยู่

{merged_need}

---

## 11. โน้ตส่งกลับเมื่อผู้ตรวจเสนอระดับ Bloom ใหม่

| | |
|---|---|
| **builder** | `prompts/plo_feedback.py` → `build_bloom_redraft_note_th(suggested, reason_th)` |
| **ผู้เรียก** | `stages/plo_feedback.py` → `_send_bloom` |
| **slot / wrapper** | ไม่เรียก LLM เอง — เป็นข้อความที่ไปต่อท้าย user message ของข้อ 5 ผ่าน `note_th` (slot `plo_synthesis`) |
| **response model** | `_SingleDraftResponse` (เดียวกับข้อ 5) |
| **cache** | ไม่มี |

คืน string ไม่ใช่ messages: ระบุระดับ Bloom ที่ผู้ตรวจเสนอและยกเหตุผลของผู้ตรวจมาตรง ๆ · ถูกอ่านเป็นแนวทางเลือกถ้อยคำ
ตาม `NOTE_POLICY_TH` ด่าน SMART ยังมีคำสุดท้าย จึงบันทึกทั้งระดับที่ขอและระดับที่ได้ไว้ใน `plo_feedback_actions`

```text
{bloom_note}
```

---

## ชิ้นส่วนที่ prompt หลายก้อนใช้ร่วมกัน

### `prompts/designer_note.py` — ข้อความเพิ่มเติมจากผู้ออกแบบ

ไปถึง prompt ข้อ 4 และ 5 เท่านั้น

`append_note(user_content, note_th)` ต่อ note เข้า **user message** เสมอ ไม่ใช่ system — ข้อความที่ผู้ใช้
พิมพ์เองถ้าไปอยู่ใน system จะถูกเสนอในฐานะนโยบาย · ส่วน `NOTE_POLICY_TH` อยู่ใน system เพื่อบอกว่าให้อ่าน
note นั้นอย่างไร และเติมแบบไม่มีเงื่อนไข เพื่อให้ fingerprint ที่คำนวณจาก prompt ยังมีความหมาย

หัวข้อที่ note ถูกยื่นเข้าไปใต้:

```text
{note_header}
```

บรรทัดนโยบายใน system message:

```text
{note_policy}
```

### `prompts/program_context.py` — บริบทหลักสูตรหนึ่งบรรทัด

`build_program_context_th(metadata)` คืนบรรทัดเดียวจาก field + degree level ที่ผู้ออกแบบพิมพ์ตอน intake:

```text
{context_line}
```

ไปถึง prompt ข้อ 2 และ 4 · เป็น **metadata ไม่ใช่ evidence** จึงใช้กำกับการอ่านเท่านั้น
ชื่อทักษะลอย ๆ อย่าง "การดูแล" จับกลุ่มกับงานคลินิกในหลักสูตรพยาบาล และกับงานอาคารสถานที่ในหลักสูตร
วิศวกรรม และไม่มีอะไรอื่นใน prompt ทั้งสองบอกว่านี่คือหลักสูตรอะไร · หลักสูตรที่ไม่มี `field` ได้ `None`
และ prompt กลับไปเหมือนก่อนมีฟีเจอร์นี้ทุกตัวอักษร

บรรทัดนี้อยู่ใน **cache key** ของ clustering ด้วยเหตุผลเดียวกับ `target_clusters`: มันไปถึง prompt
สองหลักสูตรที่ชื่อทักษะบังเอิญตรงกันจึงต้องไม่ใช้ entry ร่วมกัน

---

## `prompts/guidances/` — ร่าง ไม่ใช่ของที่รันอยู่

เอกสาร 4 ไฟล์ในนั้นเป็น **ร่างว่า prompt ควรอ่านอย่างไร** ไม่มีโค้ดบรรทัดใดเปิดมันเลย
แก้แล้วไม่มีอะไรเปลี่ยน — รายละเอียดและข้อควรระวังก่อนหยิบมาใช้อยู่ใน `prompts/guidances/README.md`
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the prompt inventory.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the committed inventory differs from what the builders return",
    )
    args = parser.parse_args()

    rendered = _build()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != rendered:
            print(f"{OUTPUT} is out of date - run: uv run python scripts/dump_prompts.py")
            return 1
        print(f"{OUTPUT} is up to date")
        return 0

    OUTPUT.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT} ({len(rendered)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
