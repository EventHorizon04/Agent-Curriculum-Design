# Need-Based Pipeline Design

**Date:** 2026-07-26
**Branch:** `feature/need-based-pipeline` (targets `main`)
**Status:** Approved

## Goal

Restructure stages 2–4 so that the artifact between skills and PLOs is an explicit **Need** —
one market-perspective sentence carrying evidence, frequency, and demand — and so that every
skill and every Need carries exactly one unambiguous competency tag.

Four problems with the current pipeline motivate this:

1. **Skill extraction does too much.** `stages/skill_extraction.py` extracts, dedupes, clusters,
   names clusters, Bloom-tags, and scores demand in a single node. The Stage 3 review page shows
   clusters as the primary object, so a designer cannot inspect raw extraction quality.
2. **Tags mix.** A skill carries three overlapping fields (`skill_type` including a literal
   `"mixed"` value, `is_subject_specific`, `ksec_category`). "Mixed" is unusable for MHESI
   mapping, and the three fields can disagree with each other.
3. **PLO synthesis is one big call.** One prompt asks for 6–10 PLOs across many clusters at once,
   which the project's own guidance warns against.
4. **No explicit market-vs-graduate distinction.** Clusters are named capabilities; PLOs are
   graduate outcomes. Nothing in the data model records the market-side statement, so the
   traceability story ("which market demand does this PLO answer?") is implicit.

## Pipeline shape

```
intake
  ↓ review
stakeholder_needs      community/parent → want (pure code); others → LLM (requirement|need)
  ↓ review
skill_extraction       raw skills only: phrase + cognitive Bloom + one KSEC tag + groundedness
  ↓ (no checkpoint)
need_combination       dedupe/Bloom-max → per-bucket cluster → freq+demand → merge to 6–10 → summarize
  ↓ review             ← single checkpoint, two tabs (raw skills | Needs)
plo_synthesis          1:1 Need→PLO; designer may merge N Needs into 1 PLO
  ↓ review
plo_report
```

`skill_extraction` and `need_combination` are separate LangGraph nodes but share **one** HITL
checkpoint, placed after `need_combination`. Separate nodes keep each file focused and unit
testable; a single checkpoint avoids asking the designer to approve raw skills they cannot yet
judge in context.

`StageCheckpoint.stage` gains the value `"need_combination"`. The existing
`"skill_extraction"` value is retained so already-persisted checkpoint rows still deserialize.

### Code moved out of `skill_extraction.py`

`stages/llm_clustering.py`, `prompts/name_cluster.py`, and `prompts/classify_cluster_bloom.py`
become the property of `stages/need_combination.py`. Skill extraction keeps only per-evidence
extraction, tagging, groundedness validation, and per-skill-name importance.

