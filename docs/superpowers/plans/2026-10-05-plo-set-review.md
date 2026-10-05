# PLO Set Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an advisory reviewer that reads the finished PLO set once — redundancy, KSEC (possibly several per PLO), Bloom — stores its findings per program, and shows them in the PLO report, changing nothing.

**Architecture:** A new `plo_review` LLM slot and stage. `stages/plo_review.py` makes one structured call over the whole set, judges the answer in pure code (`accept_review`), and stores one `PLOSetReview` row per program keyed by a fingerprint of the PLO set, reusing it while the set is unchanged. The graph gains a `plo_review` node between `review_plos_node` and `plo_report` with no interrupt of its own; the REST report route runs it first; two new routes re-run and read the review.

**Tech Stack:** Python 3.11, pydantic v2, instructor (via `llm._complete`), FastAPI, SQLAlchemy 2 async, Alembic/Postgres, LangGraph, pytest (`asyncio_mode = "auto"`), loguru.

**Spec:** `docs/superpowers/specs/2026-10-04-plo-set-review-design.md`

## Global Constraints

- Advisory only: nothing in this plan writes to a PLO, a Need, a KSEC tag or a Bloom level. The reviewer's output goes only to the `plo_reviews` table and to API responses.
- KSEC suggestions are a set drawn from `K`, `S`, `E`, `C` (stored `EC` reads as `E` and `C`).
- `current`, `agrees` and `declared` are computed in code, never taken from the model.
- A review that did not run produces no findings; the report never fails because the review failed.
- Not in the Excel export. No frontend changes.
- Slot `plo_review`: provider default `"openrouter"`, model default `"z-ai/glm-5.3-flash"`, `disableable=True` (`PLO_REVIEW_PROVIDER=` empty = off). Timeout `plo_review_timeout_seconds = 180`. Call with `temperature=0`, `max_tokens=8192`, `max_retries=2`.
- Max redundancy group size 3.
- `from __future__ import annotations`, type hints on every signature, loguru only, English code/comments/logs, Thai only in prompt text and user-facing details.
- Stage by explicit path only. The working tree has unrelated dirty files (`frontend/**`, `.scratch/**`, untracked `.claude/skills/*`, deleted `curriculum-design-agent.skill`) that must never be staged. Never read `.env`. No live LLM calls in tests. Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Use Edit, never `git checkout --`/`git restore`/`git stash`, for mutation checks.
- Verify each task with: `PYTHONIOENCODING=utf-8 uv run pytest -q`, `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`, `uv run mypy src/`.

---

### Task 1: The `plo_review` slot

**Files:**
- Modify: `src/curriculum_agent/config.py` (append to `SLOTS` after `validation`; add three `Settings` fields after the validation fields)
- Modify: `src/curriculum_agent/llm.py` (add `complete_plo_review` after `complete_need_dedup`, ~line 256)
- Test: `tests/unit/test_llm_slots.py`

**Interfaces:**
- Produces: `settings.plo_review_provider: Literal["ollama","openrouter","opentyphoon",""] | None` (default `"openrouter"`), `settings.plo_review_model: str` (default `""`, filled by `_apply_provider_model_defaults`), `settings.plo_review_timeout_seconds: int = 180`; `async def complete_plo_review(response_model: type[T], messages: list[dict[str, Any]], **kwargs: Any) -> T`.

- [ ] **Step 1: Update the existing slot test to expect the new disableable slot**

In `tests/unit/test_llm_slots.py`, the assertion at line ~72 reads `assert disableable == ["need_dedup", "validation"]`. Change it to:

```python
    assert disableable == ["need_dedup", "validation", "plo_review"]
```

and add at the end of the file:

```python
def test_plo_review_runs_on_glm_and_can_be_switched_off() -> None:
    s = Settings(_env_file=None)
    assert s.plo_review_provider == "openrouter"
    assert s.plo_review_model == "z-ai/glm-5.3-flash"
    assert s.plo_review_timeout_seconds == 180
    assert Settings(_env_file=None, plo_review_provider="").plo_review_provider == ""
```

- [ ] **Step 2: Run to see them fail**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/unit/test_llm_slots.py -q`
Expected: FAIL (`plo_review_provider` not a field / disableable list mismatch).

- [ ] **Step 3: Declare the slot and fields**

In `config.py`, append to `SLOTS` after the `validation` entry:

```python
    # Reads the finished PLO set once, after synthesis, and reports — it never
    # writes a statement. glm-5.3-flash for the same reason as need_dedup: the
    # task is judging and labelling, and one call per program pays its reasoning
    # latency once. disableable: the review is advisory, so "" turns it off.
    SlotSpec(
        "plo_review",
        "plo_review_provider",
        "plo_review_model",
        default_models={"openrouter": "z-ai/glm-5.3-flash"},
        disableable=True,
    ),
```

In `Settings`, after the validation fields, add:

```python
    # The PLO set review (stages/plo_review.py). Advisory: "" (empty) switches it
    # off and the report says so; None follows LLM_PROVIDER like every slot.
    plo_review_provider: Literal["ollama", "openrouter", "opentyphoon", ""] | None = "openrouter"
    plo_review_model: str = ""
    plo_review_timeout_seconds: int = 180
```

In `llm.py`, after `complete_need_dedup`:

```python
async def complete_plo_review(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """The PLO set review before the report — see Settings.plo_review_provider.

    One caller, `stages.plo_review`, once per changed PLO set. Its answer is
    advice for the designer and is judged again in pure code before it is stored.
    """
    return await _complete(*_resolve("plo_review"), response_model, messages, **kwargs)
```

If any other test enumerates slot names or counts (`grep -rn "need_dedup" tests/unit/test_llm*.py tests/unit/test_config*.py`), update it to include `plo_review` in pipeline order (after `validation`).

- [ ] **Step 4: Run tests**

Run: `PYTHONIOENCODING=utf-8 uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/curriculum_agent/config.py src/curriculum_agent/llm.py tests/unit/test_llm_slots.py
git commit -m "feat(llm): a plo_review slot for the PLO set review

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The review prompt

**Files:**
- Create: `src/curriculum_agent/prompts/plo_review.py`
- Modify: `scripts/dump_prompts.py` (render the new builder; add its table row and its section, mirroring the `build_need_dedup_prompt` entries at ~lines 102, 185, 393)
- Regenerate: `docs/prompt-inventory.md`
- Test: `tests/unit/test_plo_review_prompt.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class ReviewItem` with fields `plo_id: str, is_optional: bool, statement_th: str, action_verb_th: str, bloom_level: str, current_ksec: tuple[str, ...], need_statements_th: tuple[str, ...]`; `def build_plo_review_prompt(items: Sequence[ReviewItem], *, program_context: str | None = None) -> list[dict[str, str]]`.

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

from curriculum_agent.prompts.plo_review import ReviewItem, build_plo_review_prompt


def _item(plo_id: str = "PLO1", **kw: object) -> ReviewItem:
    base: dict[str, object] = dict(
        plo_id=plo_id,
        is_optional=False,
        statement_th="แปลเอกสารกฎหมายระหว่างภาษาไทยและภาษาจีน",
        action_verb_th="แปล",
        bloom_level="apply",
        current_ksec=("S",),
        need_statements_th=("ต้องการบัณฑิตที่แปลเอกสารกฎหมายได้",),
    )
    base.update(kw)
    return ReviewItem(**base)  # type: ignore[arg-type]


def _system() -> str:
    return build_plo_review_prompt([_item()])[0]["content"]


def test_every_plo_and_its_needs_and_ksec_reach_the_user_turn() -> None:
    user = build_plo_review_prompt(
        [_item(), _item("OPT1", is_optional=True, current_ksec=("E", "C"))]
    )[1]["content"]
    assert "[PLO1]" in user and "[OPT1]" in user
    assert "แปลเอกสารกฎหมายระหว่างภาษาไทยและภาษาจีน" in user
    assert "ต้องการบัณฑิตที่แปลเอกสารกฎหมายได้" in user
    assert "E|C" in user
    assert "(เสริม)" in user and "(หลัก)" in user


def test_program_context_line_only_when_given() -> None:
    with_ctx = build_plo_review_prompt([_item()], program_context="หลักสูตรระดับปริญญาตรี สาขาการแปล")
    assert "หลักสูตร: หลักสูตรระดับปริญญาตรี สาขาการแปล" in with_ctx[1]["content"]
    assert "หลักสูตร:" not in build_plo_review_prompt([_item()])[1]["content"]


def test_rubric_names_the_three_checks_and_the_json_keys() -> None:
    system = _system()
    for key in ("redundancies", "ksec", "bloom", "bloom_distribution_th", "summary_th"):
        assert key in system


def test_rubric_allows_more_than_one_ksec() -> None:
    assert "มากกว่าหนึ่งหมวด" in _system()


def test_rubric_says_the_reviewer_changes_nothing() -> None:
    system = _system()
    assert "คุณไม่ได้แก้ PLO" in system
    assert "ห้ามเขียนประโยค PLO ใหม่" in system


def test_rubric_says_sharing_a_field_is_not_redundancy() -> None:
    assert "ไม่ถือว่าซ้ำ" in _system()


def test_rubric_allows_a_clean_set() -> None:
    assert "ให้ส่งรายการของเรื่องนั้นว่าง" in _system()
```

- [ ] **Step 2: Run to see them fail**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/unit/test_plo_review_prompt.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Write the builder**

```python
"""The PLO set review prompt: read the finished set, advise, change nothing.

Every other check reads one PLO against its own Needs. This one reads the set,
because redundancy between drafts, a domain that spans KSEC tags, and a Bloom
distribution are properties of the set. See
docs/superpowers/specs/2026-10-04-plo-set-review-design.md.

The answer is advice, so the prompt says outright that the reviewer rewrites
nothing — a reviewer handed the statements and no such line drifts into
proposing replacement sentences, which nothing downstream would check.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewItem:
    plo_id: str
    is_optional: bool
    statement_th: str
    action_verb_th: str
    bloom_level: str
    current_ksec: tuple[str, ...]
    need_statements_th: tuple[str, ...]


_SYSTEM_TH = """คุณเป็นกรรมการพิจารณาหลักสูตรอุดมศึกษาไทยตามแนว OBE และมาตรฐาน อว.
งานของคุณคือตรวจ PLO ทั้งชุดของหลักสูตรหนึ่ง แล้วรายงานข้อเสนอแนะให้ผู้ออกแบบหลักสูตร
คุณไม่ได้แก้ PLO ห้ามเขียนประโยค PLO ใหม่ ให้บอกเพียงว่าควรปรับอะไรและเพราะอะไร

ตรวจ 3 เรื่อง
1) redundancies (ความซ้ำซ้อน): กลุ่ม PLO 2-3 ข้อที่กรรมการหลักสูตรจะอ่านว่าเป็นผลลัพธ์เดียวกัน
   คือมีงานหลักเดียวกันกับวัตถุประเภทเดียวกัน ต่างกันแค่บริบท เครื่องมือ หรือถ้อยคำ
   การอยู่ในสาขาเดียวกันหรือใช้เครื่องมือเดียวกันไม่ถือว่าซ้ำ เช่น ทุกข้อของหลักสูตรการแปลมีการแปลอยู่แล้ว
   แต่ละกลุ่ม: plo_ids, reason_th (ซ้ำกันตรงไหน), suggestion_th (ควรรวม หรือควรแยกวัตถุให้ชัดอย่างไร)
