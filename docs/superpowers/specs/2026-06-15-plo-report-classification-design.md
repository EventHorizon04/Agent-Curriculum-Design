# PLO Report & Generic/Specific Classification — Design

**Date:** 2026-06-15
**Status:** Approved (design phase)
**Supersedes (active flow only):** Stage 5 YLO Derivation is removed from the active pipeline. YLO code is retained for later — see Immutable Rule #1.

## Goal

Replace Stage 5 (YLO Derivation) in the *active* PoC pipeline with a **PLO Report** stage that classifies every PLO as **generic** (transferable / cross-discipline) or **specific** (subject / domain knowledge), then presents the result to a human reviewer for edit before finalizing.

This narrows PoC scope. YLO is deferred, not abandoned: the agent's PLO → YLO → CLO architecture (Immutable Rule #1) is preserved by keeping all YLO code and only detaching it from the graph edges and UI nav.

## Definitions

- **Generic skill** — transferable, cross-discipline (communication, critical thinking, teamwork). Maps to `is_subject_specific = false`.
- **Specific skill** — subject / domain knowledge (write Python, design a database). Maps to `is_subject_specific = true`.

## Scope

**In scope:**
1. Detach YLO from the active pipeline (graph + UI nav), keep code.
2. New `plo_report` stage that classifies each PLO generic/specific via method D (structured fields first, LLM fallback).
3. Additive PLO model fields for classification + method + rationale.
4. HITL review node after the report stage.
5. New `PloReport.tsx` frontend: grouped list view + PLO × Cluster matrix, inline edit.

**Out of scope:**
- YLO derivation (deferred).
- Deleting any YLO code, route, model, test, or migration.
- CLO (faculty work, never in this agent).

## Pipeline Change

Current active graph (`graph.py`):

```
intake → stakeholder_needs → review_evidence → skill_extraction → review_clusters
       → plo_synthesis → review_plos_node → ylo_derivation → review_ylo → END
```

New active graph:

```
intake → stakeholder_needs → review_evidence → skill_extraction → review_clusters
       → plo_synthesis → review_plos_node → plo_report → review_plo_report → END
```

- Add nodes `plo_report` (stage) and `review_plo_report` (HITL interrupt).
- Remove edges into/out of `ylo_derivation` and `review_ylo`. **Keep** the node functions `stage_4_ylo_derivation`, `review_ylo_matrix`, and the `stages/ylo_derivation.py` module — they are simply no longer wired.
- `AgentState` keeps `ylo_matrix` (unused for now). No state field removed.

UI:
- `StageLayout.tsx` nav: replace `{ path: '/ylo-derivation', label: 'Stage 5: YLO Derivation' }` with `{ path: '/plo-report', label: 'Stage 5: PLO Report' }`. Keep the `/ylo-derivation` route registered in `App.tsx` (reachable directly, just not in nav).
- `PloSynthesis.tsx` "ดำเนินการต่อ" link points to `/plo-report` instead of `/ylo-derivation`.

## Data Model

Add three **optional** fields to `PLO` in `models.py` (additive — existing validators and rows unaffected; existing rows deserialize with `None`):

```python
classification: Literal["generic", "specific"] | None = None
classification_method: Literal["skill_type", "llm", "manual"] | None = None
classification_rationale_th: str | None = None
```

**Relationship to `is_subject_specific`:** `is_subject_specific` already encodes the same axis (`true` = specific, `false` = generic). To avoid a second source of truth diverging, the report stage **syncs** them:

- `classification == "specific"` ⟺ `is_subject_specific == True`
- `classification == "generic"` ⟺ `is_subject_specific == False`

`classification` is the new primary because it additionally carries `classification_method` and `classification_rationale_th`. Any write that sets one MUST set the other consistently (enforced in the stage and in the update route).

### ORM / migration

`PLOTable` in `orm.py` gains three nullable columns: `classification`, `classification_method`, `classification_rationale_th` (all `String`/`Text`, nullable). One Alembic autogenerate migration. Existing rows get `NULL`.

## Stage Logic — Method D (`stages/plo_report.py`)

A new module mirroring the structure of `plo_synthesis.py`. Exposes `async def run(state: AgentState) -> AgentState`.

For each PLO in `state["plos"]`:

1. Resolve source clusters from `plo.source_cluster_ids` against the program's clusters (loaded via `ClusterRepository().list_by_program`).
2. **Primary signal:** each `SkillCluster` has `is_subject_specific: bool`. Compute
   `specific_fraction = (# clusters with is_subject_specific) / (# resolved clusters)`.
   `skill_type` is a secondary signal recorded in the rationale but not used for the threshold.
3. **Clear field-based decision:**
   - `specific_fraction >= 0.67` → `classification = "specific"`, `method = "skill_type"`
   - `specific_fraction <= 0.33` → `classification = "generic"`, `method = "skill_type"`
