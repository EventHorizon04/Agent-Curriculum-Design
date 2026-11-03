# Data Schemas Reference

These are the Pydantic models that flow between agent stages. Use them to type LLM outputs (via Instructor), persist to Postgres, and validate user uploads. When asked to add a field or create a new model, follow the patterns here.

All models use Pydantic v2.

## Core principle: evidence trail

Every artifact derived from another must carry the IDs of its sources. This is non-negotiable — it's how the agent answers "where did this PLO come from?" during accreditation review.

```
StakeholderEvidence (raw)
  ↓ source_evidence_id + evidence_span_th (verified in code)
ExtractedSkill (per evidence item)
  ↓ member_skill_ids
Need (grouped skills, one KSEC tag — several when merged — one sentence)
  ↓ source_need_ids
PLO (final artifact — agent scope ends here)
```

Never break the chain. If a model doesn't have a source-tracing field (or equivalent), you can't trace its provenance. Two of these links are enforced in pure code, not just by convention: `ExtractedSkill.evidence_span_th` must actually occur in its source evidence (`is_grounded()` in `stages/skill_extraction.py`), and `PLO.source_need_ids` / `PLO.source_evidence_ids` are rejected as empty by a Pydantic validator.

## Stage 1: Program metadata

```python
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime

class ProgramMetadata(BaseModel):
    """Set in Stage 1 (Intake). The fixed context all later stages reference."""
    program_id: str
    # A program is identified by university/faculty/field. The names remain for
    # rows created before intake dropped them, and default to "" otherwise.
    name_th: str = ""
    name_en: str = ""
    field: str  # e.g. "Computer Science", "ความสัมพันธ์ระหว่างประเทศ"
    isced_code: str | None = None  # ISCED-F 2013 detailed code, validated against the taxonomy
    degree_level: Literal["bachelor", "master", "doctoral"]
    duration_years: int = Field(ge=1, le=8)
    faculty: str
    university: str
    professional_council: str | None = None  # e.g. "สภาวิศวกร"
    accreditation_body: str | None = None  # e.g. "AUN-QA", "ABET" — program metadata only, unrelated to StakeholderType
    subject_benchmark_ref: str | None = None  # มคอ.1 reference — program metadata only, unrelated to StakeholderType
    # Both default to []: intake stopped collecting them. Persisted rows keep
    # whatever they already hold, and CHECO 1.5 still reads program_objectives_th.
    program_objectives_th: list[str] = []
    program_goals_th: list[str] = []
    created_at: datetime
    copied_from: str | None = None  # set only by POST /programs/{id}/copy; not a foreign key
```

**The institution's own direction is not metadata.** `vision_th`, `mission_th`, `philosophy_th`, `institutional_identity_th`, and `student_identity_th` were fields here and are gone — along with `build_institutional_evidence`, which converted them into evidence rows at intake. The designer now records those statements directly at stage 2 as `StakeholderEvidence` with `stakeholder_type=INSTITUTIONAL_DIRECTION` (`classification="requirement"`, derived in code like every other type). One home for a statement, not two, and the evidence trail works the same way for the institution's voice as for any other stakeholder's. Whether the program covered it at all is a program-level check in `plo_synthesis.run`, not a field's presence.

`isced_code` is validated against the ISCED-F 2013 taxonomy (`data/isced.py`) on `ProgramCreateRequest` only — `ProgramMetadata` overrides that validator to a no-op so a persisted row whose code later left the taxonomy still deserializes. Intake has no input for it, no LLM suggestion, and no document upload.

**`copied_from` is set only by `POST /programs/{id}/copy`.** It is nullable, carries the source `program_id` as a plain string with no foreign-key constraint (the source may itself be deleted later), and is not a field on `ProgramCreateRequest` — a client cannot set it when creating a program, only the copy route writes it.

**`program_id` comes from `field`.** With no program name to slug, `_generate_program_id` slugs the field of study and appends `-2`, `-3`, … on collision. `_slugify` keeps ASCII only, so a Thai field yields `program`, `program-2`, … — readable ids are a nice-to-have, uniqueness is not. Anything showing a program to a human should fall back through name → field → id; `ProgramSummary` carries `field` and `faculty` for exactly that.

## Stage 2: Stakeholder evidence

