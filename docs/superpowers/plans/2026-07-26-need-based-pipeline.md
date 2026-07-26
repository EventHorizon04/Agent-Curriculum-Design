# Need-Based Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure stages 2–4 so raw skill extraction is separated from grouping, every skill carries exactly one KSEC tag, skills distill into 6–10 market-perspective Need statements, and each Need maps 1:1 to a PLO.

**Architecture:** `skill_extraction` shrinks to extraction + tagging + a pure-code groundedness check. A new `need_combination` stage clusters skills *within each KSEC bucket* (which structurally prevents mixed tags), merges to a 6–10 quota, and summarizes each group into one Need sentence. `plo_synthesis` then issues one focused LLM call per Need. A shared `stages/demand.py` holds the weighted scoring formula both stages need.

**Tech Stack:** Python 3.11+, Pydantic v2, LangGraph, Instructor + Ollama, SQLAlchemy 2.0 + Alembic, PostgreSQL, React 19 + Vite + TypeScript + Tailwind.

**Spec:** `docs/superpowers/specs/2026-07-26-need-based-pipeline-design.md` (commit `e7bc40b`)

## Global Constraints

- Type hints on every function signature; `from __future__ import annotations` at the top of every module.
- Pydantic v2 for anything crossing a boundary (LLM I/O, API, DB rows).
- `loguru` for logging. Never import the stdlib `logging` module.
- Async in API and stage handlers; sync only for pure CPU work.
- No hand-parsing LLM JSON — always Instructor → Pydantic.
- Thai for student-facing strings. Code, comments, variable names, log messages in English.
- Prompts live in `src/curriculum_agent/prompts/`, one file per prompt, returned by typed builder functions. Never inline a prompt in stage code.
- Data access through `src/curriculum_agent/data/repositories.py`. No SQL sprinkled elsewhere.
- DB schema changes only via Alembic. Never edit the DB by hand.
- Forbidden words in PLO statements: รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก.
- 6–10 main PLOs; optional (`is_optional=True`) PLOs are exempt from that count.
- Every PLO must have non-empty `source_need_ids` and `source_evidence_ids`.
- Verification gate for every task: `uv run pytest`, `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`, `uv run mypy src/` must all pass before committing. Frontend tasks additionally require `cd frontend && npx tsc --noEmit -p tsconfig.json && npm run lint`.

## Deviations from the spec, and why

1. **Three Alembic revisions, not one.** The spec describes the schema change as a single revision. Splitting it across the three tasks that own the corresponding model changes keeps the DB consistent with the code at the end of *every* task, so the test suite is runnable throughout. A single revision would force two tasks to end with a schema that does not match the models.
2. **`BLOOM_ORDER` is kept.** The spec says the deleted enums' `*_ORDER` lists go too. `BLOOM_ORDER` is not one of them — it is required to compute the "take the higher Bloom level" merge. Only `PSYCHOMOTOR_ORDER` and `KRATHWOHL_ORDER` are deleted.
3. **`api/routes/clusters.py` reuses `compute_demand_score`.** That route currently re-derives the freq/breadth/demand formula inline, a third copy. Folding it into the shared module in Task 1 is in scope because the shared module exists precisely to stop that duplication.

## File structure

**New files**

| Path | Responsibility |
|---|---|
| `src/curriculum_agent/stages/demand.py` | The weighted demand formula + `WEIGHTED_CLASSES`. Pure functions, no I/O. Imported by skill extraction, need combination, and the API route. |
| `src/curriculum_agent/stages/need_grouping.py` | Pure helpers for need combination: KSEC bucketing, Bloom max-merge, quota allocation. No LLM, no DB — trivially testable. |
| `src/curriculum_agent/stages/need_combination.py` | The stage: orchestrates bucketing → clustering → scoring → merge → summarize. |
| `src/curriculum_agent/prompts/summarize_need.py` | Prompt turning one skill group into one market-perspective Thai sentence. |
| `src/curriculum_agent/api/routes/needs.py` | Replaces `routes/clusters.py`. |
| `frontend/src/pages/components/SkillTable.tsx` | The 5-column raw-skill table with expandable rows. |
| `frontend/src/pages/components/NeedCard.tsx` | One Need card with expandable member/evidence trace. |

**Deleted files**

| Path | Reason |
|---|---|
| `src/curriculum_agent/prompts/name_cluster.py` | Replaced by `summarize_need.py` — a Need is a sentence, not a name + description. |
| `src/curriculum_agent/prompts/classify_cluster_bloom.py` | Bloom now comes from max-merging member skills in pure code; the three-scale prompt is obsolete. |
| `src/curriculum_agent/api/routes/clusters.py` | Becomes `routes/needs.py`. |
| `tests/unit/test_cluster_bloom.py` | Tests the deleted prompt. Replaced by `test_need_grouping.py`. |

**Substantially rewritten**

`stages/skill_extraction.py` (loses all clustering), `stages/plo_synthesis.py` (1:1), `stages/plo_report.py` (KSEC instead of `is_subject_specific`, no `domain`), `models.py`, `data/orm.py`, `data/repositories.py`, `frontend/src/pages/SkillExtraction.tsx`.

---

### Task 1: Shared demand-scoring module

Pure refactor — no behavior change. Establishes the module Tasks 2 and 5 both import.

**Files:**
- Create: `src/curriculum_agent/stages/demand.py`
- Modify: `src/curriculum_agent/stages/skill_extraction.py` (remove `_WEIGHTED_CLASSES` and `_compute_demand_score`, import instead)
- Modify: `src/curriculum_agent/api/routes/clusters.py:60-83` (use the shared function instead of re-deriving the formula)
- Test: `tests/unit/test_demand_score.py` (update import)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `WEIGHTED_CLASSES: set[str]` — `{"requirement", "need", "unclassified"}`
  - `compute_demand_score(source_evidence_ids: list[str], stakeholder_coverage: dict[str, int], total_req_need_evidence: int, classification_by_evidence: dict[str, str]) -> tuple[float, bool, dict[str, int]]` returning `(demand_score, is_optional, classification_coverage)`

- [ ] **Step 1: Write the failing test**

Replace the import line at the top of `tests/unit/test_demand_score.py`:

```python
from curriculum_agent.stages.demand import compute_demand_score
```

Then replace every `_compute_demand_score(` call in that file with `compute_demand_score(`. Append this new test, which pins the invariant the shared module exists to protect:

```python
def test_score_is_capped_at_one():
    cls = _classify(e1="requirement")
    score, _, _ = compute_demand_score(
        ["e1"], {t: 1 for t in ("employer", "alumni", "community")}, 1, cls
    )
    assert score <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_demand_score.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'curriculum_agent.stages.demand'`

- [ ] **Step 3: Create the shared module**

Create `src/curriculum_agent/stages/demand.py`:

```python
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
```

- [ ] **Step 4: Update `skill_extraction.py` to import it**

In `src/curriculum_agent/stages/skill_extraction.py`, delete the `_WEIGHTED_CLASSES` constant and the whole `_compute_demand_score` function, then add to the imports:

```python
from curriculum_agent.stages.demand import WEIGHTED_CLASSES, compute_demand_score
```

Replace the three internal usages: `_WEIGHTED_CLASSES` → `WEIGHTED_CLASSES`, and both `_compute_demand_score(` call sites (inside `_compute_skill_importance` and inside `run`) → `compute_demand_score(`.

- [ ] **Step 5: Remove the duplicated formula from the API route**

In `src/curriculum_agent/api/routes/clusters.py`, add the import:

```python
from curriculum_agent.stages.demand import BREADTH_WEIGHT, FREQ_WEIGHT
```

Replace the `demand_score=round(min(freq * 0.6 + breadth * 0.4, 1.0), 4),` line with:

```python
        demand_score=round(min(freq * FREQ_WEIGHT + breadth * BREADTH_WEIGHT, 1.0), 4),
```

Leave the rest of `DemandSignal` alone — it intentionally exposes the *components* for UI display, which `compute_demand_score` does not return.

- [ ] **Step 6: Run the full gate**

Run: `uv run pytest && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/`
Expected: all pass; test count unchanged except the one added test.

- [ ] **Step 7: Commit**

```bash
git add src/curriculum_agent/stages/demand.py src/curriculum_agent/stages/skill_extraction.py src/curriculum_agent/api/routes/clusters.py tests/unit/test_demand_score.py
git commit -m "refactor(demand): extract shared demand-scoring module

The weighted freq/breadth formula existed in three places. Skill
extraction and the upcoming need_combination stage both need it, so it
moves to stages/demand.py as a pure module owned by neither stage."
```

---

### Task 2: KSEC tag, PARENT stakeholder, and grounded skill extraction

Reshapes `ExtractedSkill` and rewrites the extraction half of the stage. `SkillCluster` and the `SkillType`/`PsychomotorLevel`/`KrathwohlLevel` enums stay alive here — they still back `SkillCluster`, which Task 5 removes.

**Files:**
- Modify: `src/curriculum_agent/models.py` (`KSECCategory`, `StakeholderType`, `ExtractedSkill`)
- Modify: `src/curriculum_agent/data/orm.py` (`SkillTable`)
- Create: `migrations/versions/<rev1>_ksec_split_and_evidence_span.py`
- Modify: `src/curriculum_agent/prompts/extract_skills.py`
- Modify: `src/curriculum_agent/stages/skill_extraction.py`
- Modify: `frontend/src/pages/SkillExtraction.tsx` (interface only — keep it compiling; the rebuild is Task 7)
- Test: `tests/unit/test_models.py`, `tests/unit/test_groundedness.py` (new)

**Interfaces:**
- Consumes: `compute_demand_score`, `WEIGHTED_CLASSES` from Task 1.
- Produces:
  - `KSECCategory` with members `K`, `GS`, `SS`, `C`, `E` (values `"K"`, `"GS"`, `"SS"`, `"C"`, `"E"`)
  - `StakeholderType.PARENT` (value `"parent"`)
  - `ExtractedSkill` with required `ksec_category: KSECCategory`, required `bloom_level: BloomLevel`, required `evidence_span_th: str`, and no `skill_type` / `is_subject_specific`
  - `normalize_for_match(text: str) -> str` and `is_grounded(span_th: str, evidence_text: str) -> bool` in `stages/skill_extraction.py`
  - `build_extract_skills_prompt(evidence_text: str, classification: str) -> list[dict[str, str]]` (unchanged signature, new instruction body)

- [ ] **Step 1: Write the failing model tests**

Append to `tests/unit/test_models.py`:

```python
def test_ksec_category_has_five_values_with_skill_split():
    assert {c.value for c in KSECCategory} == {"K", "GS", "SS", "C", "E"}


def test_ksec_category_rejects_mixed_and_bare_s():
    for bad in ("mixed", "S"):
        with pytest.raises(ValueError):
            KSECCategory(bad)


def test_parent_stakeholder_type_exists():
    assert StakeholderType.PARENT.value == "parent"


def _skill_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "skill_id": "S1",
        "program_id": "cs-test",
        "skill_name_th": "วิเคราะห์ข้อมูลขนาดใหญ่",
        "ksec_category": KSECCategory.SS,
        "bloom_level": BloomLevel.ANALYZE,
        "evidence_span_th": "ต้องวิเคราะห์ข้อมูลขนาดใหญ่ได้",
        "source_evidence_id": "E1",
        "extraction_method": "llm",
        "confidence": 0.9,
        "importance_score": 0.5,
    }
    base.update(overrides)
    return base


def test_extracted_skill_accepts_full_tag_set():
    skill = ExtractedSkill(**_skill_kwargs())
    assert skill.ksec_category is KSECCategory.SS
    assert skill.bloom_level is BloomLevel.ANALYZE


@pytest.mark.parametrize("missing", ["bloom_level", "ksec_category", "evidence_span_th"])
def test_extracted_skill_requires_tags_and_span(missing: str):
    kwargs = _skill_kwargs()
    del kwargs[missing]
    with pytest.raises(ValidationError):
        ExtractedSkill(**kwargs)


def test_extracted_skill_no_longer_has_mixed_capable_fields():
    skill = ExtractedSkill(**_skill_kwargs())
    assert not hasattr(skill, "skill_type")
    assert not hasattr(skill, "is_subject_specific")
```

Make sure the file's imports include `KSECCategory`, `ExtractedSkill`, `BloomLevel`, `StakeholderType`, `pytest`, and `ValidationError` from `pydantic`.

- [ ] **Step 2: Write the failing groundedness tests**

Create `tests/unit/test_groundedness.py`:

```python
from __future__ import annotations

from curriculum_agent.stages.skill_extraction import is_grounded, normalize_for_match

EVIDENCE = "ผู้สมัครต้อง   วิเคราะห์ข้อมูลขนาดใหญ่\nและนำเสนอผลได้"


def test_normalize_collapses_whitespace_and_trims():
    assert normalize_for_match("  a \n\t b  ") == "a b"


def test_exact_quote_is_grounded():
    assert is_grounded("และนำเสนอผลได้", EVIDENCE) is True


def test_quote_grounded_despite_differing_whitespace():
    # The model re-spaced the quote; the claim is still traceable.
    assert is_grounded("ผู้สมัครต้อง วิเคราะห์ข้อมูลขนาดใหญ่", EVIDENCE) is True


def test_invented_quote_is_not_grounded():
    assert is_grounded("ต้องมีประสบการณ์ 5 ปี", EVIDENCE) is False


def test_blank_span_is_not_grounded():
    assert is_grounded("   ", EVIDENCE) is False
```

- [ ] **Step 3: Run both test files to verify they fail**

Run: `uv run pytest tests/unit/test_models.py tests/unit/test_groundedness.py -v`
Expected: FAIL — `ImportError: cannot import name 'is_grounded'`, plus `KeyError`/`ValidationError` mismatches on the KSEC tests.

- [ ] **Step 4: Reshape the models**

In `src/curriculum_agent/models.py`, add `PARENT` to `StakeholderType`:

```python
class StakeholderType(StrEnum):
    EMPLOYER = "employer"
    ALUMNI = "alumni"
    PROFESSIONAL_COUNCIL = "professional_council"
    ACCREDITATION_BODY = "accreditation_body"
    UNIVERSITY = "university"
    COMMUNITY = "community"
    PARENT = "parent"
    SUBJECT_BENCHMARK = "subject_benchmark"
    PEER_PROGRAM = "peer_program"
```

Replace the whole `KSECCategory` class (added in commit `cec7adf`) with the five-value split:

```python
# TQF/มคอ. competency domains collapsed to five tags, used to pre-tag every
# ExtractedSkill for eventual มคอ.2/CHECO mapping. The skill domain is split by
# specificity so `is_subject_specific` is absorbed here rather than kept as a
# separate field that could disagree with the tag. This is NOT a Bloom domain —
# it is orthogonal to bloom_level, and a skill may be SS at Bloom `analyze`.
class KSECCategory(StrEnum):
    K = "K"    # ความรู้
    GS = "GS"  # ทักษะทั่วไป (generic/transferable)
    SS = "SS"  # ทักษะเฉพาะสาขา (subject-specific)
    C = "C"    # คุณลักษณะบุคคล
    E = "E"    # คุณธรรมจริยธรรม
```

Replace `ExtractedSkill` with:

```python
class ExtractedSkill(BaseModel):
    skill_id: str
    program_id: str
    # A phrase / skill word-group ("วิเคราะห์ข้อมูลขนาดใหญ่"), never a bare word.
    skill_name_th: str = Field(min_length=1)
    skill_name_en: str | None = None
    ksec_category: KSECCategory
    # Cognitive scale only. Psychomotor/affective scales are not modelled: the
    # agent stops at PLO and every PLO it produces is cognitive.
    bloom_level: BloomLevel
    # Verbatim quote from the source evidence that justifies this skill.
    # Verified against the evidence text in pure code — see is_grounded().
    evidence_span_th: str = Field(min_length=1)
    source_evidence_id: str
    extraction_method: Literal["llm", "manual"]
    confidence: float = Field(ge=0, le=1)
    # Per-skill-name demand, computed before grouping. Orders the raw-skill table.
    importance_score: float = Field(ge=0, le=1)
```

- [ ] **Step 5: Update the ORM and write the migration**

In `src/curriculum_agent/data/orm.py`, replace the `SkillTable` body below `skill_name_en` with:

