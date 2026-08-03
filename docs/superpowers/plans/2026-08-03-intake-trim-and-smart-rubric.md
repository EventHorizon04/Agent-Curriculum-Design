# Intake Trim and SMART Rubric Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the ISCED name suggestion, the document-upload prefill, and the five institutional-direction metadata fields, then rewrite the SMART soft judge to the project's five-criterion rubric with R sourced from Needs instead of `vision_th`.

**Architecture:** The institution's direction already enters the pipeline as `institutional_direction` evidence and flows through skill → Need → PLO, so the metadata copies are redundant and R's institutional component is answerable from `Need.source_stakeholder_types` in pure code. Removing `vision_th` therefore costs nothing and makes the check deterministic. Separately, the soft judge's verdicts start reaching `SMARTCheck`, whose `achievable` and `timely` fields were hardcoded `True`.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLAlchemy 2 + Alembic, FastAPI, pytest (`asyncio_mode = "auto"`), React 19 + TypeScript + Tailwind, `uv`.

**Spec:** `docs/superpowers/specs/2026-08-03-intake-trim-and-smart-rubric-design.md` (commit 2262e29). Read it before Task 1.

## Global Constraints

- Type hints on every signature; `from __future__ import annotations` at the top of every module.
- `uv run ruff format src/ tests/`, `uv run ruff check src/ tests/`, and `uv run mypy src/` clean before each commit. Line limit 100 characters.
- Frontend: `cd frontend && npm run lint && npm run build` clean before the frontend commit. One pre-existing warning at `frontend/src/pages/Pipeline.tsx:221` is not yours.
- Tests use `asyncio_mode = "auto"`; never add `@pytest.mark.asyncio`.
- `loguru` for logging, never stdlib `logging`.
- Thai for student-facing strings and prompt text; code, comments, variable names, and log messages in English.
- Prompts live in `src/curriculum_agent/prompts/`, one file per prompt, behind typed builder functions.
- No hand-parsing of LLM JSON — always Instructor → Pydantic.
- Repository pattern for data access; stage-level repository mocks must stub **every** persistence call a stage makes.
- **Never stage or modify `src/curriculum_agent/config.py`.** It carries the user's own uncommitted edits and two pre-existing mypy errors at lines 32-33 (`light_model` / `heavy_model` redefined) which are expected and must remain. Those two are the only mypy errors permitted at the end.
- Do not use `git add -A` or `git commit -a`; stage the specific paths you edit.
- **Untouched by this plan:** the SMART hard checks in `smart_rules.py` and the retry loop's mechanics; `MIN_NEEDS = 6` as a warn-only floor with no upper cap; the KSEC bucketing invariant; the forbidden-word list; one Bloom verb per outcome; every PLO tracing to non-empty evidence; the two-stage `plo_synthesis` / `plo_report` split with two checkpoints; the agent stopping at PLO with no YLO/CLO; `exporters/` and its 501 routes.
- **Soft criteria never block.** Escalation reads hard-check failures only. Mapping soft verdicts onto `SMARTCheck` changes what `passed` reports, not what escalates.

---

## File Structure

**Modified — models and data layer**
- `src/curriculum_agent/models.py` — five fields and four model classes removed
- `src/curriculum_agent/data/orm.py` — five columns removed from `ProgramTable`
- `migrations/versions/<new>_drop_institutional_metadata.py` — one revision

**Modified — stages and prompts**
- `src/curriculum_agent/stages/intake.py` — shrinks to `run()` alone
- `src/curriculum_agent/prompts/smart_validator.py` — five-verdict rewrite
- `src/curriculum_agent/stages/plo_synthesis.py` — soft-judge wiring, `SMARTCheck` mapping, institutional-coverage warning

**Modified — API**
- `src/curriculum_agent/api/routes/programs.py` — two routes and one request model removed

**Deleted**
- `src/curriculum_agent/prompts/suggest_isced.py`
- `src/curriculum_agent/prompts/extract_metadata.py`
- `src/curriculum_agent/parsers/tika_parser.py`
- `tests/unit/test_intake_evidence.py`, `tests/unit/test_extract_metadata.py`

**Modified — frontend**
- `frontend/src/pages/Intake.tsx` — upload mode, ISCED suggestion, and five inputs removed

---

### Task 1: Remove the five fields and four model classes

**Files:**
- Modify: `src/curriculum_agent/models.py:140-215` (`ProgramCreateRequest`, `ProgramMetadata`, `ExtractedMetadata`, `MetadataExtractionResult`), and the `IscedSuggestion` / `SuggestedName` definitions
- Modify: `tests/conftest.py` (the `program_metadata` fixture)
- Test: `tests/unit/test_models.py`