2) ksec (หมวดสมรรถนะ): ทุก PLO ต้องมีหนึ่งรายการ ระบุหมวดที่ผลลัพธ์ตามที่เขียนไว้ควรอยู่
   เลือกได้มากกว่าหนึ่งหมวดจาก K S E C
   K = รู้และอธิบายองค์ความรู้, S = ลงมือทำงานของวิชาชีพ, E = คุณธรรมจริยธรรม,
   C = คุณลักษณะบุคคล เช่น การปรับตัว ภาวะผู้นำ การพัฒนาตนเอง
   ตัดสินจากสิ่งที่บัณฑิตทำในประโยค ไม่ใช่จากหมวดเดิม
   แต่ละรายการ: plo_id, suggested (list เช่น ["S","E"]), reason_th
3) bloom (ระดับ Bloom): ใส่เฉพาะ PLO ที่ระดับที่ประกาศไม่เหมาะกับกริยา กรรม และระดับปริญญา
   แต่ละรายการ: plo_id, suggested_level (remember understand apply analyze evaluate create), reason_th
   และ bloom_distribution_th: หนึ่งถึงสองประโยคเรื่องการกระจายระดับ Bloom ทั้งชุดเทียบกับระดับปริญญา

summary_th: สรุป 2-5 ประโยคให้ผู้ออกแบบ เรียงเรื่องสำคัญก่อน
ถ้าชุด PLO ไม่มีปัญหาในเรื่องใด ให้ส่งรายการของเรื่องนั้นว่าง แต่ ksec ต้องมีครบทุก PLO และต้องมี summary_th เสมอ
ใช้ plo_id ตามที่ให้มาเท่านั้น