```python
class StakeholderGroup(str, Enum):
    """Whether a stakeholder speaks from outside the institution or inside it."""
    EXTERNAL = "external"
    INTERNAL = "internal"

class StakeholderType(str, Enum):
    # --- external ---
    PROFESSIONAL_COUNCIL = "professional_council"   # สภาวิชาชีพ
    EMPLOYER = "employer"                           # ผู้ใช้บัณฑิต / ผู้ประกอบการ
    INDUSTRY = "industry"                           # ภาคอุตสาหกรรม
    ALUMNI = "alumni"                               # ศิษย์เก่า
    EXPERT = "expert"                               # ผู้ทรงคุณวุฒิ
    COMMUNITY = "community"                         # ชุมชนและสังคม
    PARTNER_INSTITUTION = "partner_institution"     # สถาบันคู่ความร่วมมือ
    APPLICANT = "applicant"                         # ผู้สมัครเรียน
    PARENT = "parent"                               # ผู้ปกครอง
    # --- internal ---
    INSTITUTIONAL_DIRECTION = "institutional_direction"  # vision/mission/philosophy/identity — one voice, several documents
    ADMINISTRATOR = "administrator"                 # ผู้บริหาร
    PROGRAM_COMMITTEE = "program_committee"          # คณะกรรมการหลักสูตร
    FACULTY = "faculty"                              # อาจารย์
    STUDENT = "student"                              # ผู้เรียน
    SUPPORT_STAFF = "support_staff"                   # บุคลากรสายสนับสนุน

# The single mapping from type to group. Nothing else may hardcode the split —
# the demand weight table (stages/demand.py) and any UI grouping read from it.
STAKEHOLDER_GROUP: dict[StakeholderType, StakeholderGroup] = {...}

# สภาวิชาชีพ sets legal practice requirements; the institution's own vision/
# mission/identity is a mandate it committed to. Every other type is `general`.
REQUIREMENT_TYPES = frozenset(
    {StakeholderType.PROFESSIONAL_COUNCIL, StakeholderType.INSTITUTIONAL_DIRECTION}
)

class StakeholderEvidence(BaseModel):
    """Raw evidence collected in Stage 2. The 'source of truth' for traceability."""
    evidence_id: str  # uuid
    program_id: str
    stakeholder_type: StakeholderType
    source_name: str  # e.g. "JobThai posting #12345" or "วิสัยทัศน์" for institutional-direction rows
    source_url: str | None = None
    raw_text_th: str  # original Thai text
    raw_text_en: str | None = None  # English original if available
    collected_at: datetime
    # requirement vs general — a two-value vocabulary, decided in code
    classification: Literal["requirement", "general"] = "general"
    classification_rationale_th: str | None = None  # manual-override field; the stage no longer writes an LLM rationale into it
    metadata: dict = {}  # job title, salary, location, etc. for job postings
```

**Deleted:** `ACCREDITATION_BODY`, `UNIVERSITY`, `SUBJECT_BENCHMARK`, `PEER_PROGRAM`. `ProgramMetadata.professional_council`, `.accreditation_body`, and `.subject_benchmark_ref` are unrelated program-metadata fields and are untouched.

Why `classification` moved to two values: "how many sources asked for this" is a property of a *skill* across evidence items, not of one evidence item — a job posting is not "a need", it mentions capabilities, some rare and some common. Evidence-level `classification` is now a pure lookup (`classify_evidence_type` in `stages/stakeholder_needs.py`) from `stakeholder_type` — no LLM call, no judgement: `PROFESSIONAL_COUNCIL` and `INSTITUTIONAL_DIRECTION` are `requirement`, every other type is `general`. The `need`/`want`/`unclassified` vocabulary lives one level down, on `ExtractedSkill` — see Stage 3.

## Stage 3: Extracted skills, and Needs (Stage 3b: need_combination)