**Interfaces:**
- Produces: `ProgramCreateRequest` and `ProgramMetadata` without `vision_th`, `mission_th`, `philosophy_th`, `institutional_identity_th`, `student_identity_th`. `ExtractedMetadata`, `MetadataExtractionResult`, `IscedSuggestion`, and `SuggestedName` no longer exist.
- Consumed by every later task in this plan.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_models.py`:

```python
def test_program_models_no_longer_carry_institutional_metadata():
    """The institution's direction lives in the evidence table now — a second copy
    on the program row would be a source of truth nobody keeps consistent."""
    from curriculum_agent.models import ProgramCreateRequest, ProgramMetadata

    gone = (
        "vision_th",
        "mission_th",
        "philosophy_th",
        "institutional_identity_th",
        "student_identity_th",
    )
    for field in gone:
        assert field not in ProgramCreateRequest.model_fields
        assert field not in ProgramMetadata.model_fields


def test_removed_model_classes_are_gone():
    import curriculum_agent.models as models

    for name in (
        "ExtractedMetadata",
        "MetadataExtractionResult",
        "IscedSuggestion",
        "SuggestedName",
    ):
        assert not hasattr(models, name), f"{name} should have been deleted"


def test_isced_code_is_still_validated_against_the_taxonomy():
    """The suggestion feature is gone but the code is still typed by hand, so the
    guard against an off-taxonomy value matters more, not less."""
    import pytest

    from curriculum_agent.models import ProgramCreateRequest

    with pytest.raises(ValueError, match="ISCED"):
        ProgramCreateRequest(
            name_th="วิทยาการคอมพิวเตอร์",
            name_en="Computer Science",
            field="Computer Science",
            isced_code="9999",
            degree_level="bachelor",
            duration_years=4,
            faculty="วิทยาศาสตร์",
            university="ทดสอบ",
            program_goals_th=["ผลิตบัณฑิตที่ทำงานได้"],
            program_objectives_th=["พัฒนาทักษะการเขียนโปรแกรม"],
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_models.py -q`
Expected: FAIL — the fields and classes still exist.

- [ ] **Step 3: Remove the fields and classes**

In `models.py`, delete from `ProgramCreateRequest` and from `ProgramMetadata` the five field declarations, and delete the `ExtractedMetadata`, `MetadataExtractionResult`, `IscedSuggestion`, and `SuggestedName` class definitions entirely. Leave `isced_code`, `field`, `name_th`, `name_en`, `program_goals_th`, `program_objectives_th`, and both `_validate_isced_code` validators exactly as they are.

Read the surrounding comments before deleting: any comment that explains a *retained* field's boundary rule by referring to a removed one must be reworded rather than left dangling.

- [ ] **Step 4: Update the shared fixture**

`tests/conftest.py`'s `program_metadata` fixture constructs `ProgramMetadata` with the five fields. Remove those arguments. Every stage test depends on this fixture, so this is where stragglers surface — expect other test files to fail after this step and leave them to Task 7 unless the failure is in `test_models.py`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_models.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/models.py tests/conftest.py tests/unit/test_models.py
git commit -m "refactor(models): drop the institutional-direction metadata fields"
```

---

### Task 2: ORM columns and the migration

**Files:**
- Modify: `src/curriculum_agent/data/orm.py:27-32`
- Create: `migrations/versions/<rev>_drop_institutional_metadata.py`
- Test: `tests/unit/test_migration_drop_institutional.py` (create)

**Interfaces:**
- Consumes: Task 1's model shape.
- Produces: `ProgramTable` without the five columns; one Alembic revision chaining from the current head.

- [ ] **Step 1: Find the current head**

Run: `uv run alembic heads`

Use the printed revision as `down_revision`. If it is not `b7c4e1a9f052`, use what it prints — do not guess.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_migration_drop_institutional.py`:

```python
"""The migration's shape, tested without a database.

The five columns are dropped, not renamed or backfilled: the content's new home is
the evidence table, and a program that had them converted keeps those evidence rows
untouched. downgrade() re-adds them nullable, because the original NOT NULL values
are not recoverable once dropped.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

DROPPED = (
    "vision_th",
    "mission_th",
    "philosophy_th",
    "institutional_identity_th",
    "student_identity_th",
)


@pytest.fixture(scope="module")
def migration() -> ModuleType:
    path = next(Path("migrations/versions").glob("*_drop_institutional_metadata.py"))
    spec = importlib.util.spec_from_file_location("drop_institutional", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_it_names_every_dropped_column(migration: ModuleType) -> None:
    assert set(migration.DROPPED_COLUMNS) == set(DROPPED)


def test_downgrade_restores_them_nullable(migration: ModuleType) -> None:
    source = Path(migration.__file__ or "").read_text(encoding="utf-8")
    downgrade = source.split("def downgrade()")[1]
    for column in DROPPED:
        assert column in downgrade, f"{column} is not restored by downgrade()"
    assert "nullable=True" in downgrade
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_migration_drop_institutional.py -q`
Expected: FAIL — `StopIteration` from the glob, since the migration does not exist.

- [ ] **Step 4: Update the ORM and write the migration**

In `orm.py`, delete the five `Mapped[...]` declarations from `ProgramTable` (`vision_th`, `mission_th`, `philosophy_th`, `institutional_identity_th`, `student_identity_th`).

Create `migrations/versions/c8d5f2a71b43_drop_institutional_metadata.py`:

```python
"""drop the institutional-direction metadata columns

The program's vision, mission, philosophy, and two identity statements now live in
the evidence table as stakeholder_type='institutional_direction' rows. Keeping a
second copy on the program row left two sources of truth with nothing reconciling
them, so the columns go.

No backfill: any program whose statements were previously converted already has the
evidence rows, and this migration does not touch them.

Revision ID: c8d5f2a71b43
Revises: <HEAD FROM STEP 1>
Create Date: 2026-08-03 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c8d5f2a71b43'
down_revision: Union[str, None] = '<HEAD FROM STEP 1>'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DROPPED_COLUMNS = (
    "vision_th",
    "mission_th",
    "philosophy_th",
    "institutional_identity_th",
    "student_identity_th",
)


def upgrade() -> None:
    for column in DROPPED_COLUMNS:
        op.drop_column("programs", column)


def downgrade() -> None:
    # Restored nullable: the original NOT NULL content is gone once dropped, and a
    # server_default of "" would fabricate a vision statement rather than admit the
    # loss.
    for column in DROPPED_COLUMNS:
        op.add_column("programs", sa.Column(column, sa.Text(), nullable=True))
```

Replace `<HEAD FROM STEP 1>` with the revision Step 1 printed.

- [ ] **Step 5: Run the test and the round trip**

Run: `uv run pytest tests/unit/test_migration_drop_institutional.py -q`
Expected: PASS.

Then, with the Docker services up (`docker compose ps` to check; `.\scripts\start-dev.ps1` if they are not, and if you cannot start them say so and skip this): `uv run alembic upgrade head`, then `uv run alembic downgrade -1`, then `uv run alembic upgrade head`. Report the real output. If the database holds a program row, note that the round trip preserved it apart from the dropped columns.

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/data/orm.py migrations/versions/c8d5f2a71b43_drop_institutional_metadata.py tests/unit/test_migration_drop_institutional.py
git commit -m "feat(db): drop the institutional-direction program columns"
```

---

### Task 3: Remove the ISCED suggestion and the document-upload prefill

**Files:**
- Modify: `src/curriculum_agent/stages/intake.py` (shrinks to `run()` alone)
- Modify: `src/curriculum_agent/api/routes/programs.py:75-152`
- Delete: `src/curriculum_agent/prompts/suggest_isced.py`, `src/curriculum_agent/prompts/extract_metadata.py`, `src/curriculum_agent/parsers/tika_parser.py`, `tests/unit/test_intake_evidence.py`, `tests/unit/test_extract_metadata.py`
- Test: `tests/unit/test_api_programs.py`

**Interfaces:**
- Consumes: Task 1's model shape.
- Produces: `stages/intake` exporting only `run`. `POST /programs/suggest-isced` and `POST /programs/extract-metadata` no longer exist.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_api_programs.py`:

```python
def test_suggest_isced_route_is_gone() -> None:
    resp = client.post("/programs/suggest-isced", json={
        "name_th": "วิทยาการคอมพิวเตอร์", "name_en": "Computer Science", "field": "CS",
    })
    assert resp.status_code == 404


def test_extract_metadata_route_is_gone() -> None:
    resp = client.post("/programs/extract-metadata", files={"file": ("a.pdf", b"x")})
    assert resp.status_code == 404


def test_intake_stage_exports_only_run() -> None:
    """The stage kept helpers for two features that no longer exist, plus a
    conversion whose source fields are gone."""
    from curriculum_agent.stages import intake

    for name in (
        "suggest_isced",
        "extract_metadata_from_text",
        "build_institutional_evidence",
        "INSTITUTIONAL_FIELDS",
        "grounding_ratio",
        "low_grounding_fields",
    ):
        assert not hasattr(intake, name), f"{name} should have been deleted"
```

Use whatever `client` fixture or module-level `TestClient` that file already defines rather than creating a second one.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_api_programs.py -q`
Expected: FAIL — both routes answer something other than 404 and the helpers still exist.

- [ ] **Step 3: Shrink the intake stage**

Replace `src/curriculum_agent/stages/intake.py` in full:

```python
from __future__ import annotations

from loguru import logger

from curriculum_agent.data.repositories import EvidenceRepository, ProgramRepository
from curriculum_agent.graph import AgentState
from curriculum_agent.models import ProgramMetadata


async def run(state: AgentState) -> AgentState:
    """Stage 0: validate ProgramMetadata, persist to Postgres, load evidence into state.

    The stage used to convert the program's vision, mission, philosophy, and two
    identity statements into `institutional_direction` evidence. Those metadata
    fields are gone: the designer now enters the statements directly as evidence at
    the Stakeholder Needs stage, so there is nothing left to convert and no second
    copy to keep consistent.
    """
    metadata_dict = state.get("metadata")
    if not metadata_dict:
        raise ValueError("AgentState missing 'metadata' — cannot run intake stage")
    metadata = ProgramMetadata.model_validate(metadata_dict)
    logger.info(f"Intake: program_id={metadata.program_id}, field={metadata.field}")

    await ProgramRepository().upsert(metadata)

    evidence_items = await EvidenceRepository().list_by_program(metadata.program_id)
    logger.info(f"Intake: loaded {len(evidence_items)} evidence items for classification")

    state["raw_evidence"] = [e.model_dump(mode="json") for e in evidence_items]
    state["current_stage"] = "intake"
    return state
```

- [ ] **Step 4: Remove the routes and the dead modules**

In `api/routes/programs.py`, delete the `extract_metadata` route (lines ~75-128), the `SuggestIscedRequest` class, and the `suggest_isced_route` route (lines ~131-152). Then clean the imports: `extract_metadata_from_text` and `suggest_isced` are gone from the `stages.intake` import, and `MetadataExtractionResult` / `IscedSuggestion` from the models import. `UploadFile`, `Request`, `asyncio`, and `tempfile` may now be unused — remove only what genuinely is, checking each against the rest of the file (`create_program` still takes a `Request`).

```bash
git rm src/curriculum_agent/prompts/suggest_isced.py src/curriculum_agent/prompts/extract_metadata.py src/curriculum_agent/parsers/tika_parser.py tests/unit/test_intake_evidence.py tests/unit/test_extract_metadata.py
```

`tika_parser.py` has exactly two importers — the route you just deleted and `test_extract_metadata.py` — so it goes. `parsers/mko1_parser.py` is unrelated and stays; confirm it does not import `tika_parser` before you delete it.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_api_programs.py -q`
Expected: PASS. Other files stay red until Task 7.

- [ ] **Step 6: Commit**

```bash
git add -u src/curriculum_agent tests/unit
git add src/curriculum_agent/stages/intake.py src/curriculum_agent/api/routes/programs.py tests/unit/test_api_programs.py
git commit -m "refactor(intake): remove the ISCED suggestion and the document-upload prefill"
```

---

### Task 4: The five-verdict SMART soft judge prompt

**Files:**
- Modify: `src/curriculum_agent/prompts/smart_validator.py` (full rewrite)
- Test: `tests/unit/test_smart_soft_judge_prompt.py` (create)

**Interfaces:**
- Produces: `build_smart_soft_judge_prompt(statement_th: str, degree_level: str, duration_years: int, need_statements_th: list[str]) -> list[dict[str, str]]`, requesting the JSON keys `specific_object_ok`, `measurable_ok`, `achievable_ok`, `relevant_needs_ok`, `time_bound_ok`, `notes_th`.
- Consumed by Task 5.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_smart_soft_judge_prompt.py`:

```python
from __future__ import annotations

from curriculum_agent.prompts.smart_validator import build_smart_soft_judge_prompt

_NEEDS = ["ตลาดต้องการผู้ที่วิเคราะห์ข้อมูลขนาดใหญ่ได้", "ตลาดต้องการผู้ที่สื่อสารผลวิเคราะห์ได้"]


def _built() -> str:
    messages = build_smart_soft_judge_prompt(
        "วิเคราะห์ข้อมูลขนาดใหญ่เพื่อเสนอแนวทางเชิงธุรกิจได้",
        "bachelor",
        4,
        _NEEDS,
    )
    return "\n".join(m["content"] for m in messages)


def test_all_five_verdicts_are_requested() -> None:
    system = build_smart_soft_judge_prompt("PLO", "bachelor", 4, _NEEDS)[0]["content"]

    for key in (
        "specific_object_ok",
        "measurable_ok",
        "achievable_ok",
        "relevant_needs_ok",
        "time_bound_ok",
    ):
        assert key in system


def test_the_needs_reach_the_user_message() -> None:
    """R is judged against the Needs the PLO cites, so they have to be in the
    prompt — this is what replaces the old vision-text comparison."""
    user = build_smart_soft_judge_prompt("PLO", "bachelor", 4, _NEEDS)[1]["content"]

    for need in _NEEDS:
        assert need in user


def test_the_qualification_level_and_duration_reach_the_prompt() -> None:
    """A is about plausibility for the level AND within the time available."""
    built = _built()

    assert "bachelor" in built
    assert "4" in built


def test_vision_appears_nowhere() -> None:
    """The institutional component of R is settled in code from
    Need.source_stakeholder_types, not by asking a model to compare paragraphs."""
    assert "วิสัยทัศน์" not in _built()


def test_measurable_asks_about_real_assessment_not_just_wording() -> None:
    system = build_smart_soft_judge_prompt("PLO", "bachelor", 4, _NEEDS)[0]["content"]

    assert "ประเมิน" in system


def test_time_bound_defaults_to_true_in_the_instruction() -> None:
    """A PLO that says nothing about time is correct by convention; only a
    conflicting horizon is a finding."""
    system = build_smart_soft_judge_prompt("PLO", "bachelor", 4, _NEEDS)[0]["content"]

    assert "สิ้นสุดหลักสูตร" in system
    assert "true" in system.lower()


def test_an_empty_need_list_leaves_no_dangling_header() -> None:
    user = build_smart_soft_judge_prompt("PLO", "bachelor", 4, [])[1]["content"]

    assert "Need ที่อ้างถึง:" not in user
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_smart_soft_judge_prompt.py -q`
Expected: FAIL — `TypeError` on the new signature.

- [ ] **Step 3: Rewrite the prompt**

Replace `src/curriculum_agent/prompts/smart_validator.py` in full:

```python
from __future__ import annotations


def build_smart_soft_judge_prompt(
    statement_th: str,
    degree_level: str,
    duration_years: int,
    need_statements_th: list[str],
) -> list[dict[str, str]]:
    """Light-model soft checks against the project's SMART rubric.

    Five verdicts, none of which block: the hard checks in smart_rules.py drive
    escalation on their own. What the model is asked reflects the rubric's own
    definitions — Measurable is about whether a real assessment instrument could
    observe the outcome, not merely whether a forbidden word is absent, and
    Relevant is judged against the Needs the PLO cites rather than against a vision
    statement. The institutional half of Relevant is settled in code from
    Need.source_stakeholder_types.

    Time-bound defaults to true: a PLO carries "by the end of the program" by
    convention, so silence about time is correct and only a conflicting horizon is
    a finding.
    """
    system = (
        "คุณเป็นผู้ตรวจสอบคุณภาพ PLO ตามเกณฑ์ SMART ประเมิน 5 ข้อ ตอบเป็น JSON:\n"
        "specific_object_ok: กรรมของกริยาเจาะจง ระบุพฤติกรรม/ทักษะ/สมรรถนะที่ชัดเจน "
        "ไม่ใช่คำกว้างเช่น 'ความรู้' 'ทักษะที่จำเป็น'\n"
        "measurable_ok: สังเกตได้ และประเมินได้จริงด้วยเครื่องมือทางการศึกษา "
        "(ข้อสอบ ชิ้นงาน การปฏิบัติ แฟ้มผลงาน) — การไม่มีคำห้ามยังไม่นับว่าวัดได้\n"
        "achievable_ok: ระดับ Bloom สมเหตุสมผลกับระดับคุณวุฒิ และบรรลุได้ภายในระยะเวลาหลักสูตร\n"
        "relevant_needs_ok: ตอบสนองความต้องการของผู้มีส่วนได้ส่วนเสียที่อ้างถึงจริง "
        "และสะท้อนสมรรถนะที่ตลาดแรงงานต้องการ\n"
        "time_bound_ok: ค่าเริ่มต้นเป็น true — PLO ถือว่าบรรลุ 'เมื่อสิ้นสุดหลักสูตร' โดยปริยาย "
        "ให้ตอบ false เฉพาะเมื่อข้อความระบุกรอบเวลาอื่นที่ขัดกัน เช่น 'ภายในปีที่ 2'\n"
        "notes_th: เหตุผลสั้นๆ สำหรับข้อที่ไม่ผ่าน"
    )
    user = f"PLO: {statement_th}\nระดับคุณวุฒิ: {degree_level}\nระยะเวลาหลักสูตร: {duration_years} ปี"
    if need_statements_th:
        joined = "\n".join(f"- {n}" for n in need_statements_th)
        user += f"\nNeed ที่อ้างถึง:\n{joined}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_smart_soft_judge_prompt.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/curriculum_agent/prompts/smart_validator.py tests/unit/test_smart_soft_judge_prompt.py
git commit -m "feat(smart): rewrite the soft judge to the five-criterion rubric"
```

---

### Task 5: Wire the soft judge into plo_synthesis

**Files:**
- Modify: `src/curriculum_agent/stages/plo_synthesis.py:103-113` (`_SmartSoftJudge`), `:184-216` (the judge call and `SMARTCheck`), and `run()` for the coverage warning
- Test: `tests/unit/test_smart_retry_loop.py`, `tests/unit/test_plo_count_policy.py`

**Interfaces:**
- Consumes: Task 4's builder; `Need.source_stakeholder_types` (already present).
- Produces: `_SmartSoftJudge` with five boolean fields all defaulting `True`; `_ensure_smart` gaining a `need_statements_th: list[str]` parameter after `authoritative_need_ids`; `soft_flags` values `S_object`, `M_assessable`, `A_level`, `R_needs`, `T_horizon`; `SMARTCheck` reflecting soft verdicts; a program-level institutional-coverage warning in `run()`.

**Existing shape you are changing** — `_ensure_smart(draft, known_need_ids, metadata, authoritative_need_ids, plo_id)` at `plo_synthesis.py:140`, called once at `:255` from `synthesize_from_needs`, which already holds `needs: list[Need]`. The new parameter is sourced there as `[n.statement_th for n in needs]` — do not re-query the repository for something the caller already has.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_smart_retry_loop.py` already has `META`, `_draft()`, and `_SOFT_OK`. Note that `META` currently passes `vision_th` / `mission_th` / `philosophy_th`, which Task 1 removed — strip those three arguments as part of this step, and update `_SOFT_OK` to the new field names:

```python
_SOFT_OK = ps._SmartSoftJudge()  # every verdict defaults True
```

Then append:

```python
async def test_a_soft_failure_reaches_smart_check_without_escalating():
    """SMARTCheck.achievable and .timely were hardcoded True and the judge's
    verdicts never reached SMARTCheck at all, so `passed` reported success for a
    flagged PLO. A soft failure must show in SMARTCheck and still not escalate."""
    judge = ps._SmartSoftJudge(measurable_ok=False, notes_th="ประเมินด้วยเครื่องมือใดไม่ชัด")

    with patch.object(ps, "complete_light", AsyncMock(return_value=judge)):
        out = await ps._ensure_smart(
            _draft("วิเคราะห์ข้อมูลทางสถิติได้"), {"c1"}, META, ["c1"], ["ตลาดต้องการ"], "PLO1"
        )

    assert out.smart_check.measurable is False
    assert out.smart_check.passed is False
    assert out.escalated is False
    assert "M_assessable" in out.soft_flags


async def test_a_judge_exception_leaves_every_soft_verdict_true():
    """An LLM hiccup must degrade toward 'not flagged' rather than falsely flagging
    sound work."""
    with patch.object(ps, "complete_light", AsyncMock(side_effect=RuntimeError("boom"))):
        out = await ps._ensure_smart(
            _draft("วิเคราะห์ข้อมูลทางสถิติได้"), {"c1"}, META, ["c1"], ["ตลาดต้องการ"], "PLO1"
        )

    assert out.soft_flags == []
    assert out.smart_check.achievable is True
    assert out.smart_check.timely is True


async def test_soft_criteria_never_escalate_even_when_all_five_fail():
    """Escalation reads hard-check failures alone — an immutable project rule."""
    judge = ps._SmartSoftJudge(
        specific_object_ok=False,
        measurable_ok=False,
        achievable_ok=False,
        relevant_needs_ok=False,
        time_bound_ok=False,
    )

    with patch.object(ps, "complete_light", AsyncMock(return_value=judge)):
        out = await ps._ensure_smart(
            _draft("วิเคราะห์ข้อมูลทางสถิติได้"), {"c1"}, META, ["c1"], ["ตลาดต้องการ"], "PLO1"
        )

    assert out.escalated is False
    assert out.retry_count == 0
    assert sorted(out.soft_flags) == sorted(
        ["S_object", "M_assessable", "A_level", "R_needs", "T_horizon"]
    )


async def test_the_needs_statements_reach_the_judge_prompt():
    """R is judged against the Needs the PLO cites, so the statements must travel
    from synthesize_from_needs into the prompt."""
    seen: list[list[dict[str, str]]] = []

    async def capture(model, messages, **kw):  # noqa: ANN001, ANN003
        seen.append(messages)
        return ps._SmartSoftJudge()

    with patch.object(ps, "complete_light", side_effect=capture):
        await ps._ensure_smart(
            _draft("วิเคราะห์ข้อมูลทางสถิติได้"),
            {"c1"},
            META,
            ["c1"],
            ["ตลาดต้องการผู้ที่วิเคราะห์ข้อมูลขนาดใหญ่ได้"],
            "PLO1",
        )

    assert "ตลาดต้องการผู้ที่วิเคราะห์ข้อมูลขนาดใหญ่ได้" in seen[0][1]["content"]
```

And in `tests/unit/test_plo_count_policy.py`:

```python
async def test_warns_when_no_plo_traces_to_the_institution(
    program_metadata: ProgramMetadata,
):
    """Institutional coverage is a property of the PLO set, not of each PLO, so it
    is checked once after synthesis rather than flagged nine times."""
    needs = [_need(f"N{i}") for i in range(1, 7)]  # none carry institutional_direction
    p1, p2, p3 = _patch_llm(needs)

    with p1, p2, p3, patch.object(ps, "logger") as mock_logger:
        await ps.run({
            "program_id": "cs-test",
            "metadata": program_metadata.model_dump(mode="json"),
            "needs": [n.model_dump(mode="json") for n in needs],
        })

    warnings = [c.args[0] for c in mock_logger.warning.call_args_list if "institution" in c.args[0]]
    assert len(warnings) == 1


async def test_does_not_warn_when_a_need_carries_institutional_direction(
    program_metadata: ProgramMetadata,
):
    needs = [_need(f"N{i}") for i in range(1, 7)]
    needs[0] = needs[0].model_copy(
        update={"source_stakeholder_types": [StakeholderType.INSTITUTIONAL_DIRECTION]}
    )
    p1, p2, p3 = _patch_llm(needs)

    with p1, p2, p3, patch.object(ps, "logger") as mock_logger:
        await ps.run({
            "program_id": "cs-test",
            "metadata": program_metadata.model_dump(mode="json"),
            "needs": [n.model_dump(mode="json") for n in needs],
        })

    warnings = [c.args[0] for c in mock_logger.warning.call_args_list if "institution" in c.args[0]]
    assert warnings == []
```

`_need()` in `test_plo_count_policy.py` builds a `Need` without `source_stakeholder_types`, which defaults to an empty list — that is what makes the first case's "no institutional coverage" premise true without extra setup. Import `StakeholderType` there.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_smart_retry_loop.py tests/unit/test_plo_count_policy.py -q`
Expected: FAIL — `_SmartSoftJudge` has no `measurable_ok`, and no coverage warning exists.

- [ ] **Step 3: Widen `_SmartSoftJudge` and map it onto `SMARTCheck`**

Replace `_SmartSoftJudge` with:

```python
class _SmartSoftJudge(BaseModel):
    """The light model's soft verdicts. Every field defaults true so a failed judge
    call degrades toward 'not flagged' rather than flagging sound work."""

    specific_object_ok: bool = True
    measurable_ok: bool = True
    achievable_ok: bool = True
    relevant_needs_ok: bool = True
    time_bound_ok: bool = True
    notes_th: str | None = None
```

Replace the judge call and `SMARTCheck` construction (currently `:184-216`) with:

```python
    soft_flags: list[str] = []
    judge = _SmartSoftJudge()
    try:
        judge = await complete_light(
            _SmartSoftJudge,
            build_smart_soft_judge_prompt(
                draft.statement_th,
                metadata.degree_level,
                metadata.duration_years,
                need_statements_th,
            ),
        )
    except Exception as exc:
        # Keep the all-true default: a hiccup must not manufacture soft flags.
        logger.warning(f"  Soft judge failed for PLO {plo_id}: {exc}")

    for ok, flag in (
        (judge.specific_object_ok, "S_object"),
        (judge.measurable_ok, "M_assessable"),
        (judge.achievable_ok, "A_level"),
        (judge.relevant_needs_ok, "R_needs"),
        (judge.time_bound_ok, "T_horizon"),
    ):
        if not ok:
            soft_flags.append(flag)

    # Soft verdicts reach SMARTCheck so `passed` stops reporting success for a
    # flagged outcome. They still do not escalate — that reads `fails` alone.
    smart = SMARTCheck(
        specific=HardCriterion.S_VERB not in fails and judge.specific_object_ok,
        measurable=HardCriterion.M_FORBIDDEN not in fails and judge.measurable_ok,
        achievable=judge.achievable_ok,
        relevant=HardCriterion.R_EVIDENCE not in fails and judge.relevant_needs_ok,
        timely=judge.time_bound_ok,
        notes_th=judge.notes_th,
    )
```

Add the parameter to `_ensure_smart`'s signature after `authoritative_need_ids`:

```python
async def _ensure_smart(
    draft: _PLODraft,
    known_need_ids: set[str],
    metadata: ProgramMetadata,
    authoritative_need_ids: list[str],
    need_statements_th: list[str],
    plo_id: str,
) -> _SmartOutcome:
```

and pass it at the call site in `synthesize_from_needs` (`plo_synthesis.py:255`):

```python
    outcome = await _ensure_smart(
        response.plo,
        known_need_ids,
        metadata,
        authoritative_need_ids,
        [n.statement_th for n in needs],
        plo_id,
    )
```

Inside the judge call, use `need_statements_th` rather than reaching for a `needs` list that is not in scope there.

- [ ] **Step 4: Add the coverage warning to `run()`**

After the existing `MIN_NEEDS` core-count warning in `run()`, add:

```python
    if not any(
        StakeholderType.INSTITUTIONAL_DIRECTION in n.source_stakeholder_types for n in all_needs
    ):
        logger.warning(
            "no PLO traces to the institution's own direction — add วิสัยทัศน์/พันธกิจ "
            "evidence at the Stakeholder Needs stage, or accept at the checkpoint"
        )
```

Use whatever name the function already has for its resolved `Need` objects instead of `all_needs`, and import `StakeholderType` if it is not already imported.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_smart_retry_loop.py tests/unit/test_plo_count_policy.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/stages/plo_synthesis.py tests/unit/test_smart_retry_loop.py tests/unit/test_plo_count_policy.py
git commit -m "feat(smart): map soft verdicts onto SMARTCheck, warn on institutional coverage"
```

---

### Task 6: Trim the intake form

**Files:**
- Modify: `frontend/src/pages/Intake.tsx` (529 lines; expect a substantial reduction)

**Interfaces:**
- Consumes: the program-creation payload from Task 1 (five fields gone) and the routes removed in Task 3.

- [ ] **Step 1: Read the file in full before deleting anything**

`Intake.tsx` holds three interleaved features. What goes:

- `entryMode` state and the manual/upload mode switch, `switchMode`, the file input, `docFile`, the `POST /programs/extract-metadata` call, and the prefill/low-grounding display (`FIELD_LABELS` for the extracted fields, the grounding warnings).
- `iscedResult`, `iscedCode`, `iscedLoading`, `iscedError`, the `POST /programs/suggest-isced` call, the suggestion card, and the accept-suggestion handler.
- The five form inputs and their `form` state entries: `vision_th`, `mission_th`, `philosophy_th`, `institutional_identity_th`, `student_identity_th`, plus their required-field validation entries.

What stays: `name_th`, `name_en`, `field`, `isced_code` as a hand-typed input, `degree_level`, `duration_years`, `faculty`, `university`, `program_goals_th`, `program_objectives_th`, and the existing submit flow, loading state, error display, and success navigation.

- [ ] **Step 2: Add a pointer to where the statements now go**

The designer needs to know the vision did not simply vanish. Add one short line near the form's heading, in the page's existing voice:

```tsx
<p className="mt-1 text-xs text-gray-500">
  วิสัยทัศน์ พันธกิจ และอัตลักษณ์ ให้บันทึกเป็นหลักฐานที่หน้า Stakeholder Needs
  (ประเภท "วิสัยทัศน์/พันธกิจ/อัตลักษณ์")
</p>
```

- [ ] **Step 3: Verify**

Run: `cd frontend && npm run lint && npm run build`
Expected: 0 errors, no new warnings. The pre-existing `Pipeline.tsx:221` warning remains.

Then grep the frontend for stragglers: no reference to `extract-metadata`, `suggest-isced`, `vision_th`, `mission_th`, `philosophy_th`, `institutional_identity_th`, `student_identity_th`, `IscedSuggestion`, or `MetadataExtractionResult` may remain in `frontend/src`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Intake.tsx
git commit -m "feat(ui): trim intake to program metadata only"
```

---

### Task 7: Test sweep and documentation

**Files:**
- Modify: whatever remains red, plus `CLAUDE.md` and `.claude/skills/curriculum-design-agent/**`

- [ ] **Step 1: Bring the suite green**

Run: `uv run pytest -q`

Expected red files after Tasks 1-6, from the `program_metadata` fixture change and the removed helpers: `tests/integration/test_end_to_end.py`, `tests/integration/test_stage_3_plo.py`, `tests/unit/test_state_safety.py`, `tests/unit/test_designer_note.py`, and anything else constructing `ProgramMetadata` or patching a deleted function. Treat this list as a starting point, not the whole set.

Two rules, both load-bearing:

1. **Fix tests to match the new design, never weaken them to pass.** A test whose premise is gone (it covered the upload prefill, the ISCED suggestion, or the metadata→evidence conversion) is deleted, and you say so. A test whose premise survives but whose fixture is stale keeps every assertion.
2. Anything you change substantially must still fail when its production line is reverted. Spot-check the ones you touch most.

- [ ] **Step 2: Run the full gate**

```bash
uv run ruff format src/ tests/
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest -q
```

Only the two `config.py:32-33` errors may remain in mypy.

- [ ] **Step 3: Update the documentation**

`CLAUDE.md` — the intake stage no longer collects vision/mission/philosophy or offers upload/suggestion; check `## Project layout` for the deleted modules; add a pitfall recording that the institution's direction is evidence, not metadata, and that R's institutional component is checked from `Need.source_stakeholder_types` rather than a text comparison.

`.claude/skills/curriculum-design-agent/SKILL.md` — pipeline step 1 (intake's inputs), and rule 5's SMART description now covers five soft verdicts.

`references/obe-principles.md` — replace the SMART rubric text with the project's five definitions as the spec states them, keeping the forbidden-word list and the hard/soft split intact. Record that R has three components and that the institutional one is settled structurally.

`references/prompts.md` — delete the `suggest_isced` and `extract_metadata` sections; rewrite the soft-judge section for the new signature and five verdicts.

`references/data-schemas.md` — `ProgramMetadata` loses five fields; `SMARTCheck`'s fields now carry soft verdicts rather than being hardcoded.

- [ ] **Step 4: Commit**

```bash
git add -u tests/ CLAUDE.md .claude/skills/curriculum-design-agent/
git commit -m "test+docs: sweep the suite and document the intake trim and SMART rubric"
```

---

## Verification checklist

- [ ] `uv run pytest -q` green
- [ ] `uv run alembic upgrade head` → `downgrade -1` → `upgrade head` clean
- [ ] `POST /programs/` succeeds with a payload carrying none of the five fields
- [ ] `POST /programs/suggest-isced` and `POST /programs/extract-metadata` return 404
- [ ] No reference anywhere in `src/`, `tests/`, or `frontend/src` to the five field names, `IscedSuggestion`, `MetadataExtractionResult`, or `tika_parser`
- [ ] A PLO whose soft judge fails one criterion has that criterion False in `smart_check` and is not escalated
- [ ] Synthesizing with no institutional Need logs exactly one coverage warning