ตอบเป็น JSON object เดียว:
{"redundancies": [...], "ksec": [...], "bloom": [...], "bloom_distribution_th": "...", "summary_th": "..."}"""


def _ksec_label(tags: tuple[str, ...]) -> str:
    return "|".join(tags) if tags else "-"


def build_plo_review_prompt(
    items: Sequence[ReviewItem], *, program_context: str | None = None
) -> list[dict[str, str]]:
    """The rubric, then the whole set in one user turn."""
    blocks: list[str] = []
    for item in items:
        needs = "\n".join(f"- {s}" for s in item.need_statements_th) or "- (ไม่พบ Need)"
        blocks.append(
            f"[{item.plo_id}] ({'เสริม' if item.is_optional else 'หลัก'})\n"
            f"ประโยค: {item.statement_th}\n"
            f"กริยา: {item.action_verb_th} | ระดับ Bloom: {item.bloom_level} | "
            f"KSEC ปัจจุบัน: {_ksec_label(item.current_ksec)}\n"
            f"Need ที่อ้างถึง:\n{needs}"
        )
    header = f"หลักสูตร: {program_context}\n" if program_context else ""
    user = f"{header}PLO ทั้งหมด {len(items)} ข้อ:\n\n" + "\n\n".join(blocks)
    return [
        {"role": "system", "content": _SYSTEM_TH},
        {"role": "user", "content": user},
    ]
```

Register it in `scripts/dump_prompts.py` the way `build_need_dedup_prompt` is: import it, render it in `_build()` with two sample `ReviewItem`s (one core S, one optional with `("E", "C")`) and a sample program context, add a row to the index table (next number; stage "ตรวจชุด PLO ก่อนรายงาน"; caller `stages/plo_review.py` → `review_plo_set`; slot `plo_review`; response model `ReviewAnswer`; no cache), and a section like the need_dedup one (builder, caller, slot/wrapper `plo_review` → `complete_plo_review` · ปิดได้ด้วย `PLO_REVIEW_PROVIDER=`). Then run `uv run python scripts/dump_prompts.py`.

- [ ] **Step 4: Run tests and the inventory check**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/unit/test_plo_review_prompt.py -q` → PASS.
Run: `uv run python scripts/dump_prompts.py --check` → up to date.
Mutation: delete the line containing "คุณไม่ได้แก้ PLO" → `test_rubric_says_the_reviewer_changes_nothing` fails; restore.

- [ ] **Step 5: Commit**

```bash
git add src/curriculum_agent/prompts/plo_review.py scripts/dump_prompts.py docs/prompt-inventory.md tests/unit/test_plo_review_prompt.py
git commit -m "feat(prompts): the PLO set review prompt

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Review models and the pure-code judge

**Files:**
- Modify: `src/curriculum_agent/models.py` (append the four review models at the end of the PLO section)
- Create: `src/curriculum_agent/stages/plo_review.py` (pure parts only in this task)
- Test: `tests/unit/test_plo_review_accept.py`

**Interfaces:**
- Consumes: `ReviewItem` (Task 2) — not used yet in this task.
- Produces (in `models.py`): `RedundancyFinding(plo_ids: list[str], reason_th: str, suggestion_th: str = "")`, `KsecFinding(plo_id: str, current: list[str], suggested: list[str], agrees: bool, reason_th: str = "")`, `BloomFinding(plo_id: str, declared: BloomLevel, suggested_level: BloomLevel | None = None, reason_th: str = "")`, `PLOSetReview(program_id: str, plo_fingerprint: str, model: str, created_at: datetime, redundancies: list[RedundancyFinding] = [], ksec: list[KsecFinding] = [], bloom: list[BloomFinding] = [], bloom_distribution_th: str = "", summary_th: str = "")`.
- Produces (in `stages/plo_review.py`): `class ReviewAnswer(BaseModel)` (+ `_Redundancy`, `_KsecVerdict`, `_BloomVerdict`), `MAX_REDUNDANCY_GROUP = 3`, `def current_ksec(plo: PLO, needs_by_id: Mapping[str, Need]) -> list[str]`, `def plo_fingerprint(plos: Sequence[PLO]) -> str`, `def is_stale(review: PLOSetReview, plos: Sequence[PLO]) -> bool`, `def accept_review(answer: ReviewAnswer, plos: Sequence[PLO], needs_by_id: Mapping[str, Need], *, program_id: str, fingerprint: str, model: str, created_at: datetime) -> tuple[PLOSetReview, Counter[str]]`, `def is_empty(review: PLOSetReview) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

from datetime import datetime

from curriculum_agent.models import PLO, BloomLevel, KSECCategory, Need, SMARTCheck
from curriculum_agent.stages.plo_review import (
    ReviewAnswer,
    _BloomVerdict,
    _KsecVerdict,
    _Redundancy,
    accept_review,
    current_ksec,
    is_empty,
    is_stale,
    plo_fingerprint,
)

_SMART = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)
_NOW = datetime(2026, 10, 5, 12, 0, 0)


def _need(nid: str, ksec: KSECCategory) -> Need:
    return Need(
        need_id=nid,
        program_id="p",
        statement_th=f"ต้องการบัณฑิตที่ทำงาน {nid} ในสถานประกอบการจริงได้",
        ksec_category=ksec,
        bloom_level=BloomLevel.APPLY,
        member_skill_ids=[f"S-{nid}"],
        source_evidence_ids=[f"E-{nid}"],
        freq=1,
        demand_score=0.5,
    )


def _plo(pid: str, need_ids: list[str], *, statement: str | None = None) -> PLO:
    return PLO(
        plo_id=pid,
        program_id="p",
        statement_th=statement or f"วิเคราะห์ระบบงาน {pid} เพื่อเสนอแนวทางแก้ปัญหา",
        bloom_level=BloomLevel.APPLY,
        action_verb_th="วิเคราะห์",
        smart_check=_SMART,
        source_need_ids=need_ids,
        source_evidence_ids=["E1"],
        rationale_th="เหตุผล",
    )


NEEDS = {"n1": _need("n1", KSECCategory.S), "n2": _need("n2", KSECCategory.EC)}
PLOS = [_plo("PLO1", ["n1"]), _plo("PLO2", ["n2"]), _plo("PLO3", ["n1", "n2"])]


def _accept(answer: ReviewAnswer):
    return accept_review(
        answer, PLOS, NEEDS, program_id="p", fingerprint="f", model="m", created_at=_NOW
    )


# ------------------------------ current_ksec ------------------------------


def test_current_ksec_expands_ec_and_follows_ksec_order() -> None:
    assert current_ksec(PLOS[1], NEEDS) == ["E", "C"]
    assert current_ksec(PLOS[2], NEEDS) == ["S", "E", "C"]


def test_current_ksec_ignores_an_unknown_need() -> None:
    assert current_ksec(_plo("PLO9", ["gone", "n1"]), NEEDS) == ["S"]


# ------------------------------ fingerprint ------------------------------


def test_fingerprint_ignores_order_and_moves_on_each_field() -> None:
    base = plo_fingerprint(PLOS)
    assert plo_fingerprint(list(reversed(PLOS))) == base
    changed = [PLOS[0].model_copy(update={"statement_th": "ออกแบบระบบ"}), *PLOS[1:]]
    assert plo_fingerprint(changed) != base
    for field, value in [
        ("bloom_level", BloomLevel.CREATE),
        ("action_verb_th", "ออกแบบ"),
        ("is_optional", True),
        ("source_need_ids", ["n2"]),
    ]:
        assert plo_fingerprint([PLOS[0].model_copy(update={field: value}), *PLOS[1:]]) != base


def test_is_stale_compares_fingerprints() -> None:
    review, _ = accept_review(
        ReviewAnswer(summary_th="ดี"), PLOS, NEEDS,
        program_id="p", fingerprint=plo_fingerprint(PLOS), model="m", created_at=_NOW,
    )
    assert not is_stale(review, PLOS)
    assert is_stale(review, PLOS[:2])


# ------------------------------ redundancy ------------------------------


def test_redundancy_keeps_known_ids_and_drops_short_or_oversized_groups() -> None:
    review, drops = _accept(
        ReviewAnswer(
            redundancies=[
                _Redundancy(plo_ids=["PLO1", "PLO2"], reason_th="ซ้ำ", suggestion_th="รวม"),
                _Redundancy(plo_ids=["PLO1", "PLO99"], reason_th="ซ้ำ"),
                _Redundancy(plo_ids=["PLO1", "PLO2", "PLO3", "PLO1"], reason_th="ซ้ำ"),
                _Redundancy(plo_ids=["PLO2", "PLO1"], reason_th="ซ้ำอีก"),
                _Redundancy(plo_ids=["PLO2", "PLO3"], reason_th="  "),
            ]
        )
    )
    assert [r.plo_ids for r in review.redundancies] == [["PLO1", "PLO2"], ["PLO1", "PLO2", "PLO3"]]
    assert drops["redundancy"] == 3


def test_a_group_naming_more_than_three_distinct_plos_is_dropped() -> None:
    plos = [*PLOS, _plo("PLO4", ["n1"])]
    review, _ = accept_review(
        ReviewAnswer(redundancies=[_Redundancy(plo_ids=["PLO1", "PLO2", "PLO3", "PLO4"], reason_th="ซ้ำ")]),
        plos, NEEDS, program_id="p", fingerprint="f", model="m", created_at=_NOW,
    )
    assert review.redundancies == []


# ------------------------------ KSEC ------------------------------


def test_ksec_current_and_agrees_are_computed_in_code() -> None:
    review, drops = _accept(
        ReviewAnswer(
            ksec=[
                _KsecVerdict(plo_id="PLO1", suggested=["s", "E"], reason_th="มีจริยธรรมด้วย"),
                _KsecVerdict(plo_id="PLO2", suggested=["EC"], reason_th="ตรง"),
                _KsecVerdict(plo_id="PLO2", suggested=["K"], reason_th="ซ้ำ plo_id"),
                _KsecVerdict(plo_id="PLO99", suggested=["K"], reason_th="ไม่มีจริง"),
                _KsecVerdict(plo_id="PLO3", suggested=["X", "Y"], reason_th="ไม่มีหมวดจริง"),
            ]
        )
    )
    by_id = {k.plo_id: k for k in review.ksec}
    assert set(by_id) == {"PLO1", "PLO2"}
    assert by_id["PLO1"].current == ["S"] and by_id["PLO1"].suggested == ["S", "E"]
    assert by_id["PLO1"].agrees is False
    assert by_id["PLO2"].suggested == ["E", "C"] and by_id["PLO2"].agrees is True
    assert drops["ksec"] == 3


def test_ksec_accepts_the_e_bar_c_spelling() -> None:
    review, _ = _accept(ReviewAnswer(ksec=[_KsecVerdict(plo_id="PLO2", suggested=["E|C"], reason_th="ตรง")]))
    assert review.ksec[0].suggested == ["E", "C"]


# ------------------------------ Bloom ------------------------------


def test_bloom_declared_is_filled_in_code_and_a_bad_level_becomes_none() -> None:
    review, drops = _accept(
        ReviewAnswer(
            bloom=[
                _BloomVerdict(plo_id="PLO1", suggested_level="Analyze", reason_th="กรรมคือการวิเคราะห์"),
                _BloomVerdict(plo_id="PLO2", suggested_level="psychic", reason_th="ระดับสูงเกิน"),
                _BloomVerdict(plo_id="PLO3", suggested_level="apply", reason_th=""),
                _BloomVerdict(plo_id="PLO99", suggested_level="apply", reason_th="ไม่มีจริง"),
            ]
        )
    )
    by_id = {b.plo_id: b for b in review.bloom}
    assert set(by_id) == {"PLO1", "PLO2"}
    assert by_id["PLO1"].declared is BloomLevel.APPLY
    assert by_id["PLO1"].suggested_level is BloomLevel.ANALYZE
    assert by_id["PLO2"].suggested_level is None
    assert drops["bloom"] == 2


# ------------------------------ texts and emptiness ------------------------------


def test_texts_are_stripped_and_an_answer_with_nothing_is_empty() -> None:
    review, _ = _accept(ReviewAnswer(summary_th="  ดีแล้ว  ", bloom_distribution_th=" apply เป็นหลัก "))
    assert review.summary_th == "ดีแล้ว"
    assert review.bloom_distribution_th == "apply เป็นหลัก"
    assert not is_empty(review)
    blank, _ = _accept(ReviewAnswer(summary_th="   "))
    assert is_empty(blank)
```

- [ ] **Step 2: Run to see them fail**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/unit/test_plo_review_accept.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Add the models**

Append to `models.py` (after the PLO models; `datetime` and `BloomLevel` are already available there — import `datetime` if not):

```python
class RedundancyFinding(BaseModel):
    """PLOs the set review reads as one outcome. Advisory."""

    plo_ids: list[str]
    reason_th: str
    suggestion_th: str = ""


class KsecFinding(BaseModel):
    """Where one PLO's domain should sit, possibly several of K/S/E/C.

    `current` and `agrees` are computed in code from the PLO's Needs; only
    `suggested` and `reason_th` come from the reviewer. Plain `str` lists, not a
    Literal: a stored row must stay readable if the vocabulary ever moves (the
    `soft_flags` lesson).
    """

    plo_id: str
    current: list[str]
    suggested: list[str]
    agrees: bool
    reason_th: str = ""


class BloomFinding(BaseModel):
    plo_id: str
    declared: BloomLevel
    suggested_level: BloomLevel | None = None
    reason_th: str = ""


class PLOSetReview(BaseModel):
    """The advisory review of one program's PLO set — see stages/plo_review.py.

    `plo_fingerprint` is the set it was made from; a review whose fingerprint no
    longer matches the stored PLOs is stale and is shown labelled as such.
    """

    program_id: str
    plo_fingerprint: str
    model: str
    created_at: datetime
    redundancies: list[RedundancyFinding] = Field(default_factory=list)
    ksec: list[KsecFinding] = Field(default_factory=list)
    bloom: list[BloomFinding] = Field(default_factory=list)
    bloom_distribution_th: str = ""
    summary_th: str = ""
```

- [ ] **Step 4: Write the pure part of `stages/plo_review.py`**

```python
"""Review the finished PLO set once, before the report. Advisory only.