```python
class KSECCategory(str, Enum):
    """TQF/มคอ. competency domains, pre-tagging every ExtractedSkill for eventual
    มคอ.2/CHECO mapping. NOT a Bloom domain — it is orthogonal to bloom_level.
    A skill carries one of K/S/E/C; a Need carries one of K/S/EC/E/C — EC is a
    Need-level umbrella tag produced when a group mixes E and C members."""
    K = "K"    # ความรู้
    S = "S"    # ทักษะ — SS and GS collapsed into one tag
    EC = "EC"  # คุณธรรมจริยธรรมและคุณลักษณะบุคคล — Need-level only, displayed "E|C"
    E = "E"    # คุณธรรมจริยธรรม — standalone when a Need is distinctly ethical
    C = "C"    # คุณลักษณะบุคคล — standalone when a Need is distinctly about character

# The tags an ExtractedSkill may carry. EC is Need-level only.
SKILL_KSEC = frozenset({KSECCategory.K, KSECCategory.S, KSECCategory.E, KSECCategory.C})

class ExtractedSkill(BaseModel):
    """A single skill mention extracted from one evidence item. High-volume."""
    skill_id: str
    program_id: str
    skill_name_th: str = Field(min_length=1)  # a phrase, never a bare word
    skill_name_en: str | None = None
    ksec_category: KSECCategory  # one of K/S/E/C — never EC at skill level
    # Cognitive scale only, and required. Psychomotor/affective are not
    # modelled anywhere in the agent — it stops at PLO and every PLO it
    # produces is cognitive.
    bloom_level: BloomLevel
    # Verbatim quote from the source evidence that justifies this skill.
    # Verified against the evidence text in pure code, not trusted from the
    # LLM — see `is_grounded()` below.
    evidence_span_th: str = Field(min_length=1)
    source_evidence_id: str  # FK to StakeholderEvidence
    source_stakeholder_type: StakeholderType  # provenance kept for the UI — which stakeholder named this skill
    # need/want/unclassified/requirement — decided in code by classify_skills,
    # once every evidence item in the program has been extracted (see below).
    classification: Literal["requirement", "need", "want", "unclassified"] = "unclassified"
    # Set by the extraction model in the same call as the rest of the skill:
    # does this belong to the program's field at all? False yields
    # `unclassified` unless the skill is mandated (see precedence below).
    is_field_relevant: bool = True
    extraction_method: Literal["llm", "manual"]
    confidence: float = Field(ge=0, le=1)
    # Per-skill-name demand, computed pre-grouping with the SAME weighting as
    # Need.demand_score, grouped by normalized skill_name_th instead of Need
    # membership. Every mention of the same skill name across evidence carries
    # the same importance_score.
    importance_score: float = Field(ge=0, le=1)

class Need(BaseModel):
    """Output of need_combination — a market-side demand distilled from a
    group of extracted skills. One sentence stating what the labour market
    asks for; PLO synthesis restates it from the graduate's side."""
    need_id: str
    program_id: str
    statement_th: str = Field(min_length=1)
    statement_en: str | None = None
    rationale_th: str = ""  # why this group is one demand — an explanation, NOT a trail
    # One tag unless this Need is a merge (Agent 2), which carries the sorted union
    # of its originals' tags in K, S, E, C order. At least one, no duplicates.
    # A checkpoint dict with the old `ksec_category` key is mapped to [value].
    ksec_categories: list[KSECCategory] = Field(min_length=1)
    bloom_level: BloomLevel  # lower mention-weighted median of member levels (group_bloom)
    member_skill_ids: list[str] = Field(min_length=1)  # ExtractedSkill IDs
    source_evidence_ids: list[str] = Field(min_length=1)
    stakeholder_coverage: dict[StakeholderType, int] = {}  # which groups, how often
    source_stakeholder_types: list[StakeholderType] = []  # distinct types, external first (enum order) — the display list
    freq: int = Field(ge=1)  # = len(member_skill_ids), a raw mention count
    demand_score: float = Field(ge=0, le=1)  # 0.30 mandate block + 0.70 frequency block
    is_optional: bool = False  # majority-want group → supplementary, not core
    classification_coverage: dict[str, int] = {}  # member-skill count per classification
    # Set only on a merged Need: the skills that stand for it (rank order, top 7 by
    # importance_score), its originals in demand order, and the dedup reason.
    top_skill_ids: list[str] = []
    merged_from: list[str] = []
    merged_into: str | None = None  # set on an ORIGINAL: hides it from every reader
    merge_reason_th: str = ""
    merged_by: Literal["agent", "designer"] | None = None  # who decided the merge; None on rows merged before 2026-11-03
    excluded_at: datetime | None = None  # set when the designer excludes it: hides it from every reader, restorable

class SkillGroup(BaseModel):
    """Agent 1's output, stored so Agent 2 starts without calling the clustering
    slot. One cluster inside ONE KSEC bucket; mirrors the candidate group
    need_combination writes a Need sentence from."""
    group_id: str
    program_id: str
    ksec: KSECCategory  # K / S / EC / E / C — resolved tag of the bucket
    skill_ids: list[str]
    evidence_ids: list[str]
    skill_names: list[str]  # most-mentioned first
    skill_frequencies: list[int]  # skill_frequencies[i] = member rows behind skill_names[i]
    bloom_level: BloomLevel  # group_bloom
    demand_score: float
    is_optional: bool
    is_graduate: bool  # graduate capability, not purely institutional
    classification_coverage: dict[str, int]
    stakeholder_coverage: dict[StakeholderType, int]
    stakeholder_types: list[StakeholderType]
    in_field_skill_count: int
    graduate_capability_skill_count: int
```

**Merged and active Needs.** Agent 2's duplicate check (up to 5 Needs, across KSEC) writes one new Need per group and keeps the originals with `merged_into = <merged need_id>`; readers use only active Needs (`merged_into is None` and `excluded_at is None`, `NeedRepository.list_active_by_program`). Since phase 2 (2026-11-03) the designer can also merge 2-5 active Needs at the Need checkpoint (`POST /needs/merge`, `merged_by="designer"`; a selected merged Need nests rather than flattens) and exclude/restore a Need (`POST /needs/{id}/exclude|restore`); both are refused for a Need a stored PLO cites, and a re-run of Agent 2 discards them. A merged Need's `member_skill_ids` and `source_evidence_ids` are the union over its originals (the trail is never smaller), `top_skill_ids` are the top 7 pooled skills by `importance_score`, and its scores are recomputed from the pooled skills, not the max of the originals. `POST /programs/{id}/needs/{need_id}/split` deletes the merged Need and clears `merged_into` on its originals. `skill_groups` is a table (`SkillGroupRepository`), replaced with the skills on a re-run of Agent 1.

