# PLO Agentic Design System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the restored codebase into a PLO-focused 5-stage pipeline (intake → stakeholder_needs → skill_extraction → plo_synthesis → plo_report) with evidence-classification weighting, Bloom-level cluster tagging, a hard/soft SMART retry loop, optional PLOs from want-evidence, and a 6–10 PLO policy.

**Architecture:** LangGraph state machine (already 5-stage, YLO detached); each feature lands as changes to one stage handler plus its prompt file, Pydantic model, ORM column set, and UI page. One Alembic migration carries all schema changes. YLO code is deleted first so everything after compiles against the final model set.

**Tech Stack:** Python 3.11+, Pydantic v2, LangGraph, Instructor/Ollama (`complete_light`/`complete_heavy`), SQLAlchemy 2 + Alembic, FastAPI, React 19 + Vite + TS + Tailwind, pytest (asyncio_mode=auto).

**Spec:** `docs/superpowers/specs/2026-07-09-plo-agentic-design-design.md`

## Global Constraints

- Python ≥ 3.11, deps via `uv` (`uv run <cmd>` for everything)
- Type hints on every signature; `from __future__ import annotations`
- Thai for student-facing strings; English code/comments/logs; `loguru` only
- LLM output only via Instructor → Pydantic (`complete_light` / `complete_heavy` from `curriculum_agent.llm`)
- Forbidden words in outcome statements: รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก
- Main PLO count: **6–10** (optional PLOs excluded from the count)
- Every PLO: non-empty `source_cluster_ids` + `source_evidence_ids`
- Tests: `uv run pytest` — asyncio_mode=auto (no `@pytest.mark.asyncio`)
- Lint gate before each commit: `uv run ruff check src/ tests/ && uv run ruff format src/ tests/`

---

### Task 1: Remove YLO code

**Files:**
- Delete: `src/curriculum_agent/stages/ylo_derivation.py`, `src/curriculum_agent/prompts/stage_4_ylo.py`, `src/curriculum_agent/api/routes/ylos.py`, `frontend/src/pages/YloDerivation.tsx`, `tests/unit/test_ylo_matrix.py`
- Modify: `src/curriculum_agent/models.py` (remove `YLO`, `YLOMatrix` classes, lines ~203–270), `src/curriculum_agent/graph.py` (remove `stage_4_ylo_derivation`, `review_ylo_matrix`, `ylo_matrix` state key), `src/curriculum_agent/data/repositories.py` (remove `YLORepository` incl. `save_matrix`/`get_matrix`), `src/curriculum_agent/api/main.py:13,69` (remove `ylos` import + router), `frontend/src/App.tsx:21` (remove YLO route + import), `frontend/src/components/StageLayout.tsx` (remove YLO nav entry if present)
- Keep: `src/curriculum_agent/data/orm.py` `YLOTable` (dropped by the Task 3 migration, ORM class removed there too)

**Interfaces:**
- Produces: a codebase with no `YLO`/`YLOMatrix` symbols outside `orm.py`; `AgentState` without `ylo_matrix`.

- [ ] **Step 1: Delete the five files**

```bash
git rm src/curriculum_agent/stages/ylo_derivation.py src/curriculum_agent/prompts/stage_4_ylo.py src/curriculum_agent/api/routes/ylos.py frontend/src/pages/YloDerivation.tsx tests/unit/test_ylo_matrix.py
```

- [ ] **Step 2: Remove YLO from `models.py`** — delete the `# Stage 4` section (classes `YLO` and `YLOMatrix`, currently lines 201–270). `BLOOM_ORDER`/`KRATHWOHL_ORDER` stay (used by Bloom tagging later). Also change `StageCheckpoint.stage` Literal: replace `"ylo_derivation"` with `"plo_report"`.

- [ ] **Step 3: Remove YLO from `graph.py`** — delete `stage_4_ylo_derivation` node fn (lines 76–78), `review_ylo_matrix` (109–113), and the `ylo_matrix: dict` key in `AgentState` (line 47). Update `review_plos` interrupt message to `"Stage 3 complete — review/edit PLOs before PLO report"`.

- [ ] **Step 4: Remove `YLORepository`** from `repositories.py` (lines ~171–197) and its `YLO`/`YLOMatrix` imports. Remove `ylos` import + `include_router` line from `api/main.py`. Remove YLO route/import from `App.tsx` and nav entry from `StageLayout.tsx`.

- [ ] **Step 5: Verify no dangling references**

Run: `grep -rn "YLO\|ylo" src/ tests/ frontend/src/ --include="*.py" --include="*.tsx" --include="*.ts" | grep -v orm.py | grep -v "Krathwohl"`
Expected: no matches (case-sensitive review of anything that appears).

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest`
Expected: PASS (YLO tests deleted; nothing else imports YLO). Fix any residual import errors by deleting the referencing YLO-only code.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "refactor: remove YLO code — agent scope ends at PLO"
```

---

### Task 2: New model fields (SkillCluster + PLO)

**Files:**
- Modify: `src/curriculum_agent/models.py`
- Test: `tests/unit/test_models.py` (append)

**Interfaces:**
- Produces: `SkillCluster.bloom_level: BloomLevel | None`, `SkillCluster.krathwohl_level: KrathwohlLevel | None`, `SkillCluster.is_optional: bool = False`, `SkillCluster.classification_coverage: dict[str, int] = {}`; `PLO.smart_retry_count: int = 0`, `PLO.smart_escalated: bool = False`, `PLO.soft_flags: list[str] = []`, `PLO.is_optional: bool = False`.