Every other check reads one PLO against its own Needs; this reads the set —
redundancy between drafts, a domain that spans KSEC tags, the Bloom
distribution. It changes nothing: its findings are stored per program and shown
on the report page. See docs/superpowers/specs/2026-10-04-plo-set-review-design.md.

The response schema is loose on purpose (plain strings, no Literal): a pydantic
failure fails the whole call and loses every good entry with the bad one, the
lesson of `supporting_indices` and `need_dedup.accept_groups`. `accept_review`
judges entry by entry, and computes in code everything the model could only
claim — a PLO's current KSEC, whether a suggestion agrees, the declared level.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from curriculum_agent.models import (
    PLO,
    BloomFinding,
    BloomLevel,
    KsecFinding,
    Need,
    PLOSetReview,
    RedundancyFinding,
)

MAX_REDUNDANCY_GROUP = 3
_KSEC_ORDER = ("K", "S", "E", "C")


class _Redundancy(BaseModel):
    plo_ids: list[str] = Field(default_factory=list)
    reason_th: str = ""
    suggestion_th: str = ""


class _KsecVerdict(BaseModel):
    plo_id: str = ""
    suggested: list[str] = Field(default_factory=list)
    reason_th: str = ""


class _BloomVerdict(BaseModel):
    plo_id: str = ""
    suggested_level: str | None = None
    reason_th: str = ""


class ReviewAnswer(BaseModel):
    redundancies: list[_Redundancy] = Field(default_factory=list)
    ksec: list[_KsecVerdict] = Field(default_factory=list)
    bloom: list[_BloomVerdict] = Field(default_factory=list)
    bloom_distribution_th: str = ""
    summary_th: str = ""


def _normalize_ksec(values: Sequence[str]) -> list[str]:
    """K/S/E/C in canonical order; "EC" and "E|C" read as E and C; anything else dropped."""
    found: set[str] = set()
    for raw in values:
        token = raw.strip().upper().replace("|", "")
        if token == "EC":
            found.update({"E", "C"})
        elif token in _KSEC_ORDER:
            found.add(token)
    return [k for k in _KSEC_ORDER if k in found]


def current_ksec(plo: PLO, needs_by_id: Mapping[str, Need]) -> list[str]:
    """The KSEC tags of the Needs behind a PLO, EC expanded, unknown Needs ignored."""
    return _normalize_ksec(
        [needs_by_id[nid].ksec_category.value for nid in plo.source_need_ids if nid in needs_by_id]
    )


def plo_fingerprint(plos: Sequence[PLO]) -> str:
    """What the review was made from. Any edit a designer could act on moves it."""
    parts = [
        "\x1f".join(
            [
                p.plo_id,
                p.statement_th,
                p.bloom_level.value,
                p.action_verb_th,
                "1" if p.is_optional else "0",
                ",".join(sorted(p.source_need_ids)),
            ]
        )
        for p in sorted(plos, key=lambda p: p.plo_id)
    ]
    return hashlib.sha256("\x1e".join(parts).encode()).hexdigest()


def is_stale(review: PLOSetReview, plos: Sequence[PLO]) -> bool:
    return review.plo_fingerprint != plo_fingerprint(plos)


def is_empty(review: PLOSetReview) -> bool:
    """Nothing kept and nothing said: treated as a review that did not happen."""
    return not (review.redundancies or review.ksec or review.bloom or review.summary_th)


def _bloom_level(raw: str | None) -> BloomLevel | None:
    if raw is None:
        return None
    try:
        return BloomLevel(raw.strip().lower())
    except ValueError:
        return None


def accept_review(
    answer: ReviewAnswer,
    plos: Sequence[PLO],
    needs_by_id: Mapping[str, Need],
    *,
    program_id: str,
    fingerprint: str,
    model: str,
    created_at: datetime,
) -> tuple[PLOSetReview, Counter[str]]:
    """Keep what breaks no rule, entry by entry; count what was dropped."""
    by_id = {p.plo_id: p for p in plos}
    drops: Counter[str] = Counter()

    redundancies: list[RedundancyFinding] = []
    seen_groups: set[frozenset[str]] = set()
    for r in answer.redundancies:
        named = list(dict.fromkeys(i.strip() for i in r.plo_ids if i.strip()))
        known = [i for i in named if i in by_id]
        key = frozenset(known)
        # More than three named is dropped whole, not trimmed: which member to
        # cut is the judgement the model was asked for.
        if (
            len(known) < 2
            or len(named) > MAX_REDUNDANCY_GROUP
            or not r.reason_th.strip()
            or key in seen_groups
        ):
            drops["redundancy"] += 1
            continue
        seen_groups.add(key)
        redundancies.append(
            RedundancyFinding(
                plo_ids=known,
                reason_th=r.reason_th.strip(),
                suggestion_th=r.suggestion_th.strip(),
            )
        )

    ksec: list[KsecFinding] = []
    ksec_seen: set[str] = set()
    for k in answer.ksec:
        pid = k.plo_id.strip()
        suggested = _normalize_ksec(k.suggested)
        if pid not in by_id or pid in ksec_seen or not suggested:
            drops["ksec"] += 1
            continue
        ksec_seen.add(pid)
        current = current_ksec(by_id[pid], needs_by_id)
        ksec.append(
            KsecFinding(
                plo_id=pid,
                current=current,
                suggested=suggested,
                agrees=set(current) == set(suggested),
                reason_th=k.reason_th.strip(),
            )
        )

    bloom: list[BloomFinding] = []
    bloom_seen: set[str] = set()
    for b in answer.bloom:
        pid = b.plo_id.strip()
        if pid not in by_id or pid in bloom_seen:
            drops["bloom"] += 1
            continue
        declared = by_id[pid].bloom_level
        level = _bloom_level(b.suggested_level)
        if (level is None or level == declared) and not b.reason_th.strip():
            drops["bloom"] += 1
            continue
        bloom_seen.add(pid)
        bloom.append(
            BloomFinding(
                plo_id=pid, declared=declared, suggested_level=level, reason_th=b.reason_th.strip()
            )
        )

    review = PLOSetReview(
        program_id=program_id,
        plo_fingerprint=fingerprint,
        model=model,
        created_at=created_at,
        redundancies=redundancies,
        ksec=ksec,
        bloom=bloom,
        bloom_distribution_th=answer.bloom_distribution_th.strip(),
        summary_th=answer.summary_th.strip(),
    )
    return review, drops
```

Check the test expectations against this code before running: in `test_redundancy_keeps_known_ids_and_drops_short_or_oversized_groups`, `["PLO1","PLO2","PLO3","PLO1"]` de-duplicates to three named → kept; `["PLO2","PLO1"]` is the same set as the first → dropped; `["PLO1","PLO99"]` → one known → dropped; blank reason → dropped (3 drops). In the bloom test, `PLO3` with `"apply"` (= declared) and empty reason is dropped; `PLO2` with an invalid level but a reason is kept with `None`.

- [ ] **Step 5: Run tests; mutation-check**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/unit/test_plo_review_accept.py -q` → PASS, then the full suite.
Mutations (each must fail a test, then restore): `agrees=True` constant; drop the `len(named) > MAX_REDUNDANCY_GROUP` clause; drop the `"EC"` branch in `_normalize_ksec`.

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/models.py src/curriculum_agent/stages/plo_review.py tests/unit/test_plo_review_accept.py
git commit -m "feat(plo_review): review models and the pure-code judge

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Storage — table, migration, repository, cascade

**Files:**
- Modify: `src/curriculum_agent/data/orm.py` (add `PLOReviewTable` after `PLOTable`)
- Create: `migrations/versions/<new_rev>_plo_reviews.py` (`down_revision = "e4b6d19a3f72"` — confirm with `uv run alembic heads`)
- Modify: `src/curriculum_agent/data/repositories.py` (add `PLOReviewRepository` after `PLORepository`; add one delete to `ProgramRepository.delete_cascade` before the `ProgramTable` delete)
- Test: `tests/unit/test_plo_review_storage.py`

**Interfaces:**
- Consumes: `PLOSetReview` (Task 3).
- Produces: `class PLOReviewRepository` with `async def get(self, program_id: str) -> PLOSetReview | None`, `async def upsert(self, review: PLOSetReview) -> None`, `async def delete_by_program(self, program_id: str) -> int`.

- [ ] **Step 1: Write the failing tests**

Use the mocked-session pattern from `tests/unit/test_plo_composite_primary_key.py` (`_fake_session_ctx`, patching `curriculum_agent.data.repositories.AsyncSessionLocal`), and its migration-module-loading pattern (load the file with `importlib.util`, run `upgrade()`/`downgrade()` against a recording stand-in for `op`).