`rationale_th` is the model's account of why these skills form one demand, written by the same call that writes the sentence. Keep it apart from traceability: `source_evidence_ids` is what immutable rule 2 is about and is assembled in code, while this is free text nothing validates against the evidence — so the prompt forbids citing anything outside the skill names it was given, and both UI cards label it "คำอธิบายของโมเดล" and keep it out of the trail panel. `_NeedStatement` bounds it (20-240 characters) and rejects an empty answer with the same `find_vague_phrase` the statement uses. It defaults to `""` rather than being required, because a Need also arrives as a plain dict from a LangGraph checkpoint suspended across the deploy that added the column (migration `c7e2f81a4b93`, which backfills a self-identifying `[สร้างย้อนหลัง]` sentence into pre-existing rows rather than composing a reason nobody gave).

A Need holds no evidence text. `sample_quotes_th` was dropped (migration `e1a7c93b5d02`) when `need_combination` stopped reading evidence: the stage writes each sentence from the member skills alone, so there was nothing left to sample. The trail survives in `source_evidence_ids`, inherited from those skills, and the full text stays in the evidence table for drill-down. `demand_score`'s denominator moved with it — it is now the weight of the evidence that yielded at least one skill, since an evidence item nobody extracted a skill from expresses no demand for a Need to be a share of.

**Groundedness (`ExtractedSkill.evidence_span_th`):** verified by `is_grounded()` in `stages/skill_extraction.py`. A span passes only if, after whitespace-normalisation, it is at least `_MIN_SPAN_CHARS` (12) characters long *and* occurs verbatim in the source evidence text. Skills whose quote is too short to prove anything, or whose quote isn't actually in the evidence (a fabrication), are dropped before persistence; the stage counts and logs both drop reasons separately (`dropped_too_short` / `dropped_not_found`) and the total dropped count travels in `AgentState["dropped_ungrounded_count"]` for checkpoint display.

**Skill classification (`ExtractedSkill.classification`):** computed once, in `skill_extraction.classify_skills`, after every evidence item in the program has been extracted — need vs want is a cross-evidence frequency property and cannot be known per-item. Precedence, highest first:

1. Named by evidence whose `classification == "requirement"` → `requirement`.
2. Its normalized name (`need_grouping.normalize_need_name`) matches a skill already classified `requirement` by rule 1 → `requirement`. **Requirement wins**: a สภาวิชาชีพ mandate or the faculty's own vision stays in the pipeline whatever the extraction model thought of its field fit.
3. `is_field_relevant == False` → `unclassified`.
4. Named by more than one distinct `source_evidence_id` → `need`.
5. Otherwise → `want`.

Rules 1–2 outrank 3 on purpose — a mandated skill is never dropped for being judged off-field. Semantic matching is deliberately not used in rule 2 (that is what LLM clustering does one stage later, in `need_combination`); only normalized-name matching.

**Single-tag guarantee for unmerged Needs (`Need.ksec_categories`):** Agent 1 (`stages/skill_grouping.py`) buckets `ExtractedSkill`s by `ksec_category` (`bucket_by_ksec` in `stages/need_grouping.py`) *before* clustering — `E` and `C` share one `EC` bucket, everything else buckets by its own tag — and clustering never fuses groups across buckets. An unmerged Need therefore has exactly one tag. After a group forms, `resolve_need_ksec` decides its tag from its raw member tags: all-`E` → `E`, all-`C` → `C`, mixed → `EC`. Only Agent 2's merge (designer's decision of 2026-10-26) produces a Need with more than one tag.

`demand_score` is the signal the agent uses to decide which Needs are core vs optional. It is also what the 10-PLO ceiling ranks by. The rule (`compute_demand_score` in `stages/demand.py`, shared by skill-level `importance_score` and Need-level `demand_score`):

- Two blocks, not one weighted sum: `demand_score = 0.30 × (สภาวิชาชีพ named it? 1 : 0) + 0.70 × (distinct evidence ids naming it / distinct evidence ids in the corpus)`. `MANDATE_WEIGHT` and `FREQUENCY_WEIGHT` in `stages/demand.py`.
- The 30% block has exactly one buyer: `PROFESSIONAL_COUNCIL`. This is deliberately narrower than `models.REQUIREMENT_TYPES`, which also holds `INSTITUTIONAL_DIRECTION` and still governs evidence and skill classification — the institution's direction binds the program, but it is the program's own voice, and letting it buy the same 30% would let a faculty lift any Need's rank by restating its vision. `test_demand.py` pins the divergence; don't "fix" the two back into agreement.
- Everyone who is not the council sits in one class. What separates an employer's ask from a student's is how often it was raised, not a per-type multiplier. The old table (1.0 / 0.8 / 0.6 / 0.4) is gone: every score depended on numbers nobody could defend, and retuning one moved every stored score.
- The corpus is whatever the caller's `stakeholder_type_by_evidence` map holds. `need_combination` builds it from the extracted skills, so the denominator is the evidence that yielded at least one skill — an evidence item nobody extracted a skill from expresses no demand for a Need to be a share of.
- `is_optional` on a Need is derived from its member skills' classifications: `want` count > `requirement` count + `need` count.
- `classification_coverage` records the per-classification count over member *skills* (not source evidence items, since that is where classification now lives) — the report shows it as e.g. "3 requirement / 2 need / 1 want" under each Need.