- [ ] **Step 1: Write failing tests** (append to `tests/unit/test_models.py`; reuse the file's existing valid-PLO/cluster fixture helpers if present, else construct inline like its other tests)

```python
def test_skill_cluster_new_field_defaults():
    c = SkillCluster(
        cluster_id="c1", program_id="p1", canonical_name_th="วิเคราะห์ข้อมูล",
        description_th="กลุ่มทักษะวิเคราะห์ข้อมูล", skill_type=SkillType.KNOWLEDGE,
        is_subject_specific=True, member_skill_ids=["s1"],
        source_evidence_ids=["e1"], demand_score=0.5,
    )
    assert c.bloom_level is None
    assert c.krathwohl_level is None
    assert c.is_optional is False
    assert c.classification_coverage == {}


def test_plo_new_field_defaults():
    plo = PLO(
        plo_id="PLO1", program_id="p1",
        statement_th="วิเคราะห์ข้อมูลด้วยเทคนิคทางสถิติได้",
        domain=Domain.COGNITIVE, bloom_level=BloomLevel.ANALYZE,
        is_subject_specific=True, action_verb_th="วิเคราะห์",
        smart_check=SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True),
        source_cluster_ids=["c1"], source_evidence_ids=["e1"],
        rationale_th="จำเป็นต่อวิชาชีพ",
    )
    assert plo.smart_retry_count == 0
    assert plo.smart_escalated is False
    assert plo.soft_flags == []
    assert plo.is_optional is False
```

- [ ] **Step 2: Run to verify fail** — `uv run pytest tests/unit/test_models.py -k "new_field" -v` → FAIL (unexpected keyword / missing attribute)

- [ ] **Step 3: Add the fields**

In `SkillCluster` (after `sample_quotes_th`):

```python
    bloom_level: BloomLevel | None = None
    krathwohl_level: KrathwohlLevel | None = None
    is_optional: bool = False
    classification_coverage: dict[str, int] = Field(default_factory=dict)
```

In `PLO` (after `classification_rationale_th`):

```python
    smart_retry_count: int = 0
    smart_escalated: bool = False
    soft_flags: list[str] = Field(default_factory=list)
    is_optional: bool = False
```

Also amend `PLO.check_no_forbidden_words`: an escalated PLO is allowed to carry forbidden words (it exists precisely so a human can fix it) — this exemption is part of the validator, not a bypass:

```python
    @model_validator(mode="after")
    def check_no_forbidden_words(self) -> PLO:
        if self.smart_escalated:
            return self  # kept for human review; SMART gate already failed it loudly
        for word in FORBIDDEN_WORDS_TH:
            ...
```

Add to the Step 1 tests:

```python
def test_escalated_plo_may_carry_forbidden_word():
    plo = PLO(
        plo_id="PLO9", program_id="p1",
        statement_th="เข้าใจหลักการวิเคราะห์ข้อมูล",  # forbidden word, but escalated
        domain=Domain.COGNITIVE, bloom_level=BloomLevel.ANALYZE,
        is_subject_specific=True, action_verb_th="วิเคราะห์",
        smart_check=SMARTCheck(specific=True, measurable=False, achievable=True, relevant=True, timely=True),
        source_cluster_ids=["c1"], source_evidence_ids=["e1"],
        rationale_th="เหตุผล", smart_escalated=True,
    )
    assert plo.smart_escalated is True
```

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_models.py -v` → PASS

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: add SMART bookkeeping + optional/Bloom fields to PLO and SkillCluster models"`

---

### Task 3: ORM columns + Alembic migration

**Files:**
- Modify: `src/curriculum_agent/data/orm.py` (add columns; delete `YLOTable` class)
- Create: `migrations/versions/<generated>_plo_agentic_fields.py`

**Interfaces:**
- Consumes: Task 2 model fields (column names identical — `_row_to_dict`/`model_dump` mapping in repositories is generic, no repo change needed).
- Produces: DB schema with new columns; `ylos` table dropped.

- [ ] **Step 1: Add columns to `orm.py`**

`ClusterTable` (after `sample_quotes_th`):

```python
    bloom_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    krathwohl_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False)
    classification_coverage: Mapped[dict] = mapped_column(JSONB, default=dict)
```

`PLOTable` (after `classification_rationale_th`):

```python
    smart_retry_count: Mapped[int] = mapped_column(Integer, default=0)
    smart_escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    soft_flags: Mapped[list] = mapped_column(JSONB, default=list)
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False)
```

Delete the whole `YLOTable` class.

- [ ] **Step 2: Write the migration** — `uv run alembic revision -m "plo agentic fields"` (down_revision must be `c29520094a26`), then fill in:

```python
def upgrade() -> None:
    op.add_column("clusters", sa.Column("bloom_level", sa.String(20), nullable=True))
    op.add_column("clusters", sa.Column("krathwohl_level", sa.String(20), nullable=True))
    op.add_column("clusters", sa.Column("is_optional", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("clusters", sa.Column("classification_coverage", postgresql.JSONB(), nullable=False, server_default="{}"))
    op.add_column("plos", sa.Column("smart_retry_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("plos", sa.Column("smart_escalated", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("plos", sa.Column("soft_flags", postgresql.JSONB(), nullable=False, server_default="[]"))
    op.add_column("plos", sa.Column("is_optional", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.drop_table("ylos")


def downgrade() -> None:
    op.create_table(
        "ylos",
        sa.Column("ylo_id", sa.String(), primary_key=True),
        sa.Column("program_id", sa.String(), sa.ForeignKey("programs.program_id")),
        sa.Column("parent_plo_id", sa.String(), sa.ForeignKey("plos.plo_id")),
        sa.Column("year", sa.Integer()),
        sa.Column("statement_th", sa.Text()),
        sa.Column("statement_en", sa.Text(), nullable=True),
        sa.Column("bloom_level", sa.String(20), nullable=True),
        sa.Column("krathwohl_level", sa.String(20), nullable=True),
        sa.Column("action_verb_th", sa.Text()),
        sa.Column("smart_check", postgresql.JSONB()),
        sa.Column("rationale_th", sa.Text()),
        sa.Column("version", sa.Integer(), server_default="1"),
    )
    for col in ("is_optional", "soft_flags", "smart_escalated", "smart_retry_count"):
        op.drop_column("plos", col)
    for col in ("classification_coverage", "is_optional", "krathwohl_level", "bloom_level"):
        op.drop_column("clusters", col)
```

(Imports: `import sqlalchemy as sa`, `from sqlalchemy.dialects import postgresql`.)

- [ ] **Step 3: Apply against the dev DB** — start services if down (`docker compose up -d`), then `uv run alembic upgrade head`
Expected: `Running upgrade c29520094a26 -> <newrev>`

- [ ] **Step 4: Sanity + suite** — `uv run pytest` → PASS

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: migration for SMART/Bloom/optional columns, drop ylos table"`

---

### Task 4: Evidence-classification weighting in skill extraction

**Files:**
- Modify: `src/curriculum_agent/stages/skill_extraction.py:81-88` (`_compute_demand_score`), `:97-133` (extraction context), `:197-262` (cluster build)
- Test: `tests/unit/test_demand_score.py` (create)

**Interfaces:**
- Produces: `_compute_demand_score(source_evidence_ids: list[str], stakeholder_coverage: dict, total_req_need_evidence: int, classification_by_evidence: dict[str, str]) -> tuple[float, bool, dict[str, int]]` returning `(demand_score, is_optional, classification_coverage)`.
- Rule: score counts **requirement + need evidence only** (want weight = 0); `is_optional=True` when want-evidence count > requirement+need count within the cluster; coverage = counts per classification.

- [ ] **Step 1: Write failing tests** (`tests/unit/test_demand_score.py`)

```python
from curriculum_agent.stages.skill_extraction import _compute_demand_score


def _classify(**kw: str) -> dict[str, str]:
    return dict(kw)


def test_want_evidence_contributes_zero_weight():
    cls = _classify(e1="need", e2="requirement", e3="want")
    score_with_want, _, _ = _compute_demand_score(["e1", "e2", "e3"], {"employer": 3}, 2, cls)
    score_without, _, _ = _compute_demand_score(["e1", "e2"], {"employer": 2}, 2, cls)
    assert score_with_want == score_without  # e3 (want) adds nothing


def test_majority_want_cluster_is_optional():
    cls = _classify(e1="want", e2="want", e3="need")
    _, is_optional, coverage = _compute_demand_score(["e1", "e2", "e3"], {"employer": 3}, 1, cls)
    assert is_optional is True
    assert coverage == {"want": 2, "need": 1}


def test_requirement_and_need_cluster_not_optional():
    cls = _classify(e1="requirement", e2="need")
    score, is_optional, coverage = _compute_demand_score(["e1", "e2"], {"employer": 1, "alumni": 1}, 2, cls)
    assert is_optional is False
    assert score > 0
    assert coverage == {"requirement": 1, "need": 1}


def test_unclassified_treated_as_need():
    cls = _classify(e1="unclassified")
    score, is_optional, _ = _compute_demand_score(["e1"], {"employer": 1}, 1, cls)
    assert is_optional is False
    assert score > 0
```

- [ ] **Step 2: Run to fail** — `uv run pytest tests/unit/test_demand_score.py -v` → FAIL (signature mismatch)

- [ ] **Step 3: Implement** — replace `_compute_demand_score`:

```python
_WEIGHTED_CLASSES = {"requirement", "need", "unclassified"}


def _compute_demand_score(
    source_evidence_ids: list[str],
    stakeholder_coverage: dict,
    total_req_need_evidence: int,
    classification_by_evidence: dict[str, str],
) -> tuple[float, bool, dict[str, int]]:
    """Score from requirement+need evidence only; want evidence carries zero weight.

    Returns (demand_score, is_optional, classification_coverage).
    """
    coverage: dict[str, int] = {}
    weighted = 0
    want = 0
    for eid in set(source_evidence_ids):
        cls = classification_by_evidence.get(eid, "unclassified")
        coverage[cls] = coverage.get(cls, 0) + 1
        if cls in _WEIGHTED_CLASSES:
            weighted += 1
        elif cls == "want":
            want += 1

    freq = weighted / max(total_req_need_evidence, 1)
    breadth = len(stakeholder_coverage) / max(len(StakeholderType), 1)
    score = round(min(freq * 0.6 + breadth * 0.4, 1.0), 4)
    is_optional = want > weighted
    return score, is_optional, coverage
```

- [ ] **Step 4: Wire into `run()`** — in the cluster loop, build the classification map once before the loop and change the call site:

```python
    classification_by_evidence = {
        d.get("evidence_id"): d.get("classification", "unclassified") for d in classified
    }
    total_req_need = sum(
        1 for c in classification_by_evidence.values() if c in _WEIGHTED_CLASSES
    )
```

and replace the `_compute_demand_score(...)` call:

```python
        demand, is_optional, cls_coverage = _compute_demand_score(
            source_eids, stk_coverage, total_req_need, classification_by_evidence
        )
```

then pass to the `SkillCluster(...)` constructor: `is_optional=is_optional, classification_coverage=cls_coverage,` (demand stays `demand_score=demand`; `is_common_need=demand > 0.4` unchanged but add `and not is_optional`).

- [ ] **Step 5: Extraction context** — in the per-evidence LLM call, prepend the classification to the user message so extraction knows the evidence class:

```python
            messages = [
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": f"[ประเภทหลักฐาน: {evidence.classification}]\n{text_slice}"},
            ]
```

Note: include `evidence.classification` in the cache key too (replace the `cache_key` line):

```python
        cache_key = hashlib.sha256(
            f"{text_slice}\x00{evidence.classification}\x00{settings.light_model}".encode()
        ).hexdigest()
```

- [ ] **Step 6: Run** — `uv run pytest tests/unit/test_demand_score.py tests/unit/test_skill_extraction_cache.py -v` → PASS (update the cache test's expected key derivation to the new 3-part hash if it asserts on it)

- [ ] **Step 7: Commit** — `git add -A && git commit -m "feat: weight demand_score by requirement+need evidence, mark majority-want clusters optional"`

---

### Task 5: Bloom tagging of clusters

**Files:**
- Create: `src/curriculum_agent/prompts/classify_cluster_bloom.py`
- Modify: `src/curriculum_agent/stages/skill_extraction.py` (sub-step after naming)
- Test: `tests/unit/test_cluster_bloom.py` (create)

**Interfaces:**
- Produces: `build_cluster_bloom_prompt(name_th: str, description_th: str, skill_names: list[str], skill_type: str) -> list[dict]`; stage sets `cluster.bloom_level` (cognitive/psychomotor/mixed/knowledge) or `cluster.krathwohl_level` (affective) and may correct `is_subject_specific`. Tagging failure → both levels stay `None` (checkpoint shows untagged).

- [ ] **Step 1: Write failing test for the prompt builder** (`tests/unit/test_cluster_bloom.py`)

```python
from curriculum_agent.prompts.classify_cluster_bloom import build_cluster_bloom_prompt


def test_bloom_prompt_contains_cluster_info():
    msgs = build_cluster_bloom_prompt("วิเคราะห์ข้อมูล", "กลุ่มทักษะวิเคราะห์", ["สถิติ", "Python"], "knowledge")
    assert msgs[0]["role"] == "system"
    joined = msgs[0]["content"] + msgs[1]["content"]
    assert "Bloom" in joined
    assert "วิเคราะห์ข้อมูล" in msgs[1]["content"]
    assert "สถิติ" in msgs[1]["content"]
```

- [ ] **Step 2: Run to fail** — `uv run pytest tests/unit/test_cluster_bloom.py -v` → FAIL (module not found)

- [ ] **Step 3: Implement the prompt builder**

```python
from __future__ import annotations


def build_cluster_bloom_prompt(
    name_th: str,
    description_th: str,
    skill_names: list[str],
    skill_type: str,
) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "คุณเป็นผู้เชี่ยวชาญ OBE จัดระดับกลุ่มทักษะตาม Bloom's Taxonomy "
                "(remember|understand|apply|analyze|evaluate|create) "
                "หรือ Krathwohl (receiving|responding|valuing|organization|characterization) "
                "สำหรับกลุ่ม affective เท่านั้น "
                "และยืนยันว่าเป็นทักษะเฉพาะสาขา (specific) หรือทักษะทั่วไป (generic) "
                "ตอบเป็น JSON ตาม schema"
            ),
        },
        {
            "role": "user",
            "content": (
                f"กลุ่มทักษะ: {name_th}\n"
                f"คำอธิบาย: {description_th}\n"
                f"ประเภท: {skill_type}\n"
                f"ทักษะสมาชิก: {', '.join(skill_names[:10])}"
            ),
        },
    ]
```

- [ ] **Step 4: Add the sub-step in `skill_extraction.run()`** — after `naming` succeeds and before `SkillCluster(...)` is constructed, add response model at module level:

```python
class _ClusterBloomResult(BaseModel):
    bloom_level: Literal["remember", "understand", "apply", "analyze", "evaluate", "create"] | None = None
    krathwohl_level: Literal["receiving", "responding", "valuing", "organization", "characterization"] | None = None
    is_subject_specific: bool
```

and in the loop:

```python
        bloom_level: str | None = None
        krathwohl_level: str | None = None
        is_specific = naming.is_subject_specific
        try:
            tag = await complete_light(
                _ClusterBloomResult,
                build_cluster_bloom_prompt(
                    naming.canonical_name_th, naming.description_th, kw_list, naming.skill_type
                ),
            )
            if naming.skill_type == "affective":
                krathwohl_level = tag.krathwohl_level
            else:
                bloom_level = tag.bloom_level
            is_specific = tag.is_subject_specific
        except Exception as exc:
            logger.warning(f"Cluster {cluster_idx} Bloom tagging failed: {exc}")
```

then in the constructor use `is_subject_specific=is_specific, bloom_level=bloom_level, krathwohl_level=krathwohl_level,` (import `build_cluster_bloom_prompt` at top).

- [ ] **Step 5: Model + routing tests** (append to `tests/unit/test_cluster_bloom.py`)

```python
import curriculum_agent.stages.skill_extraction as se


def test_bloom_result_model_affective_gets_krathwohl():
    r = se._ClusterBloomResult(krathwohl_level="valuing", is_subject_specific=False)
    assert r.bloom_level is None
    assert r.krathwohl_level == "valuing"


def test_bloom_result_model_cognitive_gets_bloom():
    r = se._ClusterBloomResult(bloom_level="analyze", is_subject_specific=True)
    assert r.bloom_level == "analyze"
    assert r.krathwohl_level is None
```

The full-stage path (tagging call wired into `run()`) is covered by the existing stage-level tests once they're updated: patch `curriculum_agent.stages.skill_extraction.complete_light` with an `AsyncMock` whose `side_effect` returns `_ExtractedSkillsResponse` for extraction calls, `_ClusterNameResult` for naming calls, and `_ClusterBloomResult(bloom_level="analyze", is_subject_specific=True)` for tagging calls (dispatch on the first positional arg, the response model class), then assert each dict in `state["skill_clusters"]` has `bloom_level == "analyze"`.

- [ ] **Step 6: Run** — `uv run pytest tests/unit/test_cluster_bloom.py -v` → PASS

- [ ] **Step 7: Commit** — `git add -A && git commit -m "feat: tag skill clusters with Bloom/Krathwohl level via light model"`

---

### Task 6: SMART hard-check rules (pure code)

**Files:**
- Create: `src/curriculum_agent/stages/smart_rules.py`
- Test: `tests/unit/test_smart_rules.py` (create)

**Interfaces:**
- Produces:

```python
class HardCriterion(str, Enum):
    S_VERB = "S_verb"          # action verb missing from statement
    M_FORBIDDEN = "M_forbidden"  # forbidden word present
    R_EVIDENCE = "R_evidence"    # empty/unresolvable source_cluster_ids

def hard_failures(statement_th: str, action_verb_th: str,
                  source_cluster_ids: list[str], known_cluster_ids: set[str]) -> list[HardCriterion]
CRITERION_FIX_HINTS_TH: dict[HardCriterion, str]  # Thai hint per criterion for retry prompts
```

- [ ] **Step 1: Write failing tests** (`tests/unit/test_smart_rules.py`)

```python
from curriculum_agent.stages.smart_rules import CRITERION_FIX_HINTS_TH, HardCriterion, hard_failures

KNOWN = {"c1", "c2"}


def test_clean_plo_has_no_hard_failures():
    fails = hard_failures("วิเคราะห์ข้อมูลด้วยเทคนิคทางสถิติได้", "วิเคราะห์", ["c1"], KNOWN)
    assert fails == []


def test_forbidden_word_fails_measurable():
    fails = hard_failures("เข้าใจหลักการเขียนโปรแกรม", "เข้าใจ", ["c1"], KNOWN)
    assert HardCriterion.M_FORBIDDEN in fails


def test_verb_absent_from_statement_fails_specific():
    fails = hard_failures("ข้อมูลด้วยเทคนิคทางสถิติ", "ออกแบบ", ["c1"], KNOWN)
    assert HardCriterion.S_VERB in fails


def test_empty_clusters_fails_evidence():
    assert HardCriterion.R_EVIDENCE in hard_failures("วิเคราะห์ข้อมูลได้", "วิเคราะห์", [], KNOWN)


def test_unknown_cluster_id_fails_evidence():
    assert HardCriterion.R_EVIDENCE in hard_failures("วิเคราะห์ข้อมูลได้", "วิเคราะห์", ["c9"], KNOWN)


def test_every_criterion_has_a_thai_hint():
    assert set(CRITERION_FIX_HINTS_TH) == set(HardCriterion)
```

- [ ] **Step 2: Run to fail** — `uv run pytest tests/unit/test_smart_rules.py -v` → FAIL

- [ ] **Step 3: Implement `smart_rules.py`**

```python
from __future__ import annotations

from enum import Enum

from curriculum_agent.models import FORBIDDEN_WORDS_TH


class HardCriterion(str, Enum):
    S_VERB = "S_verb"
    M_FORBIDDEN = "M_forbidden"
    R_EVIDENCE = "R_evidence"


CRITERION_FIX_HINTS_TH: dict[HardCriterion, str] = {
    HardCriterion.S_VERB: (
        "Specific ไม่ผ่าน: action_verb_th ต้องปรากฏใน statement_th "
        "และเป็นกริยา Bloom เพียงตัวเดียวที่ชัดเจน"
    ),
    HardCriterion.M_FORBIDDEN: (
        "Measurable ไม่ผ่าน: ห้ามใช้คำ รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก "
        "ให้แทนด้วยกริยาที่สังเกตได้ เช่น อธิบาย วิเคราะห์ ออกแบบ"
    ),
    HardCriterion.R_EVIDENCE: (
        "Relevant ไม่ผ่าน: source_cluster_ids ต้องอ้างอิง cluster ที่มีอยู่จริง "
        "อย่างน้อย 1 รายการ"
    ),
}


def hard_failures(
    statement_th: str,
    action_verb_th: str,
    source_cluster_ids: list[str],
    known_cluster_ids: set[str],
) -> list[HardCriterion]:
    """Code-level SMART hard checks (S verb presence, M forbidden words, R evidence)."""
    fails: list[HardCriterion] = []
    if not action_verb_th or action_verb_th not in statement_th:
        fails.append(HardCriterion.S_VERB)
    if any(word in statement_th for word in FORBIDDEN_WORDS_TH):
        fails.append(HardCriterion.M_FORBIDDEN)
    if not source_cluster_ids or not set(source_cluster_ids) <= known_cluster_ids:
        fails.append(HardCriterion.R_EVIDENCE)
    return fails
```

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_smart_rules.py -v` → PASS

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: pure-code SMART hard checks with Thai retry hints"`

---

### Task 7: SMART retry loop rework in plo_synthesis

**Files:**
- Modify: `src/curriculum_agent/stages/plo_synthesis.py` (`_ensure_smart`, `_build_fix_prompt`, `run`), `src/curriculum_agent/prompts/smart_validator.py` (add soft-judge prompt)
- Test: `tests/unit/test_smart_retry_loop.py` (create); update `tests/unit/test_smart_check.py` expectations if they assert on old `_ensure_smart` signature

**Interfaces:**
- Consumes: `hard_failures`, `CRITERION_FIX_HINTS_TH`, `HardCriterion` (Task 6); PLO bookkeeping fields (Task 2).
- Produces:

```python
class _SmartOutcome(BaseModel):
    draft: _PLODraft
    smart_check: SMARTCheck
    retry_count: int
    escalated: bool
    soft_flags: list[str]

async def _ensure_smart(draft: _PLODraft, known_cluster_ids: set[str], metadata: ProgramMetadata) -> _SmartOutcome
```

- Semantics: hard fails (from `hard_failures`) drive the retry loop (max 3, per-PLO, criterion hints in the prompt); one light-model call judges S-object quality + A + R-alignment → soft results fill `soft_flags` (strings `"S_object"`, `"A_level"`, `"R_alignment"`) without blocking. `SMARTCheck` gate fields reflect **hard** status only (`specific` = verb ok, `measurable` = no forbidden word, `relevant` = evidence ok, `achievable`/`timely` = `True`; soft concerns live in `soft_flags` + `notes_th`).

- [ ] **Step 1: Add the soft-judge prompt** to `prompts/smart_validator.py`:

```python
def build_smart_soft_judge_prompt(
    statement_th: str, vision_th: str, degree_level: str
) -> list[dict]:
    """Light-model soft checks: S object quality, A level plausibility, R vision alignment."""
    return [
        {
            "role": "system",
            "content": (
                "คุณเป็นผู้ตรวจสอบคุณภาพ PLO ประเมิน 3 ข้อ ตอบเป็น JSON:\n"
                "specific_object_ok: กรรมของกริยาเจาะจง (ไม่ใช่คำกว้างเช่น 'ความรู้' 'ทักษะที่จำเป็น')\n"
                "achievable_ok: ระดับ Bloom เหมาะกับระดับปริญญา\n"
                "relevant_alignment_ok: สอดคล้องกับวิสัยทัศน์หลักสูตร\n"
                "notes_th: เหตุผลสั้นๆ สำหรับข้อที่ไม่ผ่าน"
            ),
        },
        {
            "role": "user",
            "content": (
                f"PLO: {statement_th}\n"
                f"ระดับปริญญา: {degree_level}\n"
                f"วิสัยทัศน์: {vision_th}"
            ),
        },
    ]
```

- [ ] **Step 2: Write failing tests** (`tests/unit/test_smart_retry_loop.py`) — mock both LLM fns:

```python
from unittest.mock import AsyncMock, patch

from curriculum_agent.models import ProgramMetadata
from curriculum_agent.stages import plo_synthesis as ps

META = ProgramMetadata(
    program_id="p1", name_th="วท.บ.", name_en="BSc", field="CS",
    degree_level="bachelor", duration_years=4, faculty="วิทยาศาสตร์",
    university="ม.ทดสอบ", vision_th="ผลิตบัณฑิตคุณภาพ", program_objectives_th=["obj"],
)

_SOFT_OK = ps._SmartSoftJudge(specific_object_ok=True, achievable_ok=True, relevant_alignment_ok=True)


def _draft(statement: str, verb: str = "วิเคราะห์", clusters: list[str] | None = None) -> ps._PLODraft:
    return ps._PLODraft(
        plo_id="PLO1", statement_th=statement, domain="cognitive", bloom_level="analyze",
        action_verb_th=verb, source_cluster_ids=clusters if clusters is not None else ["c1"],
        rationale_th="เหตุผล",
    )


async def test_clean_draft_passes_without_retry():
    with patch.object(ps, "complete_light", AsyncMock(return_value=_SOFT_OK)):
        out = await ps._ensure_smart(_draft("วิเคราะห์ข้อมูลทางสถิติได้"), {"c1"}, META)
    assert out.retry_count == 0
    assert out.escalated is False
    assert out.smart_check.passed


async def test_hard_fail_retries_with_criterion_and_escalates():
    bad = _draft("ข้อมูลทางสถิติ", verb="ออกแบบ")  # verb absent → S_VERB forever
    fix_calls: list[list[dict]] = []

    async def fake_heavy(model, messages, **kw):
        fix_calls.append(messages)
        return ps._SingleDraftResponse(plo=bad)  # never fixes it

    with (
        patch.object(ps, "complete_heavy", side_effect=fake_heavy),
        patch.object(ps, "complete_light", AsyncMock(return_value=_SOFT_OK)),
    ):
        out = await ps._ensure_smart(bad, {"c1"}, META)

    assert out.retry_count == 3
    assert out.escalated is True
    assert len(fix_calls) == 3
    assert "Specific" in fix_calls[0][1]["content"]  # criterion hint named in retry prompt


async def test_soft_fail_flags_without_blocking():
    judge = ps._SmartSoftJudge(specific_object_ok=True, achievable_ok=False, relevant_alignment_ok=False, notes_th="ระดับสูงไป")
    with patch.object(ps, "complete_light", AsyncMock(return_value=judge)):
        out = await ps._ensure_smart(_draft("วิเคราะห์ข้อมูลทางสถิติได้"), {"c1"}, META)
    assert out.escalated is False
    assert set(out.soft_flags) == {"A_level", "R_alignment"}
    assert out.smart_check.passed  # soft fails never block
```

- [ ] **Step 3: Run to fail** — `uv run pytest tests/unit/test_smart_retry_loop.py -v` → FAIL

- [ ] **Step 4: Implement** in `plo_synthesis.py` — replace `_validate_smart`, `_ensure_smart`, `_build_fix_prompt`:

```python
from curriculum_agent.prompts.smart_validator import build_smart_soft_judge_prompt
from curriculum_agent.stages.smart_rules import (
    CRITERION_FIX_HINTS_TH,
    HardCriterion,
    hard_failures,
)


class _SmartSoftJudge(BaseModel):
    specific_object_ok: bool
    achievable_ok: bool
    relevant_alignment_ok: bool
    notes_th: str | None = None


class _SmartOutcome(BaseModel):
    draft: _PLODraft
    smart_check: SMARTCheck
    retry_count: int
    escalated: bool
    soft_flags: list[str]


def _build_fix_prompt(draft: _PLODraft, violated: list[HardCriterion]) -> list[dict]:
    hints = "\n".join(f"- {CRITERION_FIX_HINTS_TH[c]}" for c in violated)
    return [
        {
            "role": "system",
            "content": (
                "คุณเป็นผู้เชี่ยวชาญ OBE ปรับปรุง PLO ที่ไม่ผ่านเกณฑ์ SMART ข้อที่ระบุ "
                "โดยคงสาระสำคัญเดิม ตอบเป็น JSON object field เหมือน PLO เดิม"
            ),
        },
        {
            "role": "user",
            "content": (
                f"PLO เดิม:\n{draft.statement_th}\n\n"
                f"เกณฑ์ที่ไม่ผ่าน:\n{hints}\n\n"
                f"Domain: {draft.domain.value}, action_verb_th: {draft.action_verb_th}\n"
                "เขียน PLO ใหม่ให้ผ่านเกณฑ์ข้างต้นทุกข้อ"
            ),
        },
    ]


async def _ensure_smart(
    draft: _PLODraft, known_cluster_ids: set[str], metadata: ProgramMetadata
) -> _SmartOutcome:
    """Hard fails → per-PLO retry (max _MAX_RETRIES) naming the criterion; soft fails → flags."""
    fails = hard_failures(
        draft.statement_th, draft.action_verb_th, draft.source_cluster_ids, known_cluster_ids
    )
    retries = 0
    while fails and retries < _MAX_RETRIES:
        retries += 1
        logger.debug(f"  SMART retry {retries} for PLO {draft.plo_id}: {[f.value for f in fails]}")
        try:
            fix = await complete_heavy(
                _SingleDraftResponse, _build_fix_prompt(draft, fails), max_retries=2
            )
            draft = fix.plo
        except Exception as exc:
            logger.warning(f"  SMART fix attempt {retries} failed: {exc}")
        fails = hard_failures(
            draft.statement_th, draft.action_verb_th, draft.source_cluster_ids, known_cluster_ids
        )

    escalated = bool(fails)
    if escalated:
        logger.warning(f"  PLO {draft.plo_id} escalated after {retries} retries: {[f.value for f in fails]}")

    soft_flags: list[str] = []
    notes: str | None = None
    try:
        judge = await complete_light(
            _SmartSoftJudge,
            build_smart_soft_judge_prompt(draft.statement_th, metadata.vision_th, metadata.degree_level),
        )
        notes = judge.notes_th
        if not judge.specific_object_ok:
            soft_flags.append("S_object")
        if not judge.achievable_ok:
            soft_flags.append("A_level")
        if not judge.relevant_alignment_ok:
            soft_flags.append("R_alignment")
    except Exception as exc:
        logger.warning(f"  Soft judge failed for PLO {draft.plo_id}: {exc}")

    smart = SMARTCheck(
        specific=HardCriterion.S_VERB not in fails,
        measurable=HardCriterion.M_FORBIDDEN not in fails,
        achievable=True,
        relevant=HardCriterion.R_EVIDENCE not in fails,
        timely=True,
        notes_th=notes,
    )
    return _SmartOutcome(
        draft=draft, smart_check=smart, retry_count=retries,
        escalated=escalated, soft_flags=soft_flags,
    )
```

Update `run()`: build `known_cluster_ids = {c.cluster_id for c in clusters}` before the draft loop; replace `validated_draft, smart_check = await _ensure_smart(draft)` with:

```python
        outcome = await _ensure_smart(draft, known_cluster_ids, metadata)
        validated_draft, smart_check = outcome.draft, outcome.smart_check
```

and add to the `PLO(...)` constructor: `smart_retry_count=outcome.retry_count, smart_escalated=outcome.escalated, soft_flags=outcome.soft_flags,`. Delete the now-unused `_validate_smart` and old `build_smart_validate_prompt` import (keep the prompt fn in the file for API reuse if referenced elsewhere — check with grep; if unreferenced, delete it).

Note: `_PLODraft._check_forbidden` currently raises on forbidden words, which would block Instructor from ever returning a draft that `hard_failures` should catch — **remove the `_check_forbidden` validator from `_PLODraft`**. Escalated PLOs pass `PLO` model validation normally because `check_no_forbidden_words` exempts `smart_escalated=True` (added in Task 2) — never use `model_construct`.

- [ ] **Step 5: Run** — `uv run pytest tests/unit/test_smart_retry_loop.py tests/unit/test_smart_check.py -v` → PASS (rewrite any old `_ensure_smart`-signature assertions in `test_smart_check.py` to the new `_SmartOutcome` API)

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: hard/soft SMART retry loop with criterion-named retries and escalation"`

---

### Task 8: 6–10 PLO policy

**Files:**
- Modify: `src/curriculum_agent/stages/plo_synthesis.py:25-26` (`_MIN_PLOS = 6`, `_MAX_PLOS = 10`; fallback slice `[:8]` → `[:12]`), `src/curriculum_agent/prompts/stage_3_plo.py` (both "4-6" strings → "6-10")
- Test: `tests/unit/test_plo_count_policy.py` (create)

- [ ] **Step 1: Failing tests**

```python
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


def test_synthesis_prompt_asks_for_6_to_10(sample_metadata, sample_clusters):
    msgs = build_plo_synthesis_prompt(sample_metadata, sample_clusters)
    assert "6-10" in msgs[0]["content"]
    assert "4-6" not in msgs[0]["content"] + msgs[1]["content"]
```

(If `sample_metadata`/`sample_clusters` fixtures don't exist in `tests/conftest.py`, add them there — a `ProgramMetadata` and one-element `list[SkillCluster]` mirroring the Task 7 test literals.)

- [ ] **Step 2: Run to fail** → FAIL (values 4/6)

- [ ] **Step 3: Apply the three edits** (`_MIN_PLOS`/`_MAX_PLOS`, fallback `[:12]`, prompt strings "4-6 รายการ" → "6-10 รายการ" in both system and user messages)

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_plo_count_policy.py -v` → PASS; then `uv run pytest` → fix any test fixtures that build 4–6 PLO lists (e.g. `tests/integration/test_stage_3_plo.py` mock drafts must now return ≥6)

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: raise PLO policy to 6-10 per program"`

---

### Task 9: Optional PLO pass from want-clusters

**Files:**
- Modify: `src/curriculum_agent/stages/plo_synthesis.py` (`run()`), `src/curriculum_agent/prompts/stage_3_plo.py` (add optional-pass builder)
- Test: `tests/unit/test_optional_plos.py` (create)

**Interfaces:**
- Produces: `build_optional_plo_prompt(metadata: ProgramMetadata, clusters: list[SkillCluster]) -> list[dict]`; `run()` excludes `is_optional` clusters from the main pass, then (if any exist) runs a second heavy call producing 1–4 drafts marked `is_optional=True` (same `_ensure_smart` treatment, exempt from the 6–10 count). Failure of the optional pass logs a warning and never blocks the main set.

- [ ] **Step 1: Failing tests** (`tests/unit/test_optional_plos.py`)

```python
from curriculum_agent.prompts.stage_3_plo import build_optional_plo_prompt


def test_optional_prompt_labels_output_optional(sample_metadata, sample_clusters):
    msgs = build_optional_plo_prompt(sample_metadata, sample_clusters)
    joined = msgs[0]["content"] + msgs[1]["content"]
    assert "เสริม" in joined or "optional" in joined.lower()
    assert "1-4" in joined
```

Plus a cluster-split unit test (pure, no mocks needed):

```python
from curriculum_agent.models import SkillCluster, SkillType


def _cluster(cid: str, optional: bool) -> SkillCluster:
    return SkillCluster(
        cluster_id=cid, program_id="p1", canonical_name_th=f"กลุ่ม {cid}",
        description_th="คำอธิบาย", skill_type=SkillType.KNOWLEDGE,
        is_subject_specific=True, member_skill_ids=["s1"],
        source_evidence_ids=["e1"], demand_score=0.6, is_optional=optional,
    )


def test_optional_clusters_split_from_core():
    clusters = [_cluster("c1", False), _cluster("c2", True), _cluster("c3", False)]
    core = [c for c in clusters if not c.is_optional]
    optional = [c for c in clusters if c.is_optional]
    assert [c.cluster_id for c in core] == ["c1", "c3"]
    assert [c.cluster_id for c in optional] == ["c2"]
```

And a `run()`-level test in the same file (mock `complete_heavy` with `side_effect` returning a `_PLODraftList` of 6 valid drafts on the first call and `_OptionalDraftList` with one `OPT-1` draft on the second; mock `complete_light` → `_SmartSoftJudge` all-ok; mock `PLORepository.bulk_insert` with `AsyncMock`): given `state` with clusters `c1..c6` core + `c7` optional, assert `complete_heavy.call_count == 2`, the second call's user message contains `"c7"` and not `"c1"`, and `state["plos"]` contains exactly one dict with `"is_optional": True`.

- [ ] **Step 2: Run to fail** → FAIL

- [ ] **Step 3: Implement the prompt builder** (append to `stage_3_plo.py`)

```python
def build_optional_plo_prompt(
    metadata: ProgramMetadata,
    clusters: list[SkillCluster],
) -> list[dict]:
    cluster_summary = "\n".join(
        f"- [{c.cluster_id}] {c.canonical_name_th}: {c.description_th}"
        for c in clusters
    )
    return [
        {
            "role": "system",
            "content": (
                "คุณเป็นผู้เชี่ยวชาญ OBE สร้าง PLO เสริม (optional) จากทักษะประเภท want "
                "(ตลาดต้องการเพิ่มเติมแต่ไม่จำเป็นทุกคน) จำนวน 1-4 รายการ "
                "กติกาเดียวกับ PLO หลัก: กริยา Bloom วัดได้ ไม่ใช้คำต้องห้าม "
                "(รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก)"
            ),
        },
        {
            "role": "user",
            "content": (
                f"สาขาวิชา: {metadata.field} ระดับ {metadata.degree_level}\n"
                f"Want-based skill clusters:\n{cluster_summary}\n\n"
                "สังเคราะห์ PLO เสริม 1-4 รายการ พร้อม plo_id (นำหน้าด้วย OPT), statement_th, "
                "domain, bloom_level/krathwohl_level, action_verb_th, source_cluster_ids, rationale_th"
            ),
        },
    ]
```

- [ ] **Step 4: Implement the pass in `run()`** — split before the main synthesis:

```python
    optional_clusters = [c for c in clusters if c.is_optional]
    core_clusters = [c for c in clusters if not c.is_optional]
```

use `core_clusters` everywhere `clusters` fed selection (the `selected` computation). After the main `plos` list is built, add:

```python
    class _OptionalDraftList(BaseModel):
        plos: list[_PLODraft] = Field(min_length=1, max_length=4)

    if optional_clusters:
        try:
            opt_msgs = build_optional_plo_prompt(metadata, optional_clusters)
            opt_list = await complete_heavy(_OptionalDraftList, opt_msgs, max_retries=2)
            for draft in opt_list.plos:
                outcome = await _ensure_smart(draft, known_cluster_ids, metadata)
                # evidence fallback: same chain as main pass, scoped to optional clusters
                evidence_ids = outcome.draft.source_evidence_ids or list({
                    eid for cid in outcome.draft.source_cluster_ids
                    for eid in cluster_evidence_map.get(cid, [])
                }) or list({eid for c in optional_clusters for eid in c.source_evidence_ids})
                if not evidence_ids:
                    logger.warning(f"optional PLO {outcome.draft.plo_id}: no evidence — skipped")
                    continue
                plos.append(PLO(
                    plo_id=outcome.draft.plo_id or f"OPT-{uuid.uuid4().hex[:6]}",
                    program_id=program_id,
                    statement_th=outcome.draft.statement_th,
                    statement_en=outcome.draft.statement_en,
                    domain=outcome.draft.domain,
                    bloom_level=outcome.draft.bloom_level,
                    krathwohl_level=outcome.draft.krathwohl_level,
                    is_subject_specific=outcome.draft.is_subject_specific,
                    action_verb_th=outcome.draft.action_verb_th,
                    smart_check=outcome.smart_check,
                    source_cluster_ids=outcome.draft.source_cluster_ids,
                    source_evidence_ids=evidence_ids,
                    rationale_th=outcome.draft.rationale_th,
                    smart_retry_count=outcome.retry_count,
                    smart_escalated=outcome.escalated,
                    soft_flags=outcome.soft_flags,
                    is_optional=True,
                ))
        except Exception as exc:
            logger.warning(f"Optional PLO pass failed (non-blocking): {exc}")
```

(Move `_OptionalDraftList` to module level next to `_PLODraftList`.)

- [ ] **Step 5: Run** — `uv run pytest tests/unit/test_optional_plos.py -v` → PASS; full suite → PASS

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: optional PLO pass from want-based clusters, non-blocking"`

---

### Task 10: Frontend — SkillExtraction Bloom grouping

**Files:**
- Modify: `frontend/src/pages/SkillExtraction.tsx`

**Interfaces:**
- Consumes: cluster API objects now carrying `bloom_level: string | null`, `krathwohl_level: string | null`, `is_optional: boolean`, `classification_coverage: Record<string, number>`.

- [ ] **Step 1: Read the page first** — `frontend/src/pages/SkillExtraction.tsx` (484 lines) to locate the cluster type definition and the cluster-list render block.

- [ ] **Step 2: Extend the cluster TS type** with the four new fields (nullable/optional as above).

- [ ] **Step 3: Group render by Bloom level** — replace the flat cluster list with grouping. Insert above the render:

```tsx
const BLOOM_ORDER = ['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create'] as const
const BLOOM_TH: Record<string, string> = {
  remember: 'จำได้ (Remember)', understand: 'เข้าใจ (Understand)', apply: 'ประยุกต์ (Apply)',
  analyze: 'วิเคราะห์ (Analyze)', evaluate: 'ประเมิน (Evaluate)', create: 'สร้างสรรค์ (Create)',
}

function groupByBloom(clusters: Cluster[]): [string, Cluster[]][] {
  const groups = new Map<string, Cluster[]>()
  for (const level of BLOOM_ORDER) groups.set(level, [])
  groups.set('untagged', [])
  for (const c of clusters) {
    const key = c.bloom_level && BLOOM_ORDER.includes(c.bloom_level as never) ? c.bloom_level : 'untagged'
    groups.get(key)!.push(c)
  }
  return [...groups.entries()].filter(([, v]) => v.length > 0)
}
```

Render each group as a section headed by `BLOOM_TH[level] ?? 'ยังไม่จัดระดับ'`, reusing the existing cluster-card markup inside. On each card add two badges (Tailwind, match the page's existing badge styling if any):

```tsx
<span className={c.is_subject_specific
  ? 'rounded-full bg-indigo-100 px-2 py-0.5 text-xs text-indigo-700'
  : 'rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700'}>
  {c.is_subject_specific ? 'เฉพาะสาขา' : 'ทักษะทั่วไป'}
</span>
{c.is_optional && (
  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">
    เสริม (want)
  </span>
)}
```

- [ ] **Step 4: Verify build + lint** — `cd frontend; npm run lint; npm run build` → clean

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(ui): group skill clusters by Bloom level with specific/generic and optional badges"`

---

### Task 11: Frontend — PloSynthesis flags + PloReport optional section

**Files:**
- Modify: `frontend/src/pages/PloSynthesis.tsx`, `frontend/src/pages/PloReport.tsx`

**Interfaces:**
- Consumes: PLO API objects now carrying `smart_retry_count: number`, `smart_escalated: boolean`, `soft_flags: string[]`, `is_optional: boolean`.

- [ ] **Step 1: Read both pages** to locate the PLO TS type and card render blocks; extend the type with the four fields.

- [ ] **Step 2: PloSynthesis — flag display.** On each PLO card add:

```tsx
{plo.smart_escalated && (
  <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
    ไม่ผ่าน SMART หลัง retry {plo.smart_retry_count} ครั้ง — ต้องแก้ด้วยมือ
  </span>
)}
{plo.soft_flags?.length > 0 && (
  <div className="mt-1 flex flex-wrap gap-1">
    {plo.soft_flags.map((f) => (
      <span key={f} className="rounded-full bg-yellow-100 px-2 py-0.5 text-xs text-yellow-800">
        {SOFT_FLAG_TH[f] ?? f}
      </span>
    ))}
  </div>
)}
```

with:

```tsx
const SOFT_FLAG_TH: Record<string, string> = {
  S_object: 'กรรมของกริยากว้างเกินไป',
  A_level: 'ระดับ Bloom อาจสูง/ต่ำเกินไป',
  R_alignment: 'อาจไม่สอดคล้องวิสัยทัศน์',
}
```

- [ ] **Step 3: PloReport — optional section.** Split fetched PLOs: `const mainPlos = plos.filter(p => !p.is_optional)`, `const optionalPlos = plos.filter(p => p.is_optional)`. Existing list/matrix views consume `mainPlos` unchanged. Below them, when `optionalPlos.length > 0`, render a bordered section titled `PLO เสริม (จากความต้องการประเภท want)` listing each optional PLO with the existing card markup plus an amber `เสริม` badge, and helper text: `รายการเหล่านี้ไม่นับใน PLO หลัก 6-10 ข้อ — เลือกใช้ได้ตามดุลยพินิจของหลักสูตร`.

- [ ] **Step 4: Verify** — `cd frontend; npm run lint; npm run build` → clean. Also confirm every API prefix the pages call exists in `frontend/vite.config.ts` proxy (currently only `/programs`, `/health` — pages call `/programs/...` so no change expected; add any missing prefix found).

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(ui): SMART flags on synthesis page, optional PLO section in report"`

---

### Task 12: Docs sync (CLAUDE.md + skill references)

**Files:**
- Modify: `CLAUDE.md` (full rewrite — on-disk copy is the pre-restart version), `.claude/skills/curriculum-design-agent/SKILL.md`, `.claude/skills/curriculum-design-agent/references/data-schemas.md`

- [ ] **Step 1: Rewrite `CLAUDE.md`** to the current scope. Keep the existing section order but with these facts: 5-stage pipeline `intake → stakeholder needs → skill extraction → PLO synthesis → PLO report`, agent stops at PLO (YLO/CLO faculty work, code removed); React 19 + Vite + TS + Tailwind UI in `frontend/`; hybrid deploy (Ollama native — no `ca-ollama` container; postgres/qdrant/minio/pgadmin in Docker); run via `.\scripts\start-dev.ps1` / `cd frontend && npm run dev`; 6–10 PLO policy; SMART hard/soft retry loop (rubric in the project skill); skill lives at `.claude/skills/curriculum-design-agent/`; test commands `uv run pytest -k "plo"`; immutable rules updated (drop YLO monotonicity rule, add SMART-gate rule and stop-at-PLO rule).

- [ ] **Step 2: Update skill SKILL.md** — pipeline description now 5 stages ending `plo_report`; note optional PLOs from want-clusters are exempt from the 6–10 count.

- [ ] **Step 3: Update skill `references/data-schemas.md`** — add the new `SkillCluster`/`PLO` fields and the `_compute_demand_score` weighting rule (requirement+need only; majority-want → `is_optional`); update the checkpoint `stage` Literal to end at `"plo_report"`.

- [ ] **Step 4: Commit** — `git add -A && git commit -m "docs: sync CLAUDE.md and skill references to PLO-scope pipeline"`

---

### Task 13: Full verification + E2E

- [ ] **Step 1: Static gates** — `uv run ruff check src/ tests/ && uv run mypy src/` → clean; `cd frontend; npm run lint; npm run build` → clean

- [ ] **Step 2: Full test suite** — `uv run pytest -v` → all PASS

- [ ] **Step 3: E2E (real Ollama, real UI)** — prerequisites: Ollama running with `scb10x/typhoon2-8b-instruct` + `qwen2.5:7b` pulled.

```powershell
.\scripts\start-dev.ps1        # docker DB services + alembic + uvicorn
cd frontend; npm run dev       # http://localhost:5173
```

Walk the UI: Intake (create program) → Stakeholder Needs (add ≥6 evidence items, mix of requirement/need/want, approve) → Skill Extraction (verify clusters grouped by Bloom level, specific/generic badges, want-heavy cluster shows เสริม badge; approve) → PLO Synthesis (verify 6–10 main PLOs, soft flags/escalation badges render; approve) → PLO Report (verify generic/specific views plus the optional-PLO section).

Success criteria: pipeline completes without manual DB intervention; 6–10 main PLOs each SMART-passing or explicitly marked escalated; optional PLOs (if want evidence given) appear only in the report's optional section.

- [ ] **Step 4: Fix anything found, re-run, commit** — `git add -A && git commit -m "chore: post-E2E fixes for PLO agentic pipeline"` (only if fixes were needed)