```python
    ksec_category: Mapped[str] = mapped_column(String(2))
    bloom_level: Mapped[str] = mapped_column(String(20))
    evidence_span_th: Mapped[str] = mapped_column(Text)
    source_evidence_id: Mapped[str] = mapped_column(String, ForeignKey("evidence.evidence_id"))
    extraction_method: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float] = mapped_column(Float)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)
```

Generate a revision id, then create `migrations/versions/<rev1>_ksec_split_and_evidence_span.py`. Get `<rev1>` from `python -c "import uuid; print(uuid.uuid4().hex[:12])"` and set `down_revision` to the current head (`4f083b3c2d95`):

```python
"""ksec K/GS/SS/C/E split, evidence_span_th, required bloom_level

Revision ID: <rev1>
Revises: 4f083b3c2d95
Create Date: 2026-07-26 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '<rev1>'
down_revision: Union[str, None] = '4f083b3c2d95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Destructive by design: pre-existing skills have no evidence_span_th and
    # carry the old 4-value tag, so any program past Stage 2 must re-run skill
    # extraction. Recorded in the design spec; the project has no production data.
    op.execute("DELETE FROM skills")
    op.drop_column("skills", "skill_type")
    op.drop_column("skills", "is_subject_specific")
    op.add_column("skills", sa.Column("evidence_span_th", sa.Text(), nullable=False,
                                      server_default=""))
    op.alter_column("skills", "ksec_category", type_=sa.String(2), existing_type=sa.String(1),
                    nullable=False)
    op.alter_column("skills", "bloom_level", type_=sa.String(20), existing_type=sa.String(20),
                    nullable=False)


def downgrade() -> None:
    op.alter_column("skills", "bloom_level", type_=sa.String(20), existing_type=sa.String(20),
                    nullable=True)
    op.alter_column("skills", "ksec_category", type_=sa.String(1), existing_type=sa.String(2),
                    nullable=False)
    op.drop_column("skills", "evidence_span_th")
    op.add_column("skills", sa.Column("is_subject_specific", sa.Boolean(), nullable=False,
                                      server_default=sa.true()))
    op.add_column("skills", sa.Column("skill_type", sa.String(20), nullable=False,
                                      server_default="knowledge"))
```

- [ ] **Step 6: Rewrite the extraction prompt**

Replace the body of `build_extract_skills_prompt` in `src/curriculum_agent/prompts/extract_skills.py`:

```python
def build_extract_skills_prompt(evidence_text: str, classification: str) -> list[dict[str, str]]:
    system = (
        "คุณเป็นผู้เชี่ยวชาญวิเคราะห์ทักษะจากข้อความ\n"
        "จากข้อความ evidence จงระบุทักษะที่ตลาดแรงงานต้องการ\n\n"
        "กติกา:\n"
        "- แต่ละทักษะต้องเป็น 'วลี' หรือกลุ่มคำที่สื่อความสามารถ ห้ามเป็นคำโดดคำเดียว\n"
        "- ทักษะแต่ละรายการต้องไม่ซ้ำและไม่คาบเกี่ยวกัน (unique, independent) "
        "ห้ามเขียนสิ่งเดียวกันด้วยถ้อยคำต่างกัน\n"
        "- evidence_span_th ต้องคัดลอกข้อความ 'ตรงตัว' จาก evidence ที่ทำให้สรุปทักษะนี้ได้ "
        "ห้ามเรียบเรียงใหม่ ห้ามแต่งเพิ่ม ถ้าไม่มีข้อความรองรับ ห้ามเสนอทักษะนั้น\n"
        "- ทักษะที่ไม่เกี่ยวข้องกับสาขาวิชาของหลักสูตร ห้ามเสนอ\n\n"
        "ตอบเป็น JSON object: { skills: [ {\n"
        "  skill_name_th: วลีทักษะภาษาไทย,\n"
        "  skill_name_en: ชื่อภาษาอังกฤษมาตรฐาน (เช่น 'Data Analysis') ห้ามเว้นว่าง,\n"
        "  ksec_category: K|GS|SS|C|E — K=ความรู้, GS=ทักษะทั่วไป, "
        "SS=ทักษะเฉพาะสาขา, C=คุณลักษณะบุคคล, E=คุณธรรมจริยธรรม "
        "(เลือกได้เพียงค่าเดียว ห้ามตอบว่าผสมกัน),\n"
        "  bloom_level: remember|understand|apply|analyze|evaluate|create "
        "— ระดับ Bloom ด้าน Cognitive เท่านั้น,\n"
        "  evidence_span_th: ข้อความที่คัดลอกตรงตัวจาก evidence,\n"
        "  confidence: 0.0-1.0\n"
        "} ] }\n"
        "สกัดไม่เกิน 8 ทักษะต่อข้อความ เน้นทักษะที่วัดได้จริง"
    )
    user = f"[ประเภทหลักฐาน: {classification}]\n{evidence_text}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
```

- [ ] **Step 7: Add the groundedness helpers and rewire the stage**

In `src/curriculum_agent/stages/skill_extraction.py`, add `import re` and these module-level definitions above `_SkillItem`:

```python
_WS_RE = re.compile(r"\s+")


def normalize_for_match(text: str) -> str:
    """Collapse whitespace, trim, lowercase — for substring comparison only."""
    return _WS_RE.sub(" ", text).strip().lower()


def is_grounded(span_th: str, evidence_text: str) -> bool:
    """True when `span_th` really occurs in `evidence_text`.

    Verifies the model quoted rather than invented. Whitespace-insensitive so a
    re-spaced but genuine quote still passes; anything the evidence does not
    contain fails, and the skill is dropped by the caller.
    """
    span = normalize_for_match(span_th)
    if not span:
        return False
    return span in normalize_for_match(evidence_text)
```

Replace `_SkillItem` with:

```python
class _SkillItem(BaseModel):
    skill_name_th: str = Field(min_length=1)
    skill_name_en: str | None = None
    ksec_category: Literal["K", "GS", "SS", "C", "E"]
    bloom_level: Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]
    evidence_span_th: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)

    @field_validator("skill_name_th", "evidence_span_th", mode="before")
    @classmethod
    def _strip_text(cls, v: object) -> object:
        """Strip before min_length runs, so a whitespace-only value fails
        validation (Instructor reasks) instead of passing as a non-empty string."""
        return v.strip() if isinstance(v, str) else v
```

In `run`, inside the `if result is not None:` block, filter by groundedness before appending, and count drops:

```python
    dropped_ungrounded = 0
```

declared next to `raw_skills`, and the append block becomes:

```python
        if result is not None:
            for sk in result.skills:
                if not is_grounded(sk.evidence_span_th, evidence.raw_text_th):
                    dropped_ungrounded += 1
                    logger.debug(
                        f"  dropped ungrounded skill '{sk.skill_name_th}' "
                        f"from {evidence.evidence_id}"
                    )
                    continue
                raw_skills.append(
                    {
                        **sk.model_dump(mode="json"),
                        "evidence_id": evidence.evidence_id,
                        "stakeholder_type": evidence.stakeholder_type.value,
                    }
                )
```

After the extraction loop, log the rate:

```python
    if dropped_ungrounded:
        total_seen = len(raw_skills) + dropped_ungrounded
        logger.warning(
            f"Dropped {dropped_ungrounded}/{total_seen} skills failing the groundedness "
            "check (quoted text not found in evidence)"
        )
    state["dropped_ungrounded_count"] = dropped_ungrounded
```

Add `dropped_ungrounded_count: int` to `AgentState` in `src/curriculum_agent/graph.py` under the Stage 2 comment.

Update the `ExtractedSkill(...)` construction to the new field set (drop `skill_type` and `is_subject_specific`, make the tag fields non-optional):

```python
            ExtractedSkill(
                skill_id=skill_id,
                program_id=program_id,
                skill_name_th=s["skill_name_th"],
                skill_name_en=s.get("skill_name_en"),
                ksec_category=KSECCategory(s["ksec_category"]),
                bloom_level=BloomLevel(s["bloom_level"]),
                evidence_span_th=s["evidence_span_th"],
                source_evidence_id=s["evidence_id"],
                extraction_method="llm",
                confidence=s.get("confidence", 0.8),
                importance_score=importance_by_name.get(s["skill_name_th"], 0.0),
            )
```

Add `BloomLevel` to the `curriculum_agent.models` import list. The clustering half of `run` (Steps 3–5 in that file) is untouched in this task — `SkillCluster` still exists.

- [ ] **Step 8: Keep the frontend compiling**

In `frontend/src/pages/SkillExtraction.tsx`, update the `ExtractedSkill` interface only:

```ts
interface ExtractedSkill {
  skill_id: string
  skill_name_th: string
  skill_name_en: string | null
  ksec_category: string
  bloom_level: string
  evidence_span_th: string
  source_evidence_id: string
  extraction_method: string
  confidence: number
  importance_score: number
}
```

Delete the `skill_type` badge `<span>` from the skill row (the one using `SKILL_TYPE_COLOR[s.skill_type]`) since the field is gone. Keep `SKILL_TYPE_LABEL`/`SKILL_TYPE_COLOR` — the cluster row still uses them until Task 7. Update `KSEC_LABEL`/`KSEC_COLOR` to the five keys:

```ts
const KSEC_LABEL: Record<string, string> = {
  K: 'K · ความรู้',
  GS: 'GS · ทักษะทั่วไป',
  SS: 'SS · ทักษะเฉพาะสาขา',
  C: 'C · คุณลักษณะ',
  E: 'E · จริยธรรม',
}

const KSEC_COLOR: Record<string, string> = {
  K: 'bg-sky-100 text-sky-800',
  GS: 'bg-teal-100 text-teal-800',
  SS: 'bg-emerald-100 text-emerald-800',
  C: 'bg-amber-100 text-amber-800',
  E: 'bg-rose-100 text-rose-800',
}
```

- [ ] **Step 9: Fix the remaining test fallout**

`tests/unit/test_skill_extraction_cache.py` builds `_SkillItem`/`_ExtractedSkillsResponse` payloads. Add `ksec_category`, `bloom_level`, and an `evidence_span_th` that is a real substring of whatever evidence text the test feeds in, and remove `skill_type`/`is_subject_specific`. Read the file first — the fixture text must actually contain the span or the new filter drops the skill and the assertions break.

- [ ] **Step 10: Run the full gate**

Run: `uv run alembic upgrade head && uv run pytest && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/`
Then: `cd frontend && npx tsc --noEmit -p tsconfig.json && npm run lint`
Expected: all pass. `uv run alembic heads` must print exactly one head.

- [ ] **Step 11: Commit**

```bash
git add src/curriculum_agent/models.py src/curriculum_agent/data/orm.py src/curriculum_agent/prompts/extract_skills.py src/curriculum_agent/stages/skill_extraction.py src/curriculum_agent/graph.py migrations/versions/ tests/ frontend/src/pages/SkillExtraction.tsx
git commit -m "feat(skills): single KSEC tag, required Bloom, grounded extraction

ksec_category becomes K/GS/SS/C/E, absorbing skill_type (which carried an
unusable 'mixed' value) and is_subject_specific into one field that cannot
self-contradict. bloom_level is now required.

evidence_span_th makes the skill-to-evidence link verifiable: the model
must quote the evidence, and is_grounded() checks the quote really occurs
there. Ungrounded skills are dropped and counted rather than trusted.

Adds StakeholderType.PARENT for the want-classification rule."
```

---

### Task 3: Want classification bound to community and parent stakeholders

Independent of the Need work; touches only stage 1.

**Files:**
- Modify: `src/curriculum_agent/stages/stakeholder_needs.py`
- Modify: `src/curriculum_agent/prompts/classify_evidence.py`
- Test: `tests/unit/test_want_classification.py` (new)

**Interfaces:**
- Consumes: `StakeholderType.PARENT` from Task 2.
- Produces:
  - `WANT_ONLY_TYPES: frozenset[StakeholderType]` in `stages/stakeholder_needs.py`
  - `classify_single(evidence: StakeholderEvidence) -> StakeholderEvidence` — unchanged signature, now short-circuits for want-only stakeholder types without calling the LLM.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_want_classification.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import StakeholderEvidence, StakeholderType
from curriculum_agent.stages import stakeholder_needs as sn


def _evidence(stakeholder_type: StakeholderType) -> StakeholderEvidence:
    return StakeholderEvidence(
        evidence_id="E1",
        program_id="cs-test",
        stakeholder_type=stakeholder_type,
        source_name="ตัวอย่างแหล่งข้อมูล",
        raw_text_th="อยากให้บัณฑิตสื่อสารกับชุมชนได้ดี",
    )


@pytest.mark.parametrize("stype", [StakeholderType.COMMUNITY, StakeholderType.PARENT])
async def test_community_and_parent_are_want_without_llm(
    stype: StakeholderType, monkeypatch: pytest.MonkeyPatch
):
    llm = AsyncMock()
    monkeypatch.setattr(sn, "complete_light", llm)

    result = await sn.classify_single(_evidence(stype))

    assert result.classification == "want"
    llm.assert_not_awaited()  # pure code — no tokens spent


async def test_employer_takes_the_llm_path(monkeypatch: pytest.MonkeyPatch):
    llm = AsyncMock(
        return_value=sn._ClassifyResult(
            classification="requirement", classification_rationale_th="เป็นข้อกำหนดของวิชาชีพ"
        )
    )
    monkeypatch.setattr(sn, "complete_light", llm)

    result = await sn.classify_single(_evidence(StakeholderType.EMPLOYER))

    assert result.classification == "requirement"
    llm.assert_awaited_once()


def test_llm_result_model_cannot_return_want():
    # `want` is reserved for community/parent, decided in code. The LLM schema
    # must not offer it, or an employer posting could be demoted to a wish.
    with pytest.raises(ValueError):
        sn._ClassifyResult(classification="want", classification_rationale_th="x")


