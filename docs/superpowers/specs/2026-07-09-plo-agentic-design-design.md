# PLO Agentic Design System — Design Spec

**Date:** 2026-07-09
**Status:** Approved for planning
**Baseline:** working tree restored from commit `6b3bde1`

## Goal

Rework the restored codebase into a PLO-focused agentic design system: a 5-stage LangGraph pipeline ending at PLO Report, with evidence classification driving skill extraction, Bloom-level cluster grouping, a SMART retry loop per the merged skill rubric, and a 6–10 PLO policy. Success is a full end-to-end run through the real React UI against real Ollama models.

## Current state (after restore)

- Full PoC code from `6b3bde1`: 5 stages with YLO detached from the graph, PLO Report stage implemented (generic/specific classification), React UI with pages per stage, 40+ passing tests, Alembic migrations.
- `StakeholderEvidence.classification` (need/requirement/want) exists in the schema and classification prompt, but is **not consumed** downstream — `demand_score` ignores it.
- `SkillCluster` has `is_subject_specific` but no Bloom level.
- A SMART validator prompt exists but there is no hard/soft classification or bounded retry loop.
- PLO synthesis prompt asks for 4–6 PLOs.
- On-disk `CLAUDE.md` is the pre-restart version (restored from HEAD) and must be replaced as part of this work.

## Architecture

### Pipeline (LangGraph, HITL at every boundary)

```
intake → stakeholder_needs → skill_extraction → plo_synthesis → plo_report
```

Each stage remains an isolated LangGraph node with typed I/O and an `interrupt` checkpoint. YLO nodes and code are **removed** (recoverable from git history).

### Feature 1 — Evidence classification as extraction context

The need/requirement/want classification produced in `stakeholder_needs` becomes load-bearing:

1. **Extraction context:** each evidence item carries its classification into skill extraction; extraction prompts receive it.
2. **Weighting:** `demand_score` is computed from **requirement + need evidence only**. Want evidence contributes zero weight.
3. **Cluster coverage:** `SkillCluster` gains `classification_coverage: dict[str, int]` (counts per classification) so the designer can see the evidence mix.
4. **Optional clusters:** a cluster whose evidence is majority-want is marked `is_optional: bool = True`. Optional clusters are excluded from the main PLO synthesis input.
5. **Optional PLO candidates:** synthesis runs a second, separate pass over optional clusters producing PLO candidates marked `is_optional`. These do not count toward the 6–10 main PLO policy and are rendered in the PLO Report page as a distinct "optional" section for the designer to accept or discard.

### Feature 2 — Bloom grouping of skill clusters

A new sub-step at the end of `skill_extraction`, after clustering and naming:

1. The light model tags each `SkillCluster` with `bloom_level` (Bloom for cognitive clusters; clusters whose `skill_type` is `affective` get `krathwohl_level` instead) and confirms/corrects `is_subject_specific`.
2. The `review_clusters` checkpoint and the SkillExtraction UI page display clusters **grouped by Bloom level**, with a visual distinction between specific and generic clusters.
3. PLO synthesis receives the Bloom level in each cluster summary, guiding action-verb selection toward the right cognitive level.

### Feature 3 — SMART retry loop (in the `plo_synthesis` handler)

Per the rubric in `.claude/skills/curriculum-design-agent/references/obe-principles.md`:

1. **Validation order and classification:**
   - **[S, hard]** exactly one Bloom action verb applied to a named, non-generic object. Verb check is code (verb list + PyThaiNLP tokenization); the "non-generic object" test uses the light model.
   - **[M, hard]** no forbidden word (รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก) — pure string check.
   - **[R-evidence, hard]** `source_cluster_ids` non-empty and resolving to real clusters — pure code.
   - **[A, soft]** Bloom level plausible for qualification level/resources — light model, produces a flag.
   - **[R-alignment, soft]** semantic alignment with program vision — light model, produces a flag.