The weighted scoring formula is needed by **both** stages — skill extraction scores each skill
name, `need_combination` scores each group — so it moves to a new shared module
`stages/demand.py` holding `compute_demand_score()` and the `WEIGHTED_CLASSES` constant. Both
stages import it; neither owns it. (Without this, `_compute_skill_importance` in one stage would
have to reach into the other stage's private helper.)

## Data model

### New: `KSECCategory` replaces three fields

The TQF/มคอ. domains collapse to five tags, with the skill domain split by specificity:

```python
class KSECCategory(StrEnum):
    K = "K"    # ความรู้
    GS = "GS"  # ทักษะทั่วไป (generic/transferable)
    SS = "SS"  # ทักษะเฉพาะสาขา (subject-specific)
    C = "C"    # คุณลักษณะบุคคล
    E = "E"    # คุณธรรมจริยธรรม
```

This single field replaces `skill_type` (which carried the unusable `"mixed"` value),
`is_subject_specific` (absorbed into the GS/SS split), and the previous four-value
`ksec_category`. One skill has exactly one tag; "mixed" becomes unrepresentable.

`KSECCategory` is **not** a Bloom domain. It is a compliance tag for eventual มคอ.2/CHECO
mapping, orthogonal to `bloom_level`. A skill may legitimately be `SS` while sitting at Bloom
`analyze`.

### `StakeholderType` gains `PARENT`

```python
PARENT = "parent"   # ผู้ปกครอง
```

### `ExtractedSkill`

| Field | Change |
|---|---|
| `ksec_category: KSECCategory` | replaces `skill_type` + `is_subject_specific` + old 4-value tag |
| `bloom_level: BloomLevel` | now **required** (was nullable); cognitive scale only |
| `evidence_span_th: str` | **new** — verbatim quote from the source evidence (see Groundedness) |
| `extraction_method` | narrows to `Literal["llm", "manual"]`; `keybert`/`ner` die with the NLP stack |
| `importance_score` | kept — per-skill-name demand, drives the raw-skill tab ordering |
| `skill_type`, `is_subject_specific` | **removed** |

### `SkillCluster` → `Need`

```python
class Need(BaseModel):
    need_id: str
    program_id: str
    statement_th: str                 # THE one sentence, market perspective
    statement_en: str | None
    ksec_category: KSECCategory       # guaranteed single-valued by bucketed clustering
    bloom_level: BloomLevel           # max across member skills
    member_skill_ids: list[str]
    source_evidence_ids: list[str]
    stakeholder_coverage: dict[StakeholderType, int]
    freq: int                         # new: len(member_skill_ids) — mentions, not unique names
    demand_score: float               # weighted score (existing formula)
    is_optional: bool                 # want-dominant → supplementary
    classification_coverage: dict[str, int]
    sample_quotes_th: list[str]
```

`canonical_name_th`, `canonical_name_en`, and `description_th` collapse into `statement_th`.
Removed: `skill_type`, `is_subject_specific`, `psychomotor_level`, `krathwohl_level`, and
`is_common_need` — the last is redundant now that Need count is capped at 6–10 during merge and
every non-optional Need becomes a PLO.

### `PLO`

| Field | Change |
|---|---|
| `source_need_ids: list[str]` | replaces `source_cluster_ids`; a list, so the N:1 designer merge works |
| `bloom_level: BloomLevel` | now required |
| `domain`, `psychomotor_level`, `krathwohl_level` | **removed** — every PLO is cognitive |

`is_subject_specific` stays, populated from the source Need's tag (`SS` → true, `GS` → false,
`K`/`C`/`E` → LLM judgment during synthesis).

### Enums deleted

`SkillType`, `PsychomotorLevel`, `KrathwohlLevel`, `Domain`, and their `*_ORDER` lists become
unreferenced and are removed. The psychomotor/affective sections of
`references/obe-principles.md` are retained but marked as faculty reference for the YLO/CLO
hand-off, not agent behavior.

### Migration (destructive)

One Alembic revision:

- `clusters` → `needs`: rename the table and `cluster_id` → `need_id`; drop `canonical_name_th`,
  `canonical_name_en`, `description_th`, `skill_type`, `is_subject_specific`, `psychomotor_level`,
  `krathwohl_level`, `is_common_need`; add `statement_th`, `statement_en`, `freq`
- `skills`: drop `skill_type`, `is_subject_specific`; add `evidence_span_th`; `bloom_level`
  becomes `NOT NULL`
- `plos`: drop `domain`, `psychomotor_level`, `krathwohl_level`; rename `source_cluster_ids` →
  `source_need_ids`; `bloom_level` becomes `NOT NULL`

Existing program data is **not** backfilled. Skills persisted before this change have no
`evidence_span_th` and carry the old four-value tag, so any program already past Stage 2 must
re-run `skill_extraction` onward. This is acceptable because the project is a proof of concept
with no production data. Recorded here so the decision is not rediscovered later.

## Stage internals

### `stakeholder_needs.py`

```python
_WANT_ONLY_TYPES = {StakeholderType.COMMUNITY, StakeholderType.PARENT}
```

A hard rule in both directions:

- Evidence from community or parent stakeholders is classified `want` in **pure code**, with no
  LLM call. Deterministic and free.
- Evidence from every other stakeholder type goes to the LLM, whose prompt offers only
  `requirement` and `need`. `want` is not selectable. An LLM failure yields `unclassified`.

`prompts/classify_evidence.py` drops the `want` option from its instruction text.

### `skill_extraction.py`

Per evidence item, one cache-first light-model call returns skills shaped as:

```python
class _SkillItem(BaseModel):
    skill_name_th: str           # a phrase / skill word-group, never a single bare word
    skill_name_en: str | None
    ksec_category: Literal["K", "GS", "SS", "C", "E"]
    bloom_level: Literal["remember", ..., "create"]
    evidence_span_th: str        # verbatim quote justifying this skill
    confidence: float
```