**Floor 6, ceiling 10 — enforced at different stages.** `need_combination` still turns every core group clustering finds within a KSEC bucket into its own Need; it merges nothing down to a quota. `MIN_NEEDS=6` (`stages/need_grouping.py`) is a floor code cannot manufacture, so falling short only logs a policy warning at `need_combination` and again at `plo_synthesis`, for the designer to address at the checkpoint. `MAX_CORE_PLOS=10` (`stages/plo_synthesis.py`) is a ceiling code can enforce, and it does so by **selection, not merging**: `synthesis_order` ranks the core Needs by descending `demand_score` and synthesis takes the first 10. The rest stay stored, still trace to their evidence, and are named in the synthesis warning and in `plo_report`'s `needs_not_synthesized`. Optional (want-dominant) Needs are outside both bounds.

The ceiling binds the **stored set**, not just the synthesis loop: `POST /programs/{id}/plos/from-needs` appends a merged PLO and removes nothing, so it returns 422 once the core count already sits at `MAX_CORE_PLOS`, naming the limit. It does not delete the PLOs the merged Needs produced — which outcomes a merge replaces is a designer decision, and a route that guessed would silently discard a reviewed outcome. An all-optional merge is exempt, matching synthesis.

## Stage 4: PLO (plo_synthesis) — cognitive-only, one Need → one PLO

```python
# Bloom's Taxonomy has three learning-domain scales in the OBE tradition
# (see obe-principles.md for the full three-domain picture), but PLO is
# cognitive-only: the agent's scope ends at PLO, and the other two domains'
# level scales are YLO/CLO-era faculty work, not modelled here. This
# codebase has no second or third level-scale class alongside BloomLevel.

class BloomLevel(str, Enum):
    REMEMBER = "remember"
    UNDERSTAND = "understand"
    APPLY = "apply"
    ANALYZE = "analyze"
    EVALUATE = "evaluate"
    CREATE = "create"

class SmartFinding(BaseModel):
    criterion: SmartFindingCode  # eight codes: three hard, five soft
    severity: Literal["hard", "soft"]
    note_th: str  # why, for the designer

class SMARTCheck(BaseModel):
    # Each field combines its hard check (pure code) with the matching soft
    # verdict from the validation agent — none of these are hardcoded True.
    specific: bool   # S_VERB not failed AND specific_object_ok
    measurable: bool # M_FORBIDDEN not failed AND measurable_ok
    achievable: bool # achievable_ok (no hard counterpart)
    relevant: bool   # R_EVIDENCE not failed AND relevant_needs_ok
    timely: bool     # time_bound_ok (no hard counterpart, defaults true)
    notes_th: str | None = None  # rationale or what fails
    findings: list[SmartFinding] = []  # why each false field is false

class PLO(BaseModel):
    """A Program Learning Outcome — what every graduate can do at graduation."""
    # Assigned by code, never by the model — see the note below the class.
    plo_id: str  # "PLO1".."PLOn" for the main set, "OPT1".."OPTn" for supplementary
    program_id: str
    statement_th: str  # the actual outcome text in Thai
    statement_en: str | None = None
    bloom_level: BloomLevel  # cognitive only — no domain field, no other scale
    action_verb_th: str  # the single Bloom verb extracted
    smart_check: SMARTCheck
    source_need_ids: list[str]  # Need IDs that justify this PLO (1+ — see below)
    source_evidence_ids: list[str] = []  # rolled up from those Needs
    rationale_th: str  # why this PLO exists, for designer review
    distinctive_feature_th: str | None = None  # what differentiates this PLO
    version: int = 1
    smart_retry_count: int = 0  # repair drafts the validator asked for (max 3)
    smart_escalated: bool = False  # still hard-failing after repairs → human repair
    soft_flags: list[str] = []  # non-blocking: "S_object", "M_assessable", "A_level", "R_needs", "T_horizon"
    smart_validated_by: str = "legacy"  # agent | code_only | stale | legacy — see below
    smart_diagnosis_th: str | None = None  # the validator's reason, for the designer
    is_optional: bool = False  # PLO from want-dominant Need(s), exempt from the core-Need count
```

**`SupersededPLO` — history of replaced outcomes.** `POST /plos/from-needs` (and review send-back, `cause=review`) replaces every PLO citing a selected Need; `PLORepository.replace` snapshots each removed row into `superseded_plos` in the same transaction as the delete. Read-only: nothing restores from it.

```python
class SupersededPLO(BaseModel):
    id: str
    program_id: str
    superseded_by: str       # plo_id of the PLO that replaced it
    superseded_at: datetime  # naive UTC in the DB; "+00:00" in JSON output
    plo: PLO                 # the row as it stood when removed (JSONB snapshot)
    cause: str | None = None # designer | review; None (older rows) reads as designer
```

`GET /programs/{id}/plos/superseded` lists newest first (ties by `plo_id`) and skips, with a warning, a snapshot that no longer passes `PLO.model_validate`. The table is cleared with the program's PLOs and cascade-deleted with the program; a full program copy clones it (fresh ids, remapped), `evidence_only` copies none.