def test_want_only_types_is_exactly_community_and_parent():
    assert sn.WANT_ONLY_TYPES == frozenset(
        {StakeholderType.COMMUNITY, StakeholderType.PARENT}
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_want_classification.py -v`
Expected: FAIL — `AttributeError: module 'curriculum_agent.stages.stakeholder_needs' has no attribute 'WANT_ONLY_TYPES'`

- [ ] **Step 3: Implement the hard rule**

Rewrite the top half of `src/curriculum_agent/stages/stakeholder_needs.py`:

```python
class _ClassifyResult(BaseModel):
    # `want` is deliberately absent: it is reserved for WANT_ONLY_TYPES and
    # assigned in code, so the LLM cannot demote an employer requirement to a wish.
    classification: Literal["need", "requirement", "unclassified"]
    classification_rationale_th: str


# Community and parent input is aspirational by nature — a wish for the
# programme rather than a hiring requirement. The binding is a hard rule in both
# directions: these types are always `want`, and no other type can be `want`.
WANT_ONLY_TYPES = frozenset({StakeholderType.COMMUNITY, StakeholderType.PARENT})

_WANT_RATIONALE_TH = "ผู้มีส่วนได้ส่วนเสียกลุ่มชุมชน/ผู้ปกครอง จัดเป็น want ตามนโยบายหลักสูตร"


async def classify_single(evidence: StakeholderEvidence) -> StakeholderEvidence:
    """Classify one evidence item. Used by both the stage and the SSE endpoint.

    Community and parent evidence is classified in pure code — deterministic and
    free. Everything else goes to the LLM, which chooses requirement vs need.
    """
    if evidence.stakeholder_type in WANT_ONLY_TYPES:
        return evidence.model_copy(
            update={
                "classification": "want",
                "classification_rationale_th": _WANT_RATIONALE_TH,
            }
        )

    messages = build_classify_evidence_prompt(evidence)
    result = await complete_light(_ClassifyResult, messages)
    return evidence.model_copy(
        update={
            "classification": result.classification,
            "classification_rationale_th": result.classification_rationale_th,
        }
    )
```

Add `StakeholderType` to the `curriculum_agent.models` import.

- [ ] **Step 4: Drop `want` from the prompt**

In `src/curriculum_agent/prompts/classify_evidence.py`, replace the classification list and the response contract:

```python
        "จงจัดประเภทข้อมูลความต้องการจากผู้มีส่วนได้ส่วนเสียออกเป็น 1 ประเภท:\n"
        "- requirement: ข้อกำหนด/มาตรฐานที่ต้องปฏิบัติตาม (compliance) บังคับต้องมี\n"
        "- need: ความต้องการของตลาดที่ทำให้หลักสูตรทันสมัยและตรงงานจริง\n"
        "- unclassified: ข้อมูลที่ไม่ชัดเจนพอที่จะจัดประเภท\n\n"
        "ตอบเป็น JSON object ที่มี field:\n"
        "  classification: string (requirement|need|unclassified)\n"
        "  classification_rationale_th: string (เหตุผลสั้น ๆ ภาษาไทย ไม่เกิน 2 ประโยค)"
```

- [ ] **Step 5: Run the full gate**

Run: `uv run pytest && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/`
Expected: all pass. If a test elsewhere asserted an employer item could be classified `want`, update it — that is now impossible by design.

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/stages/stakeholder_needs.py src/curriculum_agent/prompts/classify_evidence.py tests/unit/test_want_classification.py
git commit -m "feat(stakeholder-needs): bind want classification to community and parent

Community and parent evidence is classified want in pure code with no LLM
call; every other stakeholder type goes to the LLM, whose schema no longer
offers want. The binding is a hard rule both ways, so demand scoring can
trust that a want really is an aspiration."
```

---

### Task 4: Pure grouping helpers for need combination

No LLM, no DB, no wiring — just the arithmetic and bookkeeping the next task orchestrates. Isolating it means the tricky quota logic is tested without mocking anything.

**Files:**
- Create: `src/curriculum_agent/stages/need_grouping.py`
- Test: `tests/unit/test_need_grouping.py` (new)

**Interfaces:**
- Consumes: `KSECCategory`, `BloomLevel`, `ExtractedSkill`, `BLOOM_ORDER` from `models.py`.
- Produces:
  - `bucket_by_ksec(skills: list[ExtractedSkill]) -> dict[KSECCategory, list[ExtractedSkill]]`
  - `merge_bloom(levels: Iterable[BloomLevel]) -> BloomLevel`
  - `dedupe_with_bloom_max(skills: list[ExtractedSkill]) -> tuple[list[str], list[list[int]], dict[str, BloomLevel]]` returning `(display_names, index_groups, bloom_by_display_name)`
  - `allocate_quota(group_counts: dict[KSECCategory, int], bucket_demand: dict[KSECCategory, float], cap: int = 10) -> dict[KSECCategory, int]`
  - `MAX_NEEDS: int = 10`, `MIN_NEEDS: int = 6`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_need_grouping.py`:

```python
from __future__ import annotations

import pytest

from curriculum_agent.models import BloomLevel, ExtractedSkill, KSECCategory
from curriculum_agent.stages.need_grouping import (
    MAX_NEEDS,
    allocate_quota,
    bucket_by_ksec,
    dedupe_with_bloom_max,
    merge_bloom,
)


def _skill(
    name: str,
    ksec: KSECCategory = KSECCategory.SS,
    bloom: BloomLevel = BloomLevel.APPLY,
    skill_id: str = "S1",
) -> ExtractedSkill:
    return ExtractedSkill(
        skill_id=skill_id,
        program_id="cs-test",
        skill_name_th=name,
        ksec_category=ksec,
        bloom_level=bloom,
        evidence_span_th=name,
        source_evidence_id="E1",
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.5,
    )


def test_bucket_by_ksec_never_mixes_tags():
    skills = [
        _skill("เขียนโปรแกรม", KSECCategory.SS, skill_id="S1"),
        _skill("ทำงานเป็นทีม", KSECCategory.GS, skill_id="S2"),
        _skill("จรรยาบรรณวิชาชีพ", KSECCategory.E, skill_id="S3"),
        _skill("โครงสร้างข้อมูล", KSECCategory.K, skill_id="S4"),
    ]
    buckets = bucket_by_ksec(skills)
    for ksec, members in buckets.items():
        assert {m.ksec_category for m in members} == {ksec}
    assert sum(len(v) for v in buckets.values()) == len(skills)


def test_bucket_by_ksec_omits_empty_buckets():
    buckets = bucket_by_ksec([_skill("เขียนโปรแกรม", KSECCategory.SS)])
    assert set(buckets) == {KSECCategory.SS}


def test_merge_bloom_takes_the_higher_level():
    # The user's example: Recognition < Analysis.
    assert merge_bloom([BloomLevel.REMEMBER, BloomLevel.ANALYZE]) is BloomLevel.ANALYZE
    assert merge_bloom([BloomLevel.CREATE, BloomLevel.APPLY]) is BloomLevel.CREATE


def test_merge_bloom_single_level_is_itself():
    assert merge_bloom([BloomLevel.EVALUATE]) is BloomLevel.EVALUATE


def test_merge_bloom_rejects_empty():
    with pytest.raises(ValueError):
        merge_bloom([])


def test_dedupe_collapses_same_name_and_keeps_max_bloom():
    skills = [
        _skill("วิเคราะห์ข้อมูล", bloom=BloomLevel.REMEMBER, skill_id="S1"),
        _skill("  วิเคราะห์ข้อมูล  ", bloom=BloomLevel.ANALYZE, skill_id="S2"),
        _skill("เขียนรายงาน", bloom=BloomLevel.APPLY, skill_id="S3"),
    ]
    names, groups, bloom_by_name = dedupe_with_bloom_max(skills)

    assert len(names) == 2
    analysed = next(n for n in names if "วิเคราะห์" in n)
    assert bloom_by_name[analysed] is BloomLevel.ANALYZE
    assert sorted(len(g) for g in groups) == [1, 2]


def test_quota_passthrough_when_already_within_cap():
    counts = {KSECCategory.SS: 4, KSECCategory.GS: 3}
    quota = allocate_quota(counts, {KSECCategory.SS: 0.8, KSECCategory.GS: 0.4})
    assert quota == counts


def test_quota_caps_total_at_max_needs():
    counts = {KSECCategory.SS: 12, KSECCategory.GS: 6, KSECCategory.K: 4}
    demand = {KSECCategory.SS: 0.9, KSECCategory.GS: 0.5, KSECCategory.K: 0.2}
    quota = allocate_quota(counts, demand)
    assert sum(quota.values()) == MAX_NEEDS


def test_quota_keeps_every_non_empty_bucket_alive():
    # One dominant bucket must not squeeze the others out — the generic/specific
    # balance the programme needs depends on every bucket surviving.
    counts = {
        KSECCategory.SS: 30,
        KSECCategory.GS: 1,
        KSECCategory.K: 1,
        KSECCategory.C: 1,
        KSECCategory.E: 1,
    }
    demand = {
        KSECCategory.SS: 0.95,
        KSECCategory.GS: 0.1,
        KSECCategory.K: 0.1,
        KSECCategory.C: 0.05,
        KSECCategory.E: 0.05,
    }
    quota = allocate_quota(counts, demand)
    assert sum(quota.values()) == MAX_NEEDS
    assert all(v >= 1 for v in quota.values())


def test_quota_never_exceeds_available_groups_in_a_bucket():
    counts = {KSECCategory.SS: 11, KSECCategory.GS: 2}
    demand = {KSECCategory.SS: 0.2, KSECCategory.GS: 0.9}
    quota = allocate_quota(counts, demand)
    assert quota[KSECCategory.GS] <= 2
    assert sum(quota.values()) == MAX_NEEDS


def test_quota_ignores_empty_buckets():
    counts = {KSECCategory.SS: 12, KSECCategory.GS: 0}
    quota = allocate_quota(counts, {KSECCategory.SS: 0.9, KSECCategory.GS: 0.0})
    assert KSECCategory.GS not in quota
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_need_grouping.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'curriculum_agent.stages.need_grouping'`

- [ ] **Step 3: Implement the helpers**

Create `src/curriculum_agent/stages/need_grouping.py`:

```python
from __future__ import annotations

import re
from collections.abc import Iterable

from loguru import logger

from curriculum_agent.models import BLOOM_ORDER, BloomLevel, ExtractedSkill, KSECCategory

# Project policy: 6-10 main Needs, which become 6-10 main PLOs one-to-one.
MIN_NEEDS = 6
MAX_NEEDS = 10

_WS_RE = re.compile(r"\s+")
_BLOOM_RANK = {level: i for i, level in enumerate(BLOOM_ORDER)}


def _normalize(name: str) -> str:
    return _WS_RE.sub(" ", name.strip()).lower()


def bucket_by_ksec(skills: list[ExtractedSkill]) -> dict[KSECCategory, list[ExtractedSkill]]:
    """Split skills into one bucket per KSEC tag, omitting empty buckets.

    Clustering runs inside a bucket and merging never crosses buckets, so a Need
    can never contain two different tags. This is what makes "tags must not mix"
    a structural guarantee instead of a rule someone has to remember.
    """
    buckets: dict[KSECCategory, list[ExtractedSkill]] = {}
    for skill in skills:
        buckets.setdefault(skill.ksec_category, []).append(skill)
    return buckets


def merge_bloom(levels: Iterable[BloomLevel]) -> BloomLevel:
    """Return the highest Bloom level present.

    The same capability described by two sources at different cognitive demands
    (remember vs analyze) is taught to the higher one — the lower is implied by it.
    """
    ordered = list(levels)
    if not ordered:
        raise ValueError("merge_bloom requires at least one Bloom level")
    return max(ordered, key=lambda lv: _BLOOM_RANK[lv])


def dedupe_with_bloom_max(
    skills: list[ExtractedSkill],
) -> tuple[list[str], list[list[int]], dict[str, BloomLevel]]:
    """Collapse duplicate skill names within one bucket.

    Returns (display_names, index_groups, bloom_by_display_name). `display_names`
    is sorted by normalized form so prompts and cache keys are deterministic
    regardless of input order; `index_groups[i]` lists the positions in `skills`
    that collapsed into `display_names[i]`.
    """
    by_norm: dict[str, list[int]] = {}
    display: dict[str, str] = {}
    for i, skill in enumerate(skills):
        norm = _normalize(skill.skill_name_th)
        if not norm:
            continue
        by_norm.setdefault(norm, []).append(i)
        display.setdefault(norm, skill.skill_name_th.strip())

    ordered = sorted(by_norm)
    names = [display[k] for k in ordered]
    groups = [by_norm[k] for k in ordered]
    blooms = {
        display[k]: merge_bloom([skills[i].bloom_level for i in by_norm[k]]) for k in ordered
    }
    return names, groups, blooms


def allocate_quota(
    group_counts: dict[KSECCategory, int],
    bucket_demand: dict[KSECCategory, float],
    cap: int = MAX_NEEDS,
) -> dict[KSECCategory, int]:
    """Decide how many Needs each KSEC bucket may keep, totalling at most `cap`.

    Shares are allocated by group count rather than demand so a bucket holding
    many distinct capabilities is not squeezed out by one bucket holding a single
    very high-demand capability; demand only breaks ties. Every non-empty bucket
    keeps at least one Need. That is always satisfiable here: there are at most
    five buckets and `cap` is 10.
    """
    active = {b: n for b, n in group_counts.items() if n > 0}
    if not active:
        return {}
    total = sum(active.values())
    if total <= cap:
        return dict(active)

    if len(active) > cap:  # unreachable with 5 buckets and cap 10; guard anyway
        raise ValueError(f"cannot keep {len(active)} buckets within cap {cap}")

    target = {b: max(1, (cap * n) // total) for b, n in active.items()}

    while sum(target.values()) > cap:
        shrinkable = [b for b in target if target[b] > 1]
        victim = min(shrinkable, key=lambda b: bucket_demand.get(b, 0.0))
        target[victim] -= 1

    while sum(target.values()) < cap:
        growable = [b for b in target if target[b] < active[b]]
        if not growable:
            break
        winner = max(growable, key=lambda b: bucket_demand.get(b, 0.0))
        target[winner] += 1

    logger.debug(f"Need quota: {total} groups → {target} (cap {cap})")
    return target
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_need_grouping.py -v`
Expected: PASS — 12 tests.

- [ ] **Step 5: Run the full gate**

Run: `uv run pytest && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/stages/need_grouping.py tests/unit/test_need_grouping.py
git commit -m "feat(needs): pure grouping helpers for need combination

KSEC bucketing, Bloom max-merge, and quota allocation as pure functions.
Bucketing is what structurally prevents a Need from holding two different
competency tags; the quota keeps every non-empty bucket alive so one
dominant bucket cannot destroy the generic/specific balance."
```

---

### Task 5: Need model and the need_combination stage

The atomic rename. `SkillCluster` cannot be half-replaced, so the model, ORM, repository, both stages, the graph, and the dependent call sites move together.

**Files:**
- Modify: `src/curriculum_agent/models.py` (add `Need`, delete `SkillCluster`, `SkillType`, `PsychomotorLevel`, `KrathwohlLevel`, `PSYCHOMOTOR_ORDER`, `KRATHWOHL_ORDER`)
- Modify: `src/curriculum_agent/data/orm.py` (`ClusterTable` → `NeedTable`)
- Create: `migrations/versions/<rev2>_clusters_to_needs.py`
- Modify: `src/curriculum_agent/data/repositories.py` (`ClusterRepository` → `NeedRepository`)
- Modify: `src/curriculum_agent/prompts/cluster_skills.py` (add `build_merge_to_target_prompt`)
- Create: `src/curriculum_agent/prompts/summarize_need.py`
- Create: `src/curriculum_agent/stages/need_combination.py`
- Modify: `src/curriculum_agent/stages/skill_extraction.py` (delete clustering; the file ends after persisting skills)
- Modify: `src/curriculum_agent/graph.py` (new node + state key)
- Delete: `src/curriculum_agent/prompts/name_cluster.py`, `src/curriculum_agent/prompts/classify_cluster_bloom.py`, `tests/unit/test_cluster_bloom.py`
- Modify: `src/curriculum_agent/stages/plo_synthesis.py`, `src/curriculum_agent/stages/plo_report.py` (compile against `Need`; the 1:1 rewrite is Task 6)
- Modify: `tests/conftest.py`, `tests/unit/test_models.py`, `tests/integration/test_end_to_end.py`
- Test: `tests/unit/test_need_combination.py` (new)

**Interfaces:**
- Consumes: `bucket_by_ksec`, `dedupe_with_bloom_max`, `merge_bloom`, `allocate_quota`, `MIN_NEEDS`, `MAX_NEEDS` (Task 4); `compute_demand_score`, `WEIGHTED_CLASSES` (Task 1); `cluster_skill_names`, `validate_assignments` (existing `stages/llm_clustering.py`).
- Produces:
  - `Need` model with `need_id`, `program_id`, `statement_th`, `statement_en`, `ksec_category`, `bloom_level`, `member_skill_ids`, `source_evidence_ids`, `stakeholder_coverage`, `freq`, `demand_score`, `is_optional`, `classification_coverage`, `sample_quotes_th`
  - `NeedRepository` with `bulk_insert(needs: list[Need]) -> None` and `list_by_program(program_id: str) -> list[Need]`
  - `build_summarize_need_prompt(skill_names: list[str], sample_evidence: list[str], ksec: str) -> list[dict[str, str]]`
  - `build_merge_to_target_prompt(cluster_labels: list[str], target_count: int) -> list[dict[str, str]]`
  - `run(state: AgentState) -> AgentState` in `stages/need_combination.py`, writing `state["needs"]`
  - `AgentState` gains `needs: list[dict[str, Any]]` and loses `skill_clusters`

- [ ] **Step 1: Write the failing model test**

Append to `tests/unit/test_models.py`:

```python
def _need_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "need_id": "N1",
        "program_id": "cs-test",
        "statement_th": "สามารถวิเคราะห์ข้อมูลขนาดใหญ่เพื่อหา insight ทางธุรกิจ",
        "ksec_category": KSECCategory.SS,
        "bloom_level": BloomLevel.ANALYZE,
        "member_skill_ids": ["S1", "S2"],
        "source_evidence_ids": ["E1"],
        "freq": 2,
        "demand_score": 0.8,
    }
    base.update(overrides)
    return base


def test_need_accepts_valid_payload():
    need = Need(**_need_kwargs())
    assert need.freq == 2
    assert need.is_optional is False


@pytest.mark.parametrize("empty_field", ["member_skill_ids", "source_evidence_ids"])
def test_need_requires_evidence_trail(empty_field: str):
    with pytest.raises(ValidationError):
        Need(**_need_kwargs(**{empty_field: []}))


def test_skill_cluster_and_mixed_enums_are_gone():
    import curriculum_agent.models as m

    for removed in ("SkillCluster", "SkillType", "PsychomotorLevel", "KrathwohlLevel"):
        assert not hasattr(m, removed), f"{removed} should have been deleted"
```

Add `Need` to the imports in that file.

- [ ] **Step 2: Write the failing stage test**

Create `tests/unit/test_need_combination.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import BloomLevel, ExtractedSkill, KSECCategory
from curriculum_agent.stages import need_combination as nc


def _skill(name: str, ksec: KSECCategory, sid: str, eid: str) -> ExtractedSkill:
    return ExtractedSkill(
        skill_id=sid,
        program_id="cs-test",
        skill_name_th=name,
        ksec_category=ksec,
        bloom_level=BloomLevel.APPLY,
        evidence_span_th=name,
        source_evidence_id=eid,
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.5,
    )


@pytest.fixture
def skills() -> list[ExtractedSkill]:
    return [
        _skill("เขียนโปรแกรมเว็บ", KSECCategory.SS, "S1", "E1"),
        _skill("ออกแบบฐานข้อมูล", KSECCategory.SS, "S2", "E1"),
        _skill("ทำงานเป็นทีม", KSECCategory.GS, "S3", "E2"),
        _skill("ยึดถือจรรยาบรรณ", KSECCategory.E, "S4", "E3"),
    ]


@pytest.fixture
def evidence() -> list[dict[str, str]]:
    return [
        {"evidence_id": "E1", "classification": "requirement", "stakeholder_type": "employer"},
        {"evidence_id": "E2", "classification": "need", "stakeholder_type": "alumni"},
        {"evidence_id": "E3", "classification": "want", "stakeholder_type": "community"},
    ]


def _patch_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cluster each bucket into singletons; summarize echoes the first skill name."""

    async def fake_cluster(names: list[str]) -> list[list[int]]:
        return [[i] for i in range(len(names))]

    async def fake_summarize(model, messages, **kw):  # noqa: ANN001, ANN003
        return nc._NeedStatement(
            statement_th="สามารถทำงานตามที่ตลาดต้องการ", statement_en="Market capability"
        )

    monkeypatch.setattr(nc, "cluster_skill_names", fake_cluster)
    monkeypatch.setattr(nc, "complete_light", fake_summarize)


async def test_every_need_holds_exactly_one_ksec_tag(
    skills: list[ExtractedSkill], evidence: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
):
    _patch_llm(monkeypatch)
    monkeypatch.setattr(nc.NeedRepository, "bulk_insert", AsyncMock())

    state = await nc.run(
        {
            "program_id": "cs-test",
            "classified_evidence": evidence,
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


async def test_want_only_need_is_marked_optional(
    skills: list[ExtractedSkill], evidence: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
):
    _patch_llm(monkeypatch)
    monkeypatch.setattr(nc.NeedRepository, "bulk_insert", AsyncMock())

    state = await nc.run(
        {
            "program_id": "cs-test",
            "classified_evidence": evidence,
            "extracted_skills": [s.model_dump(mode="json") for s in skills],
        }
    )

    ethics = [n for n in state["needs"] if n["ksec_category"] == "E"]
    assert ethics and all(n["is_optional"] for n in ethics)


async def test_freq_counts_mentions_not_unique_names(
    evidence: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
):
    # Same capability named twice in one bucket, clustered together.
    dupes = [
        _skill("วิเคราะห์ข้อมูล", KSECCategory.SS, "S1", "E1"),
        _skill("วิเคราะห์ข้อมูล", KSECCategory.SS, "S2", "E2"),
    ]

    async def one_cluster(names: list[str]) -> list[list[int]]:
        return [list(range(len(names)))]

    async def fake_summarize(model, messages, **kw):  # noqa: ANN001, ANN003
        return nc._NeedStatement(statement_th="วิเคราะห์ข้อมูลได้", statement_en="Analyse data")

    monkeypatch.setattr(nc, "cluster_skill_names", one_cluster)
    monkeypatch.setattr(nc, "complete_light", fake_summarize)
    monkeypatch.setattr(nc.NeedRepository, "bulk_insert", AsyncMock())

    state = await nc.run(
        {
            "program_id": "cs-test",
            "classified_evidence": evidence,
            "extracted_skills": [s.model_dump(mode="json") for s in dupes],
        }
    )

    assert len(state["needs"]) == 1
    assert state["needs"][0]["freq"] == 2  # two mentions, one name


async def test_empty_skills_yields_no_needs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(nc.NeedRepository, "bulk_insert", AsyncMock())
    state = await nc.run(
        {"program_id": "cs-test", "classified_evidence": [], "extracted_skills": []}
    )
    assert state["needs"] == []


def _group(name: str, demand: float, eid: str) -> nc._Group:
    return nc._Group(
        ksec=KSECCategory.SS,
        skill_ids=[f"S-{name}"],
        evidence_ids=[eid],
        skill_names=[name],
        bloom_level=BloomLevel.APPLY,
        demand_score=demand,
        is_optional=False,
        classification_coverage={"need": 1},
        stakeholder_coverage={"employer": 1},
    )


def test_fuse_unions_evidence_and_takes_max_bloom():
    a = _group("a", 0.4, "E1")
    b = _group("b", 0.9, "E2").model_copy(update={"bloom_level": BloomLevel.CREATE})
    fused = nc._fuse([a, b])
    assert set(fused.evidence_ids) == {"E1", "E2"}
    assert fused.bloom_level is BloomLevel.CREATE
    assert fused.demand_score == 0.9
    assert sorted(fused.skill_ids) == ["S-a", "S-b"]


def test_fuse_by_demand_hits_the_limit_and_keeps_all_evidence():
    bucket = [_group(f"g{i}", i / 10, f"E{i}") for i in range(7)]
    fused = nc._fuse_by_demand(bucket, 3)
    assert len(fused) == 3
    all_evidence = {e for g in fused for e in g.evidence_ids}
    assert all_evidence == {f"E{i}" for i in range(7)}


async def test_merge_bucket_falls_back_when_llm_returns_wrong_count(
    monkeypatch: pytest.MonkeyPatch,
):
    bucket = [_group(f"g{i}", i / 10, f"E{i}") for i in range(5)]

    async def bad_merge(model, messages, **kw):  # noqa: ANN001, ANN003
        return nc.MergeGroupsResponse(groups=[[0, 1, 2, 3, 4]])  # 1 group, asked for 2

    monkeypatch.setattr(nc, "complete_heavy", bad_merge)
    merged = await nc._merge_bucket(bucket, 2, KSECCategory.SS)
    assert len(merged) == 2


async def test_merge_bucket_falls_back_when_llm_raises(monkeypatch: pytest.MonkeyPatch):
    bucket = [_group(f"g{i}", i / 10, f"E{i}") for i in range(4)]

    async def boom(model, messages, **kw):  # noqa: ANN001, ANN003
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(nc, "complete_heavy", boom)
    merged = await nc._merge_bucket(bucket, 2, KSECCategory.SS)
    assert len(merged) == 2


async def test_merge_bucket_uses_llm_grouping_when_count_matches(
    monkeypatch: pytest.MonkeyPatch,
):
    bucket = [_group(f"g{i}", 0.5, f"E{i}") for i in range(4)]

    async def good_merge(model, messages, **kw):  # noqa: ANN001, ANN003
        return nc.MergeGroupsResponse(groups=[[0, 1], [2, 3]])

    monkeypatch.setattr(nc, "complete_heavy", good_merge)
    merged = await nc._merge_bucket(bucket, 2, KSECCategory.SS)
    assert len(merged) == 2
    assert all(len(g.skill_names) == 2 for g in merged)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_need_combination.py tests/unit/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'curriculum_agent.stages.need_combination'`

- [ ] **Step 4: Add `Need`, delete `SkillCluster` and the unused enums**

In `src/curriculum_agent/models.py`, delete the `SkillType`, `PsychomotorLevel`, and `KrathwohlLevel` classes, the `PSYCHOMOTOR_ORDER` and `KRATHWOHL_ORDER` lists, and the whole `SkillCluster` class. Keep `BLOOM_ORDER` — `merge_bloom` depends on it. Keep `Domain` for now; Task 6 removes it with the PLO reshape.

Add in place of `SkillCluster`:

```python
class Need(BaseModel):
    """A market-side demand distilled from a group of extracted skills.

    One sentence stating what the labour market asks for. PLO synthesis restates
    it from the graduate's side; keeping both makes "which demand does this PLO
    answer?" answerable from the data rather than inferred.
    """

    need_id: str
    program_id: str
    statement_th: str = Field(min_length=1)
    statement_en: str | None = None
    # Single-valued by construction: grouping runs inside one KSEC bucket.
    ksec_category: KSECCategory
    # Highest Bloom level among member skills.
    bloom_level: BloomLevel
    member_skill_ids: list[str] = Field(min_length=1)
    source_evidence_ids: list[str] = Field(min_length=1)
    stakeholder_coverage: dict[StakeholderType, int] = Field(default_factory=dict)
    # Raw mention count: len(member_skill_ids). Explainable to a designer in a
    # way the weighted score is not.
    freq: int = Field(ge=1)
    demand_score: float = Field(ge=0, le=1)
    is_optional: bool = False
    classification_coverage: dict[str, int] = Field(default_factory=dict)
    sample_quotes_th: list[str] = Field(default_factory=list, max_length=5)
```

- [ ] **Step 5: Rename the table, repository, and write the migration**

In `src/curriculum_agent/data/orm.py`, replace `ClusterTable` with:

```python
class NeedTable(Base):
    __tablename__ = "needs"

    need_id: Mapped[str] = mapped_column(String, primary_key=True)
    program_id: Mapped[str] = mapped_column(String, ForeignKey("programs.program_id"))
    statement_th: Mapped[str] = mapped_column(Text)
    statement_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    ksec_category: Mapped[str] = mapped_column(String(2))
    bloom_level: Mapped[str] = mapped_column(String(20))
    member_skill_ids: Mapped[list[str]] = mapped_column(JSONB)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSONB)
    stakeholder_coverage: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    freq: Mapped[int] = mapped_column(Integer)
    demand_score: Mapped[float] = mapped_column(Float)
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False)
    classification_coverage: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    sample_quotes_th: Mapped[list[str]] = mapped_column(JSONB, default=list)
```

In `src/curriculum_agent/data/repositories.py`, rename `ClusterRepository` to `NeedRepository` and retype it — same body shape as before, with `NeedTable`/`Need`/`need_id`:

```python
class NeedRepository:
    async def bulk_insert(self, needs: list[Need]) -> None:
        async with AsyncSessionLocal() as session:
            for need in needs:
                data = need.model_dump(mode="json")
                existing = await session.get(NeedTable, need.need_id)
                if existing is None:
                    session.add(NeedTable(**data))
                else:
                    for k, v in data.items():
                        setattr(existing, k, v)
            await session.commit()

    async def list_by_program(self, program_id: str) -> list[Need]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(NeedTable).where(NeedTable.program_id == program_id)
            )
            return [Need.model_validate(_row_to_dict(row)) for row in result.scalars().all()]
```

Update that file's imports (`SkillCluster` → `Need`, `ClusterTable` → `NeedTable`). Check `ProgramRepository.delete_cascade` — it references the clusters table and must be updated to `needs`; read it before editing.

Create `migrations/versions/<rev2>_clusters_to_needs.py` with `down_revision` set to `<rev1>` from Task 2:

```python
"""clusters table becomes needs

Revision ID: <rev2>
Revises: <rev1>
Create Date: 2026-07-26 00:00:01.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '<rev2>'
down_revision: Union[str, None] = '<rev1>'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Cluster rows cannot become Need rows: a Need needs a statement sentence and
    # a single KSEC tag that no cluster row carries. Programmes past Stage 2
    # re-run skill extraction, as recorded in the design spec.
    op.execute("DELETE FROM clusters")
    op.rename_table("clusters", "needs")
    op.alter_column("needs", "cluster_id", new_column_name="need_id")
    for col in (
        "canonical_name_th",
        "canonical_name_en",
        "description_th",
        "skill_type",
        "is_subject_specific",
        "psychomotor_level",
        "krathwohl_level",
        "is_common_need",
    ):
        op.drop_column("needs", col)
    # `clusters` never had a ksec_category column — it is added here, not altered.
    op.add_column("needs", sa.Column("ksec_category", sa.String(2), nullable=False,
                                     server_default="SS"))
    op.add_column("needs", sa.Column("statement_th", sa.Text(), nullable=False,
                                     server_default=""))
    op.add_column("needs", sa.Column("statement_en", sa.Text(), nullable=True))
    op.add_column("needs", sa.Column("freq", sa.Integer(), nullable=False, server_default="1"))
    # bloom_level existed and was nullable (cognitive clusters only); Needs always
    # carry one because every skill is Bloom-tagged.
    op.alter_column("needs", "bloom_level", existing_type=sa.String(20), nullable=False,
                    server_default="apply")


def downgrade() -> None:
    op.execute("DELETE FROM needs")
    op.alter_column("needs", "bloom_level", existing_type=sa.String(20), nullable=True,
                    server_default=None)
    op.drop_column("needs", "freq")
    op.drop_column("needs", "statement_en")
    op.drop_column("needs", "statement_th")
    op.drop_column("needs", "ksec_category")
    op.add_column("needs", sa.Column("is_common_need", sa.Boolean(), nullable=False,
                                     server_default=sa.false()))
    op.add_column("needs", sa.Column("krathwohl_level", sa.String(20), nullable=True))
    op.add_column("needs", sa.Column("psychomotor_level", sa.String(20), nullable=True))
    op.add_column("needs", sa.Column("is_subject_specific", sa.Boolean(), nullable=False,
                                     server_default=sa.true()))
    op.add_column("needs", sa.Column("skill_type", sa.String(20), nullable=False,
                                     server_default="knowledge"))
    op.add_column("needs", sa.Column("description_th", sa.Text(), nullable=False,
                                     server_default=""))
    op.add_column("needs", sa.Column("canonical_name_en", sa.Text(), nullable=True))
    op.add_column("needs", sa.Column("canonical_name_th", sa.Text(), nullable=False,
                                     server_default=""))
    op.alter_column("needs", "need_id", new_column_name="cluster_id")
    op.rename_table("needs", "clusters")
```

The `server_default` values exist only to satisfy the `NOT NULL` add on a table the migration just emptied; the ORM always supplies real values. Confirm the round trip works before committing:

```bash
uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
```

- [ ] **Step 6a: Add the target-count merge prompt**

Append to `src/curriculum_agent/prompts/cluster_skills.py`. This is a separate builder rather than a new parameter on `build_merge_clusters_prompt`, because that one is still used by the map-reduce path where no target count exists.

```python
def build_merge_to_target_prompt(
    cluster_labels: list[str], target_count: int
) -> list[dict[str, str]]:
    """Merge semantically-close groups until exactly `target_count` remain."""
    system = (
        "คุณเป็นผู้เชี่ยวชาญด้านการวิเคราะห์ทักษะแรงงาน\n"
        "รายการต่อไปนี้คือชื่อกลุ่มทักษะภายในหมวดสมรรถนะเดียวกัน "
        f"จงรวมกลุ่มที่มีความหมายใกล้เคียงกันเข้าด้วยกัน ให้เหลือ {target_count} กลุ่มพอดี\n\n"
        "กติกา:\n"
        f"- ผลลัพธ์ต้องมี {target_count} group พอดี ไม่มากไม่น้อยกว่านี้\n"
        "- ทุก index ต้องปรากฏใน groups ครั้งเดียวเท่านั้น ห้ามตกหล่น ห้ามซ้ำ\n"
        "- ห้ามใช้ index ที่ไม่มีในรายการ\n"
        "- เลือกรวมกลุ่มที่ทำงานลักษณะเดียวกันหรือใช้ทักษะร่วมกันก่อน "
        "ห้ามรวมกลุ่มที่ไม่เกี่ยวข้องกันเพียงเพื่อให้ครบจำนวน\n\n"
        "ตอบเป็น JSON object:\n"
        "{ groups: [ [index ของกลุ่มที่ควรรวมเข้าด้วยกัน] ] }"
    )
    numbered = "\n".join(f"{i}: {label}" for i, label in enumerate(cluster_labels))
    user = f"รายการกลุ่มทักษะ (index: ชื่อกลุ่ม):\n{numbered}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
```

- [ ] **Step 6b: Write the summarize prompt**

Create `src/curriculum_agent/prompts/summarize_need.py`:

```python
from __future__ import annotations

_KSEC_LABEL_TH = {
    "K": "ความรู้",
    "GS": "ทักษะทั่วไป",
    "SS": "ทักษะเฉพาะสาขา",
    "C": "คุณลักษณะบุคคล",
    "E": "คุณธรรมจริยธรรม",
}


def build_summarize_need_prompt(
    skill_names: list[str], sample_evidence: list[str], ksec: str
) -> list[dict[str, str]]:
    """Turn one group of related skills into a single market-demand sentence."""
    system = (
        "คุณเป็นผู้เชี่ยวชาญด้านการวิเคราะห์ความต้องการของตลาดแรงงาน\n"
        "จากกลุ่มทักษะที่ให้มา จงสรุปเป็น 'ความต้องการของตลาด' หนึ่งประโยค\n\n"
        "กติกา:\n"
        "- เขียนเป็นประโยคเดียว มุมมองของ 'ตลาดแรงงานต้องการอะไร' "
        "ไม่ใช่มุมมองผู้เรียนหรือผลลัพธ์การเรียนรู้\n"
        "- ต้องสื่อถึงความสามารถจริงที่ใช้ทำงานได้ ไม่ใช่แค่ชื่อหมวดทักษะ\n"
        "- ห้ามเป็นเพียงการนำชื่อทักษะมาต่อกันด้วยเครื่องหมายจุลภาค\n"
        "- ความยาวไม่เกิน 2 บรรทัด\n\n"
        "ตอบเป็น JSON object ที่มี field:\n"
        "  statement_th: string (ประโยคภาษาไทย)\n"
        "  statement_en: string (ประโยคภาษาอังกฤษ)"
    )
    label = _KSEC_LABEL_TH.get(ksec, ksec)
    keywords = ", ".join(skill_names[:30])
    evidence_block = "\n".join(f"- {q[:200]}" for q in sample_evidence[:5]) or "(ไม่มีตัวอย่าง)"
    user = (
        f"หมวดสมรรถนะ: {label} ({ksec})\n"
        f"ทักษะในกลุ่มนี้: {keywords}\n\n"
        f"ตัวอย่างข้อความ evidence:\n{evidence_block}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
```

- [ ] **Step 7: Write the need_combination stage**

Create `src/curriculum_agent/stages/need_combination.py`:

```python
from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from curriculum_agent.data.repositories import NeedRepository
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_heavy, complete_light
from curriculum_agent.models import (
    BloomLevel,
    ExtractedSkill,
    KSECCategory,
    Need,
    StakeholderType,
)
from curriculum_agent.prompts.cluster_skills import build_merge_to_target_prompt
from curriculum_agent.prompts.summarize_need import build_summarize_need_prompt
from curriculum_agent.stages.demand import WEIGHTED_CLASSES, compute_demand_score
from curriculum_agent.stages.llm_clustering import (
    MergeGroupsResponse,
    cluster_skill_names,
    validate_assignments,
)
from curriculum_agent.stages.need_grouping import (
    MIN_NEEDS,
    allocate_quota,
    bucket_by_ksec,
    dedupe_with_bloom_max,
    merge_bloom,
)


class _NeedStatement(BaseModel):
    statement_th: str = Field(min_length=1)
    statement_en: str | None = None


class _Group(BaseModel):
    """A candidate Need before its sentence is written."""

    ksec: KSECCategory
    skill_ids: list[str]
    evidence_ids: list[str]
    skill_names: list[str]
    bloom_level: BloomLevel
    demand_score: float
    is_optional: bool
    classification_coverage: dict[str, int]
    stakeholder_coverage: dict[str, int]


def _stakeholder_coverage(
    evidence_ids: list[str], classified: list[dict[str, Any]]
) -> dict[str, int]:
    coverage: dict[str, int] = {}
    wanted = set(evidence_ids)
    for item in classified:
        if item.get("evidence_id") in wanted:
            stype = str(item.get("stakeholder_type", "employer"))
            coverage[stype] = coverage.get(stype, 0) + 1
    return coverage


async def _build_groups(
    skills: list[ExtractedSkill],
    classified: list[dict[str, Any]],
    classification_by_evidence: dict[str, str],
    total_req_need: int,
) -> list[_Group]:
    """Cluster within each KSEC bucket and score every resulting group.

    Bucketing before clustering is what guarantees a group never mixes tags.
    """
    groups: list[_Group] = []
    for ksec, bucket in bucket_by_ksec(skills).items():
        names, index_groups, bloom_by_name = dedupe_with_bloom_max(bucket)
        if not names:
            continue
        logger.info(f"Clustering {len(names)} unique {ksec.value} skills")
        name_clusters = validate_assignments(
            [("", g) for g in await cluster_skill_names(names)], names
        )
        for _, name_indices in name_clusters:
            member_positions = sorted({p for ni in name_indices for p in index_groups[ni]})
            members = [bucket[p] for p in member_positions]
            evidence_ids = sorted({m.source_evidence_id for m in members})
            stk_coverage = _stakeholder_coverage(evidence_ids, classified)
            demand, is_optional, cls_coverage = compute_demand_score(
                evidence_ids, stk_coverage, total_req_need, classification_by_evidence
            )
            groups.append(
                _Group(
                    ksec=ksec,
                    skill_ids=[m.skill_id for m in members],
                    evidence_ids=evidence_ids,
                    skill_names=[names[ni] for ni in name_indices],
                    bloom_level=merge_bloom([bloom_by_name[names[ni]] for ni in name_indices]),
                    demand_score=demand,
                    is_optional=is_optional,
                    classification_coverage=cls_coverage,
                    stakeholder_coverage=stk_coverage,
                )
            )
    return groups


def _fuse(members: list[_Group]) -> _Group:
    """Combine several groups of the same KSEC bucket into one.

    Union rather than selection: a dropped group would take its evidence out of
    the pipeline, breaking the traceability the programme is assessed on.
    """
    head = members[0]
    skill_ids: list[str] = []
    skill_names: list[str] = []
    evidence: set[str] = set()
    for g in members:
        skill_ids.extend(g.skill_ids)
        skill_names.extend(g.skill_names)
        evidence |= set(g.evidence_ids)
    return head.model_copy(
        update={
            "skill_ids": skill_ids,
            "skill_names": skill_names,
            "evidence_ids": sorted(evidence),
            "bloom_level": merge_bloom([g.bloom_level for g in members]),
            "demand_score": max(g.demand_score for g in members),
            "is_optional": all(g.is_optional for g in members),
        }
    )


def _fuse_by_demand(bucket: list[_Group], limit: int) -> list[_Group]:
    """Fallback merge: fold the lowest-demand groups into the highest-demand ones.

    Used only when the LLM merge fails or returns the wrong group count. Purely
    arithmetic, so it always terminates at exactly `limit` groups.
    """
    ranked = sorted(bucket, key=lambda g: g.demand_score, reverse=True)
    keep, surplus = ranked[:limit], ranked[limit:]
    for i, extra in enumerate(surplus):
        target = i % limit
        keep[target] = _fuse([keep[target], extra])
    return keep


async def _merge_bucket(bucket: list[_Group], limit: int, ksec: KSECCategory) -> list[_Group]:
    """Reduce one bucket to `limit` groups, preferring a semantic merge.

    The heavy model decides which groups mean the same thing — that judgement is
    the reason this stage merges instead of truncating. Its output is validated
    for exactly-once coverage and for hitting the target count; anything else
    falls back to demand-ranked fusion so the stage cannot stall.
    """
    if len(bucket) <= limit:
        return bucket

    labels = [g.skill_names[0] for g in bucket]
    try:
        result = await complete_heavy(
            MergeGroupsResponse,
            build_merge_to_target_prompt(labels, limit),
            temperature=0,
        )
        merged = validate_assignments([("", g) for g in result.groups], labels)
        if len(merged) == limit:
            return [_fuse([bucket[i] for i in indices]) for _, indices in merged]
        logger.warning(
            f"{ksec.value} merge returned {len(merged)} groups, expected {limit} — "
            "falling back to demand-ranked fusion"
        )
    except Exception as exc:
        logger.warning(f"{ksec.value} merge call failed ({exc}) — falling back to demand ranking")

    return _fuse_by_demand(bucket, limit)


async def _apply_quota(groups: list[_Group]) -> list[_Group]:
    """Reduce core groups to the 6-10 policy, one bucket at a time.

    Optional (want-dominant) groups are exempt from the count, matching the
    project's optional-PLO rule, so only core groups are merged. Merging never
    crosses buckets, which is what keeps every Need single-tagged.
    """
    core = [g for g in groups if not g.is_optional]
    optional = [g for g in groups if g.is_optional]

    counts: dict[KSECCategory, int] = {}
    demand: dict[KSECCategory, float] = {}
    for g in core:
        counts[g.ksec] = counts.get(g.ksec, 0) + 1
        demand[g.ksec] = demand.get(g.ksec, 0.0) + g.demand_score

    quota = allocate_quota(counts, demand)
    kept: list[_Group] = []
    for ksec, limit in quota.items():
        in_bucket = [g for g in core if g.ksec == ksec]
        kept.extend(await _merge_bucket(in_bucket, limit, ksec))
    return kept + optional


async def run(state: AgentState) -> AgentState:
    """Stage 3b: distil extracted skills into 6-10 market-demand Needs."""
    program_id = state.get("program_id", "unknown")
    classified = state.get("classified_evidence", [])
    skill_dicts = state.get("extracted_skills", [])
    skills = [ExtractedSkill.model_validate(d) for d in skill_dicts]
    logger.info(f"Stage 3b: need_combination from {len(skills)} skills")

    if not skills:
        logger.warning("need_combination: no extracted skills — returning no Needs")
        state["needs"] = []
        state["current_stage"] = "need_combination"
        return state

    classification_by_evidence = {
        str(d["evidence_id"]): str(d.get("classification", "unclassified"))
        for d in classified
        if d.get("evidence_id")
    }
    total_req_need = sum(1 for c in classification_by_evidence.values() if c in WEIGHTED_CLASSES)

    groups = await _build_groups(skills, classified, classification_by_evidence, total_req_need)
    groups = await _apply_quota(groups)

    evidence_text_by_id = {
        str(d["evidence_id"]): str(d.get("raw_text_th", ""))
        for d in classified
        if d.get("evidence_id")
    }

    needs: list[Need] = []
    for group in groups:
        samples = [evidence_text_by_id.get(eid, "") for eid in group.evidence_ids[:3]]
        try:
            written = await complete_light(
                _NeedStatement,
                build_summarize_need_prompt(group.skill_names, samples, group.ksec.value),
            )
        except Exception as exc:
            logger.warning(f"Need summarize failed for {group.ksec.value} group: {exc}")
            written = _NeedStatement(statement_th=", ".join(group.skill_names[:5]))

        needs.append(
            Need(
                need_id=str(uuid.uuid4()),
                program_id=program_id,
                statement_th=written.statement_th,
                statement_en=written.statement_en,
                ksec_category=group.ksec,
                bloom_level=group.bloom_level,
                member_skill_ids=group.skill_ids,
                source_evidence_ids=group.evidence_ids,
                stakeholder_coverage={
                    StakeholderType(k): v
                    for k, v in group.stakeholder_coverage.items()
                    if k in StakeholderType._value2member_map_
                },
                freq=len(group.skill_ids),
                demand_score=group.demand_score,
                is_optional=group.is_optional,
                classification_coverage=group.classification_coverage,
                sample_quotes_th=[s[:200] for s in samples if s][:3],
            )
        )

    core_count = sum(1 for n in needs if not n.is_optional)
    if core_count < MIN_NEEDS:
        logger.warning(
            f"need_combination produced only {core_count} core Needs (policy is {MIN_NEEDS}-10) — "
            "the designer must add more at the review checkpoint"
        )

    await NeedRepository().bulk_insert(needs)
    state["needs"] = [n.model_dump(mode="json") for n in needs]
    state["current_stage"] = "need_combination"
    return state
```

- [ ] **Step 8: Strip clustering out of skill_extraction**

In `src/curriculum_agent/stages/skill_extraction.py`, delete `_ClusterNameResult`, `_ClusterBloomResult`, the `build_name_cluster_prompt`/`build_cluster_bloom_prompt`/`cluster_skill_names`/`dedupe_names`/`SkillCluster`/`ClusterRepository` imports, and everything in `run` from `# --- Step 3: LLM clustering ---` to the end of the cluster loop. The function now ends:

```python
    await SkillRepository().bulk_insert(extracted)

    state["extracted_skills"] = [s.model_dump(mode="json") for s in extracted]
    state["current_stage"] = "skill_extraction"
    return state
```

Delete the now-unused prompt files and their test:

```bash
git rm src/curriculum_agent/prompts/name_cluster.py src/curriculum_agent/prompts/classify_cluster_bloom.py tests/unit/test_cluster_bloom.py
```

- [ ] **Step 9: Wire the graph**

In `src/curriculum_agent/graph.py`: replace `skill_clusters` with `needs` in `AgentState`, add the node function, and insert it between extraction and review.

```python
async def stage_2b_need_combination(state: AgentState) -> AgentState:
    from curriculum_agent.stages.need_combination import run  # noqa: PLC0415

    return await run(state)
```

Rename the review node's message and rewire the edges:

```python
def review_needs(state: AgentState) -> AgentState:
    payload = interrupt("Stage 3 complete — review raw skills and distilled Needs")
    if isinstance(payload, dict):
        return {**state, **payload}
    return state
```

```python
    g.add_node("skill_extraction", stage_2_skill_extraction)
    g.add_node("need_combination", stage_2b_need_combination)
    g.add_node("review_needs_node", review_needs)
    ...
    g.add_edge("review_evidence", "skill_extraction")
    g.add_edge("skill_extraction", "need_combination")
    g.add_edge("need_combination", "review_needs_node")
    g.add_edge("review_needs_node", "plo_synthesis")
```

Remove the old `review_clusters` node and `review_skill_clusters` function. Add `"need_combination"` to the `StageCheckpoint.stage` Literal in `models.py`, keeping `"skill_extraction"` so persisted rows still validate.

- [ ] **Step 10: Make the downstream stages compile**

`plo_synthesis.py` and `plo_report.py` reference `SkillCluster`/`ClusterRepository`. Task 6 rewrites their logic; here, do the minimum to compile and keep tests green: swap `SkillCluster` → `Need`, `ClusterRepository` → `NeedRepository`, `cluster.cluster_id` → `need.need_id`, `c.canonical_name_th` → `n.statement_th`, and in `plo_report._cluster_summary` use `n.ksec_category.value` where it used `skill_type`/`is_subject_specific`:

```python
def _need_summary(n: Need) -> str:
    return f"{n.statement_en or n.statement_th} (ksec={n.ksec_category.value})"
```

and in `_classify_one`, count specificity from the tag:

```python
        n_specific = sum(1 for n in resolved if n.ksec_category is KSECCategory.SS)
```

Update `tests/conftest.py`: replace the `skill_cluster` and `sample_clusters` fixtures with `need`/`sample_needs` producing `Need` objects, and drop `SkillType`/`Domain` imports that no longer resolve.

```python
@pytest.fixture
def need() -> Need:
    return Need(
        need_id="N1",
        program_id="cs-test",
        statement_th="สามารถเขียนและออกแบบโปรแกรมตามความต้องการของธุรกิจ",
        ksec_category=KSECCategory.SS,
        bloom_level=BloomLevel.CREATE,
        member_skill_ids=["S1", "S2"],
        source_evidence_ids=["E1"],
        freq=2,
        demand_score=0.9,
    )


@pytest.fixture
def sample_needs(need: Need) -> list[Need]:
    return [need]
```

Grep for the old fixture names and update every consumer: `rg -n "skill_cluster|sample_clusters" tests/`.

- [ ] **Step 11: Run the full gate**

Run: `uv run alembic upgrade head && uv run alembic heads && uv run pytest && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/`
Expected: one alembic head, all tests pass, no type errors.

- [ ] **Step 12: Commit**

```bash
git add -A src/curriculum_agent migrations tests
git commit -m "feat(needs): replace SkillCluster with Need and add need_combination stage

Skill extraction now only extracts; grouping moves to a new
need_combination stage that clusters within each KSEC bucket, scores
freq and demand, merges surplus groups down to the 6-10 policy, and
writes one market-demand sentence per Need.

Surplus groups are merged rather than dropped so no evidence leaves the
pipeline. Deletes SkillType, PsychomotorLevel, and KrathwohlLevel, which
no model references now that Needs and PLOs are cognitive-only."
```

---

### Task 6: One-to-one Need-to-PLO synthesis

**Files:**
- Modify: `src/curriculum_agent/models.py` (`PLO`: drop `domain`/`psychomotor_level`/`krathwohl_level`, rename `source_cluster_ids`, delete `Domain`)
- Modify: `src/curriculum_agent/data/orm.py` (`PLOTable`)
- Create: `migrations/versions/<rev3>_plo_cognitive_only.py`
- Modify: `src/curriculum_agent/prompts/stage_3_plo.py`, `src/curriculum_agent/prompts/plo_classify.py`
- Modify: `src/curriculum_agent/stages/plo_synthesis.py`, `src/curriculum_agent/stages/plo_report.py`, `src/curriculum_agent/stages/smart_rules.py`
- Modify: `src/curriculum_agent/api/routes/plos.py`
- Test: `tests/unit/test_plo_one_to_one.py` (new), plus updates to `test_models.py`, `test_optional_plos.py`, `test_plo_count_policy.py`, `test_plo_report.py`, `test_smart_retry_loop.py`, `tests/integration/test_stage_3_plo.py`

**Interfaces:**
- Consumes: `Need`, `NeedRepository`, `KSECCategory` (Task 5).
- Produces:
  - `PLO` with `source_need_ids: list[str]`, required `bloom_level`, no `domain`
  - `build_plo_from_need_prompt(metadata: ProgramMetadata, need: Need) -> list[dict[str, str]]` in `prompts/stage_3_plo.py`
  - `run(state: AgentState) -> AgentState` in `plo_synthesis.py`, one PLO per Need

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_plo_one_to_one.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import BloomLevel, KSECCategory, Need, ProgramMetadata
from curriculum_agent.stages import plo_synthesis as ps


def _need(nid: str, optional: bool = False) -> Need:
    return Need(
        need_id=nid,
        program_id="cs-test",
        statement_th=f"สามารถทำงาน {nid} ตามที่ตลาดต้องการ",
        ksec_category=KSECCategory.SS,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=[f"S-{nid}"],
        source_evidence_ids=[f"E-{nid}"],
        freq=1,
        demand_score=0.7,
        is_optional=optional,
    )


def _draft(nid: str) -> ps._PLODraft:
    return ps._PLODraft(
        plo_id=f"PLO-{nid}",
        statement_th=f"วิเคราะห์งาน {nid} เพื่อเสนอแนวทางแก้ปัญหาได้",
        bloom_level=BloomLevel.ANALYZE,
        is_subject_specific=True,
        action_verb_th="วิเคราะห์",
        source_need_ids=[nid],
        source_evidence_ids=[f"E-{nid}"],
        rationale_th="ตรงกับความต้องการของตลาด",
    )


@pytest.fixture(autouse=True)
def _no_db(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ps.PLORepository, "bulk_insert", AsyncMock())


def _patch_llm(monkeypatch: pytest.MonkeyPatch, needs: list[Need]) -> AsyncMock:
    drafts = {n.need_id: _draft(n.need_id) for n in needs}
    calls: list[str] = []

    async def fake_heavy(model, messages, **kw):  # noqa: ANN001, ANN003
        body = messages[-1]["content"]
        nid = next(n.need_id for n in needs if n.need_id in body)
        calls.append(nid)
        return ps._SingleDraftResponse(plo=drafts[nid])

    async def fake_light(model, messages, **kw):  # noqa: ANN001, ANN003
        return ps._SmartSoftJudge(
            specific_object_ok=True, achievable_ok=True, relevant_alignment_ok=True
        )

    monkeypatch.setattr(ps, "complete_heavy", fake_heavy)
    monkeypatch.setattr(ps, "complete_light", fake_light)
    mock = AsyncMock()
    mock.calls = calls  # type: ignore[attr-defined]
    return mock


async def test_each_need_produces_exactly_one_plo(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    needs = [_need("N1"), _need("N2"), _need("N3")]
    _patch_llm(monkeypatch, needs)

    state = await ps.run(
        {
            "program_id": "cs-test",
            "metadata": program_metadata.model_dump(mode="json"),
            "needs": [n.model_dump(mode="json") for n in needs],
        }
    )

    plos = state["plos"]
    assert len(plos) == len(needs)
    assert [p["source_need_ids"] for p in plos] == [["N1"], ["N2"], ["N3"]]


async def test_optional_need_yields_optional_plo(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    needs = [_need("N1"), _need("N2", optional=True)]
    _patch_llm(monkeypatch, needs)

    state = await ps.run(
        {
            "program_id": "cs-test",
            "metadata": program_metadata.model_dump(mode="json"),
            "needs": [n.model_dump(mode="json") for n in needs],
        }
    )

    by_need = {p["source_need_ids"][0]: p for p in state["plos"]}
    assert by_need["N1"]["is_optional"] is False
    assert by_need["N2"]["is_optional"] is True


async def test_no_needs_raises_rather_than_inventing_plos(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    with pytest.raises(ValueError, match="no Needs"):
        await ps.run(
            {
                "program_id": "cs-test",
                "metadata": program_metadata.model_dump(mode="json"),
                "needs": [],
            }
        )


async def test_merging_needs_keeps_every_source_id_and_evidence(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    needs = [_need("N1"), _need("N2")]

    async def fake_heavy(model, messages, **kw):  # noqa: ANN001, ANN003
        # The model omits evidence ids; the Needs' own trail must fill the gap.
        draft = _draft("N1").model_copy(
            update={"source_need_ids": ["N1", "N2"], "source_evidence_ids": []}
        )
        return ps._SingleDraftResponse(plo=draft)

    async def fake_light(model, messages, **kw):  # noqa: ANN001, ANN003
        return ps._SmartSoftJudge(
            specific_object_ok=True, achievable_ok=True, relevant_alignment_ok=True
        )

    monkeypatch.setattr(ps, "complete_heavy", fake_heavy)
    monkeypatch.setattr(ps, "complete_light", fake_light)

    plo = await ps.synthesize_from_needs(
        program_metadata, needs, "cs-test", {"N1", "N2"}
    )

    assert plo is not None
    assert plo.source_need_ids == ["N1", "N2"]
    assert set(plo.source_evidence_ids) == {"E-N1", "E-N2"}


async def test_merged_plo_is_optional_only_when_all_sources_are(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    async def fake_heavy(model, messages, **kw):  # noqa: ANN001, ANN003
        return ps._SingleDraftResponse(
            plo=_draft("N1").model_copy(update={"source_need_ids": ["N1", "N2"]})
        )

    async def fake_light(model, messages, **kw):  # noqa: ANN001, ANN003
        return ps._SmartSoftJudge(
            specific_object_ok=True, achievable_ok=True, relevant_alignment_ok=True
        )

    monkeypatch.setattr(ps, "complete_heavy", fake_heavy)
    monkeypatch.setattr(ps, "complete_light", fake_light)

    mixed = await ps.synthesize_from_needs(
        program_metadata, [_need("N1"), _need("N2", optional=True)], "cs-test", {"N1", "N2"}
    )
    all_optional = await ps.synthesize_from_needs(
        program_metadata,
        [_need("N1", optional=True), _need("N2", optional=True)],
        "cs-test",
        {"N1", "N2"},
    )

    assert mixed is not None and mixed.is_optional is False
    assert all_optional is not None and all_optional.is_optional is True


async def test_synthesize_returns_none_when_the_model_fails(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    async def boom(model, messages, **kw):  # noqa: ANN001, ANN003
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(ps, "complete_heavy", boom)
    result = await ps.synthesize_from_needs(program_metadata, [_need("N1")], "cs-test", {"N1"})
    assert result is None


async def test_synthesize_rejects_an_empty_need_list(program_metadata: ProgramMetadata):
    with pytest.raises(ValueError, match="at least one Need"):
        await ps.synthesize_from_needs(program_metadata, [], "cs-test", set())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_plo_one_to_one.py -v`
Expected: FAIL — `_PLODraft` has no field `source_need_ids`.

- [ ] **Step 3: Reshape the PLO model, ORM, and migration**

In `models.py`, delete the `Domain` class and rewrite `PLO`'s head and validators:

```python
class PLO(BaseModel):
    plo_id: str
    program_id: str
    statement_th: str
    statement_en: str | None = None
    # Cognitive only. The agent stops at PLO, and psychomotor/affective level
    # scales belong to the faculty's YLO/CLO work, not here.
    bloom_level: BloomLevel
    is_subject_specific: bool
    action_verb_th: str
    smart_check: SMARTCheck
    source_need_ids: list[str]
    source_evidence_ids: list[str] = Field(default_factory=list)
    rationale_th: str
    distinctive_feature_th: str | None = None
    version: int = 1
    classification: Literal["generic", "specific"] | None = None
    classification_method: Literal["ksec", "llm", "manual"] | None = None
    classification_rationale_th: str | None = None
    smart_retry_count: int = 0
    smart_escalated: bool = False
    soft_flags: list[str] = Field(default_factory=list)
    is_optional: bool = False
```

Delete `check_domain_level_match` entirely and rewrite `check_evidence` to name the new field:

```python
    @model_validator(mode="after")
    def check_evidence(self) -> PLO:
        if not self.source_need_ids:
            raise ValueError(
                f"PLO {self.plo_id} has no source Needs — every PLO must trace to evidence."
            )
        if not self.source_evidence_ids:
            raise ValueError(
                f"PLO {self.plo_id} has empty source_evidence_ids — "
                "every PLO must trace to evidence."
            )
        return self
```

Note `classification_method` gains `"ksec"` and loses `"skill_type"`.

In `orm.py`, drop `domain`, `psychomotor_level`, `krathwohl_level` from `PLOTable`, rename `source_cluster_ids` to `source_need_ids`, and make `bloom_level` non-nullable:

```python
    bloom_level: Mapped[str] = mapped_column(String(20))
    is_subject_specific: Mapped[bool] = mapped_column(Boolean)
    action_verb_th: Mapped[str] = mapped_column(Text)
    # Serialized SMARTCheck model — bool criteria plus optional notes string
    smart_check: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source_need_ids: Mapped[list[str]] = mapped_column(JSONB)
```

Create `migrations/versions/<rev3>_plo_cognitive_only.py`:

```python
"""PLO becomes cognitive-only and traces to Needs

Revision ID: <rev3>
Revises: <rev2>
Create Date: 2026-07-26 00:00:02.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '<rev3>'
down_revision: Union[str, None] = '<rev2>'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing PLOs point at cluster ids that no longer exist after <rev2>, so
    # they cannot be carried over. Programmes re-run synthesis from their Needs.
    op.execute("DELETE FROM plos")
    op.alter_column("plos", "source_cluster_ids", new_column_name="source_need_ids")
    op.drop_column("plos", "domain")
    op.drop_column("plos", "psychomotor_level")
    op.drop_column("plos", "krathwohl_level")
    op.alter_column("plos", "bloom_level", existing_type=sa.String(20), nullable=False,
                    server_default="apply")


def downgrade() -> None:
    op.execute("DELETE FROM plos")
    op.alter_column("plos", "bloom_level", existing_type=sa.String(20), nullable=True,
                    server_default=None)
    op.add_column("plos", sa.Column("krathwohl_level", sa.String(20), nullable=True))
    op.add_column("plos", sa.Column("psychomotor_level", sa.String(20), nullable=True))
    op.add_column("plos", sa.Column("domain", sa.String(20), nullable=False,
                                    server_default="cognitive"))
    op.alter_column("plos", "source_need_ids", new_column_name="source_cluster_ids")
```

- [ ] **Step 4: Replace the synthesis prompt**

In `src/curriculum_agent/prompts/stage_3_plo.py`, replace `build_plo_synthesis_prompt` and `build_optional_plo_prompt` with a single per-Need builder (read the file first to keep the metadata-block formatting it already uses):

```python
def build_plo_from_need_prompt(
    metadata: ProgramMetadata, needs: list[Need]
) -> list[dict[str, str]]:
    """Restate one or more market Needs as a single graduate-side PLO.

    Takes a list because the designer may merge several Needs into one PLO; the
    1:1 stage path passes a single-element list.
    """
    plural = len(needs) > 1
    system = (
        "คุณเป็นผู้เชี่ยวชาญ OBE ตามมาตรฐาน MHESI\n"
        + (
            "จงรวม 'ความต้องการของตลาด' ที่ให้มาทั้งหมด ให้เป็น PLO เพียงหนึ่งข้อ\n\n"
            if plural
            else "จงแปลง 'ความต้องการของตลาด' หนึ่งข้อ ให้เป็น PLO หนึ่งข้อ\n\n"
        )
        + "กติกา:\n"
        "- เขียนจากมุมผู้เรียน: 'บัณฑิตทำอะไรได้' ไม่ใช่ 'ตลาดต้องการอะไร'\n"
        "- ใช้คำกริยาแสดงพฤติกรรมตาม Bloom เพียง 1 คำ\n"
        "- ห้ามใช้คำที่วัดไม่ได้: รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก\n"
        "- ต้องระบุวัตถุของกริยาให้เจาะจง ห้ามใช้คำกว้างเช่น 'ความรู้ที่จำเป็น'\n"
        "- source_need_ids ต้องเป็น need_id ที่ให้มาทั้งหมด ห้ามเพิ่มหรือตัดทิ้ง\n"
        + ("- ต้องครอบคลุมสาระของทุกความต้องการที่ให้มา ห้ามละข้อใดข้อหนึ่ง\n" if plural else "")
        + "\nตอบเป็น JSON object ที่มี field: plo (object) โดย plo มี field:\n"
        "  plo_id, statement_th, statement_en, bloom_level, is_subject_specific,\n"
        "  action_verb_th, source_need_ids, source_evidence_ids, rationale_th,\n"
        "  distinctive_feature_th"
    )
    need_block = "\n\n".join(
        f"need_id: {n.need_id}\n"
        f"ความต้องการของตลาด: {n.statement_th}\n"
        f"หมวดสมรรถนะ: {n.ksec_category.value}\n"
        f"ระดับ Bloom ที่เหมาะสม: {n.bloom_level.value}\n"
        f"ความถี่ที่ถูกกล่าวถึง: {n.freq} ครั้ง (demand {n.demand_score})"
        for n in needs
    )
    user = (
        f"หลักสูตร: {metadata.name_th} ({metadata.degree_level}, {metadata.duration_years} ปี)\n"
        f"สาขา: {metadata.field}\n"
        f"วิสัยทัศน์: {metadata.vision_th}\n\n"
        f"{need_block}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
```

- [ ] **Step 5: Rewrite the synthesis stage**

In `src/curriculum_agent/stages/plo_synthesis.py`: delete `_PLODraftList`, `_OptionalDraftList`, `_MIN_PLOS`, `_MAX_PLOS`; update `_PLODraft` to the new field set (`bloom_level` required, `source_need_ids`, no `domain`/`psychomotor_level`/`krathwohl_level`, `_check_level` deleted, `_check_clusters` renamed to check `source_need_ids`); change `_ensure_smart`'s `known_cluster_ids` parameter to `known_need_ids`; and replace `run` with a loop over Needs:

```python
async def synthesize_from_needs(
    metadata: ProgramMetadata,
    needs: list[Need],
    program_id: str,
    known_need_ids: set[str],
) -> PLO | None:
    """Draft one PLO from one or more Needs, then run it through the SMART gate.

    Shared by the 1:1 stage loop and the designer-driven N:1 endpoint, so both
    paths get the same SMART enforcement and evidence fallback. Returns None when
    the model call fails outright — the caller decides whether that is fatal.
    """
    if not needs:
        raise ValueError("synthesize_from_needs requires at least one Need")

    try:
        response = await complete_heavy(
            _SingleDraftResponse,
            build_plo_from_need_prompt(metadata, needs),
            max_retries=_MAX_RETRIES,
        )
    except Exception as exc:
        ids = ", ".join(n.need_id for n in needs)
        logger.warning(f"PLO synthesis failed for Need(s) {ids}: {exc}")
        return None

    outcome = await _ensure_smart(response.plo, known_need_ids, metadata)
    draft = outcome.draft

    # The Needs already carry a verified evidence trail; fall back to it rather
    # than trusting the model to echo evidence ids correctly.
    evidence_ids = draft.source_evidence_ids or sorted(
        {eid for n in needs for eid in n.source_evidence_ids}
    )

    return PLO(
        plo_id=draft.plo_id or f"PLO-{uuid.uuid4().hex[:6]}",
        program_id=program_id,
        statement_th=draft.statement_th,
        statement_en=draft.statement_en,
        bloom_level=draft.bloom_level,
        # Specific when any contributing Need is subject-specific: a PLO covering
        # a domain capability stays domain-specific even if merged with a generic one.
        is_subject_specific=any(n.ksec_category is KSECCategory.SS for n in needs),
        action_verb_th=draft.action_verb_th,
        smart_check=outcome.smart_check,
        source_need_ids=[n.need_id for n in needs],
        source_evidence_ids=evidence_ids,
        rationale_th=draft.rationale_th,
        distinctive_feature_th=draft.distinctive_feature_th,
        version=1,
        smart_retry_count=outcome.retry_count,
        smart_escalated=outcome.escalated,
        soft_flags=outcome.soft_flags,
        # Optional only when every contributing Need is optional.
        is_optional=all(n.is_optional for n in needs),
    )


async def run(state: AgentState) -> AgentState:
    """Stage 4: one PLO per Need."""
    program_id = state.get("program_id", "unknown")
    metadata_dict = state.get("metadata")
    if not metadata_dict:
        raise ValueError("AgentState missing 'metadata' — cannot run PLO synthesis stage")
    metadata = ProgramMetadata.model_validate(metadata_dict)

    needs = [Need.model_validate(d) for d in state.get("needs", [])]
    if not needs:
        raise ValueError(
            f"Stage 4: no Needs for program '{program_id}' — "
            "run need_combination successfully before PLO synthesis"
        )

    known_need_ids = {n.need_id for n in needs}
    logger.info(f"Stage 4: synthesizing one PLO per Need ({len(needs)} Needs)")

    plos: list[PLO] = []
    for need in needs:
        plo = await synthesize_from_needs(metadata, [need], program_id, known_need_ids)
        if plo is not None:
            plos.append(plo)

    core = sum(1 for p in plos if not p.is_optional)
    if not MIN_NEEDS <= core <= MAX_NEEDS:
        logger.warning(
            f"Stage 4 produced {core} core PLOs, outside the {MIN_NEEDS}-{MAX_NEEDS} policy — "
            "need_combination should have enforced this; review at the checkpoint"
        )

    await PLORepository().bulk_insert(plos)
    state["plos"] = [p.model_dump(mode="json") for p in plos]
    state["current_stage"] = "plo_synthesis"
    return state
```

Import `MIN_NEEDS`, `MAX_NEEDS` from `stages.need_grouping`, plus `Need`, `KSECCategory`, `uuid`.

In `stages/smart_rules.py`, rename the `known_cluster_ids` parameter of `hard_failures` to `known_need_ids` and update `CRITERION_FIX_HINTS_TH` wording that mentions clusters.

In `stages/plo_report.py`, change `plo.source_cluster_ids` → `plo.source_need_ids`, `"skill_type"` method string → `"ksec"`, and drop `plo.domain.value` from the `build_plo_classify_prompt` call — pass `plo.bloom_level.value` instead, renaming that prompt's `domain` parameter to `bloom_level`.

- [ ] **Step 6: Fix remaining tests**

Run `uv run pytest -x` repeatedly and fix each failure. Expect: `test_models.py` (PLO fixtures), `test_optional_plos.py` and `test_plo_count_policy.py` (both assert the old batch behavior — rewrite them against the 1:1 loop or delete them if `test_plo_one_to_one.py` now covers the same ground), `test_plo_report.py`, `test_plo_report_router.py`, `test_smart_retry_loop.py`, `test_plo_classify_prompt.py`, `tests/integration/test_stage_3_plo.py`, `tests/integration/test_end_to_end.py`, `tests/unit/test_state_safety.py`, and `api/routes/plos.py`.

- [ ] **Step 7: Run the full gate**

Run: `uv run alembic upgrade head && uv run alembic heads && uv run pytest && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/`
Expected: one head, all green.

- [ ] **Step 8: Commit**

```bash
git add -A src/curriculum_agent migrations tests
git commit -m "feat(plo): synthesize one PLO per Need

Replaces the single prompt that requested 6-10 PLOs at once with one
focused call per Need, which the project's own prompt guidance prefers and
which lets each call name its Need directly. The 6-10 constraint is now
enforced upstream in need_combination.

PLO drops domain, psychomotor_level, and krathwohl_level: every PLO the
agent produces is cognitive. source_cluster_ids becomes source_need_ids,
a list, so the designer-driven N:1 merge works without a schema change."
```

---

### Task 7: API route rename and the rebuilt Stage 3 page

**REQUIRED SUB-SKILL for this task:** invoke `frontend-design` before writing the TSX — the table and card layouts are new UI surfaces, not tweaks.

**Files:**
- Create: `src/curriculum_agent/api/routes/needs.py`
- Delete: `src/curriculum_agent/api/routes/clusters.py`
- Modify: `src/curriculum_agent/api/main.py:14,63`
- Create: `frontend/src/pages/components/SkillTable.tsx`, `frontend/src/pages/components/NeedCard.tsx`
- Modify: `frontend/src/pages/SkillExtraction.tsx` (rebuild), `frontend/src/pages/PloSynthesis.tsx` (multi-select), `frontend/src/pages/PloReport.tsx` (drop `domain`)
- Test: `tests/unit/test_needs_router.py` (new)

**Interfaces:**
- Consumes: `Need`, `NeedRepository`, `ExtractedSkill` (Task 5); PLO shape (Task 6).
- Produces: `GET /programs/{program_id}/needs/`, `GET /programs/{program_id}/needs/{need_id}/trace`, `POST /programs/{program_id}/needs/run` (runs `skill_extraction` then `need_combination`), and `GET /programs/{program_id}/needs/skills` returning the raw skills for the table.

- [ ] **Step 1: Write the failing router test**

Read `tests/unit/test_plo_report_router.py` first to match its client-construction style, then create `tests/unit/test_needs_router.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from curriculum_agent.api.routes import needs as needs_route
from curriculum_agent.models import (
    BloomLevel,
    ExtractedSkill,
    KSECCategory,
    Need,
)


def _need() -> Need:
    return Need(
        need_id="N1",
        program_id="cs-test",
        statement_th="สามารถวิเคราะห์ข้อมูลขนาดใหญ่เพื่อหา insight ทางธุรกิจ",
        ksec_category=KSECCategory.SS,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=["S1"],
        source_evidence_ids=["E1"],
        freq=1,
        demand_score=0.7,
    )


def _skill() -> ExtractedSkill:
    return ExtractedSkill(
        skill_id="S1",
        program_id="cs-test",
        skill_name_th="วิเคราะห์ข้อมูลขนาดใหญ่",
        ksec_category=KSECCategory.SS,
        bloom_level=BloomLevel.ANALYZE,
        evidence_span_th="ต้องวิเคราะห์ข้อมูลขนาดใหญ่ได้",
        source_evidence_id="E1",
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.75,
    )


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(needs_route.router, prefix="/programs/{program_id}/needs")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_list_needs_returns_repository_rows(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        needs_route.NeedRepository, "list_by_program", AsyncMock(return_value=[_need()])
    )
    response = await client.get("/programs/cs-test/needs/")
    assert response.status_code == 200
    body = response.json()
    assert [n["need_id"] for n in body] == ["N1"]
    assert body[0]["ksec_category"] == "SS"


async def test_list_skills_exposes_span_and_importance(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        needs_route.SkillRepository, "list_by_program", AsyncMock(return_value=[_skill()])
    )
    response = await client.get("/programs/cs-test/needs/skills")
    assert response.status_code == 200
    row = response.json()[0]
    assert row["evidence_span_th"] == "ต้องวิเคราะห์ข้อมูลขนาดใหญ่ได้"
    assert row["importance_score"] == 0.75


async def test_trace_returns_404_for_unknown_need(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        needs_route.NeedRepository, "list_by_program", AsyncMock(return_value=[_need()])
    )
    response = await client.get("/programs/cs-test/needs/does-not-exist/trace")
    assert response.status_code == 404


async def test_run_rejects_program_without_evidence(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        needs_route.EvidenceRepository, "list_by_program", AsyncMock(return_value=[])
    )
    response = await client.post("/programs/cs-test/needs/run")
    assert response.status_code == 422
    assert "evidence" in response.json()["detail"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_needs_router.py -v`
Expected: FAIL — 404s on every route because the router does not exist.

- [ ] **Step 3: Write the needs router**

Create `src/curriculum_agent/api/routes/needs.py`, porting `routes/clusters.py` with these changes: `ClusterRepository` → `NeedRepository`, `SkillCluster` → `Need`, `cluster_id` → `need_id`, `NeedTrace` in place of `ClusterTrace`, and `run_skill_extraction` becomes a two-stage runner:

```python
class NeedRunResult(BaseModel):
    """POST /run returns the drop count alongside the Needs.

    The count is a property of the run, not of any stored row, so it travels in
    the response rather than being re-derivable from the database later.
    """

    needs: list[Need]
    dropped_ungrounded_count: int


@router.post("/run", response_model=NeedRunResult)
async def run_need_pipeline(program_id: str) -> NeedRunResult:
    from curriculum_agent.stages.need_combination import run as run_needs  # noqa: PLC0415
    from curriculum_agent.stages.skill_extraction import run as run_skills  # noqa: PLC0415

    evidence_items = await EvidenceRepository().list_by_program(program_id)
    if not evidence_items:
        raise HTTPException(
            status_code=422,
            detail="ไม่มี evidence สำหรับโปรแกรมนี้ กรุณาเพิ่ม evidence ก่อน",
        )

    state: AgentState = {
        "program_id": program_id,
        "classified_evidence": [e.model_dump(mode="json") for e in evidence_items],
    }
    state = await asyncio.wait_for(run_skills(state), timeout=300)
    state = await asyncio.wait_for(run_needs(state), timeout=300)
    return NeedRunResult(
        needs=[Need.model_validate(n) for n in state.get("needs", [])],
        dropped_ungrounded_count=state.get("dropped_ungrounded_count", 0),
    )


@router.get("/skills", response_model=list[ExtractedSkill])
async def list_skills(program_id: str) -> list[ExtractedSkill]:
    return await SkillRepository().list_by_program(program_id)
```

Keep `DemandSignal` and its `FREQ_WEIGHT`/`BREADTH_WEIGHT` reuse from Task 1. Then:

```bash
git rm src/curriculum_agent/api/routes/clusters.py
```

and in `api/main.py` change the import to `needs` and the registration to:

```python
app.include_router(needs.router, prefix="/programs/{program_id}/needs", tags=["needs"])
```

- [ ] **Step 4: Build the skill table component**

Create `frontend/src/pages/components/SkillTable.tsx`. Five columns exactly — Skill, Bloom's, KSEC, Stakeholder class, Importance score — default-sorted by importance descending, with click-to-expand rows revealing `evidence_span_th`, the source evidence name, and the stakeholder type. Column headers are clickable to re-sort. Wrap the table in `overflow-x-auto` so narrow viewports scroll the table rather than the page.

```tsx
import { Fragment, useMemo, useState } from 'react'

export interface SkillRow {
  skill_id: string
  skill_name_th: string
  skill_name_en: string | null
  ksec_category: string
  bloom_level: string
  evidence_span_th: string
  source_evidence_id: string
  importance_score: number
}

export interface EvidenceMeta {
  source_name: string
  stakeholder_type: string
  classification: string
}

type SortKey = 'skill_name_th' | 'bloom_level' | 'ksec_category' | 'classification' | 'importance_score'

const KSEC_LABEL: Record<string, string> = {
  K: 'K · ความรู้',
  GS: 'GS · ทักษะทั่วไป',
  SS: 'SS · ทักษะเฉพาะสาขา',
  C: 'C · คุณลักษณะ',
  E: 'E · จริยธรรม',
}

const KSEC_COLOR: Record<string, string> = {
  K: 'bg-sky-100 text-sky-800',
  GS: 'bg-teal-100 text-teal-800',
  SS: 'bg-emerald-100 text-emerald-800',
  C: 'bg-amber-100 text-amber-800',
  E: 'bg-rose-100 text-rose-800',
}

const BLOOM_TH: Record<string, string> = {
  remember: 'จำได้ (Remember)',
  understand: 'เข้าใจ (Understand)',
  apply: 'ประยุกต์ (Apply)',
  analyze: 'วิเคราะห์ (Analyze)',
  evaluate: 'ประเมิน (Evaluate)',
  create: 'สร้างสรรค์ (Create)',
}

const CLASS_COLOR: Record<string, string> = {
  requirement: 'bg-green-100 text-green-700',
  need: 'bg-blue-100 text-blue-700',
  want: 'bg-amber-100 text-amber-700',
  unclassified: 'bg-gray-100 text-gray-500',
}

const COLUMNS: { key: SortKey; label: string; numeric?: boolean }[] = [
  { key: 'skill_name_th', label: 'Skill' },
  { key: 'bloom_level', label: "Bloom's" },
  { key: 'ksec_category', label: 'KSEC' },
  { key: 'classification', label: 'Stakeholder class' },
  { key: 'importance_score', label: 'Importance', numeric: true },
]

export default function SkillTable({
  skills,
  evidenceById,
  droppedCount,
}: {
  skills: SkillRow[]
  evidenceById: Record<string, EvidenceMeta>
  droppedCount: number
}) {
  const [sortKey, setSortKey] = useState<SortKey>('importance_score')
  const [asc, setAsc] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  const sorted = useMemo(() => {
    const value = (s: SkillRow): string | number =>
      sortKey === 'classification'
        ? (evidenceById[s.source_evidence_id]?.classification ?? '')
        : (s[sortKey] as string | number)
    return [...skills].sort((a, b) => {
      const av = value(a)
      const bv = value(b)
      const cmp = typeof av === 'number' && typeof bv === 'number'
        ? av - bv
        : String(av).localeCompare(String(bv), 'th')
      return asc ? cmp : -cmp
    })
  }, [skills, sortKey, asc, evidenceById])

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) setAsc(!asc)
    else {
      setSortKey(key)
      setAsc(key !== 'importance_score')
    }
  }

  if (skills.length === 0) {
    return <p className="py-8 text-center text-sm text-gray-400">ยังไม่มีทักษะที่สกัดได้</p>
  }

  return (
    <div className="space-y-3">
      {droppedCount > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          ทิ้งไป {droppedCount} ทักษะ (ข้อความที่ยกอ้างไม่ตรงกับ evidence)
        </div>
      )}
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              {COLUMNS.map(c => (
                <th
                  key={c.key}
                  onClick={() => toggleSort(c.key)}
                  className={`cursor-pointer select-none px-3 py-2 text-xs font-semibold uppercase tracking-wide text-gray-500 ${c.numeric ? 'text-right' : 'text-left'}`}
                >
                  {c.label}
                  {sortKey === c.key && <span className="ml-1">{asc ? '▲' : '▼'}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {sorted.map(s => {
              const ev = evidenceById[s.source_evidence_id]
              const open = expanded === s.skill_id
              return (
                <Fragment key={s.skill_id}>
                  <tr
                    onClick={() => setExpanded(open ? null : s.skill_id)}
                    className="cursor-pointer hover:bg-gray-50"
                  >
                    <td className="px-3 py-2">
                      <span className="font-medium text-gray-800">{s.skill_name_th}</span>
                      {s.skill_name_en && (
                        <span className="ml-2 text-xs text-gray-400 italic">{s.skill_name_en}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-600">
                      {BLOOM_TH[s.bloom_level] ?? s.bloom_level}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${KSEC_COLOR[s.ksec_category] ?? 'bg-gray-100 text-gray-600'}`}>
                        {KSEC_LABEL[s.ksec_category] ?? s.ksec_category}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${CLASS_COLOR[ev?.classification ?? 'unclassified']}`}>
                        {ev?.classification ?? 'unclassified'}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs text-gray-700">
                      {(s.importance_score * 100).toFixed(0)}%
                    </td>
                  </tr>
                  {open && (
                    <tr className="bg-gray-50">
                      <td colSpan={COLUMNS.length} className="px-3 py-2">
                        <p className="text-xs text-gray-500">ข้อความที่ยกอ้างจาก evidence:</p>
                        <blockquote className="mt-1 border-l-2 border-gray-300 pl-2 text-xs text-gray-700">
                          {s.evidence_span_th}
                        </blockquote>
                        <p className="mt-1 text-xs text-gray-400">
                          จาก: {ev?.source_name ?? s.source_evidence_id}
                          {ev && <> · {ev.stakeholder_type}</>}
                        </p>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Build the Need card and rebuild the page**

Create `frontend/src/pages/components/NeedCard.tsx`:

```tsx
import { useState } from 'react'
import api from '../../api/client'

export interface NeedRow {
  need_id: string
  statement_th: string
  statement_en: string | null
  ksec_category: string
  bloom_level: string
  member_skill_ids: string[]
  source_evidence_ids: string[]
  freq: number
  demand_score: number
  is_optional: boolean
  sample_quotes_th: string[]
}

interface NeedTrace {
  need: NeedRow
  skills: { skill_id: string; skill_name_th: string; bloom_level: string }[]
  evidence: { evidence_id: string; source_name: string; classification: string }[]
}

const KSEC_LABEL: Record<string, string> = {
  K: 'K · ความรู้',
  GS: 'GS · ทักษะทั่วไป',
  SS: 'SS · ทักษะเฉพาะสาขา',
  C: 'C · คุณลักษณะ',
  E: 'E · จริยธรรม',
}

export default function NeedCard({ programId, need }: { programId: string; need: NeedRow }) {
  const [trace, setTrace] = useState<NeedTrace | null>(null)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')

  const toggle = async () => {
    const next = !open
    setOpen(next)
    if (next && !trace) {
      try {
        const res = await api.get<NeedTrace>(`/programs/${programId}/needs/${need.need_id}/trace`)
        setTrace(res.data)
      } catch {
        setError('โหลด trace ไม่สำเร็จ')
      }
    }
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="flex items-start gap-2">
        <p className="flex-1 text-sm font-medium leading-relaxed text-gray-800">
          {need.statement_th}
        </p>
        {need.is_optional && (
          <span className="shrink-0 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
            เสริม
          </span>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-600">
        <span className="rounded bg-gray-100 px-1.5 py-0.5">
          {KSEC_LABEL[need.ksec_category] ?? need.ksec_category}
        </span>
        <span className="rounded bg-indigo-100 px-1.5 py-0.5 text-indigo-800">
          {need.bloom_level}
        </span>
        <span title="จำนวนครั้งที่ถูกกล่าวถึง">Freq {need.freq}</span>
        <span title="คะแนนถ่วงน้ำหนักตามความถี่และความกว้างของ stakeholder">
          Demand {(need.demand_score * 100).toFixed(0)}%
        </span>
        <button onClick={toggle} className="ml-auto text-blue-600 hover:underline">
          {open ? 'ซ่อนที่มา' : 'ดูที่มา'}
        </button>
      </div>
      {open && (
        <div className="mt-3 space-y-2 border-t border-gray-100 pt-3 text-xs">
          {error && <p className="text-red-600">{error}</p>}
          {!trace && !error && <p className="text-gray-400">กำลังโหลด...</p>}
          {trace && (
            <>
              <div>
                <p className="font-semibold text-gray-500">ทักษะในกลุ่ม ({trace.skills.length})</p>
                <ul className="mt-1 list-disc pl-4 text-gray-700">
                  {trace.skills.map(s => (
                    <li key={s.skill_id}>
                      {s.skill_name_th} <span className="text-gray-400">· {s.bloom_level}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="font-semibold text-gray-500">
                  Evidence ({trace.evidence.length})
                </p>
                <ul className="mt-1 list-disc pl-4 text-gray-700">
                  {trace.evidence.map(e => (
                    <li key={e.evidence_id}>
                      {e.source_name} <span className="text-gray-400">· {e.classification}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
```

Rebuild `SkillExtraction.tsx` as a two-tab shell. Fetch all three sources in parallel, build the `evidenceById` lookup the table needs, and keep one approve action covering both tabs:

```tsx
const [tab, setTab] = useState<'skills' | 'needs'>('skills')
const [skills, setSkills] = useState<SkillRow[]>([])
const [needs, setNeeds] = useState<NeedRow[]>([])
const [evidenceById, setEvidenceById] = useState<Record<string, EvidenceMeta>>({})

const fetchAll = useCallback(async () => {
  if (!programId) return
  setLoading(true)
  setError('')
  try {
    const [skillRes, needRes, evidenceRes] = await Promise.all([
      api.get<SkillRow[]>(`/programs/${programId}/needs/skills`),
      api.get<NeedRow[]>(`/programs/${programId}/needs/`),
      api.get<(EvidenceMeta & { evidence_id: string })[]>(`/programs/${programId}/evidence/`),
    ])
    setSkills(skillRes.data)
    setNeeds(needRes.data)
    setEvidenceById(
      Object.fromEntries(
        evidenceRes.data.map(e => [
          e.evidence_id,
          {
            source_name: e.source_name,
            stakeholder_type: e.stakeholder_type,
            classification: e.classification,
          },
        ]),
      ),
    )
  } catch {
    setError('โหลดข้อมูล Stage 3 ไม่สำเร็จ')
  } finally {
    setLoading(false)
  }
}, [programId])
```

Render the tab strip and bodies:

```tsx
<div className="mb-4 flex gap-1 border-b border-gray-200">
  {([
    ['skills', `Skill ดิบ (${skills.length})`],
    ['needs', `Need (${needs.length})`],
  ] as const).map(([key, label]) => (
    <button
      key={key}
      onClick={() => setTab(key)}
      className={`px-4 py-2 text-sm font-medium ${
        tab === key
          ? 'border-b-2 border-blue-600 text-blue-700'
          : 'text-gray-500 hover:text-gray-700'
      }`}
    >
      {label}
    </button>
  ))}
</div>

{tab === 'skills' ? (
  <SkillTable skills={skills} evidenceById={evidenceById} droppedCount={droppedCount} />
) : (
  <div className="space-y-3">
    {needs.map(n => (
      <NeedCard key={n.need_id} programId={programId!} need={n} />
    ))}
  </div>
)}
```

Wire the run button to the `NeedRunResult` response from Step 3, storing the drop count so the banner survives until the next run:

```tsx
const [droppedCount, setDroppedCount] = useState(0)

const runStage = async () => {
  if (!programId) return
  setRunning(true)
  setError('')
  try {
    const res = await api.post<{ needs: NeedRow[]; dropped_ungrounded_count: number }>(
      `/programs/${programId}/needs/run`,
    )
    setDroppedCount(res.data.dropped_ungrounded_count)
    await fetchAll()
  } catch {
    setError('รัน Stage 3 ไม่สำเร็จ')
  } finally {
    setRunning(false)
  }
}
```

Delete `SKILL_TYPE_LABEL`, `SKILL_TYPE_COLOR`, `groupByBloom`, `LEVEL_ORDER`, `PSYCHOMOTOR_ORDER`, `BLOOM_ORDER`, `LEVEL_TH`, the `SkillCluster`/`ClusterTrace`/`DemandSignal` interfaces, and `ClusterTracePanel` — `NeedCard` replaces it.

- [ ] **Step 6: Add the N:1 endpoint, the PLO multi-select, and fix PloReport**

First the test. Append to `tests/unit/test_needs_router.py` (it already has the client fixture), adjusting the router prefix to mount `plos` as well:

```python
async def test_from_needs_rejects_fewer_than_two_needs(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    # One Need already becomes a PLO through the normal 1:1 path.
    response = await client.post("/programs/cs-test/plos/from-needs", json={"need_ids": ["N1"]})
    assert response.status_code == 422


async def test_from_needs_rejects_unknown_need_ids(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        plos_route.NeedRepository, "list_by_program", AsyncMock(return_value=[_need()])
    )
    response = await client.post(
        "/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "ghost"]}
    )
    assert response.status_code == 422
    assert "ghost" in response.json()["detail"]
```

Import `plos as plos_route` and include its router in the fixture's app alongside `needs_route`. Then implement — add to `src/curriculum_agent/api/routes/plos.py`:

```python
class MergeNeedsRequest(BaseModel):
    need_ids: list[str] = Field(min_length=2)


@router.post("/from-needs", response_model=PLO)
async def create_plo_from_needs(program_id: str, body: MergeNeedsRequest) -> PLO:
    """Synthesize one PLO covering several designer-selected Needs."""
    from curriculum_agent.stages.plo_synthesis import synthesize_from_needs  # noqa: PLC0415

    program = await ProgramRepository().get(program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="ไม่พบหลักสูตรนี้")

    all_needs = await NeedRepository().list_by_program(program_id)
    by_id = {n.need_id: n for n in all_needs}
    missing = [nid for nid in body.need_ids if nid not in by_id]
    if missing:
        raise HTTPException(
            status_code=422, detail=f"ไม่พบ Need: {', '.join(missing)}"
        )

    selected = [by_id[nid] for nid in body.need_ids]
    plo = await synthesize_from_needs(
        program, selected, program_id, {n.need_id for n in all_needs}
    )
    if plo is None:
        raise HTTPException(status_code=502, detail="สร้าง PLO ไม่สำเร็จ กรุณาลองใหม่")

    await PLORepository().bulk_insert([plo])
    return plo
```

Add the imports it needs (`Field`, `NeedRepository`, `ProgramRepository`, `PLO`) and read the existing file first — `ProgramRepository.get` may be named differently; use whatever the repository actually exposes for fetching one program's metadata.

In `PloSynthesis.tsx`, add selection state and the merge action:

```tsx
const [selected, setSelected] = useState<Set<string>>(new Set())

const toggleNeed = (needId: string) => {
  setSelected(prev => {
    const next = new Set(prev)
    if (next.has(needId)) next.delete(needId)
    else next.add(needId)
    return next
  })
}

const mergeSelected = async () => {
  if (selected.size < 2 || !programId) return
  setRunning(true)
  setError('')
  try {
    await api.post(`/programs/${programId}/plos/from-needs`, {
      need_ids: [...selected],
    })
    setSelected(new Set())
    await fetchPlos()
  } catch {
    setError('รวม Need เป็น PLO เดียวไม่สำเร็จ')
  } finally {
    setRunning(false)
  }
}
```

Render a checkbox per Need and the action bar, disabled until at least two are picked (one Need already becomes a PLO through the normal 1:1 path, so merging one is meaningless):

```tsx
{needs.map(n => (
  <label key={n.need_id} className="flex items-start gap-2 rounded-lg border border-gray-200 p-3">
    <input
      type="checkbox"
      checked={selected.has(n.need_id)}
      onChange={() => toggleNeed(n.need_id)}
      className="mt-1"
    />
    <span className="text-sm text-gray-800">{n.statement_th}</span>
  </label>
))}

<button
  onClick={mergeSelected}
  disabled={selected.size < 2 || running}
  className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:bg-gray-300"
>
  รวมเป็น PLO เดียว ({selected.size})
</button>
```

In `PloReport.tsx`, remove every reference to `domain`, `psychomotor_level`, and `krathwohl_level` (including any label maps keyed on them) and rename `source_cluster_ids` to `source_need_ids`.

- [ ] **Step 7: Run the full gate**

Run: `uv run pytest && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/`
Then: `cd frontend && npx tsc --noEmit -p tsconfig.json && npm run lint && npm run build`
Expected: all pass. `npm run lint` should report no new warnings beyond the pre-existing `Pipeline.tsx` exhaustive-deps one.

- [ ] **Step 8: Verify in the running app**

Run `.\scripts\start-dev.ps1`, then `cd frontend; npm run dev`. Open the Stage 3 page for a program with evidence, click run, and confirm: the skill table sorts by every column, rows expand to show a quote, the drop banner appears when skills were dropped, and tab 2 shows 6–10 Need cards.

- [ ] **Step 9: Commit**

```bash
git add -A src/curriculum_agent frontend tests
git commit -m "feat(ui): rebuild Stage 3 as a skill table plus Need cards

Raw skills become a sortable five-column table — Skill, Bloom's, KSEC,
stakeholder class, importance — because the designer's job on that tab is
scanning hundreds of rows for outliers, which cards cannot support. The
quoted evidence span and stakeholder type move to row expand.

Needs stay as cards: each is a sentence to read, and there are at most
ten. Renames the clusters router to needs and adds the raw-skill endpoint
the table needs."
```

---

### Task 8: Documentation sync

The skill directory is the canonical source for schemas and OBE rules, so it must not lag the code.

**Files:**
- Modify: `.claude/skills/curriculum-design-agent/SKILL.md`
- Modify: `.claude/skills/curriculum-design-agent/references/data-schemas.md`
- Modify: `.claude/skills/curriculum-design-agent/references/obe-principles.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the data-schemas reference**

In `references/data-schemas.md`: change `KSECCategory` to the five-value split, update `ExtractedSkill` (required `bloom_level`, `evidence_span_th`, no `skill_type`/`is_subject_specific`), replace the `SkillCluster` block with `Need`, update `PLO` (no `domain`/`psychomotor_level`/`krathwohl_level`, `source_need_ids`), and redraw the evidence-trail diagram:

```
StakeholderEvidence (raw)
  ↓ source_evidence_id + evidence_span_th (verified in code)
ExtractedSkill (per evidence item)
  ↓ member_skill_ids
Need (grouped skills, one KSEC tag, one sentence)
  ↓ source_need_ids
PLO (final artifact — agent scope ends here)
```

- [ ] **Step 2: Update the OBE reference**

In `references/obe-principles.md`: rewrite the "K/S/E/C vs Bloom domain" section for the GS/SS split, and mark the psychomotor (Dave) and affective (Krathwohl) sections as faculty reference for the YLO/CLO hand-off — the agent no longer models those scales.

- [ ] **Step 3: Update SKILL.md and CLAUDE.md**

In `SKILL.md`, update the pipeline list to six stages with `need_combination`, and change rule 1 to say the 6–10 constraint is enforced on Needs. In `CLAUDE.md`, update the pipeline description in the intro, immutable rule 6 (6–10 Needs → 6–10 PLOs one-to-one), rule 7 (skill extraction and need combination share one checkpoint), the "Where to find things" paths, and the common-pitfalls section (drop the "don't ask for as many PLOs as needed" pitfall's batch framing, add one about never clustering across KSEC buckets).

- [ ] **Step 4: Verify no stale references remain**

Run: `rg -n "SkillCluster|skill_type|psychomotor|krathwohl|source_cluster_ids|canonical_name" CLAUDE.md .claude/skills/`
Expected: only intentional mentions — the faculty-reference notes in `obe-principles.md`.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md .claude/skills/curriculum-design-agent
git commit -m "docs: sync skill references and CLAUDE.md to the Need-based pipeline"
```

---

## Verification

After Task 8, run the whole gate once more from a clean state:

```bash
uv run alembic upgrade head
uv run alembic heads          # exactly one head
uv run pytest
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
cd frontend && npx tsc --noEmit -p tsconfig.json && npm run lint && npm run build
```

Then exercise the pipeline end to end in the running app on a program with real `Data/` evidence: classify → extract → review both tabs → synthesize → report. Confirm 6–10 core Needs, 6–10 core PLOs, no PLO with an empty `source_need_ids`, and no Need holding two KSEC tags.