```python
from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from curriculum_agent.data.orm import PLOReviewTable
from curriculum_agent.data.repositories import PLOReviewRepository
from curriculum_agent.models import BloomLevel, BloomFinding, KsecFinding, PLOSetReview, RedundancyFinding

_REVIEW = PLOSetReview(
    program_id="p",
    plo_fingerprint="f" * 64,
    model="z-ai/glm-5.3-flash",
    created_at=datetime(2026, 10, 5, 12, 0, 0),
    redundancies=[RedundancyFinding(plo_ids=["PLO1", "PLO4"], reason_th="ซ้ำ", suggestion_th="รวม")],
    ksec=[KsecFinding(plo_id="PLO6", current=["S"], suggested=["S", "E"], agrees=False, reason_th="จริยธรรม")],
    bloom=[BloomFinding(plo_id="PLO5", declared=BloomLevel.CREATE, suggested_level=BloomLevel.APPLY, reason_th="ปริญญาตรี")],
    bloom_distribution_th="apply เป็นหลัก",
    summary_th="มีสองข้อซ้ำกัน",
)


def _ctx(session: AsyncMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def test_table_is_keyed_by_program() -> None:
    assert {c.name for c in PLOReviewTable.__table__.primary_key.columns} == {"program_id"}


async def test_upsert_then_get_round_trips_the_review() -> None:
    stored: dict[str, PLOReviewTable] = {}
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda cls, key: stored.get(key))
    session.add = MagicMock(side_effect=lambda row: stored.__setitem__(row.program_id, row))
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_ctx(session)):
        await PLOReviewRepository().upsert(_REVIEW)
        got = await PLOReviewRepository().get("p")
    assert got == _REVIEW


async def test_get_answers_none_for_a_program_never_reviewed() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_ctx(session)):
        assert await PLOReviewRepository().get("nobody") is None


async def test_upsert_replaces_the_existing_row() -> None:
    existing = PLOReviewTable(
        program_id="p", plo_fingerprint="old", model="m", created_at=datetime(2026, 1, 1), review={}
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=existing)
    session.add = MagicMock()
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_ctx(session)):
        await PLOReviewRepository().upsert(_REVIEW)
    session.add.assert_not_called()
    assert existing.plo_fingerprint == "f" * 64
    assert existing.review["summary_th"] == "มีสองข้อซ้ำกัน"


def test_program_delete_cascade_drops_the_review() -> None:
    source = Path("src/curriculum_agent/data/repositories.py").read_text(encoding="utf-8")
    cascade = source.split("async def delete_cascade", 1)[1].split("async def ", 1)[0]
    assert "PLOReviewTable" in cascade
    assert cascade.index("PLOReviewTable") < cascade.index("ProgramTable")


@pytest.fixture
def migration() -> ModuleType:
    path = next(Path("migrations/versions").glob("*_plo_reviews.py"))
    spec = importlib.util.spec_from_file_location("plo_reviews_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_follows_the_composite_key_migration(migration: ModuleType) -> None:
    assert migration.down_revision == "e4b6d19a3f72"


def test_upgrade_creates_and_downgrade_drops_the_table(migration: ModuleType) -> None:
    op = MagicMock()
    with patch.object(migration, "op", op):
        migration.upgrade()
        migration.downgrade()
    assert op.create_table.call_args.args[0] == "plo_reviews"
    op.drop_table.assert_called_once_with("plo_reviews")
```

If the repo's existing migration tests load migrations differently (see `tests/unit/test_migration_backfill.py`), follow that instead; keep the same assertions.

- [ ] **Step 2: Run to see them fail**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/unit/test_plo_review_storage.py -q` → FAIL.

- [ ] **Step 3: ORM, repository, cascade, migration**

`orm.py`, after `PLOTable`:

```python
class PLOReviewTable(Base):
    """The advisory PLO set review, one row per program (stages/plo_review.py).

    Keyed by program alone: only the latest review is kept, and a new one
    replaces it. `plo_fingerprint` says which PLO set it was made from; the
    findings ride in one JSONB column because nothing queries inside them.
    """

    __tablename__ = "plo_reviews"

    program_id: Mapped[str] = mapped_column(
        String, ForeignKey("programs.program_id"), primary_key=True
    )
    plo_fingerprint: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    review: Mapped[dict[str, Any]] = mapped_column(JSONB)
```

`repositories.py`: add `PLOReviewTable` to the `curriculum_agent.data.orm` import and `PLOSetReview` to the models import; add after `PLORepository`:

```python
_REVIEW_BODY_FIELDS = {"redundancies", "ksec", "bloom", "bloom_distribution_th", "summary_th"}


class PLOReviewRepository:
    """The latest PLO set review per program. Advisory data; see stages/plo_review.py."""

    async def get(self, program_id: str) -> PLOSetReview | None:
        async with AsyncSessionLocal() as session:
            row = await session.get(PLOReviewTable, program_id)
            if row is None:
                return None
            return PLOSetReview.model_validate(
                {
                    **row.review,
                    "program_id": row.program_id,
                    "plo_fingerprint": row.plo_fingerprint,
                    "model": row.model,
                    "created_at": row.created_at,
                }
            )

    async def upsert(self, review: PLOSetReview) -> None:
        body = review.model_dump(mode="json", include=_REVIEW_BODY_FIELDS)
        async with AsyncSessionLocal() as session:
            existing = await session.get(PLOReviewTable, review.program_id)
            if existing is None:
                session.add(
                    PLOReviewTable(
                        program_id=review.program_id,
                        plo_fingerprint=review.plo_fingerprint,
                        model=review.model,
                        created_at=review.created_at,
                        review=body,
                    )
                )
            else:
                existing.plo_fingerprint = review.plo_fingerprint
                existing.model = review.model
                existing.created_at = review.created_at
                existing.review = body
            await session.commit()

    async def delete_by_program(self, program_id: str) -> int:
        async with AsyncSessionLocal() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    delete(PLOReviewTable).where(PLOReviewTable.program_id == program_id)
                ),
            )
            await session.commit()
            return result.rowcount
```

In `ProgramRepository.delete_cascade`, add before the `ProgramTable` delete (it has a FK to programs):

```python
            await session.execute(
                delete(PLOReviewTable).where(PLOReviewTable.program_id == program_id)
            )
```

Migration file `migrations/versions/<rev>_plo_reviews.py` — generate a 12-hex revision id, style like `e4b6d19a3f72_plos_composite_primary_key.py`:

```python
"""plo_reviews: the advisory PLO set review, one row per program

Revision ID: <rev>
Revises: e4b6d19a3f72
Create Date: 2026-10-05 00:00:00.000000

A new table, so nothing to backfill: a program with no row simply has not been
reviewed yet. See docs/superpowers/specs/2026-10-04-plo-set-review-design.md.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "<rev>"
down_revision: Union[str, None] = "e4b6d19a3f72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plo_reviews",
        sa.Column("program_id", sa.String(), sa.ForeignKey("programs.program_id"), nullable=False),
        sa.Column("plo_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("review", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("program_id", name="plo_reviews_pkey"),
    )


def downgrade() -> None:
    op.drop_table("plo_reviews")
```

Do NOT run `alembic upgrade` against the live DB. Render offline to check: `uv run alembic upgrade e4b6d19a3f72:head --sql`.

- [ ] **Step 4: Run tests; mutation-check**

Full suite + ruff + mypy. Mutations: remove the cascade delete → `test_program_delete_cascade_drops_the_review` fails; in `upsert` skip `existing.review = body` → `test_upsert_replaces_the_existing_row` fails. Restore.

- [ ] **Step 5: Commit**

```bash
git add src/curriculum_agent/data/orm.py src/curriculum_agent/data/repositories.py migrations/versions/<rev>_plo_reviews.py tests/unit/test_plo_review_storage.py
git commit -m "feat(db): store one PLO set review per program

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Running the review — reuse, call, store, fail safe

**Files:**
- Modify: `src/curriculum_agent/stages/plo_review.py` (orchestration)
- Modify: `tests/conftest.py` (autouse fixture keeping every other test offline)
- Test: `tests/unit/test_plo_review_run.py`

**Interfaces:**
- Consumes: `complete_plo_review` (Task 1), `ReviewItem`, `build_plo_review_prompt` (Task 2), `accept_review`, `plo_fingerprint`, `current_ksec`, `is_empty` (Task 3), `PLOReviewRepository` (Task 4), `ProgramRepository`, `NeedRepository`, `build_program_context_th`.
- Produces: `class ReviewAlreadyRunning(RuntimeError)`; `async def fresh_review(program_id: str, plos: Sequence[PLO]) -> PLOSetReview | None` (always calls; stores and returns on success; `None` on any failure; raises `ReviewAlreadyRunning`); `async def review_plo_set(program_id: str, plos: Sequence[PLO]) -> PLOSetReview | None` (reuses a stored review with a matching fingerprint, else `fresh_review`, else the stored one); `async def run(state: AgentState) -> AgentState` (sets `state["plo_review"]` to the review dumped as JSON, or `None`).

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from curriculum_agent.config import settings
from curriculum_agent.models import (
    PLO,
    BloomLevel,
    KSECCategory,
    Need,
    PLOSetReview,
    ProgramMetadata,
    SMARTCheck,
)
from curriculum_agent.stages import plo_review as pr

_SMART = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)
_META = ProgramMetadata.model_validate(
    {"program_id": "p", "field": "การแปล", "degree_level": "bachelor", "duration_years": 4,
     "faculty": "ศิลปศาสตร์", "university": "Test"}
)
_NEED = Need(
    need_id="n1", program_id="p", statement_th="ต้องการบัณฑิตที่แปลเอกสารธุรกิจได้",
    ksec_category=KSECCategory.S, bloom_level=BloomLevel.APPLY, member_skill_ids=["s1"],
    source_evidence_ids=["e1"], freq=1, demand_score=0.5,
)
_PLOS = [
    PLO(plo_id=pid, program_id="p", statement_th=f"แปลเอกสารธุรกิจ {pid}",
        bloom_level=BloomLevel.APPLY, action_verb_th="แปล", smart_check=_SMART,
        source_need_ids=["n1"], source_evidence_ids=["e1"], rationale_th="เหตุผล")
    for pid in ("PLO1", "PLO2")
]
_ANSWER = pr.ReviewAnswer(
    redundancies=[pr._Redundancy(plo_ids=["PLO1", "PLO2"], reason_th="ซ้ำ", suggestion_th="รวม")],
    summary_th="สองข้อซ้ำกัน",
)


class _MemoryRepo:
    rows: dict[str, PLOSetReview] = {}

    async def get(self, program_id: str) -> PLOSetReview | None:
        return self.rows.get(program_id)

    async def upsert(self, review: PLOSetReview) -> None:
        self.rows[review.program_id] = review


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Undo the conftest kill switch for this module and fake every boundary."""
    _MemoryRepo.rows = {}
    monkeypatch.setattr(settings, "plo_review_provider", "openrouter")
    monkeypatch.setattr(pr, "PLOReviewRepository", _MemoryRepo)
    monkeypatch.setattr(pr, "ProgramRepository", lambda: AsyncMock(get=AsyncMock(return_value=_META)))
    monkeypatch.setattr(pr, "NeedRepository", lambda: AsyncMock(list_by_program=AsyncMock(return_value=[_NEED])))
    call = AsyncMock(return_value=_ANSWER)
    monkeypatch.setattr(pr, "complete_plo_review", call)
    return call