**One Need → one PLO, with a designer escape hatch.** `stages/plo_synthesis.run()` drafts exactly one PLO per Need — a single focused LLM call each, not a batch call over all Needs. A designer can also merge several Needs into one PLO via `POST /programs/{id}/plos/from-needs`, which calls the same `synthesize_from_needs()` function with more than one Need; that function is shared by both paths so both get identical SMART enforcement and evidence handling. When multiple Needs feed one PLO, `is_optional` is true only if *every* contributing Need is optional. `plo_report` no longer classifies the result generic vs specific — that split (and the `SS`/`GS` KSEC tags it read) no longer exists; the report shows each PLO's actual KSEC tag (`K`/`S`/`EC`/`E`/`C`) instead.

**`plo_id` is assigned by code, never requested from the model.** `PLO1`..`PLOn` for the main set, ordered by descending `Need.demand_score` with `need_id` breaking ties, so `PLO1` is the capability the labour market asked for most and the numbering reproduces across re-runs on the same Needs. Supplementary outcomes from want-dominant Needs get their own `OPT1`..`OPTn` series. Helpers live in `stages/plo_synthesis.py`: `format_plo_id`, `next_plo_id` (for the designer-driven merge endpoint, which creates one outcome at a time), and `synthesis_order`.

This is not a style preference. Synthesis issues one LLM call per Need with no knowledge of the other calls, so a model asked to name its own outcome returns `PLO1` every time; `plo_id` is the table's primary key and `PLORepository.bulk_insert` upserts, so a duplicate silently overwrites instead of failing — a whole set collapsing into one row while the run reports success. A Need whose synthesis fails leaves its number unused rather than renumbering the rest, because designers cite these ids and renumbering would change what `PLO4` refers to between runs.

Validation rules for PLO (enforce in code):
- `statement_th` must not contain forbidden words (รู้, จำ, เข้าใจ, ซาบซึ้ง, ตระหนัก, ศรัทธา, รัก) — see `obe-principles.md`. Exception: a PLO with `smart_escalated=True` may carry them — it exists precisely so a human can repair it, and the SMART gate already failed it loudly.
- `source_need_ids` must be non-empty (no PLO without a Need behind it), and `source_evidence_ids` must be non-empty (no PLO without an evidence trail) — two separate validators, both hard rejects.
- `smart_check` all five fields must be `True` to mark the PLO ready
- Hard vs soft failure handling: S-verb / M-forbidden / R-evidence are pure code (`stages/smart_rules.py`) and are the floor — `validate_and_build` runs them on the final statement whatever the validator said, and that call alone sets `smart_escalated`. The five soft verdicts (`S_object`, `M_assessable`, `A_level`, `R_needs`, `T_horizon`) come from the validation agent, land in `soft_flags` and in the matching `SMARTCheck` field, and never block. Repairs are bounded at 3 per PLO. Implement per the SMART validation checklist in `obe-principles.md`.
- `SMARTCheck.findings: list[SmartFinding]` carries *why*: `criterion` (one of the eight codes), `severity` (`hard`/`soft`), Thai `note_th`. It rides inside the existing `smart_check` JSONB column, so it needed no migration and rows written before it deserialise on the model's default. Do not make it required and do not give `SMARTCheck` `extra="forbid"` — either makes a pre-migration row unreadable, which loses a whole program's PLO list on GET rather than one field.
- `soft_flags` stays `list[str]`, not the enum. A row carrying a code this build no longer knows would otherwise raise on read, and `R_alignment` was emitted for months. The typed detail is in `findings`; a validator keeps the flat list and the soft findings in step, exempting a row that has flags but no findings (that is what `legacy` means).
- `smart_validated_by` distinguishes four facts the UI must not conflate: `agent` (judged and this is the verdict), `code_only` (the validator could not run; the pure checks decided alone), `stale` (a designer edited the statement and nothing has re-judged it — set by `PUT /plos/{id}`), `legacy` (predates the validator). `POST /plos/{id}/revalidate` is what moves a `stale` row back to `agent`.

## Stage 6: PLO QA review (advisory findings, acted on by send-back)