2. **Retry loop:** hard fails retry **per failing PLO** (not the whole set), max 3 attempts, and each retry prompt names the specific violated criterion. A PLO still failing after 3 attempts is marked `smart_escalated = True` and kept for human review.
3. **Checkpoint surface:** `review_plos` shows soft flags and escalated PLOs so the designer sees exactly what needs attention.

### Feature 4 — Policy and scope updates

- PLO synthesis prompt and validators updated from 4–6 to **6–10 PLOs** (optional PLO candidates excluded from the count).
- All YLO code removed: `stages/ylo_derivation.py`, `prompts/stage_4_ylo.py`, `api/routes/ylos.py`, `frontend/src/pages/YloDerivation.tsx` (and its route/nav entries), `YLO`/`YLOMatrix` models, `tests/unit/test_ylo_matrix.py`, plus a migration dropping YLO tables.

## Data model changes (one Alembic migration)

| Model | New fields |
|---|---|
| `PLO` | `smart_retry_count: int = 0`, `smart_escalated: bool = False`, `soft_flags: list[str] = []`, `is_optional: bool = False` |
| `SkillCluster` | `bloom_level: BloomLevel \| None`, `krathwohl_level: KrathwohlLevel \| None`, `is_optional: bool = False`, `classification_coverage: dict[str, int] = {}` |

`demand_score` computation changes in place (no schema change). Dropped: YLO tables.

## API / UI changes

- **API:** remove `routes/ylos.py`; extend cluster and PLO responses with the new fields; PLO Report endpoints include optional PLOs.
- **UI:**
  - `SkillExtraction.tsx`: clusters grouped by Bloom level, specific/generic badges, optional-cluster indicator.
  - `PloSynthesis.tsx`: show soft flags and escalated markers per PLO.
  - `PloReport.tsx`: new "optional PLOs" section (from want-based clusters) alongside the existing generic/specific list + matrix views.
  - `StageLayout.tsx` / `App.tsx`: remove YLO nav and route.
- **Vite proxy:** verify every top-level API prefix used by the UI is in `vite.config.ts` proxy config (known pitfall).

## Docs sync

- Replace on-disk `CLAUDE.md` with the current-scope version (5 stages ending at PLO Report, React UI, hybrid deploy, 6–10 PLOs, skill at `.claude/skills/curriculum-design-agent/`).
- Update skill `references/data-schemas.md` and `references/prompts.md` where the new fields and the optional-PLO pass change the documented schemas/prompts.

## Error handling

- LLM failure mid-retry counts as a failed attempt; after max attempts the PLO escalates rather than crashing the stage.
- Optional-PLO pass failure does not block the main PLO set — log and continue with a warning flag on the checkpoint.
- Bloom-tagging failure for a cluster leaves `bloom_level = None` and flags the cluster at the checkpoint; PLO synthesis treats untagged clusters as before (no level hint).

## Testing

TDD order:

1. **Unit (pure code first):** demand_score weighting (want = 0), majority-want → `is_optional`, forbidden-word check, verb-count check, evidence-trail check, retry-loop bookkeeping (attempt count, escalation), 6–10 count validation.
2. **Unit (mocked LLM):** Bloom tagging per cluster, S non-generic-object judgment, soft-flag generation, per-PLO retry prompt contains the violated criterion.
3. **Integration (mocked LLM):** full `skill_extraction` with Bloom sub-step; full `plo_synthesis` with retry loop and optional pass; graph wiring (5 stages, no YLO nodes).
4. **E2E (manual, real Ollama):** `start-dev.ps1` + `npm run dev`; run intake → PLO Report in the browser; success = 6–10 main PLOs all SMART-passing or explicitly escalated, clusters visibly grouped by Bloom, optional PLOs displayed in the report.

## Out of scope

- YLO/CLO generation (removed by design)
- New scrapers or data sources
- CHECO/มคอ.2 exporter changes beyond compiling against renamed models
- Production hardening (vLLM, multi-tenant)