The prompt requires skills to be **unique and independent** — non-overlapping capabilities, not
restatements of each other.

**Groundedness validation (pure code, no extra LLM call).** `evidence_span_th` must appear in
the source evidence text after whitespace normalization. A span the model invented fails the
substring test, and the skill is dropped and counted. This verifies grounding instead of
trusting a model's self-reported confidence, and costs nothing.

*Risk:* a model that paraphrases instead of quoting will fail the check and inflate the drop
rate. The drop rate is logged per run. If it is implausibly high in practice, relax the check to
a fuzzy/token-overlap match rather than removing it.

Relevance to the program field cannot be verified in code and remains an LLM judgment
instruction, subject to the same drop policy.

### `need_combination.py` (new)

```
1. Bucket skills by ksec_category → 5 independent buckets
2. Per bucket: dedupe by normalized name, merging Bloom levels by MAX
   (same name at `remember` and `analyze` → `analyze`)
3. Per bucket: cluster_skill_names()          [existing module, temperature 0, cached]
4. Per group: compute freq and demand_score
5. Per group: is_optional = want evidence outnumbers requirement+need evidence
6. If non-optional groups > 10: merge within each bucket down to a per-bucket quota
7. Per surviving group: summarize into one market-perspective Thai sentence
8. If non-optional groups < 6: log a warning; do not fabricate
```

`freq` is `len(member_skill_ids)` — how many times the capability was *mentioned* across all
evidence, not how many distinct skill names the group holds. A capability named five different
ways in twelve postings has `freq = 12`, which is what makes the number explainable to a
designer.

**Quota allocation (step 6), stated explicitly so it is not reinvented at implementation time.**
Let `G` be the total non-optional group count and `Gb` the count in bucket `b`:

```
target_b = max(1, floor(10 * Gb / G))          for every bucket with Gb > 0
while sum(target_b) > 10:  decrement the target of the bucket with the lowest total demand
                           (never below 1)
while sum(target_b) < 10:  increment the target of the bucket with the highest total demand
                           (never above Gb)
```

Allocation is by group share rather than demand share so that a bucket holding many distinct
capabilities is not squeezed out by one bucket holding a single very high-demand capability;
demand breaks ties. Every non-empty bucket keeps at least one Need, which preserves the
subject-specific/generic balance the project requires. A bucket already at or below its target is
left untouched — merging only ever reduces.

**Bucketed clustering is what structurally guarantees single-valued tags.** Clustering runs
inside one KSEC bucket at a time and merging never crosses buckets, so no Need can ever contain
skills of two different tags. The alternative — cluster globally, then vote for a dominant tag —
would assign an arbitrary label to genuinely mixed groups, which is the problem this design
exists to remove.

Optional (want-dominant) Needs are exempt from the 6–10 count, consistent with the existing
project rule for optional PLOs. Only non-optional Needs are counted and quota-merged.

### `plo_synthesis.py`

One focused LLM call per Need, replacing the single call that requested 6–10 PLOs at once. This
follows the project's own guidance against asking for many outcomes in one prompt, and each call
can name its Need directly.

- Non-optional Need → one PLO
- Optional Need → one PLO with `is_optional=True`
- Designer-selected group of Needs → one PLO with several `source_need_ids`

The Need states what the market demands ("สามารถวิเคราะห์ข้อมูลขนาดใหญ่เพื่อหา insight ทางธุรกิจ");
the PLO restates it as what a graduate can do, with a single Bloom verb, no forbidden words, and
a passing SMART gate. The existing `_ensure_smart` retry loop is reused without modification.

Calls stay sequential, matching current style. Parallelising with `asyncio.gather` is a
straightforward follow-up if 6–10 sequential synthesis calls prove slow.

## UI

**Stage 3 page — two tabs, one approve button** (the checkpoint covers both). The page is rebuilt
rather than patched; the current cluster-first layout does not survive the restructure.

**Tab 1 — Skill ดิบ: a sortable table**, not cards. Columns:

| Column | Source | Notes |
|---|---|---|
| Skill | `skill_name_th` (`skill_name_en` secondary) | |
| Bloom's | `bloom_level` | Thai + English label |
| KSEC | `ksec_category` | one of K / GS / SS / C / E, colour-coded |
| Stakeholder class | source evidence `classification` | requirement / need / want only |
| Importance score | `importance_score` | default sort, descending |