async def test_a_fresh_review_is_judged_and_stored(live: AsyncMock) -> None:
    review = await pr.fresh_review("p", _PLOS)
    assert review is not None
    assert review.redundancies[0].plo_ids == ["PLO1", "PLO2"]
    assert review.plo_fingerprint == pr.plo_fingerprint(_PLOS)
    assert _MemoryRepo.rows["p"] == review
    live.assert_awaited_once()


async def test_the_prompt_carries_every_plo_and_its_needs(live: AsyncMock) -> None:
    await pr.fresh_review("p", _PLOS)
    messages = live.await_args.args[1]
    user = messages[1]["content"]
    assert "[PLO1]" in user and "[PLO2]" in user
    assert "ต้องการบัณฑิตที่แปลเอกสารธุรกิจได้" in user
    assert live.await_args.kwargs["temperature"] == 0


async def test_an_unchanged_set_reuses_the_stored_review(live: AsyncMock) -> None:
    first = await pr.review_plo_set("p", _PLOS)
    again = await pr.review_plo_set("p", _PLOS)
    assert again == first
    live.assert_awaited_once()


async def test_a_changed_set_is_reviewed_again(live: AsyncMock) -> None:
    await pr.review_plo_set("p", _PLOS)
    changed = [_PLOS[0].model_copy(update={"statement_th": "ล่ามการเจรจาธุรกิจ"}), _PLOS[1]]
    await pr.review_plo_set("p", changed)
    assert live.await_count == 2


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("provider down"), TimeoutError()],
)
async def test_a_failed_call_stores_nothing_and_returns_the_stored_review(
    live: AsyncMock, failure: BaseException
) -> None:
    old = await pr.fresh_review("p", _PLOS)
    live.side_effect = failure
    changed = [_PLOS[0].model_copy(update={"statement_th": "ล่ามการเจรจาธุรกิจ"}), _PLOS[1]]
    assert await pr.fresh_review("p", changed) is None
    assert await pr.review_plo_set("p", changed) == old
    assert _MemoryRepo.rows["p"] == old


async def test_an_answer_the_judge_empties_is_a_failure(live: AsyncMock) -> None:
    live.return_value = pr.ReviewAnswer(
        redundancies=[pr._Redundancy(plo_ids=["PLO9", "PLO8"], reason_th="ไม่มีจริง")]
    )
    assert await pr.fresh_review("p", _PLOS) is None
    assert "p" not in _MemoryRepo.rows


async def test_the_switched_off_slot_never_calls(live: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "plo_review_provider", "")
    assert await pr.fresh_review("p", _PLOS) is None
    live.assert_not_awaited()


async def test_a_second_review_while_one_is_in_flight_is_refused(live: AsyncMock) -> None:
    import asyncio

    entered, release = asyncio.Event(), asyncio.Event()

    async def hang(*_a: object, **_k: object) -> pr.ReviewAnswer:
        entered.set()
        await release.wait()
        return _ANSWER

    live.side_effect = hang
    first = asyncio.create_task(pr.fresh_review("p", _PLOS))
    await entered.wait()
    try:
        with pytest.raises(pr.ReviewAlreadyRunning):
            await asyncio.wait_for(pr.fresh_review("p", _PLOS), timeout=2)
    finally:
        release.set()
        await first


async def test_run_puts_the_review_on_the_state(live: AsyncMock) -> None:
    state = await pr.run({"program_id": "p", "plos": [p.model_dump(mode="json") for p in _PLOS]})
    assert state["plo_review"]["summary_th"] == "สองข้อซ้ำกัน"


async def test_run_with_no_plos_leaves_no_review(live: AsyncMock) -> None:
    state = await pr.run({"program_id": "p", "plos": []})
    assert state["plo_review"] is None
    live.assert_not_awaited()
```

- [ ] **Step 2: Run to see them fail**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/unit/test_plo_review_run.py -q` → FAIL.

- [ ] **Step 3: Write the orchestration**

Add to `stages/plo_review.py` (imports at the top of the module; keep the Task 3 code):

```python
import asyncio
from datetime import UTC

from loguru import logger

from curriculum_agent.config import settings
from curriculum_agent.data.repositories import NeedRepository, PLOReviewRepository, ProgramRepository
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_plo_review
from curriculum_agent.prompts.plo_review import ReviewItem, build_plo_review_prompt
from curriculum_agent.prompts.program_context import build_program_context_th

_ATTEMPTS = 2
_MAX_TOKENS = 8192

# Per process, like plo_synthesis._SYNTHESIS_IN_FLIGHT and for the same reason:
# two forced reviews of one program racing to write its single row. The same
# limit applies — a multi-worker deployment needs a DB-level lock.
_REVIEW_IN_FLIGHT: set[str] = set()


class ReviewAlreadyRunning(RuntimeError):
    """Raised by `fresh_review` when the program already has a review in flight."""


def _items(plos: Sequence[PLO], needs_by_id: Mapping[str, Need]) -> list[ReviewItem]:
    return [
        ReviewItem(
            plo_id=p.plo_id,
            is_optional=p.is_optional,
            statement_th=p.statement_th,
            action_verb_th=p.action_verb_th,
            bloom_level=p.bloom_level.value,
            current_ksec=tuple(current_ksec(p, needs_by_id)),
            need_statements_th=tuple(
                needs_by_id[nid].statement_th for nid in p.source_need_ids if nid in needs_by_id
            ),
        )
        for p in sorted(plos, key=lambda p: (p.is_optional, len(p.plo_id), p.plo_id))
    ]


async def _call(program_id: str, plos: Sequence[PLO]) -> PLOSetReview | None:
    """One review call, judged. None on every failure — nothing is manufactured."""
    if not settings.plo_review_provider:
        logger.info("plo_review: disabled — the report goes out without a set review")
        return None
    metadata = await ProgramRepository().get(program_id)
    needs = await NeedRepository().list_by_program(program_id)
    needs_by_id = {n.need_id: n for n in needs}
    messages = build_plo_review_prompt(
        _items(plos, needs_by_id),
        program_context=build_program_context_th(metadata.model_dump(mode="json"))
        if metadata
        else None,
    )
    try:
        async with asyncio.timeout(settings.plo_review_timeout_seconds):
            answer = await complete_plo_review(
                ReviewAnswer,
                messages,
                max_retries=_ATTEMPTS,
                temperature=0,
                max_tokens=_MAX_TOKENS,
            )
    except Exception as exc:  # provider error, timeout, truncation, schema failure
        logger.warning(f"plo_review: call failed for {program_id}, nothing stored: {exc!r}")
        return None
    review, drops = accept_review(
        answer,
        plos,
        needs_by_id,
        program_id=program_id,
        fingerprint=plo_fingerprint(plos),
        model=settings.plo_review_model,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    logger.info(
        f"plo_review: kept {len(review.redundancies)} redundancy / {len(review.ksec)} ksec / "
        f"{len(review.bloom)} bloom, dropped {dict(drops) or 'nothing'}"
    )
    if is_empty(review):
        logger.warning(f"plo_review: the answer for {program_id} held nothing usable, nothing stored")
        return None
    return review


async def fresh_review(program_id: str, plos: Sequence[PLO]) -> PLOSetReview | None:
    """Always calls. Stores and returns the review, or None if it did not happen."""
    if program_id in _REVIEW_IN_FLIGHT:
        raise ReviewAlreadyRunning(
            f"กำลังตรวจชุด PLO ของโปรแกรม '{program_id}' อยู่ — รอให้รอบเดิมเสร็จก่อน"
        )
    _REVIEW_IN_FLIGHT.add(program_id)  # no await between the check and the add
    try:
        review = await _call(program_id, plos)
        if review is not None:
            await PLOReviewRepository().upsert(review)
        return review
    finally:
        _REVIEW_IN_FLIGHT.discard(program_id)


async def review_plo_set(program_id: str, plos: Sequence[PLO]) -> PLOSetReview | None:
    """The review the report should show: reused if the set is unchanged."""
    stored = await PLOReviewRepository().get(program_id)
    if stored is not None and not is_stale(stored, plos):
        return stored
    try:
        fresh = await fresh_review(program_id, plos)
    except ReviewAlreadyRunning:
        logger.info(f"plo_review: a review of {program_id} is already running — showing the stored one")
        return stored
    return fresh if fresh is not None else stored


async def run(state: AgentState) -> AgentState:
    """Graph and report-route entry: put the set review on the state for plo_report."""
    program_id = state.get("program_id", "unknown")
    plos = [PLO.model_validate(d) for d in state.get("plos", [])]
    review = await review_plo_set(program_id, plos) if plos else None
    state["plo_review"] = review.model_dump(mode="json") if review is not None else None
    return state
```

