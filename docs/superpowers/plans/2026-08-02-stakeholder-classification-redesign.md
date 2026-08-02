# Stakeholder Classification Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move need/want classification from the evidence item to the skill, derive `requirement` in code from a 15-value external/internal stakeholder taxonomy, turn the program's own vision/mission/identity into requirement evidence, and simplify KSEC and `plo_report` accordingly.

**Architecture:** Classification stops being an LLM judgement. `requirement` is a lookup on `StakeholderType`; `need`/`want` are decided per skill after every evidence item is extracted, because frequency is a cross-evidence property; `unclassified` comes from an `is_field_relevant` flag the extraction model already has the context to set. `demand_score` becomes weighted frequency over evidence weights derived from the external/internal split.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLAlchemy 2 + Alembic, FastAPI, pytest (`asyncio_mode = "auto"`), React 19 + TypeScript + Tailwind, `uv` for dependencies.

**Spec:** `docs/superpowers/specs/2026-08-02-stakeholder-classification-redesign-design.md` (commit 2be6d7d). Read it before Task 1.

## Global Constraints

- Every function signature carries type hints; every module starts with `from __future__ import annotations`.
- `uv run ruff format src/ tests/`, `uv run ruff check src/ tests/`, and `uv run mypy src/` must all be clean before each commit. Line limit is 100 characters.
- Frontend: `cd frontend && npm run lint && npm run build` clean before each frontend commit. One pre-existing warning in `Pipeline.tsx:221` (`react-hooks/exhaustive-deps`) is not yours — leave it.
- Tests use `asyncio_mode = "auto"`; never add `@pytest.mark.asyncio`.
- Logging through `loguru` only; never import the stdlib `logging`.
- Thai only for student-facing strings. Code, comments, variable names, log messages: English.
- Prompts live in `src/curriculum_agent/prompts/`, one file per prompt, returned by typed builder functions. Never inline a prompt in stage code.
- No hand-parsing of LLM JSON — always Instructor → Pydantic.
- Stage-level repository mocks must stub **every** persistence call the stage makes, not just the one you are testing. `intake` gains an evidence write in Task 5; `stakeholder_needs`, `skill_extraction`, and `need_combination` each call both `delete_by_program` and `bulk_insert`.
- Do not touch: the SMART gate, `MIN_NEEDS = 6` (warn-only floor), the KSEC bucketing invariant (clustering never crosses a bucket), or the agent's scope boundary at PLO. Never re-add YLO/CLO.
- `ProgramContext.professional_council`, `.accreditation_body`, `.subject_benchmark_ref` are program-metadata fields, unrelated to the `StakeholderType` members with similar names. Do not touch them.
- Branch: work on `main` (this project's convention). Commit after each task.

---

## File Structure

**Modified — models and data layer**
- `src/curriculum_agent/models.py` — enums, classification vocabularies, `STAKEHOLDER_GROUP`, field changes on `ExtractedSkill` / `Need` / `PLO`
- `src/curriculum_agent/data/orm.py` — new and dropped columns
- `migrations/versions/<new>_stakeholder_classification_redesign.py` — one revision, 6 steps

**Modified — stages**
- `src/curriculum_agent/stages/stakeholder_needs.py` — LLM classification deleted, becomes a lookup
- `src/curriculum_agent/stages/intake.py` — writes institutional-direction evidence
- `src/curriculum_agent/stages/skill_extraction.py` — skill-level classification, provenance
- `src/curriculum_agent/stages/demand.py` — weighted-frequency rewrite
- `src/curriculum_agent/stages/need_grouping.py` — EC bucketing, Need tag resolution
- `src/curriculum_agent/stages/need_combination.py` — new scoring inputs, `source_stakeholder_types`
- `src/curriculum_agent/stages/plo_report.py` — assembly only, no LLM
- `src/curriculum_agent/stages/plo_synthesis.py` — drops `is_subject_specific`

**Modified — prompts and API**
- `src/curriculum_agent/prompts/extract_skills.py` — field context + `is_field_relevant` + 4-value KSEC
- `src/curriculum_agent/api/routes/evidence.py` — SSE classify loop without an LLM
- `src/curriculum_agent/api/routes/plos.py` — drops the classification write-back

**Deleted**
- `src/curriculum_agent/prompts/classify_evidence.py`
- `src/curriculum_agent/prompts/plo_classify.py`

**Created — frontend**
- `frontend/src/constants/stakeholder.ts` — the single source for labels, grouping, colours

**Modified — frontend**
- `frontend/src/pages/StakeholderNeeds.tsx`, `PloReport.tsx`, `PloSynthesis.tsx`
- `frontend/src/pages/components/SkillTable.tsx`, `NeedCard.tsx`

---

### Task 1: Stakeholder taxonomy and classification vocabularies

**Files:**
- Modify: `src/curriculum_agent/models.py:14-23` (enum), `:185`
- Test: `tests/unit/test_models.py`, `tests/unit/test_evidence_classification.py` (create)

**Interfaces:**
- Produces: `StakeholderGroup`, the 15-member `StakeholderType`, `STAKEHOLDER_GROUP: dict[StakeholderType, StakeholderGroup]`, `REQUIREMENT_TYPES: frozenset[StakeholderType]`, `EvidenceClassification = Literal["requirement", "general"]`, `SkillClassification = Literal["requirement", "need", "want", "unclassified"]`, and `classify_evidence_type(t: StakeholderType) -> EvidenceClassification`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_models.py`:

```python
def test_every_stakeholder_type_has_a_group():
    """A type added without a STAKEHOLDER_GROUP entry must fail loudly here,
    not default silently to internal at the weight table."""
    from curriculum_agent.models import STAKEHOLDER_GROUP, StakeholderType

    assert set(STAKEHOLDER_GROUP) == set(StakeholderType)


def test_external_and_internal_membership():
    from curriculum_agent.models import STAKEHOLDER_GROUP, StakeholderGroup, StakeholderType

    assert STAKEHOLDER_GROUP[StakeholderType.EMPLOYER] is StakeholderGroup.EXTERNAL
    assert STAKEHOLDER_GROUP[StakeholderType.PROFESSIONAL_COUNCIL] is StakeholderGroup.EXTERNAL
    assert STAKEHOLDER_GROUP[StakeholderType.FACULTY] is StakeholderGroup.INTERNAL
    assert (
        STAKEHOLDER_GROUP[StakeholderType.INSTITUTIONAL_DIRECTION] is StakeholderGroup.INTERNAL
    )


def test_deleted_stakeholder_types_are_gone():
    from curriculum_agent.models import StakeholderType

    values = {t.value for t in StakeholderType}
    assert values.isdisjoint(
        {"accreditation_body", "university", "subject_benchmark", "peer_program"}
    )
    assert len(values) == 15
```

Create `tests/unit/test_evidence_classification.py`:

```python
from __future__ import annotations

from curriculum_agent.models import StakeholderType
from curriculum_agent.stages.stakeholder_needs import classify_evidence_type


def test_professional_council_is_a_requirement():
    assert classify_evidence_type(StakeholderType.PROFESSIONAL_COUNCIL) == "requirement"


def test_institutional_direction_is_a_requirement():
    assert classify_evidence_type(StakeholderType.INSTITUTIONAL_DIRECTION) == "requirement"


def test_every_other_type_is_general():
    others = [
        t
        for t in StakeholderType
        if t
        not in {StakeholderType.PROFESSIONAL_COUNCIL, StakeholderType.INSTITUTIONAL_DIRECTION}
    ]
    assert others, "expected non-requirement types to exist"
    assert all(classify_evidence_type(t) == "general" for t in others)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_models.py tests/unit/test_evidence_classification.py -q`
Expected: FAIL — `ImportError: cannot import name 'STAKEHOLDER_GROUP'` and `cannot import name 'classify_evidence_type'`.

- [ ] **Step 3: Replace the enum and add the vocabularies**

In `src/curriculum_agent/models.py`, replace `class StakeholderType` (lines 14-23) with:

```python
class StakeholderGroup(StrEnum):
    """Whether a stakeholder speaks from outside the institution or inside it.

    External input describes the labour market the graduate enters; internal
    input describes what the institution intends to be. Both matter, and the
    demand weighting treats them differently — external requirement input
    outranks internal, and both outrank ordinary opinion.
    """

    EXTERNAL = "external"
    INTERNAL = "internal"


class StakeholderType(StrEnum):
    # --- external ---
    PROFESSIONAL_COUNCIL = "professional_council"  # สภาวิชาชีพ
    EMPLOYER = "employer"  # ผู้ใช้บัณฑิต / ผู้ประกอบการ
    INDUSTRY = "industry"  # ภาคอุตสาหกรรม
    ALUMNI = "alumni"  # ศิษย์เก่า
    EXPERT = "expert"  # ผู้ทรงคุณวุฒิ
    COMMUNITY = "community"  # ชุมชนและสังคม
    PARTNER_INSTITUTION = "partner_institution"  # สถาบันคู่ความร่วมมือ
    APPLICANT = "applicant"  # ผู้สมัครเรียน
    PARENT = "parent"  # ผู้ปกครอง
    # --- internal ---
    # One voice (the institution's) expressed across several documents; which
    # document a row came from lives in StakeholderEvidence.source_name.
    INSTITUTIONAL_DIRECTION = "institutional_direction"  # vision/mission/identity
    ADMINISTRATOR = "administrator"  # ผู้บริหาร
    PROGRAM_COMMITTEE = "program_committee"  # คณะกรรมการหลักสูตร
    FACULTY = "faculty"  # อาจารย์
    STUDENT = "student"  # ผู้เรียน
    SUPPORT_STAFF = "support_staff"  # บุคลากรสายสนับสนุน


_EXTERNAL_TYPES = frozenset(
    {
        StakeholderType.PROFESSIONAL_COUNCIL,
        StakeholderType.EMPLOYER,
        StakeholderType.INDUSTRY,
        StakeholderType.ALUMNI,
        StakeholderType.EXPERT,
        StakeholderType.COMMUNITY,
        StakeholderType.PARTNER_INSTITUTION,
        StakeholderType.APPLICANT,
        StakeholderType.PARENT,
    }
)

# The only mapping from type to group. Nothing else may hardcode the split —
# the demand weight table and the UI grouping both read from here.
STAKEHOLDER_GROUP: dict[StakeholderType, StakeholderGroup] = {
    t: (StakeholderGroup.EXTERNAL if t in _EXTERNAL_TYPES else StakeholderGroup.INTERNAL)
    for t in StakeholderType
}

# สภาวิชาชีพ sets legally binding practice requirements; the institution's own
# vision/mission/identity is a mandate it has committed to. Both are
# ข้อกำหนดที่ต้องมี. Every other type carries demand signal, not mandate.
REQUIREMENT_TYPES = frozenset(
    {StakeholderType.PROFESSIONAL_COUNCIL, StakeholderType.INSTITUTIONAL_DIRECTION}
)

# Evidence carries a mandate or it does not — a two-value vocabulary, decided in
# code from the stakeholder type. need/want/unclassified moved to the skill,
# where the cross-evidence frequency that decides them is actually visible.
EvidenceClassification = Literal["requirement", "general"]
SkillClassification = Literal["requirement", "need", "want", "unclassified"]
```

Then change `StakeholderEvidence.classification` (line 185) to:

```python
    classification: EvidenceClassification = "general"
```

- [ ] **Step 4: Add the lookup to the stage module**

Replace the whole body of `src/curriculum_agent/stages/stakeholder_needs.py` above `run()` — delete `_ClassifyResult`, `WANT_ONLY_TYPES`, `_WANT_RATIONALE_TH`, `classify_single`, and the `complete_light` / `build_classify_evidence_prompt` / `Literal` / `BaseModel` imports — with:

```python
from __future__ import annotations

from loguru import logger

from curriculum_agent.data.repositories import EvidenceRepository
from curriculum_agent.graph import AgentState
from curriculum_agent.models import (
    REQUIREMENT_TYPES,
    EvidenceClassification,
    StakeholderEvidence,
    StakeholderType,
)


def classify_evidence_type(stakeholder_type: StakeholderType) -> EvidenceClassification:
    """Whether evidence from this stakeholder carries a mandate.

    Pure lookup, no LLM. The previous design asked a model to judge each item
    need/requirement/want, which was both a cost per item and the wrong question:
    a mandate is a property of who is speaking, not of how they phrased it.
    """
    return "requirement" if stakeholder_type in REQUIREMENT_TYPES else "general"
```

Leave `run()` in place for now — Task 4 rewrites it.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_models.py tests/unit/test_evidence_classification.py -q`
Expected: PASS. Other test files will fail at this point (they reference deleted enum members and `classify_single`); Tasks 4-11 fix them. Do not fix them here.

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/models.py src/curriculum_agent/stages/stakeholder_needs.py tests/unit/test_models.py tests/unit/test_evidence_classification.py
git commit -m "feat(models): external/internal stakeholder taxonomy, classification in code"
```

---

### Task 2: KSEC collapse and model field changes

**Files:**
- Modify: `src/curriculum_agent/models.py:40-50` (KSEC), `:193-210` (`ExtractedSkill`), `:213-238` (`Need`), `:257-279` (`PLO`)
- Modify: `src/curriculum_agent/stages/need_grouping.py:30-40`
- Test: `tests/unit/test_models.py`, `tests/unit/test_need_grouping.py`

**Interfaces:**
- Consumes: `SkillClassification`, `StakeholderType` from Task 1.
- Produces: `KSECCategory` with members `K`, `S`, `EC`, `E`, `C`; `SKILL_KSEC: frozenset[KSECCategory]` (the four a skill may carry); `bucket_by_ksec(skills) -> dict[KSECCategory, list[ExtractedSkill]]` now keyed by `K`/`S`/`EC` only; `resolve_need_ksec(members: list[ExtractedSkill]) -> KSECCategory`; `ExtractedSkill.classification`, `.is_field_relevant`, `.source_stakeholder_type`; `Need.source_stakeholder_types`; `PLO` without `is_subject_specific` / `classification` / `classification_method` / `classification_rationale_th`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_models.py`:

```python
def test_ksec_has_no_ss_or_gs():
    from curriculum_agent.models import KSECCategory

    values = {c.value for c in KSECCategory}
    assert values == {"K", "S", "EC", "E", "C"}


def test_a_skill_may_not_carry_the_ec_umbrella_tag():
    """EC is a Need-level tag produced by bucketing; a skill mention is
    always specifically E or C."""
    from curriculum_agent.models import SKILL_KSEC, KSECCategory

    assert KSECCategory.EC not in SKILL_KSEC
    assert SKILL_KSEC == {KSECCategory.K, KSECCategory.S, KSECCategory.E, KSECCategory.C}


def test_plo_no_longer_carries_a_specificity_flag():
    from curriculum_agent.models import PLO

    for gone in (
        "is_subject_specific",
        "classification",
        "classification_method",
        "classification_rationale_th",
    ):
        assert gone not in PLO.model_fields
```

Append to `tests/unit/test_need_grouping.py` (its `_skill` helper needs the new required fields — update it in Step 3):

```python
def test_ethics_and_character_share_one_ec_bucket():
    from curriculum_agent.models import KSECCategory
    from curriculum_agent.stages.need_grouping import bucket_by_ksec

    skills = [
        _skill("จรรยาบรรณวิชาชีพ", KSECCategory.E, skill_id="S1"),
        _skill("ความรับผิดชอบต่อหน้าที่", KSECCategory.C, skill_id="S2"),
        _skill("เขียนโปรแกรม", KSECCategory.S, skill_id="S3"),
    ]
    buckets = bucket_by_ksec(skills)
    assert set(buckets) == {KSECCategory.EC, KSECCategory.S}
    assert len(buckets[KSECCategory.EC]) == 2


def test_need_tag_is_e_when_every_member_is_e():
    from curriculum_agent.models import KSECCategory
    from curriculum_agent.stages.need_grouping import resolve_need_ksec

    members = [
        _skill("จรรยาบรรณวิชาชีพ", KSECCategory.E, skill_id="S1"),
        _skill("ความซื่อสัตย์ในวิชาชีพ", KSECCategory.E, skill_id="S2"),
    ]
    assert resolve_need_ksec(members) is KSECCategory.E


def test_need_tag_is_c_when_every_member_is_c():
    from curriculum_agent.models import KSECCategory
    from curriculum_agent.stages.need_grouping import resolve_need_ksec

    members = [_skill("ความรับผิดชอบต่อหน้าที่", KSECCategory.C, skill_id="S1")]
    assert resolve_need_ksec(members) is KSECCategory.C


def test_need_tag_is_ec_when_members_mix_ethics_and_character():
    from curriculum_agent.models import KSECCategory
    from curriculum_agent.stages.need_grouping import resolve_need_ksec

    members = [
        _skill("จรรยาบรรณวิชาชีพ", KSECCategory.E, skill_id="S1"),
        _skill("ความรับผิดชอบต่อหน้าที่", KSECCategory.C, skill_id="S2"),
    ]
    assert resolve_need_ksec(members) is KSECCategory.EC


def test_need_tag_of_a_non_ec_bucket_is_the_member_tag():
    from curriculum_agent.models import KSECCategory
    from curriculum_agent.stages.need_grouping import resolve_need_ksec

    members = [_skill("เขียนโปรแกรม", KSECCategory.S, skill_id="S1")]
    assert resolve_need_ksec(members) is KSECCategory.S
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_models.py tests/unit/test_need_grouping.py -q`
Expected: FAIL — `AttributeError: SS` / `cannot import name 'resolve_need_ksec'`.

- [ ] **Step 3: Change the models**

In `models.py`, replace the `KSECCategory` block (lines 40-50, comment included) with:

```python
# TQF/มคอ. competency domains, used to pre-tag every ExtractedSkill for eventual
# มคอ.2/CHECO mapping. NOT a Bloom domain — orthogonal to bloom_level.
#
# A skill carries K, S, E or C. A Need carries those plus EC, the umbrella tag
# for a group whose members mix ethics and character; grouping produces it, and
# E or C survive as standalone Need tags when a group is unambiguously one.
class KSECCategory(StrEnum):
    K = "K"  # ความรู้
    S = "S"  # ทักษะ
    EC = "EC"  # คุณธรรมจริยธรรมและคุณลักษณะบุคคล — displayed "E|C"
    E = "E"  # คุณธรรมจริยธรรม
    C = "C"  # คุณลักษณะบุคคล


# The tags an ExtractedSkill may carry. EC is Need-level only.
SKILL_KSEC = frozenset({KSECCategory.K, KSECCategory.S, KSECCategory.E, KSECCategory.C})
```

In `ExtractedSkill`, add three fields after `source_evidence_id` (line 206):

```python
    source_evidence_id: str
    # Provenance kept for the UI: a designer reviewing a grouped Need can see
    # which stakeholders it came from without another query.
    source_stakeholder_type: StakeholderType
    # Decided in code after every evidence item is extracted — see
    # skill_extraction.classify_skills.
    classification: SkillClassification = "unclassified"
    # Set by the extraction model: does this belong to the program's field at
    # all? A False here yields `unclassified` unless the skill is mandated.
    is_field_relevant: bool = True
```

In `Need`, add after `stakeholder_coverage` (line 231):

```python
    # Distinct source stakeholder types, external first (enum declaration order).
    source_stakeholder_types: list[StakeholderType] = Field(default_factory=list)
```

In `PLO`, delete line 265 (`is_subject_specific: bool`) and lines 273-275 (`classification`, `classification_method`, `classification_rationale_th`).

- [ ] **Step 4: Change bucketing and add tag resolution**

In `need_grouping.py`, replace `bucket_by_ksec` (lines 30-40) with:

```python
# E and C skills are clustered together: a Need about professional conduct is
# routinely both, and forcing the split at grouping time produces two thin Needs
# that a designer immediately merges by hand. The raw tags survive on the member
# skills, so resolve_need_ksec can still hand back a standalone E or C.
_EC_MEMBERS = {KSECCategory.E, KSECCategory.C}


def bucket_by_ksec(skills: list[ExtractedSkill]) -> dict[KSECCategory, list[ExtractedSkill]]:
    """Split skills into one bucket per KSEC tag, omitting empty buckets.

    E and C skills land in a single EC bucket; everything else buckets by its own
    tag. Clustering runs inside a bucket and merging never crosses buckets, so a
    Need can never contain two different tags. This is what makes "tags must not
    mix" a structural guarantee instead of a rule someone has to remember.
    """
    buckets: dict[KSECCategory, list[ExtractedSkill]] = {}
    for skill in skills:
        key = KSECCategory.EC if skill.ksec_category in _EC_MEMBERS else skill.ksec_category
        buckets.setdefault(key, []).append(skill)
    return buckets


def resolve_need_ksec(members: list[ExtractedSkill]) -> KSECCategory:
    """The tag a Need carries, given the skills that formed it.

    An all-ethics group is tagged E and an all-character group C, so a program
    with a distinct ethics outcome can show one in its มคอ.2 table. A mixed group
    keeps the EC umbrella. Non-EC buckets are single-tag by construction.
    """
    if not members:
        raise ValueError("resolve_need_ksec requires at least one member skill")
    tags = {m.ksec_category for m in members}
    if tags <= _EC_MEMBERS:
        return tags.pop() if len(tags) == 1 else KSECCategory.EC
    if len(tags) != 1:
        raise ValueError(f"a Need's members must share one KSEC tag, got {sorted(t.value for t in tags)}")
    return tags.pop()
```

Update the `_skill` helper in `tests/unit/test_need_grouping.py` so the new required field is present, and change its default tag off the deleted `SS`:

```python
def _skill(
    name: str,
    ksec: KSECCategory = KSECCategory.S,
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
        source_stakeholder_type=StakeholderType.EMPLOYER,
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.5,
    )
```

Add `StakeholderType` to that file's imports from `curriculum_agent.models`, and change the `test_bucket_by_ksec_never_mixes_tags` / `test_bucket_by_ksec_omits_empty_buckets` cases to use `KSECCategory.S` and `KSECCategory.K` instead of `SS`/`GS`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_models.py tests/unit/test_need_grouping.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/models.py src/curriculum_agent/stages/need_grouping.py tests/unit/test_models.py tests/unit/test_need_grouping.py
git commit -m "feat(models): collapse SS/GS into S, add the EC Need tag and skill provenance"
```

---

### Task 3: ORM columns and the Alembic migration

**Files:**
- Modify: `src/curriculum_agent/data/orm.py:57-70` (skills), `:73-89` (needs), `:92-115` (plos)
- Create: `migrations/versions/<rev>_stakeholder_classification_redesign.py`
- Test: `tests/unit/test_migration_backfill.py` (create)

**Interfaces:**
- Consumes: field names from Task 2.
- Produces: columns `skills.classification`, `skills.is_field_relevant`, `skills.source_stakeholder_type`, `needs.source_stakeholder_types`; four dropped columns on `plos`. Current Alembic head is `8b207d0426c3` — the new revision's `down_revision` is that value.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_migration_backfill.py`:

```python
"""The migration's data rules, tested as pure functions.

The SQL runs against Postgres in CI; what matters here is that the mapping from
old values to new is total. A stakeholder_type left unmapped is not a cosmetic
problem: Need.stakeholder_coverage is typed dict[StakeholderType, int], so a
surviving row with a deleted value raises ValidationError inside
repositories.list_by_program and breaks GET /evidence/ for the whole program.
"""

from __future__ import annotations

from curriculum_agent.models import StakeholderType

# Imported from the migration module by file path — Alembic revisions are not
# importable as a package.
import importlib.util
from pathlib import Path


def _load_migration():
    path = next(
        Path("migrations/versions").glob("*_stakeholder_classification_redesign.py")
    )
    spec = importlib.util.spec_from_file_location("redesign_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_deleted_stakeholder_type_is_remapped():
    module = _load_migration()
    assert set(module.STAKEHOLDER_TYPE_BACKFILL) == {
        "accreditation_body",
        "university",
        "subject_benchmark",
        "peer_program",
    }


def test_every_remap_target_exists_in_the_new_enum():
    module = _load_migration()
    valid = {t.value for t in StakeholderType}
    assert set(module.STAKEHOLDER_TYPE_BACKFILL.values()) <= valid


def test_ksec_backfill_maps_both_removed_tags_to_s():
    module = _load_migration()
    assert module.KSEC_BACKFILL == {"SS": "S", "GS": "S"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_migration_backfill.py -q`
Expected: FAIL — `StopIteration` from the glob (no such migration file yet).

- [ ] **Step 3: Update the ORM**

In `orm.py`, add to `SkillTable` after `source_evidence_id` (line 67):

```python
    source_stakeholder_type: Mapped[str] = mapped_column(String(50), default="employer")
    classification: Mapped[str] = mapped_column(String(20), default="unclassified")
    is_field_relevant: Mapped[bool] = mapped_column(Boolean, default=True)
```

Add to `NeedTable` after `stakeholder_coverage` (line 84):

```python
    source_stakeholder_types: Mapped[list[str]] = mapped_column(JSONB, default=list)
```

In `PLOTable`, delete line 100 (`is_subject_specific`) and lines 109-111 (`classification`, `classification_method`, `classification_rationale_th`).

- [ ] **Step 4: Write the migration**

Create `migrations/versions/b7c4e1a9f052_stakeholder_classification_redesign.py`:

```python
"""stakeholder classification redesign: skill-level classes, new taxonomy, KSEC collapse

Revision ID: b7c4e1a9f052
Revises: 8b207d0426c3
Create Date: 2026-08-02 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'b7c4e1a9f052'
down_revision: Union[str, None] = '8b207d0426c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Deleted stakeholder types, mapped to their nearest surviving equivalent.
# Not cosmetic: Need.stakeholder_coverage validates its keys against the enum,
# so one surviving row breaks GET /evidence/ for the entire program.
STAKEHOLDER_TYPE_BACKFILL = {
    "accreditation_body": "professional_council",
    "university": "institutional_direction",
    "subject_benchmark": "expert",
    "peer_program": "partner_institution",
}

KSEC_BACKFILL = {"SS": "S", "GS": "S"}


def upgrade() -> None:
    op.add_column("skills", sa.Column("source_stakeholder_type", sa.String(50),
                                      nullable=False, server_default="employer"))
    op.add_column("skills", sa.Column("classification", sa.String(20),
                                      nullable=False, server_default="unclassified"))
    op.add_column("skills", sa.Column("is_field_relevant", sa.Boolean(),
                                      nullable=False, server_default=sa.true()))
    op.add_column("needs", sa.Column("source_stakeholder_types", JSONB(),
                                     nullable=False, server_default="[]"))

    op.drop_column("plos", "is_subject_specific")
    op.drop_column("plos", "classification")
    op.drop_column("plos", "classification_method")
    op.drop_column("plos", "classification_rationale_th")

    for old, new in STAKEHOLDER_TYPE_BACKFILL.items():
        op.execute(
            sa.text("UPDATE evidence SET stakeholder_type = :new WHERE stakeholder_type = :old")
            .bindparams(new=new, old=old)
        )

    # Evidence classes collapse to requirement/general. `requirement` rows keep
    # their value; everything else — including the old want/need/unclassified —
    # becomes general, and the skill-level pass re-derives the rest.
    op.execute("UPDATE evidence SET classification = 'general' WHERE classification <> 'requirement'")

    for old, new in KSEC_BACKFILL.items():
        for table in ("skills", "needs"):
            op.execute(
                sa.text(f"UPDATE {table} SET ksec_category = :new WHERE ksec_category = :old")
                .bindparams(new=new, old=old)
            )

    # Existing skills predate source_stakeholder_type; fill it from their evidence
    # rather than leaving every row on the 'employer' server default.
    op.execute(
        "UPDATE skills SET source_stakeholder_type = evidence.stakeholder_type "
        "FROM evidence WHERE skills.source_evidence_id = evidence.evidence_id"
    )


def downgrade() -> None:
    op.add_column("plos", sa.Column("classification_rationale_th", sa.Text(), nullable=True))
    op.add_column("plos", sa.Column("classification_method", sa.String(20), nullable=True))
    op.add_column("plos", sa.Column("classification", sa.String(20), nullable=True))
    op.add_column("plos", sa.Column("is_subject_specific", sa.Boolean(),
                                    nullable=False, server_default=sa.true()))
    op.drop_column("needs", "source_stakeholder_types")
    op.drop_column("skills", "is_field_relevant")
    op.drop_column("skills", "classification")
    op.drop_column("skills", "source_stakeholder_type")
    # The old taxonomy and the SS/GS split are not restorable — the information
    # that distinguished them is gone. Rows keep their new values.
```

- [ ] **Step 5: Run the test and apply the migration**

Run: `uv run pytest tests/unit/test_migration_backfill.py -q`
Expected: PASS.

Run: `uv run alembic upgrade head`
Expected: the revision applies with no error. (Docker services must be up — `.\scripts\start-dev.ps1` if not.)

Then verify the round trip: `uv run alembic downgrade -1` then `uv run alembic upgrade head`. Both must succeed.

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/data/orm.py migrations/versions/b7c4e1a9f052_stakeholder_classification_redesign.py tests/unit/test_migration_backfill.py
git commit -m "feat(db): migrate to skill-level classification and the new stakeholder taxonomy"
```

---

### Task 4: stakeholder_needs becomes pure code

**Files:**
- Modify: `src/curriculum_agent/stages/stakeholder_needs.py:54-77`
- Modify: `src/curriculum_agent/api/routes/evidence.py:13,37-57`
- Delete: `src/curriculum_agent/prompts/classify_evidence.py`
- Test: `tests/unit/test_stakeholder_needs.py` (rewrite whichever cases reference the LLM path)

**Interfaces:**
- Consumes: `classify_evidence_type` from Task 1.
- Produces: `classify_single(evidence: StakeholderEvidence) -> StakeholderEvidence` — same name and signature as before but synchronous logic behind an unchanged `async def`, so `api/routes/evidence.py` keeps working.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_stakeholder_needs_stage.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import StakeholderEvidence, StakeholderType
from curriculum_agent.stages import stakeholder_needs as sn


def _evidence(eid: str, stype: StakeholderType) -> StakeholderEvidence:
    return StakeholderEvidence(
        evidence_id=eid,
        program_id="cs-test",
        stakeholder_type=stype,
        source_name=f"source-{eid}",
        raw_text_th="ต้องการบัณฑิตที่วิเคราะห์ข้อมูลขนาดใหญ่ได้",
    )


async def test_run_classifies_without_any_llm_call(monkeypatch: pytest.MonkeyPatch):
    """No network, no cost: the stage must reach a full classification with the
    LLM module absent entirely."""
    monkeypatch.setattr(sn.EvidenceRepository, "bulk_insert", AsyncMock())

    state = await sn.run(
        {
            "program_id": "cs-test",
            "raw_evidence": [
                _evidence("E1", StakeholderType.PROFESSIONAL_COUNCIL).model_dump(mode="json"),
                _evidence("E2", StakeholderType.EMPLOYER).model_dump(mode="json"),
                _evidence("E3", StakeholderType.INSTITUTIONAL_DIRECTION).model_dump(mode="json"),
            ],
        }
    )

    by_id = {e["evidence_id"]: e["classification"] for e in state["classified_evidence"]}
    assert by_id == {"E1": "requirement", "E2": "general", "E3": "requirement"}


async def test_run_reclassifies_every_item_each_time(monkeypatch: pytest.MonkeyPatch):
    """Classification is now derived, not stored judgement — an item whose stored
    class disagrees with its type is corrected rather than skipped."""
    monkeypatch.setattr(sn.EvidenceRepository, "bulk_insert", AsyncMock())
    stale = _evidence("E1", StakeholderType.PROFESSIONAL_COUNCIL).model_dump(mode="json")
    stale["classification"] = "general"

    state = await sn.run({"program_id": "cs-test", "raw_evidence": [stale]})

    assert state["classified_evidence"][0]["classification"] == "requirement"


async def test_run_persists_the_classified_items(monkeypatch: pytest.MonkeyPatch):
    insert = AsyncMock()
    monkeypatch.setattr(sn.EvidenceRepository, "bulk_insert", insert)

    await sn.run(
        {
            "program_id": "cs-test",
            "raw_evidence": [_evidence("E1", StakeholderType.EMPLOYER).model_dump(mode="json")],
        }
    )

    insert.assert_awaited_once()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_stakeholder_needs_stage.py -q`
Expected: FAIL — `run` still filters on `classification == "unclassified"`, which no longer exists as an evidence value, so `classified_evidence` comes back with the stale value.

- [ ] **Step 3: Rewrite `run` and `classify_single`**

Append to `src/curriculum_agent/stages/stakeholder_needs.py`, replacing the existing `run` (lines 54-77):

```python
async def classify_single(evidence: StakeholderEvidence) -> StakeholderEvidence:
    """Classify one evidence item. Used by the stage and the SSE endpoint.

    Async only to keep the endpoint's call site unchanged — there is no I/O left
    to await now that the classification is a lookup.
    """
    return evidence.model_copy(
        update={"classification": classify_evidence_type(evidence.stakeholder_type)}
    )


async def run(state: AgentState) -> AgentState:
    """Stage 1: derive every evidence item's class from its stakeholder type.

    Every item is reclassified on every run, not just the previously unclassified
    ones: the class is now derived from the type, so a stored value that disagrees
    is stale data to correct rather than a human judgement to preserve.
    """
    raw = state.get("raw_evidence", [])
    items = [StakeholderEvidence.model_validate(d) for d in raw]
    logger.info(f"Stage 1: classifying {len(items)} evidence items")

    classified = [await classify_single(e) for e in items]
    requirements = sum(1 for e in classified if e.classification == "requirement")
    logger.info(f"Stage 1: {requirements} requirement, {len(classified) - requirements} general")

    if classified:
        await EvidenceRepository().bulk_insert(classified)

    state["classified_evidence"] = [e.model_dump(mode="json") for e in classified]
    state["current_stage"] = "stakeholder_needs"
    return state
```

- [ ] **Step 4: Update the SSE endpoint and delete the prompt**

In `api/routes/evidence.py`, replace lines 36-38 inside `_generate`:

```python
        repo = EvidenceRepository()
        items = await repo.list_by_program(program_id)
        to_classify = items
        total = len(to_classify)
```

The loop body below it is unchanged — `classify_single` keeps its signature.

Delete the prompt file:

```bash
git rm src/curriculum_agent/prompts/classify_evidence.py
```

If `tests/unit/test_classify_evidence_prompt.py` exists, delete it too — the prompt it covers is gone.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_stakeholder_needs_stage.py tests/unit/test_evidence_classification.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A src/curriculum_agent/stages/stakeholder_needs.py src/curriculum_agent/api/routes/evidence.py src/curriculum_agent/prompts/ tests/unit/
git commit -m "refactor(stakeholder-needs): derive evidence class from the stakeholder type"
```

---

### Task 5: Intake converts institutional direction into evidence

**Files:**
- Modify: `src/curriculum_agent/stages/intake.py:19-36`
- Test: `tests/unit/test_intake_evidence.py` (create)

**Interfaces:**
- Consumes: `StakeholderType.INSTITUTIONAL_DIRECTION`, `classify_evidence_type` (Task 1).
- Produces: `INSTITUTIONAL_FIELDS: tuple[tuple[str, str, str], ...]` (attribute name, id suffix, Thai `source_name`) and `build_institutional_evidence(metadata: ProgramMetadata) -> list[StakeholderEvidence]`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_intake_evidence.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import ProgramMetadata, StakeholderType
from curriculum_agent.stages import intake


def test_every_populated_field_becomes_requirement_evidence(
    program_metadata: ProgramMetadata,
):
    items = intake.build_institutional_evidence(program_metadata)

    assert all(e.stakeholder_type is StakeholderType.INSTITUTIONAL_DIRECTION for e in items)
    assert all(e.classification == "requirement" for e in items)
    assert all(e.raw_text_th.strip() for e in items)


def test_absent_optional_identity_fields_produce_no_row(program_metadata: ProgramMetadata):
    without = program_metadata.model_copy(
        update={"institutional_identity_th": None, "student_identity_th": None}
    )
    suffixes = {e.evidence_id.rsplit("-", 1)[-1] for e in intake.build_institutional_evidence(without)}

    assert "identity" not in suffixes
    assert "studentidentity" not in suffixes
    assert {"vision", "mission", "philosophy"} <= suffixes


def test_ids_are_deterministic_so_a_re_run_replaces_rather_than_accumulates(
    program_metadata: ProgramMetadata,
):
    """The repository upserts by primary key: an id derived from the program and
    the field name is what stops a second intake run from doubling the rows."""
    edited = program_metadata.model_copy(update={"vision_th": "วิสัยทัศน์ฉบับแก้ไข"})

    first = {e.evidence_id for e in intake.build_institutional_evidence(program_metadata)}
    second = {e.evidence_id for e in intake.build_institutional_evidence(edited)}

    assert first == second


def test_a_whitespace_only_field_produces_no_row(program_metadata: ProgramMetadata):
    blanked = program_metadata.model_copy(update={"institutional_identity_th": "   "})
    texts = [e.raw_text_th for e in intake.build_institutional_evidence(blanked)]

    assert "   " not in texts


async def test_run_persists_the_institutional_evidence(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(intake.ProgramRepository, "upsert", AsyncMock())
    insert = AsyncMock()
    monkeypatch.setattr(intake.EvidenceRepository, "bulk_insert", insert)
    monkeypatch.setattr(intake.EvidenceRepository, "list_by_program", AsyncMock(return_value=[]))

    await intake.run({"metadata": program_metadata.model_dump(mode="json")})

    insert.assert_awaited_once()
    written = insert.await_args.args[0]
    assert all(e.classification == "requirement" for e in written)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_intake_evidence.py -q`
Expected: FAIL — `AttributeError: module 'curriculum_agent.stages.intake' has no attribute 'build_institutional_evidence'`.

- [ ] **Step 3: Implement the conversion**

Add to `src/curriculum_agent/stages/intake.py` above `run`, and add `StakeholderEvidence` and `StakeholderType` to the `curriculum_agent.models` import:

```python
# (attribute on ProgramMetadata, evidence-id suffix, Thai source_name).
# The suffix makes the id deterministic, which is what lets a second intake run
# upsert over the first instead of accumulating a duplicate set.
INSTITUTIONAL_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("vision_th", "vision", "วิสัยทัศน์"),
    ("mission_th", "mission", "พันธกิจ"),
    ("philosophy_th", "philosophy", "ปรัชญาหลักสูตร"),
    ("institutional_identity_th", "identity", "อัตลักษณ์สถาบัน"),
    ("student_identity_th", "studentidentity", "อัตลักษณ์บัณฑิต"),
)


def build_institutional_evidence(metadata: ProgramMetadata) -> list[StakeholderEvidence]:
    """Turn the program's own direction statements into requirement evidence.

    These are mandatory inputs to a Thai program's PLOs, but until now they were
    prompt context only — so a PLO that exists because the faculty's vision demands
    it had no evidence to point at, and "every PLO traces to evidence" was quietly
    false for that case.
    """
    items: list[StakeholderEvidence] = []
    for attr, suffix, source_name in INSTITUTIONAL_FIELDS:
        value = getattr(metadata, attr, None)
        if not value or not value.strip():
            continue
        items.append(
            StakeholderEvidence(
                evidence_id=f"{metadata.program_id}-{suffix}",
                program_id=metadata.program_id,
                stakeholder_type=StakeholderType.INSTITUTIONAL_DIRECTION,
                source_name=source_name,
                raw_text_th=value.strip(),
                classification="requirement",
            )
        )
    return items
```

Then in `run`, insert between `program_repo.upsert` and the existing evidence load:

```python
    evidence_repo = EvidenceRepository()

    institutional = build_institutional_evidence(metadata)
    if institutional:
        await evidence_repo.bulk_insert(institutional)
        logger.info(f"Intake: wrote {len(institutional)} institutional-direction evidence items")

    evidence_items = await evidence_repo.list_by_program(metadata.program_id)
```

(delete the now-duplicated `evidence_repo = EvidenceRepository()` line that followed `upsert`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_intake_evidence.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/curriculum_agent/stages/intake.py tests/unit/test_intake_evidence.py
git commit -m "feat(intake): convert vision/mission/identity into requirement evidence"
```

---

### Task 6: Extraction prompt — field context, is_field_relevant, 4-value KSEC

**Files:**
- Modify: `src/curriculum_agent/prompts/extract_skills.py`
- Test: `tests/unit/test_extract_skills_prompt.py` (create)

**Interfaces:**
- Produces: `build_extract_skills_prompt(evidence_text: str, classification: str, field_th: str = "", program_name_th: str = "") -> list[dict[str, str]]`. The two new parameters default to empty so `_extraction_contract_fingerprint()` (which calls the builder with two positional arguments) keeps working unchanged.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_extract_skills_prompt.py`:

```python
from __future__ import annotations

from curriculum_agent.prompts.extract_skills import build_extract_skills_prompt


def test_ksec_instruction_offers_four_tags_not_the_old_five():
    system = build_extract_skills_prompt("ข้อความ", "general")[0]["content"]

    assert "K|S|E|C" in system
    assert "GS" not in system
    assert "SS" not in system


def test_schema_asks_for_is_field_relevant():
    system = build_extract_skills_prompt("ข้อความ", "general")[0]["content"]

    assert "is_field_relevant" in system


def test_the_field_of_study_reaches_the_model():
    """The prompt has always said 'ทักษะที่ไม่เกี่ยวข้องกับสาขาวิชา ห้ามเสนอ'
    without naming the field — an unanswerable instruction until now."""
    messages = build_extract_skills_prompt(
        "ข้อความ", "general", field_th="วิทยาการคอมพิวเตอร์", program_name_th="วท.บ. วิทยาการคอมพิวเตอร์"
    )
    joined = "\n".join(m["content"] for m in messages)

    assert "วิทยาการคอมพิวเตอร์" in joined
    assert "วท.บ. วิทยาการคอมพิวเตอร์" in joined


def test_omitting_the_field_leaves_no_dangling_header():
    messages = build_extract_skills_prompt("ข้อความ", "general")
    user = messages[1]["content"]

    assert "สาขาวิชา:" not in user
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_extract_skills_prompt.py -q`
Expected: FAIL — `"K|S|E|C" not in system` and `TypeError` on the `field_th` keyword.

- [ ] **Step 3: Rewrite the builder**

Replace `src/curriculum_agent/prompts/extract_skills.py` in full:

```python
from __future__ import annotations


def build_extract_skills_prompt(
    evidence_text: str,
    classification: str,
    field_th: str = "",
    program_name_th: str = "",
) -> list[dict[str, str]]:
    """Extract skills from one evidence item, tagged and judged for field fit.

    `field_th` and `program_name_th` are what make the "no off-field skills" rule
    answerable — before they existed the model was told to exclude skills outside
    the program's field without being told what the field was. They default to
    empty so the contract fingerprint can call this with the text alone.
    """
    system = (
        "คุณเป็นผู้เชี่ยวชาญวิเคราะห์ทักษะจากข้อความ\n"
        "จากข้อความ evidence จงระบุทักษะที่ตลาดแรงงานต้องการ\n\n"
        "กติกา:\n"
        "- แต่ละทักษะต้องเป็น 'วลี' หรือกลุ่มคำที่สื่อความสามารถ ห้ามเป็นคำโดดคำเดียว\n"
        "- ทักษะแต่ละรายการต้องไม่ซ้ำและไม่คาบเกี่ยวกัน (unique, independent) "
        "ห้ามเขียนสิ่งเดียวกันด้วยถ้อยคำต่างกัน\n"
        "- evidence_span_th ต้องคัดลอกข้อความ 'ตรงตัว' จาก evidence ที่ทำให้สรุปทักษะนี้ได้ "
        "ห้ามเรียบเรียงใหม่ ห้ามแต่งเพิ่ม ถ้าไม่มีข้อความรองรับ ห้ามเสนอทักษะนั้น\n"
        "- evidence_span_th ต้องเป็นวลีที่สมบูรณ์ ยาวอย่างน้อยประมาณ 12 ตัวอักษร "
        "คัดลอกตรงตัวจาก evidence ห้ามตัดมาเป็นเศษคำหรืออักขระเดี่ยว ๆ\n"
        "- ทักษะที่อ่านแล้วไม่เข้าข่ายสาขาวิชาของหลักสูตรเลย ให้คงไว้แต่ตั้ง "
        "is_field_relevant = false ห้ามตัดทิ้งเอง ผู้ออกแบบหลักสูตรจะเป็นผู้ตัดสิน\n\n"
        "ตอบเป็น JSON object: { skills: [ {\n"
        "  skill_name_th: วลีทักษะภาษาไทย,\n"
        "  skill_name_en: ชื่อภาษาอังกฤษมาตรฐาน (เช่น 'Data Analysis') ห้ามเว้นว่าง,\n"
        "  ksec_category: K|S|E|C — K=ความรู้, S=ทักษะ, "
        "E=คุณธรรมจริยธรรม, C=คุณลักษณะบุคคล "
        "(เลือกได้เพียงค่าเดียว ห้ามตอบว่าผสมกัน),\n"
        "  bloom_level: remember|understand|apply|analyze|evaluate|create "
        "— ระดับ Bloom ด้าน Cognitive เท่านั้น,\n"
        "  evidence_span_th: ข้อความที่คัดลอกตรงตัวจาก evidence,\n"
        "  is_field_relevant: true|false — ทักษะนี้อยู่ในขอบเขตของสาขาวิชาหรือไม่,\n"
        "  confidence: 0.0-1.0\n"
        "} ] }\n"
        "สกัดไม่เกิน 8 ทักษะต่อข้อความ เน้นทักษะที่วัดได้จริง"
    )
    header = f"[ประเภทหลักฐาน: {classification}]"
    if program_name_th:
        header += f"\n[หลักสูตร: {program_name_th}]"
    if field_th:
        header += f"\n[สาขาวิชา: {field_th}]"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"{header}\n{evidence_text}"},
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_extract_skills_prompt.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/curriculum_agent/prompts/extract_skills.py tests/unit/test_extract_skills_prompt.py
git commit -m "feat(prompts): give skill extraction the field of study and an is_field_relevant flag"
```

---

### Task 7: demand_score becomes weighted frequency

**Files:**
- Modify: `src/curriculum_agent/stages/demand.py` (full rewrite)
- Modify: `src/curriculum_agent/stages/skill_extraction.py:23` (import), `:101-132` (`_compute_skill_importance`), `:256-265` (its call site)
- Test: `tests/unit/test_demand.py` (create), `tests/unit/test_skill_importance_normalization.py`

**Interfaces:**
- Consumes: `STAKEHOLDER_GROUP`, `StakeholderGroup`, `StakeholderType` (Task 1).
- Produces: `evidence_weight(stakeholder_type: StakeholderType) -> float`; `total_evidence_weight(stakeholder_type_by_evidence: dict[str, str]) -> float`; `compute_demand_score(source_evidence_ids: list[str], stakeholder_type_by_evidence: dict[str, str], total_weight: float) -> float`; `classification_coverage(member_classes: list[str]) -> dict[str, int]`; `is_optional_group(class_coverage: dict[str, int]) -> bool`. `_compute_skill_importance(raw_skills, stakeholder_type_by_evidence)` keeps its name and loses two parameters.

This task comes before skill classification because `skill_extraction` calls into `demand`; doing it the other way round leaves a commit whose `_compute_skill_importance` call site does not match its signature.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_demand.py`:

```python
from __future__ import annotations

import pytest

from curriculum_agent.models import StakeholderType
from curriculum_agent.stages.demand import (
    classification_coverage,
    compute_demand_score,
    evidence_weight,
    is_optional_group,
    total_evidence_weight,
)


def test_the_four_weight_tiers():
    assert evidence_weight(StakeholderType.PROFESSIONAL_COUNCIL) == 1.0
    assert evidence_weight(StakeholderType.INSTITUTIONAL_DIRECTION) == 0.8
    assert evidence_weight(StakeholderType.EMPLOYER) == 0.6
    assert evidence_weight(StakeholderType.FACULTY) == 0.4


def test_every_stakeholder_type_has_a_weight():
    assert all(evidence_weight(t) > 0 for t in StakeholderType)


def test_the_professional_council_outweighs_a_single_employer():
    types = {"E1": "professional_council", "E2": "employer"}
    total = total_evidence_weight(types)

    council = compute_demand_score(["E1"], types, total)
    employer = compute_demand_score(["E2"], types, total)

    assert council > employer


def test_a_skill_named_by_every_source_scores_one():
    types = {"E1": "professional_council", "E2": "employer", "E3": "student"}
    total = total_evidence_weight(types)

    assert compute_demand_score(["E1", "E2", "E3"], types, total) == 1.0


def test_repeated_evidence_ids_count_once():
    types = {"E1": "employer", "E2": "employer"}
    total = total_evidence_weight(types)

    assert compute_demand_score(["E1", "E1", "E1"], types, total) == pytest.approx(0.5)


def test_score_does_not_move_when_the_enum_grows():
    """The old formula divided breadth by len(StakeholderType), so adding a type
    silently rescaled every stored score. Frequency-only scoring is immune."""
    types = {"E1": "employer", "E2": "alumni"}
    total = total_evidence_weight(types)

    assert compute_demand_score(["E1"], types, total) == pytest.approx(0.5)


def test_an_unknown_stakeholder_type_falls_back_to_the_internal_tier():
    types = {"E1": "not_a_real_type"}

    assert total_evidence_weight(types) == pytest.approx(0.4)


def test_empty_program_scores_zero_rather_than_dividing_by_zero():
    assert compute_demand_score(["E1"], {}, 0.0) == 0.0


def test_a_want_heavy_group_is_optional():
    assert is_optional_group({"want": 3, "need": 1, "requirement": 1}) is True


def test_a_requirement_backed_group_is_not_optional():
    assert is_optional_group({"want": 2, "requirement": 1, "need": 2}) is False


def test_unclassified_members_do_not_make_a_group_optional():
    assert is_optional_group({"unclassified": 5}) is False


def test_classification_coverage_counts_each_class():
    assert classification_coverage(["need", "need", "want"]) == {"need": 2, "want": 1}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_demand.py -q`
Expected: FAIL — `ImportError: cannot import name 'evidence_weight'`.

- [ ] **Step 3: Rewrite `demand.py`**

Replace the file in full:

```python
from __future__ import annotations

from curriculum_agent.models import STAKEHOLDER_GROUP, StakeholderGroup, StakeholderType

# What a source's word is worth. สภาวิชาชีพ speaks with legal force; the
# institution's own direction binds the program it governs; other outside voices
# describe the market the graduate enters; inside voices describe the program
# from within, where the incentive to reflect the market is weakest.
_REQUIREMENT_WEIGHT = {
    StakeholderType.PROFESSIONAL_COUNCIL: 1.0,
    StakeholderType.INSTITUTIONAL_DIRECTION: 0.8,
}
_EXTERNAL_WEIGHT = 0.6
_INTERNAL_WEIGHT = 0.4


def evidence_weight(stakeholder_type: StakeholderType) -> float:
    """Weight of one evidence item, from who produced it.

    Resolution goes through STAKEHOLDER_GROUP, so a type added to the enum later
    picks up the external or internal tier without an edit here.
    """
    explicit = _REQUIREMENT_WEIGHT.get(stakeholder_type)
    if explicit is not None:
        return explicit
    group = STAKEHOLDER_GROUP.get(stakeholder_type, StakeholderGroup.INTERNAL)
    return _EXTERNAL_WEIGHT if group is StakeholderGroup.EXTERNAL else _INTERNAL_WEIGHT


def _weight_of(raw_type: str) -> float:
    """Weight for a stored type string, tolerating a value not in the enum.

    An unrecognised value scores the internal tier rather than raising: a stale
    row must not take down the whole scoring pass.
    """
    try:
        return evidence_weight(StakeholderType(raw_type))
    except ValueError:
        return _INTERNAL_WEIGHT


def total_evidence_weight(stakeholder_type_by_evidence: dict[str, str]) -> float:
    """Denominator for every score in one program: the weight of all its evidence."""
    return sum(_weight_of(t) for t in stakeholder_type_by_evidence.values())


def compute_demand_score(
    source_evidence_ids: list[str],
    stakeholder_type_by_evidence: dict[str, str],
    total_weight: float,
) -> float:
    """Share of the program's total evidence weight that named this capability.

    Pure weighted frequency. The previous formula added a breadth term divided by
    len(StakeholderType) — the count of enum members, not of the groups the
    program actually collected from — so a well-supported skill in a 3-source
    program scored 0.33 on breadth and every stored score moved whenever the enum
    grew. Frequency alone is both honest and stable.
    """
    if total_weight <= 0:
        return 0.0
    named = sum(
        _weight_of(stakeholder_type_by_evidence.get(eid, ""))
        for eid in set(source_evidence_ids)
        if eid in stakeholder_type_by_evidence
    )
    return round(min(named / total_weight, 1.0), 4)


def classification_coverage(member_classes: list[str]) -> dict[str, int]:
    """Count of each SkillClassification among a group's member skills."""
    coverage: dict[str, int] = {}
    for value in member_classes:
        coverage[value] = coverage.get(value, 0) + 1
    return coverage


def is_optional_group(class_coverage: dict[str, int]) -> bool:
    """True when wants outnumber the mandated and demanded skills in a group.

    `unclassified` counts toward neither side: it means "the extractor was unsure",
    which is not evidence that a group is supplementary.
    """
    want = class_coverage.get("want", 0)
    backed = class_coverage.get("requirement", 0) + class_coverage.get("need", 0)
    return want > backed
```

- [ ] **Step 4: Rewire `_compute_skill_importance` and its call site**

In `skill_extraction.py`, change the import on line 23 to:

```python
from curriculum_agent.stages.demand import compute_demand_score, total_evidence_weight
```

Replace `_compute_skill_importance` (lines 101-132) with:

```python
def _compute_skill_importance(
    raw_skills: list[dict[str, Any]],
    stakeholder_type_by_evidence: dict[str, str],
) -> dict[str, float]:
    """Per-skill-name demand, computed before Need grouping (a later stage).

    Same weighting as Need.demand_score (compute_demand_score from
    curriculum_agent.stages.demand), grouped by the same normalised name
    (normalize_need_name) that need_grouping.dedupe_with_bloom_max later collapses
    duplicates by — so two spellings of one skill that land in the same Need also
    get the same importance_score here. Keyed by normalised name; the caller must
    normalise before looking a score up.
    """
    eids_by_name: dict[str, set[str]] = {}
    for s in raw_skills:
        norm = normalize_need_name(s["skill_name_th"])
        eids_by_name.setdefault(norm, set()).add(str(s["evidence_id"]))

    total = total_evidence_weight(stakeholder_type_by_evidence)
    return {
        name: compute_demand_score(sorted(eids), stakeholder_type_by_evidence, total)
        for name, eids in eids_by_name.items()
    }
```

In `run`, replace the `classification_by_evidence` / `total_req_need` / `importance_by_name` block (lines 257-265) with:

```python
    stakeholder_type_by_evidence: dict[str, str] = {
        str(d["evidence_id"]): str(d.get("stakeholder_type", "employer"))
        for d in classified
        if d.get("evidence_id")
    }
    importance_by_name = _compute_skill_importance(raw_skills, stakeholder_type_by_evidence)
```

Update `tests/unit/test_skill_importance_normalization.py` to the two-argument signature — it now passes a stakeholder-type map such as `{"E1": "employer", "E2": "alumni"}` instead of a classification map plus a total.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_demand.py tests/unit/test_skill_importance_normalization.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/stages/demand.py src/curriculum_agent/stages/skill_extraction.py tests/unit/test_demand.py tests/unit/test_skill_importance_normalization.py
git commit -m "feat(demand): replace breadth with weighted frequency over evidence weights"
```

---

### Task 8: Skill-level classification in skill_extraction

**Files:**
- Modify: `src/curriculum_agent/stages/skill_extraction.py:58-72` (`_SkillItem`), `:135-299` (`run`)
- Test: `tests/unit/test_skill_classification.py` (create)

**Interfaces:**
- Consumes: `SkillClassification`, `normalize_need_name`, `StakeholderType`, and the demand functions from Task 7.
- Produces: `classify_skills(raw_skills: list[dict[str, Any]], evidence_class_by_id: dict[str, str]) -> dict[str, str]`. The returned mapping is keyed by the **stripped display skill name** — names are compared after `normalize_need_name`, but the key handed back is the first spelling seen, so `run` looks a class up with `class_by_name.get(s["skill_name_th"].strip())`. Every raw skill whose name normalises the same receives the same class.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_skill_classification.py`:

```python
from __future__ import annotations

from curriculum_agent.stages.skill_extraction import classify_skills


def _raw(name: str, eid: str, *, relevant: bool = True) -> dict[str, object]:
    return {"skill_name_th": name, "evidence_id": eid, "is_field_relevant": relevant}


def test_a_skill_from_requirement_evidence_is_a_requirement():
    result = classify_skills([_raw("จรรยาบรรณวิชาชีพ", "E1")], {"E1": "requirement"})

    assert result["จรรยาบรรณวิชาชีพ"] == "requirement"


def test_two_distinct_evidence_items_make_a_need():
    result = classify_skills(
        [_raw("วิเคราะห์ข้อมูล", "E1"), _raw("วิเคราะห์ข้อมูล", "E2")],
        {"E1": "general", "E2": "general"},
    )

    assert result["วิเคราะห์ข้อมูล"] == "need"


def test_a_single_evidence_item_makes_a_want():
    result = classify_skills([_raw("เล่นดนตรีไทย", "E1")], {"E1": "general"})

    assert result["เล่นดนตรีไทย"] == "want"


def test_off_field_skill_is_unclassified():
    result = classify_skills(
        [_raw("ขับรถยนต์", "E1", relevant=False), _raw("ขับรถยนต์", "E2", relevant=False)],
        {"E1": "general", "E2": "general"},
    )

    assert result["ขับรถยนต์"] == "unclassified"


def test_requirement_beats_a_want_frequency_of_one():
    """A mandate does not become optional because few sources repeated it."""
    result = classify_skills([_raw("จรรยาบรรณวิชาชีพ", "E1")], {"E1": "requirement"})

    assert result["จรรยาบรรณวิชาชีพ"] == "requirement"


def test_requirement_beats_an_off_field_verdict():
    """Legal and institutional mandates stay in the pipeline whatever the model
    thinks of their field fit — the designer removes them, not the extractor."""
    result = classify_skills(
        [_raw("ปฏิบัติตามข้อบังคับสภาวิชาชีพ", "E1", relevant=False)], {"E1": "requirement"}
    )

    assert result["ปฏิบัติตามข้อบังคับสภาวิชาชีพ"] == "requirement"


def test_a_name_matching_a_requirement_skill_is_promoted():
    """Same capability, two sources: one mandates it, one merely mentions it.
    The mandate wins for both."""
    result = classify_skills(
        [_raw("ความปลอดภัยของข้อมูล", "E1"), _raw("  ความปลอดภัยของข้อมูล  ", "E2")],
        {"E1": "requirement", "E2": "general"},
    )

    assert result["ความปลอดภัยของข้อมูล"] == "requirement"


def test_names_are_matched_after_normalisation():
    result = classify_skills(
        [_raw("Data  Analysis", "E1"), _raw("data analysis", "E2")],
        {"E1": "general", "E2": "general"},
    )

    assert len(result) == 1
    assert next(iter(result.values())) == "need"


def test_missing_evidence_class_defaults_to_general():
    result = classify_skills([_raw("ทักษะลึกลับ", "E9")], {})

    assert result["ทักษะลึกลับ"] == "want"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_skill_classification.py -q`
Expected: FAIL — `ImportError: cannot import name 'classify_skills'`.

- [ ] **Step 3: Implement `classify_skills` and wire it into `run`**

In `skill_extraction.py`, add `is_field_relevant` to `_SkillItem` (after `evidence_span_th`, line 63):

```python
    is_field_relevant: bool = True
```

Add the function above `_compute_skill_importance`:

```python
def classify_skills(
    raw_skills: list[dict[str, Any]],
    evidence_class_by_id: dict[str, str],
) -> dict[str, str]:
    """Classify every extracted skill name, once the whole corpus is in hand.

    Returns a mapping from *display* skill name to SkillClassification. Names are
    matched after normalize_need_name, the same normaliser dedupe_with_bloom_max
    uses to collapse duplicates into one Need — two spellings that end up in the
    same Need therefore also share a class here.

    Runs after the extraction loop by necessity: need vs want is decided by how
    many distinct evidence items name a skill, which is not knowable while the
    corpus is still being read.

    Precedence, highest first:
      1. named by requirement evidence  → requirement
      2. name matches such a skill      → requirement
      3. is_field_relevant is False     → unclassified
      4. named by >1 evidence item      → need
      5. otherwise                      → want

    Rules 1-2 outrank 3 on purpose: a สภาวิชาชีพ mandate or the faculty's own
    vision stays in the pipeline whatever the extraction model thought of its
    field fit. Dropping it would be the code overruling a legal requirement.
    """
    eids_by_name: dict[str, set[str]] = {}
    relevant_by_name: dict[str, bool] = {}
    display_by_name: dict[str, str] = {}
    requirement_names: set[str] = set()

    for skill in raw_skills:
        name = str(skill["skill_name_th"])
        norm = normalize_need_name(name)
        if not norm:
            continue
        eid = str(skill["evidence_id"])
        eids_by_name.setdefault(norm, set()).add(eid)
        display_by_name.setdefault(norm, name.strip())
        # Any mention judged on-field keeps the name on-field: one model call
        # calling it off-field does not outvote another that did not.
        relevant_by_name[norm] = relevant_by_name.get(norm, False) or bool(
            skill.get("is_field_relevant", True)
        )
        if evidence_class_by_id.get(eid, "general") == "requirement":
            requirement_names.add(norm)

    classified: dict[str, str] = {}
    for norm, eids in eids_by_name.items():
        display = display_by_name[norm]
        if norm in requirement_names:
            classified[display] = "requirement"
        elif not relevant_by_name[norm]:
            classified[display] = "unclassified"
        elif len(eids) > 1:
            classified[display] = "need"
        else:
            classified[display] = "want"
    return classified
```

In `run`, replace the Step 2 block (lines 256-286) with:

```python
    # --- Step 2: classify every skill, then build ExtractedSkill objects ---
    evidence_class_by_id: dict[str, str] = {
        str(d["evidence_id"]): str(d.get("classification", "general"))
        for d in classified
        if d.get("evidence_id")
    }
    class_by_name = classify_skills(raw_skills, evidence_class_by_id)

    counts: dict[str, int] = {}
    for value in class_by_name.values():
        counts[value] = counts.get(value, 0) + 1
    logger.info(f"Stage 2: skill classification {counts}")

    extracted: list[ExtractedSkill] = []
    for s in raw_skills:
        extracted.append(
            ExtractedSkill(
                skill_id=str(uuid.uuid4()),
                program_id=program_id,
                skill_name_th=s["skill_name_th"],
                skill_name_en=s.get("skill_name_en"),
                ksec_category=KSECCategory(s["ksec_category"]),
                bloom_level=BloomLevel(s["bloom_level"]),
                evidence_span_th=s["evidence_span_th"],
                source_evidence_id=s["evidence_id"],
                source_stakeholder_type=StakeholderType(s["stakeholder_type"]),
                classification=class_by_name.get(s["skill_name_th"].strip(), "unclassified"),
                is_field_relevant=bool(s.get("is_field_relevant", True)),
                extraction_method="llm",
                confidence=s.get("confidence", 0.8),
                importance_score=importance_by_name.get(
                    normalize_need_name(s["skill_name_th"]), 0.0
                ),
            )
        )
```

Import `StakeholderType` from `curriculum_agent.models` at the top of the file.

Pass the program context into the prompt — replace line 176:

```python
            metadata = state.get("metadata") or {}
            messages = build_extract_skills_prompt(
                text_slice,
                evidence.classification,
                field_th=str(metadata.get("field", "")),
                program_name_th=str(metadata.get("name_th", "")),
            )
```

Hoist `metadata = state.get("metadata") or {}` to just below the `program_id` assignment so it is not re-read per item. `stakeholder_type_by_evidence` and the `importance_by_name` line above it are already in place from Task 7 — leave them where they are; the block above inserts `class_by_name` beside them.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_skill_classification.py tests/unit/test_demand.py -q`
Expected: PASS. `tests/unit/test_skill_extraction_cache.py` and `test_extraction_cache_contract.py` fail here because the extraction schema changed and the fingerprint moved — that is the intended behaviour; update their expected fingerprints in Task 10's cleanup sweep.

- [ ] **Step 5: Commit**

```bash
git add src/curriculum_agent/stages/skill_extraction.py tests/unit/test_skill_classification.py
git commit -m "feat(skill-extraction): classify skills after the corpus, with requirement winning"
```

---

### Task 9: need_combination on the new inputs

**Files:**
- Modify: `src/curriculum_agent/stages/need_combination.py:20,35-46,49-101,104-192`
- Test: `tests/unit/test_need_combination.py`

**Interfaces:**
- Consumes: `resolve_need_ksec`, `bucket_by_ksec` (Task 2), the demand functions (Task 7), `ExtractedSkill.classification` and `.source_stakeholder_type` (Task 2).
- Produces: `Need` rows carrying `source_stakeholder_types`, KSEC tags resolved per group, `classification_coverage` counted over member skills.

- [ ] **Step 1: Write the failing test**

Replace the `evidence` fixture and add cases in `tests/unit/test_need_combination.py`. The `_skill` helper gains the new fields:

```python
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
def evidence() -> list[dict[str, str]]:
    return [
        {"evidence_id": "E1", "classification": "requirement",
         "stakeholder_type": "professional_council"},
        {"evidence_id": "E2", "classification": "general", "stakeholder_type": "alumni"},
        {"evidence_id": "E3", "classification": "general", "stakeholder_type": "community"},
    ]
```

Add:

```python
async def test_ethics_and_character_skills_form_one_ec_need(
    evidence: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
):
    skills = [
        _skill("จรรยาบรรณวิชาชีพ", KSECCategory.E, "S1", "E1"),
        _skill("ความรับผิดชอบต่อหน้าที่", KSECCategory.C, "S2", "E2"),
    ]

    async def one_cluster(names: list[str]) -> list[list[int]]:
        return [list(range(len(names)))]

    monkeypatch.setattr(nc, "cluster_skill_names", one_cluster)
    monkeypatch.setattr(nc, "complete_light", _fake_summarize)
    _patch_repo(monkeypatch)

    state = await nc.run(
        {
            "program_id": "cs-test",
            "classified_evidence": evidence,
            "extracted_skills": [s.model_dump(mode="json") for s in skills],
        }
    )

    assert [n["ksec_category"] for n in state["needs"]] == ["EC"]


async def test_an_all_ethics_group_keeps_the_standalone_e_tag(
    evidence: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
):
    skills = [
        _skill("จรรยาบรรณวิชาชีพ", KSECCategory.E, "S1", "E1"),
        _skill("ความซื่อสัตย์ในวิชาชีพ", KSECCategory.E, "S2", "E2"),
    ]

    async def one_cluster(names: list[str]) -> list[list[int]]:
        return [list(range(len(names)))]

    monkeypatch.setattr(nc, "cluster_skill_names", one_cluster)
    monkeypatch.setattr(nc, "complete_light", _fake_summarize)
    _patch_repo(monkeypatch)

    state = await nc.run(
        {
            "program_id": "cs-test",
            "classified_evidence": evidence,
            "extracted_skills": [s.model_dump(mode="json") for s in skills],
        }
    )

    assert [n["ksec_category"] for n in state["needs"]] == ["E"]


async def test_needs_carry_their_source_stakeholder_types(
    evidence: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
):
    skills = [
        _skill("วิเคราะห์ข้อมูล", KSECCategory.S, "S1", "E1",
               stype=StakeholderType.PROFESSIONAL_COUNCIL),
        _skill("วิเคราะห์ข้อมูล", KSECCategory.S, "S2", "E2", stype=StakeholderType.ALUMNI),
    ]

    async def one_cluster(names: list[str]) -> list[list[int]]:
        return [list(range(len(names)))]

    monkeypatch.setattr(nc, "cluster_skill_names", one_cluster)
    monkeypatch.setattr(nc, "complete_light", _fake_summarize)
    _patch_repo(monkeypatch)

    state = await nc.run(
        {
            "program_id": "cs-test",
            "classified_evidence": evidence,
            "extracted_skills": [s.model_dump(mode="json") for s in skills],
        }
    )

    assert state["needs"][0]["source_stakeholder_types"] == ["professional_council", "alumni"]


async def test_a_want_only_group_is_optional(
    evidence: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
):
    skills = [
        _skill("เล่นดนตรีไทย", KSECCategory.S, "S1", "E3", classification="want"),
        _skill("จัดนิทรรศการ", KSECCategory.S, "S2", "E3", classification="want"),
    ]
    _patch_llm(monkeypatch)
    _patch_repo(monkeypatch)

    state = await nc.run(
        {
            "program_id": "cs-test",
            "classified_evidence": evidence,
            "extracted_skills": [s.model_dump(mode="json") for s in skills],
        }
    )

    assert all(n["is_optional"] for n in state["needs"])
```

Extract the existing inline `fake_summarize` into a module-level `_fake_summarize` so the new cases can share it:

```python
async def _fake_summarize(model, messages, **kw):  # noqa: ANN001, ANN003
    return nc._NeedStatement(
        statement_th="สามารถทำงานตามที่ตลาดต้องการ", statement_en="Market capability"
    )
```

Delete `test_want_only_need_is_marked_optional` — `test_a_want_only_group_is_optional` replaces it, since optionality is now decided by member skill classes rather than by the source evidence's class.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_need_combination.py -q`
Expected: FAIL — `ksec_category` comes back as `"E"` for the mixed group (no EC resolution) and `source_stakeholder_types` is missing.

- [ ] **Step 3: Rewire the stage**

In `need_combination.py`, change the imports:

```python
from curriculum_agent.stages.demand import (
    classification_coverage,
    compute_demand_score,
    is_optional_group,
    total_evidence_weight,
)
from curriculum_agent.stages.llm_clustering import cluster_skill_names, validate_assignments
from curriculum_agent.stages.need_grouping import (
    MIN_NEEDS,
    bucket_by_ksec,
    dedupe_with_bloom_max,
    merge_bloom,
    resolve_need_ksec,
)
```

Add `stakeholder_types: list[StakeholderType]` to `_Group` and replace `_build_groups` (lines 61-101) with:

```python
async def _build_groups(
    skills: list[ExtractedSkill],
    stakeholder_type_by_evidence: dict[str, str],
) -> list[_Group]:
    """Cluster within each KSEC bucket and score every resulting group.

    Bucketing before clustering is what guarantees a group never mixes tags; E and
    C share the EC bucket, and resolve_need_ksec hands back E or C when a group
    turns out to be purely one of them.
    """
    total_weight = total_evidence_weight(stakeholder_type_by_evidence)
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
            cls_coverage = classification_coverage([m.classification for m in members])
            stk_coverage: dict[str, int] = {}
            for m in members:
                key = m.source_stakeholder_type.value
                stk_coverage[key] = stk_coverage.get(key, 0) + 1
            # Enum declaration order puts external groups before internal ones,
            # which is the order the report shows them in.
            present = {m.source_stakeholder_type for m in members}
            groups.append(
                _Group(
                    ksec=resolve_need_ksec(members),
                    skill_ids=[m.skill_id for m in members],
                    evidence_ids=evidence_ids,
                    skill_names=[names[ni] for ni in name_indices],
                    bloom_level=merge_bloom([bloom_by_name[names[ni]] for ni in name_indices]),
                    demand_score=compute_demand_score(
                        evidence_ids, stakeholder_type_by_evidence, total_weight
                    ),
                    is_optional=is_optional_group(cls_coverage),
                    classification_coverage=cls_coverage,
                    stakeholder_coverage=stk_coverage,
                    stakeholder_types=[t for t in StakeholderType if t in present],
                )
            )
    return groups
```

In `run`, replace the `classification_by_evidence` / `total_req_need` block (lines 123-130) with:

```python
    stakeholder_type_by_evidence = {
        str(d["evidence_id"]): str(d.get("stakeholder_type", "employer"))
        for d in classified
        if d.get("evidence_id")
    }

    groups = await _build_groups(skills, stakeholder_type_by_evidence)
```

and add to the `Need(...)` construction, after `stakeholder_coverage`:

```python
                source_stakeholder_types=group.stakeholder_types,
```

Delete `_stakeholder_coverage` (lines 49-58) — coverage is now counted from the member skills, which carry their own provenance.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_need_combination.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/curriculum_agent/stages/need_combination.py tests/unit/test_need_combination.py
git commit -m "feat(need-combination): EC bucketing, skill-derived optionality, stakeholder provenance"
```

---

### Task 10: plo_report reduced to assembly; plo_synthesis and the routes follow

**Files:**
- Modify: `src/curriculum_agent/stages/plo_report.py` (full rewrite)
- Modify: `src/curriculum_agent/stages/plo_synthesis.py:81,275`
- Modify: `src/curriculum_agent/api/routes/plos.py:158-163`
- Delete: `src/curriculum_agent/prompts/plo_classify.py`, `tests/unit/test_plo_classify_prompt.py`
- Test: `tests/unit/test_plo_report.py` (rewrite)

**Interfaces:**
- Consumes: `PLO` without the four deleted fields (Task 2).
- Produces: `plo_report.run(state)` writing `state["plos"]` unchanged and `state["report"]` — a `dict[str, Any]` with keys `plos`, `needs_by_id`, `counts`.

- [ ] **Step 1: Write the failing test**

Replace `tests/unit/test_plo_report.py` with:

```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import PLO, BloomLevel, KSECCategory, Need, SMARTCheck
from curriculum_agent.stages import plo_report as pr


def _need(nid: str, ksec: KSECCategory = KSECCategory.S) -> Need:
    return Need(
        need_id=nid,
        program_id="cs-test",
        statement_th=f"ตลาดต้องการ {nid}",
        ksec_category=ksec,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=[f"S-{nid}"],
        source_evidence_ids=[f"E-{nid}"],
        freq=1,
        demand_score=0.7,
    )


def _plo(pid: str, need_ids: list[str], *, optional: bool = False) -> PLO:
    return PLO(
        plo_id=pid,
        program_id="cs-test",
        statement_th=f"วิเคราะห์งาน {pid} เพื่อเสนอแนวทางแก้ปัญหาได้",
        bloom_level=BloomLevel.ANALYZE,
        action_verb_th="วิเคราะห์",
        smart_check=SMARTCheck(
            specific=True, measurable=True, achievable=True, relevant=True, timely=True
        ),
        source_need_ids=need_ids,
        source_evidence_ids=[f"E-{n}" for n in need_ids],
        rationale_th="ตรงกับความต้องการของตลาด",
        is_optional=optional,
    )


async def test_run_assembles_without_calling_an_llm(monkeypatch: pytest.MonkeyPatch):
    """The stage no longer classifies, so it must not reach the network at all."""
    monkeypatch.setattr(
        pr.NeedRepository, "list_by_program", AsyncMock(return_value=[_need("N1")])
    )
    monkeypatch.setattr(pr.PLORepository, "bulk_insert", AsyncMock())

    state = await pr.run(
        {"program_id": "cs-test", "plos": [_plo("PLO1", ["N1"]).model_dump(mode="json")]}
    )

    assert state["report"]["counts"]["total"] == 1
    assert state["report"]["needs_by_id"]["N1"]["ksec_category"] == "S"


async def test_report_counts_split_core_and_optional(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        pr.NeedRepository, "list_by_program", AsyncMock(return_value=[_need("N1"), _need("N2")])
    )
    monkeypatch.setattr(pr.PLORepository, "bulk_insert", AsyncMock())

    state = await pr.run(
        {
            "program_id": "cs-test",
            "plos": [
                _plo("PLO1", ["N1"]).model_dump(mode="json"),
                _plo("OPT1", ["N2"], optional=True).model_dump(mode="json"),
            ],
        }
    )

    assert state["report"]["counts"] == {"total": 2, "core": 1, "optional": 1, "escalated": 0}


async def test_run_without_plos_is_an_error(monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(ValueError, match="run PLO synthesis first"):
        await pr.run({"program_id": "cs-test", "plos": []})


def test_plo_no_longer_carries_the_classification_fields():
    for gone in (
        "is_subject_specific",
        "classification",
        "classification_method",
        "classification_rationale_th",
    ):
        assert gone not in PLO.model_fields
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_plo_report.py -q`
Expected: FAIL — `state["report"]` does not exist; the stage still calls `complete_light`.

- [ ] **Step 3: Rewrite the stage**

Replace `src/curriculum_agent/stages/plo_report.py` in full:

```python
from __future__ import annotations

from typing import Any

from loguru import logger

from curriculum_agent.data.repositories import NeedRepository, PLORepository
from curriculum_agent.graph import AgentState
from curriculum_agent.models import PLO


async def run(state: AgentState) -> AgentState:
    """PLO Report stage: assemble the reviewable report and persist the PLOs.

    This stage used to classify each PLO generic vs specific. That split came from
    the SS/GS KSEC tags, which no longer exist — a PLO's competency domain is the
    KSEC tag of the Needs behind it, and the report shows that directly instead of
    reducing it to a binary. No LLM call remains here.

    The stage keeps its own checkpoint: synthesis produces outcomes, and this is
    where a designer reviews the finished set and exports it.
    """
    program_id = state.get("program_id", "unknown")
    plo_dicts = state.get("plos", [])
    if not plo_dicts:
        raise ValueError(
            f"PLO report: no PLOs for program '{program_id}' — run PLO synthesis first"
        )

    plos = [PLO.model_validate(d) for d in plo_dicts]
    needs = await NeedRepository().list_by_program(program_id)

    core = sum(1 for p in plos if not p.is_optional)
    escalated = sum(1 for p in plos if p.smart_escalated)
    logger.info(
        f"PLO report: {len(plos)} PLOs ({core} core, {len(plos) - core} optional, "
        f"{escalated} escalated for repair)"
    )

    report: dict[str, Any] = {
        "plos": [p.model_dump(mode="json") for p in plos],
        # Keyed for drill-down: the page resolves each PLO's source_need_ids
        # against this rather than issuing a request per outcome.
        "needs_by_id": {n.need_id: n.model_dump(mode="json") for n in needs},
        "counts": {
            "total": len(plos),
            "core": core,
            "optional": len(plos) - core,
            "escalated": escalated,
        },
    }

    await PLORepository().bulk_insert(plos)

    state["plos"] = report["plos"]
    state["report"] = report
    state["current_stage"] = "plo_report"
    return state
```

Add `report: dict[str, Any]` to `AgentState` in `graph.py` alongside the other stage keys.

- [ ] **Step 4: Follow through in synthesis and the route**

In `plo_synthesis.py`, delete the `is_subject_specific=...` argument at line 275 and the `- \`is_subject_specific\`: derived from the contributing Needs' KSEC tags.` docstring bullet at line 81. Remove `KSECCategory` from its imports if nothing else in the file uses it.

In `api/routes/plos.py`, replace lines 158-163 with:

```python
    update_fields: dict[str, object] = {"version": match.version + 1, "program_id": program_id}
    updated = plo.model_copy(update=update_fields)
```

Delete the dead prompt and its test:

```bash
git rm src/curriculum_agent/prompts/plo_classify.py tests/unit/test_plo_classify_prompt.py
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_plo_report.py tests/unit/test_plo_count_policy.py tests/unit/test_plo_one_to_one.py tests/unit/test_plo_id_scheme.py -q`
Expected: PASS.

Then run the whole suite: `uv run pytest -q`. Fix any remaining references to deleted fields or enum members in `tests/` — expected sites are `tests/conftest.py` (the `program_metadata` fixture), `tests/unit/test_state_safety.py`, `tests/unit/test_smart_retry_loop.py`, `tests/unit/test_designer_note.py`, `tests/unit/test_needs_router.py`, `tests/unit/test_skill_dedupe.py`, `tests/unit/test_extraction_cache_contract.py`, `tests/unit/test_skill_extraction_cache.py`, `tests/unit/test_llm_clustering.py`, `tests/integration/test_end_to_end.py`, and `tests/integration/test_stage_3_plo.py`.

- [ ] **Step 6: Commit**

```bash
git add -A src/curriculum_agent tests/
git commit -m "refactor(plo-report): drop generic/specific classification, assemble the report only"
```

---

### Task 11: Frontend — one stakeholder module, five pages

**Files:**
- Create: `frontend/src/constants/stakeholder.ts`
- Modify: `frontend/src/pages/StakeholderNeeds.tsx:6-22,44`, `frontend/src/pages/components/SkillTable.tsx:3-58,161-170`, `frontend/src/pages/components/NeedCard.tsx:4-30,62-72`, `frontend/src/pages/PloSynthesis.tsx:8-30,294-299,417-419`, `frontend/src/pages/PloReport.tsx` (rewrite)

**Interfaces:**
- Consumes: the API shapes from Tasks 2 and 10 (`source_stakeholder_type` and `classification` on a skill, `source_stakeholder_types` on a Need, `report.counts` from `plo_report`).
- Produces: `STAKEHOLDER_LABELS`, `STAKEHOLDER_GROUPS`, `stakeholderLabel(value: string): string`, `KSEC_LABEL`, `KSEC_COLOR`, `ksecLabel(value: string): string`, `ksecColor(value: string): string`, `CLASS_STYLE`, `classStyle(value: string): { label: string; cls: string }`.

- [ ] **Step 1: Create the shared module**

`frontend/src/constants/stakeholder.ts`:

```ts
// The single source for stakeholder and classification presentation. Five pages
// each carried their own copy of this before, and none of them agreed: one
// omitted `parent` (making it unreachable in the only dropdown that creates
// evidence), one named types that never existed in the API, and the need and
// requirement badge colours were swapped between two of them.

export const STAKEHOLDER_LABELS: Record<string, string> = {
  professional_council: 'สภาวิชาชีพ',
  employer: 'ผู้ใช้บัณฑิต',
  industry: 'ภาคอุตสาหกรรม',
  alumni: 'ศิษย์เก่า',
  expert: 'ผู้ทรงคุณวุฒิ',
  community: 'ชุมชนและสังคม',
  partner_institution: 'สถาบันคู่ความร่วมมือ',
  applicant: 'ผู้สมัครเรียน',
  parent: 'ผู้ปกครอง',
  institutional_direction: 'วิสัยทัศน์/พันธกิจ/อัตลักษณ์',
  administrator: 'ผู้บริหาร',
  program_committee: 'คณะกรรมการหลักสูตร',
  faculty: 'อาจารย์',
  student: 'ผู้เรียน',
  support_staff: 'บุคลากรสายสนับสนุน',
}

export const STAKEHOLDER_GROUPS: { label: string; types: string[] }[] = [
  {
    label: 'ภายนอก',
    types: [
      'professional_council', 'employer', 'industry', 'alumni', 'expert',
      'community', 'partner_institution', 'applicant', 'parent',
    ],
  },
  {
    label: 'ภายใน',
    types: [
      'institutional_direction', 'administrator', 'program_committee',
      'faculty', 'student', 'support_staff',
    ],
  },
]

export const stakeholderLabel = (value: string): string =>
  STAKEHOLDER_LABELS[value] ?? value

export const KSEC_LABEL: Record<string, string> = {
  K: 'K · ความรู้',
  S: 'S · ทักษะ',
  EC: 'E|C · คุณธรรมและคุณลักษณะ',
  E: 'E · คุณธรรมจริยธรรม',
  C: 'C · คุณลักษณะบุคคล',
}

export const KSEC_COLOR: Record<string, string> = {
  K: 'bg-sky-100 text-sky-800',
  S: 'bg-emerald-100 text-emerald-800',
  EC: 'bg-violet-100 text-violet-800',
  E: 'bg-rose-100 text-rose-800',
  C: 'bg-amber-100 text-amber-800',
}

export const ksecLabel = (value: string): string => KSEC_LABEL[value] ?? value
export const ksecColor = (value: string): string =>
  KSEC_COLOR[value] ?? 'bg-gray-100 text-gray-600'

// Evidence carries requirement/general; a skill carries all four.
export const CLASS_STYLE: Record<string, { label: string; cls: string }> = {
  requirement: { label: 'ข้อกำหนด', cls: 'bg-blue-100 text-blue-700' },
  need: { label: 'ความต้องการ', cls: 'bg-green-100 text-green-700' },
  want: { label: 'ความปรารถนา', cls: 'bg-yellow-100 text-yellow-700' },
  general: { label: 'ทั่วไป', cls: 'bg-slate-100 text-slate-600' },
  unclassified: { label: 'ยังไม่จำแนก', cls: 'bg-gray-100 text-gray-500' },
}

export const classStyle = (value: string): { label: string; cls: string } =>
  CLASS_STYLE[value] ?? CLASS_STYLE.unclassified
```

- [ ] **Step 2: Point StakeholderNeeds at it**

Delete the local `STAKEHOLDER_LABELS` (lines 6-15) and `CLASS_STYLE` (lines 17-22) and import instead:

```ts
import { STAKEHOLDER_GROUPS, classStyle, stakeholderLabel } from '../constants/stakeholder'
```

Replace every `STAKEHOLDER_LABELS[x]` with `stakeholderLabel(x)` and every `CLASS_STYLE[x]` with `classStyle(x)`. Change the stakeholder `<select>` to render grouped options:

```tsx
<select
  value={stakeholderType}
  onChange={e => setStakeholderType(e.target.value)}
  className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
>
  {STAKEHOLDER_GROUPS.map(g => (
    <optgroup key={g.label} label={g.label}>
      {g.types.map(t => (
        <option key={t} value={t}>{stakeholderLabel(t)}</option>
      ))}
    </optgroup>
  ))}
</select>
```

- [ ] **Step 3: Add provenance to SkillTable**

Delete the local `KSEC_LABEL`, `KSEC_COLOR`, and `CLASS_COLOR` (lines 21-51) and import from the module. Add `source_stakeholder_type: string` and `classification: string` to `SkillRow`, add `'stakeholder'` to `SortKey`, and add a column between KSEC and the class badge:

```tsx
const COLUMNS: { key: SortKey; label: string; numeric?: boolean }[] = [
  { key: 'skill_name_th', label: 'Skill' },
  { key: 'bloom_level', label: "Bloom's" },
  { key: 'ksec_category', label: 'KSEC' },
  { key: 'stakeholder', label: 'ที่มา' },
  { key: 'classification', label: 'Class' },
]
```

The sort accessor changes to read from the row rather than the evidence map, since the skill now carries both fields:

```tsx
const value = (s: SkillRow): string | number =>
  sortKey === 'stakeholder' ? s.source_stakeholder_type : (s[sortKey] as string | number)
```

The two cells:

```tsx
<td className="px-3 py-2 text-xs text-gray-600">
  {stakeholderLabel(s.source_stakeholder_type)}
</td>
<td className="px-3 py-2">
  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${classStyle(s.classification).cls}`}>
    {classStyle(s.classification).label}
  </span>
</td>
```

The KSEC cell uses `ksecColor(s.ksec_category)` and `ksecLabel(s.ksec_category)` — this removes the unguarded `CLASS_COLOR[...]` lookup at line 167 that could yield `undefined`.

- [ ] **Step 4: Show stakeholders on NeedCard**

Delete the local `KSEC_LABEL` (lines 24-30), import `ksecColor`, `ksecLabel`, `stakeholderLabel`, add `source_stakeholder_types: string[]` to `NeedRow`, and render the badges in the metadata row:

```tsx
<span className={`rounded px-1.5 py-0.5 ${ksecColor(need.ksec_category)}`}>
  {ksecLabel(need.ksec_category)}
</span>
{need.source_stakeholder_types.map(t => (
  <span key={t} className="rounded bg-gray-100 px-1.5 py-0.5 text-gray-700">
    {stakeholderLabel(t)}
  </span>
))}
```

Update the `Demand` tooltip text, which still describes the removed breadth term:

```tsx
<span title="สัดส่วนน้ำหนักของหลักฐานที่กล่าวถึงความต้องการนี้">
  Demand {(need.demand_score * 100).toFixed(0)}%
</span>
```

- [ ] **Step 5: Rewrite PloReport and trim PloSynthesis**

In `PloSynthesis.tsx`: delete the local stakeholder map (lines 294-299) in favour of `stakeholderLabel`, remove `is_subject_specific` from the `PLO` interface (line 22) and `classification` (line 30), and delete the `subject-specific` badge at lines 417-419.

Rewrite `PloReport.tsx` as a single list. Delete `effectiveClass`, `flip`, `ClassBadge`, `ReportGroup`, the generic/specific matrix, and the `PUT` call that wrote a classification. The page shows, per PLO: the statement, `plo_id`, Bloom level, the KSEC tags of its source Needs, `soft_flags`, an escalation warning when `smart_escalated`, and an expandable evidence trail. Keep the header counts, sourced from `report.counts`:

```tsx
<div className="flex gap-4 text-sm text-gray-600">
  <span><b className="text-gray-700">{counts.total}</b> ทั้งหมด</span>
  <span><b className="text-gray-700">{counts.core}</b> หลัก</span>
  <span><b className="text-gray-700">{counts.optional}</b> เสริม</span>
  {counts.escalated > 0 && (
    <span className="text-amber-700"><b>{counts.escalated}</b> ต้องแก้ไข</span>
  )}
</div>
```

Keep the existing มคอ.2 and CHECO export buttons and their handlers exactly as they are.

- [ ] **Step 6: Verify and commit**

Run: `cd frontend; npm run lint; npm run build`
Expected: 0 errors. The one pre-existing `Pipeline.tsx:221` warning remains.

```bash
git add frontend/src
git commit -m "feat(ui): one stakeholder constants module, skill provenance, simplified PLO report"
```

---

### Task 12: Documentation

**Files:**
- Modify: `CLAUDE.md`, `.claude/skills/curriculum-design-agent/SKILL.md`, `.claude/skills/curriculum-design-agent/references/obe-principles.md`, `.claude/skills/curriculum-design-agent/references/prompts.md`, `.claude/skills/curriculum-design-agent/references/data-schemas.md`

- [ ] **Step 1: Update CLAUDE.md**

In the pipeline description, note that stakeholder needs no longer calls an LLM. Rewrite immutable rule 2's wording to name skill-level classification. Add to "Common pitfalls":

```markdown
- **Don't classify evidence with an LLM.** `requirement` is derived in code from
  `StakeholderType` (`classify_evidence_type`); `need`/`want`/`unclassified` are
  decided per skill in `skill_extraction.classify_skills` after every evidence item
  has been extracted, because frequency is a cross-evidence property. Re-adding a
  per-item classification call reintroduces both the cost and the wrong question.
- **Requirement wins.** A skill named by สภาวิชาชีพ or by the program's own
  vision stays `requirement` even when the extraction model marked it off-field.
  Do not reorder those precedence rules.
```

Update the KSEC pitfall bullet: the buckets are now `K`, `S`, `EC`, and E/C skills deliberately share one bucket while `resolve_need_ksec` hands back a standalone `E` or `C` for a pure group.

- [ ] **Step 2: Update the skill and its references**

In `SKILL.md`: pipeline step 2 is a code lookup, not a classify call; step 5 (`PLO report`) is summary and export, not generic/specific classification. Delete rule 6 ("60–70% subject-specific") — the split it measured no longer exists.

In `references/data-schemas.md`: replace the `KSECCategory` block (lines 83-93) with the five new members and the skill-vs-Need distinction; add `classification`, `is_field_relevant`, `source_stakeholder_type` to the `ExtractedSkill` schema and `source_stakeholder_types` to `Need`; delete the four PLO fields; document `StakeholderGroup` and `STAKEHOLDER_GROUP`.

In `references/prompts.md`: delete the `classify_evidence` and `plo_classify` sections; update the `extract_skills` section for the two new parameters, the `is_field_relevant` output field, and the `K|S|E|C` tag set.

In `references/obe-principles.md`: remove the generic/specific balance criterion from the readiness checklist and any KSEC reference to `SS`/`GS`.

- [ ] **Step 3: Full verification**

```bash
uv run pytest -q
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
cd frontend; npm run lint; npm run build
```

Expected: all green. `config.py:32-33` may still report two pre-existing mypy errors (`Name "light_model" already defined`) — these predate this work and are not yours to fix.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md .claude/skills/curriculum-design-agent/
git commit -m "docs: describe skill-level classification and the new stakeholder taxonomy"
```

---

## Verification checklist

Run after Task 12, before finishing the branch:

- [ ] `uv run pytest -q` — all pass
- [ ] `uv run alembic upgrade head` then `downgrade -1` then `upgrade head` — clean round trip
- [ ] `GET /programs/{id}/evidence/` returns 200 on a database that held rows with the four deleted stakeholder types (the `stakeholder_coverage` key-validation hazard)
- [ ] No `grep -r "SS\|GS" src/` hits in a KSEC context
- [ ] No remaining import of `classify_evidence` or `plo_classify`
- [ ] `frontend/src` has exactly one definition of a stakeholder label map