A table beats cards here because the designer's task on this tab is scanning for outliers across
a few hundred rows — wrong tag, implausible Bloom level, suspiciously low importance — which is
comparison across rows, exactly what a table is for.

The source `stakeholder_type` (employer, alumni, community, …) is deliberately **not** a column.
It appears on row expand instead: it is provenance a designer occasionally drills into, not a
field worth scanning across hundreds of rows, and `classification` already carries the signal
that matters for judging a skill.

`evidence_span_th` is too long for a column, so it appears on row expand together with the source
evidence name. Above the table sits the drop summary: "ทิ้งไป N ทักษะ (ยกอ้างไม่ตรง evidence)".

**Tab 2 — Need** — 6–10 cards showing `statement_th`, Freq, Demand, KSEC, Bloom. Cards rather
than a table because a Need is a sentence to be read, and there are at most ten. Expanding a card
reveals member skills and the evidence trace.

**PLO synthesis page** — multi-select over Needs plus a "รวมเป็น PLO เดียว" action, implementing
the optional N:1 mapping.

## Error handling

| Failure | Behavior |
|---|---|
| Extraction LLM fails for one evidence item | Warn, skip that item (existing behavior) |
| Groundedness check fails | Drop the skill, count it, surface the count in the UI |
| Clustering or merge LLM fails | `validate_assignments` already guarantees no skill is lost — unassigned skills become singletons |
| Merge returns the wrong group count | Pure-code fallback: merge the lowest-demand pairs within the bucket until the total is ≤ 10 |
| Summarize fails for a group | Fall back to joining member skill names (existing pattern) |
| Fewer than 6 non-optional Needs | Warn at the checkpoint; the designer adds Needs by hand |

## Testing

Validators first, per project guidance — they are the cheapest guardrail and every downstream
test depends on them.

**Unit**

- `KSECCategory` has exactly the five values; `"mixed"` and bare `"S"` are rejected
- `ExtractedSkill` rejects a missing `bloom_level` and a missing `evidence_span_th`
- `Need` requires non-empty `member_skill_ids` and `source_evidence_ids`
- `PLO` requires non-empty `source_need_ids`; forbidden-word rejection still holds
- Bloom max-merge: the same normalized name at `remember` and `analyze` resolves to `analyze`
- Groundedness: whitespace-normalized quotes pass; invented text fails
- **Bucket purity: skills of differing `ksec_category` never land in the same Need**
- Quota: more than 10 groups merges to a total ≤ 10, and every bucket that had groups keeps at
  least one; fewer than 6 warns rather than raising
- Want rule: community/parent evidence is classified `want` with the LLM mock asserted
  *not called*; employer evidence takes the LLM path and cannot receive `want`
- One-to-one: N Needs produce N PLOs; an optional Need produces a PLO with `is_optional=True`

**Integration**

- Full `skill_extraction` → `need_combination` → `plo_synthesis` run with the LLM mocked
- Update `test_skill_extraction_cache.py`, `test_cluster_bloom.py`, `test_demand_score.py`, and
  `test_end_to_end.py`, which reference the moved and removed code

## Conflicts with project rules, and how they are resolved

`CLAUDE.md` requires that conflicts with immutable rules be surfaced rather than silently
absorbed. Two rules interact with this design.

**Rule 6 — 6–10 main PLOs.** A literal 1:1 Need→PLO mapping would make the PLO count equal the
Need count, which is uncontrolled. Resolution: the constraint moves upstream. `need_combination`
merges non-optional Needs down to 6–10, and PLO synthesis then maps 1:1. The rule is preserved;
it is enforced one stage earlier, where a designer can review the merge at the checkpoint.

**Rule 7 — HITL at every stage boundary.** `skill_extraction` → `need_combination` has no
checkpoint between them. Resolution: these two nodes form one reviewable stage with a single
checkpoint whose two tabs expose both artifacts. The boundary that matters to a designer — raw
extraction quality and the distilled Needs — is still reviewed before anything reaches PLO
synthesis, and nothing auto-chains past that checkpoint.

Rules 1–5 and 8 are unaffected. Evidence traceability (rule 2) is strengthened: the
`evidence_span_th` groundedness check makes the skill→evidence link verifiable in code rather
than asserted by the model.