Check for an import cycle: `curriculum_agent.data.repositories` imports `curriculum_agent.graph`, and this module imports both. `plo_report.py` already imports `NeedRepository` and `AgentState` the same way, so this is safe; if mypy or import fails, mirror `plo_report.py`'s imports exactly.

- [ ] **Step 4: Add the conftest autouse fixture**

Append to `tests/conftest.py`:

```python
class _NoStoredReview:
    async def get(self, program_id: str) -> None:
        return None

    async def upsert(self, review: object) -> None:
        return None


@pytest.fixture(autouse=True)
def _plo_review_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """The set review runs before every report, and both reach the network and
    the database. Off by default in tests — the same answer as the kill switch,
    so every report test sees `review=None` exactly as before the review existed.
    The review's own tests turn it back on and fake each boundary themselves."""
    from curriculum_agent.stages import plo_review  # noqa: PLC0415

    monkeypatch.setattr(settings, "plo_review_provider", "")
    monkeypatch.setattr(plo_review, "PLOReviewRepository", _NoStoredReview)
```

- [ ] **Step 5: Run tests; mutation-check**

Full suite + ruff + mypy. Mutations (each must fail a test; restore): remove the stale check in `review_plo_set` (always call) → reuse test fails; remove `if is_empty(review): ... return None` → empty-answer test fails; remove the in-flight check → the refusal test fails within ~2 s (TimeoutError, not a hang).

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/stages/plo_review.py tests/conftest.py tests/unit/test_plo_review_run.py
git commit -m "feat(plo_review): review the PLO set once per change, never block the report

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Wiring — graph, report, routes

**Files:**
- Modify: `src/curriculum_agent/graph.py` (`AgentState` key, a stage function, the node and edges at ~lines 213-234)
- Modify: `src/curriculum_agent/stages/plo_report.py` (add `review` and `review_stale` to the report)
- Modify: `src/curriculum_agent/api/routes/plos.py` (report route runs the review first; `PLOReportResponse` fields; two new routes)
- Test: `tests/unit/test_plo_review_wiring.py`

**Interfaces:**
- Consumes: `plo_review.run`, `fresh_review`, `ReviewAlreadyRunning`, `is_stale` (Tasks 3, 5), `PLOReviewRepository` (Task 4), `PLOSetReview`.
- Produces: graph node `"plo_review"`; `AgentState["plo_review"]: dict[str, Any] | None`; `report["review"]`, `report["review_stale"]`; `PLOReportResponse.review: PLOSetReview | None = None`, `PLOReportResponse.review_stale: bool = False`; `GET /programs/{id}/plos/review` and `POST /programs/{id}/plos/review/run` returning `PLOReviewResponse(review: PLOSetReview | None, stale: bool)`.

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from curriculum_agent.api.routes.plos import router
from curriculum_agent.config import settings
from curriculum_agent.graph import DESIGNER_STAGES, REVIEW_NODE_STAGE, build_graph
from curriculum_agent.models import PLO, BloomLevel, PLOSetReview, SMARTCheck
from curriculum_agent.stages import plo_report
from curriculum_agent.stages.plo_review import ReviewAlreadyRunning, plo_fingerprint

app = FastAPI()
app.include_router(router, prefix="/programs/{program_id}/plos")
client = TestClient(app)

_SMART = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)
_PLO = PLO(
    plo_id="PLO1", program_id="p1", statement_th="แปลเอกสารธุรกิจ", bloom_level=BloomLevel.APPLY,
    action_verb_th="แปล", smart_check=_SMART, source_need_ids=["c1"], source_evidence_ids=["e1"],
    rationale_th="เหตุผล",
)


def _review(fingerprint: str) -> PLOSetReview:
    return PLOSetReview(
        program_id="p1", plo_fingerprint=fingerprint, model="m",
        created_at=datetime(2026, 10, 5), summary_th="ดีแล้ว",
    )


# ------------------------------ graph ------------------------------


def test_plo_review_sits_between_the_plo_checkpoint_and_the_report() -> None:
    graph = build_graph().get_graph()
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("review_plos_node", "plo_review") in edges
    assert ("plo_review", "plo_report") in edges
    assert ("review_plos_node", "plo_report") not in edges


def test_plo_review_is_not_a_designer_stage_or_a_checkpoint() -> None:
    assert "plo_review" not in DESIGNER_STAGES
    assert "plo_review" not in REVIEW_NODE_STAGE


# ------------------------------ report ------------------------------


async def test_the_report_carries_the_review_and_whether_it_is_stale() -> None:
    state = {
        "program_id": "p1",
        "plos": [_PLO.model_dump(mode="json")],
        "plo_review": _review("not-this-set").model_dump(mode="json"),
    }
    with (
        patch.object(plo_report, "NeedRepository") as needs,
        patch.object(plo_report, "PLORepository") as plos_repo,
    ):
        needs.return_value.list_by_program = AsyncMock(return_value=[])
        plos_repo.return_value.bulk_insert = AsyncMock()
        out = await plo_report.run(state)
    assert out["report"]["review"]["summary_th"] == "ดีแล้ว"
    assert out["report"]["review_stale"] is True


async def test_a_report_without_a_review_says_so() -> None:
    state = {"program_id": "p1", "plos": [_PLO.model_dump(mode="json")]}
    with (
        patch.object(plo_report, "NeedRepository") as needs,
        patch.object(plo_report, "PLORepository") as plos_repo,
    ):
        needs.return_value.list_by_program = AsyncMock(return_value=[])
        plos_repo.return_value.bulk_insert = AsyncMock()
        out = await plo_report.run(state)
    assert out["report"]["review"] is None
    assert out["report"]["review_stale"] is False


# ------------------------------ routes ------------------------------


def test_report_route_runs_the_review_first() -> None:
    review_run = AsyncMock(side_effect=lambda s: {**s, "plo_review": _review(plo_fingerprint([_PLO])).model_dump(mode="json")})
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch("curriculum_agent.stages.plo_review.run", review_run),
        patch.object(plo_report, "NeedRepository") as needs,
        patch.object(plo_report, "PLORepository") as plos_repo,
    ):
        repo.list_by_program = AsyncMock(return_value=[_PLO])
        needs.return_value.list_by_program = AsyncMock(return_value=[])
        plos_repo.return_value.bulk_insert = AsyncMock()
        resp = client.post("/programs/p1/plos/report/run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["review"]["summary_th"] == "ดีแล้ว"
    assert body["review_stale"] is False
    review_run.assert_awaited_once()


def test_get_review_reports_staleness() -> None:
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch("curriculum_agent.api.routes.plos.PLOReviewRepository") as rr,
    ):
        repo.list_by_program = AsyncMock(return_value=[_PLO])
        rr.return_value.get = AsyncMock(return_value=_review("old"))
        resp = client.get("/programs/p1/plos/review")
    assert resp.status_code == 200
    assert resp.json()["stale"] is True


def test_get_review_with_none_stored() -> None:
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch("curriculum_agent.api.routes.plos.PLOReviewRepository") as rr,
    ):
        repo.list_by_program = AsyncMock(return_value=[_PLO])
        rr.return_value.get = AsyncMock(return_value=None)
        resp = client.get("/programs/p1/plos/review")
    assert resp.json() == {"review": None, "stale": False}


def test_review_run_422_without_plos() -> None:
    with patch("curriculum_agent.api.routes.plos._repo") as repo:
        repo.list_by_program = AsyncMock(return_value=[])
        assert client.post("/programs/p1/plos/review/run").status_code == 422


def test_review_run_503_when_switched_off() -> None:
    # conftest switches the slot off for every test.
    with patch("curriculum_agent.api.routes.plos._repo") as repo:
        repo.list_by_program = AsyncMock(return_value=[_PLO])
        resp = client.post("/programs/p1/plos/review/run")
    assert resp.status_code == 503