```python
class RedundancyFinding(BaseModel):
    """PLOs the set review reads as one outcome. Advisory."""
    plo_ids: list[str]
    reason_th: str
    suggestion_th: str = ""
    agreed_runs: int = 1                                 # runs that said this; 1 for one-run reviews and old rows

class KsecFinding(BaseModel):
    """Where one PLO's domain should sit, possibly several of K/S/E/C.

    `current` and `agrees` are computed in code from the PLO's Needs; only
    `suggested` and `reason_th` come from the reviewer. Plain `str` lists, not
    a Literal: a stored row must stay readable if the vocabulary ever moves
    (the `soft_flags` lesson)."""
    plo_id: str
    current: list[str]
    suggested: list[str]
    agrees: bool
    reason_th: str = ""
    agreed_runs: int = 1                                 # runs that said this; 1 for one-run reviews and old rows

class BloomFinding(BaseModel):
    plo_id: str
    declared: BloomLevel
    suggested_level: BloomLevel | None = None
    reason_th: str = ""
    agreed_runs: int = 1                                 # runs that said this; 1 for one-run reviews and old rows

class KsecCoverage(BaseModel):
    """PLOs per K/S/E/C (optional included), computed in code. Plain str keys and flags."""
    counts: dict[str, int] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)       # all_k | no_e_or_c

class BloomHistogram(BaseModel):
    """PLOs per Bloom level against the degree level, computed in code."""
    counts: dict[str, int] = Field(default_factory=dict)
    degree_level: str = ""
    flags: list[str] = Field(default_factory=list)       # below_apply_majority

class UnusedNeedFinding(BaseModel):
    """An important Need no PLO cites: facts from code, verdict from the agent."""
    need_id: str
    statement_th: str
    demand_score: float
    ksec_category: str
    stakeholder_types: list[str] = Field(default_factory=list)
    exclusion: str                                       # out_of_scope | unwritten | lost_on_demand
    unwritten: bool = False                              # is_unwritten_need, whatever the exclusion; the agent sees a placeholder, not the statement
    verdict: str | None = None                           # consider | ok_to_leave | None (agent gave none)
    reason_th: str = ""
    agreed_runs: int = 1                                 # runs that said this; 1 for one-run reviews and old rows

class ReviewToolCall(BaseModel):
    """One tool call the QA agent made, in order, for the "what it looked at" list."""
    tool: str                                            # bloom_lookup | check_verbs | need_detail
    arg: str = ""

class PLOSetReview(BaseModel):
    """The QA agent's review of one program's PLO set — see stages/plo_review.py.

    `plo_fingerprint` is the set it was made from; a review whose fingerprint
    no longer matches the stored PLOs is stale and is shown labelled as such."""
    program_id: str
    plo_fingerprint: str
    model: str
    created_at: datetime
    redundancies: list[RedundancyFinding] = Field(default_factory=list)
    ksec: list[KsecFinding] = Field(default_factory=list)
    bloom: list[BloomFinding] = Field(default_factory=list)
    bloom_distribution_th: str = ""
    summary_th: str = ""
    ksec_coverage: KsecCoverage = Field(default_factory=KsecCoverage)        # code
    bloom_histogram: BloomHistogram = Field(default_factory=BloomHistogram)  # code
    coverage_th: str = ""                                # agent's reading of ksec_coverage
    unused_needs: list[UnusedNeedFinding] = Field(default_factory=list)      # code selects, agent judges
    reviewed_by: str = "agent"                           # agent | code_only; "agent" for rows predating the field
    code_only_reason: str | None = None                  # disabled | failed | timeout
    tool_calls: list[ReviewToolCall] = Field(default_factory=list)           # code, in call order
    dropped_findings: dict[str, int] = Field(default_factory=dict)           # code: agent entries accept_review refused, by kind (redundancy|ksec|bloom|unused); {} for code_only and old rows
    runs_requested: int = 1                              # plo_review_runs at the time
    runs_succeeded: int = 1                              # runs with a usable answer
    agreement_threshold: int = 1                         # runs_succeeded // 2 + 1 when >=2 runs
```

`plo_reviews` is one row per program (`program_id` primary key, FK to `programs.program_id`, cascade-deleted with it), holding `plo_fingerprint`, `model`, `created_at`, and the rest of `PLOSetReview` in a single JSONB `review` column — no migration needed for a new finding field, the same reasoning as `SMARTCheck.findings`.