4. **Ambiguous** (`0.33 < specific_fraction < 0.67`, **or** zero resolvable clusters): **LLM fallback.**
   - Call `complete_light` with a typed response model (`_ClassificationResult` with `classification: Literal["generic","specific"]` and `rationale_th: str`).
   - Prompt input: PLO `statement_th`, `domain`, and a ≤200-token summary per source cluster (canonical name + skill_type + is_subject_specific). Follow the CLAUDE.md rule: summarize clusters, never dump full evidence.
   - `method = "llm"`.
5. Build `classification_rationale_th`:
   - Field-based: e.g. `"{n}/{m} source clusters เป็น subject-specific (fraction {x})"`.
   - LLM: the model's `rationale_th`.
6. Sync `is_subject_specific` to match `classification`.
7. Persist via `PLORepository` (bump `version`), and write back to `state["plos"]`.

Set `state["current_stage"] = "plo_report"`.

Prompt builder lives in `prompts/plo_classify.py` (typed builder function, per CLAUDE.md prompt convention).

### HITL node

`review_plo_report(state)` in `graph.py` calls `interrupt("Stage 5 complete — review/edit PLO generic-specific classification")` and merges any returned payload (same pattern as the other four review nodes).

## API

`routes/plos.py`:

- **New:** `POST /programs/{program_id}/plos/report/run` → loads program + PLOs + clusters, runs `plo_report.run`, returns `list[PLO]`. Mirrors the existing `/plos/run` handler. 422 if no PLOs exist yet.
- **Modified:** existing `PUT /programs/{program_id}/plos/{plo_id}` accepts the new fields. When a human edits `classification`, the route sets `classification_method = "manual"` and syncs `is_subject_specific` server-side (do not trust the client to keep them consistent). Still guarded by `require_api_key`.

The matrix needs no new endpoint — the frontend composes it from `GET /plos/` (each PLO carries `source_cluster_ids`) and `GET /clusters/`.

## Frontend — `PloReport.tsx`

Two views toggled by a tab/segment control:

**1. Grouped list (default)**
- Two sections: **Generic Skills** and **Specific Skills**.
- Each PLO row: `plo_id`, `statement_th`, domain/bloom badge, `classification_method` badge (`skill_type` / `llm` / `manual`), rationale (collapsible).
- Inline control to flip generic ⟷ specific → `PUT` the PLO; on success the row moves to the other section and method badge becomes `manual`.
- Summary header: counts of generic vs specific, and "X classified by field / Y by LLM / Z manual".

**2. Matrix (PLO × Cluster)**
- Rows = PLOs (grouped/sorted by classification).
- Columns = the union of clusters referenced across all PLOs (`GET /clusters/`, filtered to those appearing in any `source_cluster_ids`), labeled by `canonical_name_en ?? canonical_name_th`.
- Cell = ✓ when `cluster_id ∈ plo.source_cluster_ids`, blank otherwise.
- Leading frozen column shows the generic/specific badge per PLO row.
- Horizontal scroll for wide cluster sets.

**HITL finalize:** the Pipeline page's existing session approve/reject drives finalization (the graph suspends at `review_plo_report`). `PloReport.tsx` itself is the review surface; approval happens through the existing session UI. A short note/link on `PloReport.tsx` directs the user to the Pipeline page to approve once edits are done.

Routing: add `/plo-report` route in `App.tsx`; nav entry in `StageLayout.tsx`.

## Testing

**Unit (`tests/unit/`):**
- `test_plo_report.py`:
  - field-clear specific (all clusters subject-specific) → `classification="specific"`, `method="skill_type"`, no LLM call.
  - field-clear generic (all clusters not subject-specific) → `classification="generic"`, `method="skill_type"`, no LLM call.
  - ambiguous fraction (≈0.5) → LLM fallback invoked (mocked `complete_light`), `method="llm"`.
  - zero resolvable clusters → LLM fallback.
  - sync invariant: after run, `is_subject_specific == (classification == "specific")` for every PLO.
- PLO model: existing validators still pass with the new optional fields set and unset.

**Router (`tests/unit/test_plos_router.py` or extend existing):**
- `POST /plos/report/run` returns classified PLOs (repositories + stage mocked).
- `PUT /plos/{id}` with `classification="generic"` → response has `classification_method="manual"` and `is_subject_specific=False`.

**Full suite:** `uv run pytest` green; `ruff` + `mypy` clean.

## Risks / Notes

- **Immutable Rule #1** (PLO → YLO → CLO): preserved. YLO is deferred, code retained; this is a scope decision, not an architecture change. Resuming YLO later = re-add two edges + nav entry.
- The `is_subject_specific` ⟺ `classification` sync is the main correctness hazard. It is enforced in exactly two write paths (stage + update route); both must keep them consistent. Covered by the sync-invariant test.
- LLM fallback uses the light model (`complete_light`) — classification is a simple binary, no need for the heavy model.