def test_review_run_503_when_the_review_failed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "plo_review_provider", "openrouter")
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch("curriculum_agent.stages.plo_review.fresh_review", AsyncMock(return_value=None)),
    ):
        repo.list_by_program = AsyncMock(return_value=[_PLO])
        assert client.post("/programs/p1/plos/review/run").status_code == 503


def test_review_run_409_while_one_is_in_flight(monkeypatch) -> None:
    monkeypatch.setattr(settings, "plo_review_provider", "openrouter")
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch(
            "curriculum_agent.stages.plo_review.fresh_review",
            AsyncMock(side_effect=ReviewAlreadyRunning("กำลังตรวจ")),
        ),
    ):
        repo.list_by_program = AsyncMock(return_value=[_PLO])
        assert client.post("/programs/p1/plos/review/run").status_code == 409


def test_review_run_returns_the_fresh_review(monkeypatch) -> None:
    monkeypatch.setattr(settings, "plo_review_provider", "openrouter")
    fresh = _review(plo_fingerprint([_PLO]))
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch("curriculum_agent.stages.plo_review.fresh_review", AsyncMock(return_value=fresh)),
    ):
        repo.list_by_program = AsyncMock(return_value=[_PLO])
        resp = client.post("/programs/p1/plos/review/run")
    assert resp.status_code == 200
    assert resp.json()["review"]["summary_th"] == "ดีแล้ว" and resp.json()["stale"] is False
```

- [ ] **Step 2: Run to see them fail**

Run: `PYTHONIOENCODING=utf-8 uv run pytest tests/unit/test_plo_review_wiring.py -q` → FAIL.

- [ ] **Step 3: Graph**

In `AgentState` (after `report`):

```python
    # The advisory PLO set review, from plo_review — read by plo_report, never
    # by anything that writes a PLO. None when the review did not run.
    plo_review: dict[str, Any] | None
```

Stage function next to `stage_5_plo_report`:

```python
async def stage_4b_plo_review(state: AgentState) -> AgentState:
    from curriculum_agent.stages.plo_review import run  # noqa: PLC0415

    return await run(state)
```

In `build_graph`: `g.add_node("plo_review", stage_4b_plo_review)`; replace `g.add_edge("review_plos_node", "plo_report")` with:

```python
    # No interrupt of its own: the review and the report share the report's
    # checkpoint (immutable rule 7's second exception).
    g.add_edge("review_plos_node", "plo_review")
    g.add_edge("plo_review", "plo_report")
```

`DESIGNER_STAGES`, `REVIEW_NODE_STAGE` and `stage_reached` stay unchanged.

- [ ] **Step 4: Report**

In `plo_report.run`, import `from curriculum_agent.models import PLOSetReview` and `from curriculum_agent.stages.plo_review import is_stale`; after `plos` is built:

```python
    review_dict = state.get("plo_review")
    review = PLOSetReview.model_validate(review_dict) if review_dict else None
```

and add to `report`:

```python
        # Advisory; may be stale (made from an earlier PLO set) or absent (the
        # review did not run). Never changes anything above.
        "review": review.model_dump(mode="json") if review is not None else None,
        "review_stale": review is not None and is_stale(review, plos),
```

If importing `stages.plo_review` from `plo_report` creates a cycle, move `plo_fingerprint`/`is_stale` usage behind a function-level import with `# noqa: PLC0415`, as the graph does.

- [ ] **Step 5: Routes**

In `api/routes/plos.py`: import `PLOReviewRepository` and `PLOSetReview` and `settings`. Extend `PLOReportResponse`:

```python
    # The advisory set review shown beside the report (stages/plo_review.py).
    review: PLOSetReview | None = None
    review_stale: bool = False
```

In `run_plo_report`, before `result_state = await run(state)`:

```python
    from curriculum_agent.stages import plo_review  # noqa: PLC0415

    state = await plo_review.run(state)
```

and pass `review=report["review"], review_stale=report["review_stale"]` into `PLOReportResponse`.

Add, **declared before any `/{plo_id}` route** (place right after `run_plo_report`):

```python
class PLOReviewResponse(BaseModel):
    review: PLOSetReview | None
    stale: bool


@router.get("/review", response_model=PLOReviewResponse)
async def get_plo_review(program_id: str) -> PLOReviewResponse:
    from curriculum_agent.stages.plo_review import is_stale  # noqa: PLC0415

    plos = await _repo.list_by_program(program_id)
    review = await PLOReviewRepository().get(program_id)
    return PLOReviewResponse(review=review, stale=review is not None and is_stale(review, plos))


@router.post("/review/run", response_model=PLOReviewResponse)
async def run_plo_review(program_id: str) -> PLOReviewResponse:
    from curriculum_agent.stages import plo_review  # noqa: PLC0415

    plos = await _repo.list_by_program(program_id)
    if not plos:
        raise HTTPException(
            status_code=422, detail="ยังไม่มี PLO สำหรับโปรแกรมนี้ กรุณารัน PLO Synthesis ก่อน"
        )
    if not settings.plo_review_provider:
        raise HTTPException(
            status_code=503, detail="ปิดการตรวจชุด PLO อยู่ (ตั้ง PLO_REVIEW_PROVIDER ไว้ว่าง)"
        )
    try:
        review = await plo_review.fresh_review(program_id, plos)
    except plo_review.ReviewAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if review is None:
        raise HTTPException(status_code=503, detail="ตรวจชุด PLO ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง")
    return PLOReviewResponse(review=review, stale=False)
```

- [ ] **Step 6: Run tests; mutation-check**

Full suite + ruff + mypy + `uv run python scripts/dump_prompts.py --check`. Existing graph/session tests (`test_session_stage_mapping.py`, `test_plo_report_graph.py`, `test_plo_report_router.py`) must still pass unchanged. Mutations: wire `review_plos_node → plo_report` directly → graph test fails; drop `state = await plo_review.run(state)` from the route → `test_report_route_runs_the_review_first` fails. Restore.

- [ ] **Step 7: Commit**

```bash
git add src/curriculum_agent/graph.py src/curriculum_agent/stages/plo_report.py src/curriculum_agent/api/routes/plos.py tests/unit/test_plo_review_wiring.py
git commit -m "feat(plo_review): review the set before the report; routes to read and re-run it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.claude/skills/curriculum-design-agent/references/data-schemas.md` (only this file under `.claude/skills/`)

- [ ] **Step 1: CLAUDE.md**

1. Opening paragraph: "a 6-stage pipeline (intake → stakeholder needs → skill extraction → need combination → PLO synthesis → PLO report)" → add "→ PLO set review" before "PLO report" and say the review shares the report's checkpoint, in the same sentence that names the skill_extraction/need_combination exception.
2. Stack → LLM: "six slots" → "seven slots", add **plo_review** after validation in the list, and one short paragraph in the existing style: `PLO_REVIEW_PROVIDER`/`PLO_REVIEW_MODEL` (default OpenRouter `z-ai/glm-5.3-flash`, `complete_plo_review`) reads the finished set once, after synthesis — redundancy, KSEC (a set of K/S/E/C), Bloom — and stores advice per program; it writes nothing a designer submits; `disableable` like need_dedup and validation (`PLO_REVIEW_PROVIDER=` off). Update the sentence that names "need_dedup and validation are the only slots with `disableable=True`" to include plo_review.
3. Immutable rule 7: replace with the amended text from the spec ("Rule 7, amended").
4. Project layout `stages/` list: add `plo_review`.
5. One pitfall after the need_dedup pitfall: "**The set review advises; nothing reads it back.** `stages/plo_review.py` stores findings and the report shows them, and no code path turns a finding into a change — a KSEC suggestion is not a PLO KSEC field and a redundancy is not a merge. `current`, `agrees` and `declared` are computed in code, because the model can only claim them. A review is reused while the PLO set's fingerprint is unchanged and shown labelled stale once it moves; one that did not run produces no findings."

- [ ] **Step 2: data-schemas.md**

Add a short section "PLO set review" listing `PLOSetReview` and its three finding models with their fields (as in Task 3), the `plo_reviews` table (one row per program), and the rule that it is advisory.

- [ ] **Step 3: Verify and commit**

Run the full suite and `uv run python scripts/dump_prompts.py --check`.

```bash
git add CLAUDE.md .claude/skills/curriculum-design-agent/references/data-schemas.md
git commit -m "docs: the PLO set review, its slot, and rule 7's second shared checkpoint

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8 (controller, not a subagent): migrate and measure

- [ ] Run `uv run alembic upgrade head` on the live DB; confirm `plo_reviews` exists.
- [ ] Probe on `program-2` (tourism), 3 runs, by calling `plo_review._call` directly (no store): record per run the redundancy groups, the KSEC suggestions for the ethics/conduct PLOs, drop counts, latency.
- [ ] Criteria (spec, "Testing"): PLO1+PLO4 flagged redundant in ≥2/3 runs; E suggested for the ethics/conduct PLOs; no unknown-id drops in most runs; each call < 180 s.
- [ ] Add a "Measured" section to the spec with the numbers; commit the spec by explicit path.
- [ ] Repeat on `program` after its PLOs are re-synthesised (separate, when the user has run it).