**The agent only advises.** The QA agent reads the finished PLO set as a whole, after the report (it is stage 06; the graph runs `plo_synthesis → [PLO checkpoint] → plo_report → plo_review → END`), and itself writes nothing back to a PLO, a Need, a KSEC tag, or a Bloom level — it has its own table. Agreed redundancy, Bloom and unused-Need findings are then acted on by code (send-back, `stages/plo_feedback.py`, through `plo_redraft`) and recorded as `FeedbackAction` below; KSEC findings stay advisory. `current`, `agrees`, and `declared` in `KsecFinding`/`BloomFinding` are computed from the PLO's own Needs and `bloom_level` in code, never taken from the model; only `suggested`/`suggestion_th`/`reason_th` are the reviewer's. The stage 06 page shows a stored review and labels it stale once `plo_fingerprint` no longer matches the current PLO set and Needs (the fingerprint hashes the PLOs plus the program's `(need_id, demand_score)` pairs); `plo_report` no longer carries a review. Every number and the unused-Need selection are code's (`stages/plo_review_facts.py`); only the judgements are the agent's. A review that could not run (slot disabled, failure, timeout) is stored with `reviewed_by="code_only"`, a `code_only_reason`, the code facts and no agent finding — none is manufactured — and never blocks anything. Every new field defaults, so rows written before them still read; no migration (JSONB, the `SMARTCheck.findings` reasoning).

**`FeedbackAction` — the send-back trail.** One row per actionable finding Agent 4 considered, written right after its action; table `plo_feedback_actions`, same life as `superseded_plos` (cleared with the program's PLOs, cascade-deleted, cloned by a full copy, not by `evidence_only`). `GET /programs/{id}/plos/feedback` lists newest first.

```python
class FeedbackAction(BaseModel):
    id: str
    program_id: str
    review_created_at: datetime   # the review the finding came from
    kind: str                     # redundancy | bloom | unused_need (plain string: a new kind needs no migration)
    plo_ids: list[str] = []
    need_ids: list[str] = []
    finding_reason_th: str = ""   # the reviewer's reason
    instruction_th: str = ""      # what was sent to the redraft
    outcome: str                  # applied | skipped | failed
    outcome_reason_th: str = ""
    result_plo_id: str | None = None   # the PLO written, when applied
```

## Cross-stage: human-in-the-loop checkpoint

```python
class StageCheckpoint(BaseModel):
    """Saved at every stage boundary for human review."""
    checkpoint_id: str
    program_id: str
    stage: Literal[
        "intake", "stakeholder_needs", "skill_extraction",
        "need_combination", "plo_synthesis", "plo_report", "plo_review",
    ]
    artifacts: dict  # serialized output of the stage
    created_at: datetime
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    status: Literal["pending", "approved", "needs_revision", "rejected"] = "pending"
    designer_notes_th: str | None = None
    edits: dict = {}  # any edits the designer made
```

LangGraph's interrupt mechanism saves a `StageCheckpoint` and waits. The React UI fetches pending checkpoints via the FastAPI routes, lets the designer edit, then signals approval. The graph resumes with the (possibly edited) artifacts.

Note: `skill_extraction` and `need_combination` are separate graph nodes but share one checkpoint, placed after `need_combination` — the designer reviews raw extracted skills and the distilled Needs together in one review, not at two separate boundaries. Every other stage boundary gets its own checkpoint.

Exception: after the PLO checkpoint, `plo_report` and `plo_review` run to the end with none (waived by the designer, 2026-10-12; see CLAUDE.md rule 7). The Literal keeps both values because `models.py` does; the graph writes no checkpoint for them.

## Cross-stage: background jobs

```python
JobKind = Literal[
    "needs_pipeline", "skill_extraction", "need_combination",
    "plo_synthesis", "plo_review", "plo_report", "plo_revalidate",
]
JobStatus = Literal["running", "succeeded", "failed"]

class JobInfo(BaseModel):
    """A background stage run as the API reports it (api/jobs.py)."""
    job_id: str
    program_id: str
    kind: JobKind
    label_th: str = ""        # filled by the API from the kind, not stored
    status: JobStatus
    params: dict = {}         # what the run was started with (note_th, plo_id, ...)
    result: Any | None = None # the body the route used to return synchronously
    error_th: str | None = None  # Thai reason, set when status == "failed"
    created_at: datetime
    finished_at: datetime | None = None
```

The seven long run routes answer 202 with a `JobInfo` instead of holding the request open; the stage's own output (`NeedRunResult`, `SkillRunResult`, `list[PLO]`, `PLOReportResponse`, the review response, the revalidated `PLO`) lands in `result` once `status` is `succeeded`. The page reads `GET /programs/{id}/jobs` (`?active=true` for running only) and `GET /programs/{id}/jobs/{job_id}`.

`jobs` is one row per run (`job_id` primary key, FK to `programs.program_id`), `kind` and `status` as plain strings, `params` and `result` as JSONB. Its datetimes are naive UTC like every other table's; `JobInfo` adds `+00:00` only when serialised to JSON, so a browser does not read them as local time.

**One writer per program.** A `running` job, or a graph session whose status is `running`, blocks every other job and the synchronous writers (`POST /sessions/`, `/approve`, `/plos/from-needs`, `/copy`) with a 409 whose `detail` is a Thai string. Rows still `running` after a restart belong to a dead process and are marked `failed` at startup. A job is an operational record, not an OBE artifact: it carries no evidence trail and no stage reads it.

## Versioning

PLOs are mutable objects under designer review. Use this versioning approach:

- `version: int` on PLO, starts at 1
- On every edit, increment version and write a new row (don't update in place)
- Keep a `current_version_id` on the program for the active set
- This preserves audit trail for accreditation

## Database mapping

These Pydantic models map to Postgres tables 1:1 with these adjustments:
- `list[str]` fields → JSON column or junction table depending on access pattern
- `dict` metadata → JSONB column
- `datetime` → a naive UTC `timestamp` column (`DateTime` without a time zone), not `timestamptz`; an API model adds the `+00:00` offset only when it serialises to JSON (`JobInfo` does)
- Enums → Postgres enum types or text with check constraint

Use SQLAlchemy 2.0 with Pydantic for the ORM layer. Schema changes go through Alembic migrations.

## Export formats

For CHECO and มคอ.2 export, derive the document from these models. Don't store CHECO-specific fields on the core models — keep the core clean and transform at export time.

Mapping summary:
- `PLO.statement_th` → CHECO 1.6.2 (ผลลัพธ์การเรียนรู้ของหลักสูตร)
- `ProgramMetadata.program_objectives_th` → CHECO 1.5
