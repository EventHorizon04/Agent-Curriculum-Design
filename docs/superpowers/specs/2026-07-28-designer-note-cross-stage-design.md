# Designer Note — Cross-Stage Context — Design

**Date:** 2026-07-28
**Branch:** main
**Status:** Approved

## Goal

Let a curriculum designer attach a short free-text note when triggering a generation stage, and have the next stage's LLM prompt see it. Today each stage prompt is blind to the designer's intent: a designer who decides at the Need review that "this programme should lean toward AI/Data" has no way to tell PLO synthesis, and re-runs the stage hoping the wording changes.

## Problem in the current code

`AgentState.designer_note` does not exist. `AgentState.designer_notes` (`graph.py:50`) does, and is dead: the `review_*` nodes merge an interrupt payload into state, but no stage reads the key. `StageCheckpoint` (`models.py:310`) and `CheckpointRepository` (`repositories.py:268`) carry `designer_notes_th` and `edits` fields and are never called from anywhere — `CheckpointRepository` has zero call sites outside its own definition.

Two execution paths exist in parallel:

1. **LangGraph session flow** — `graph.py` + `api/routes/sessions.py`, `interrupt()` / `Command(resume=...)`. `Pipeline.tsx` posts to `/sessions/{id}/approve` with no body; the resume payload is hardcoded to `{"checkpoint_status": "approved"}`.
2. **Direct REST stage endpoints** — `needs.py POST /run`, `plos.py POST /run`, `plos.py POST /from-needs`. Each builds a fresh `AgentState` from the database on every call. `SkillExtraction.tsx` and `PloSynthesis.tsx` use these.

Path 2 is what the UI actually drives, and it is where this feature goes. Path 1 is out of scope and is left untouched.

## Scope

**In:** an optional `note_th` on the three direct REST stage endpoints, threaded into the two prompts that write natural-language content.

**Out:**

- Persistence. The note is a per-request input, not a stored row. A re-run needs the note typed again, which matches how these stateless endpoints already behave.
- Accumulation across stages. Each endpoint reads the note from its own request body, so a stage sees the note given to it and nothing earlier. This is the chosen behaviour, and it needs no extra machinery — no reducer, no history table.
- The LangGraph session flow, `StageCheckpoint`, and `CheckpointRepository`. Their deadness is noted above, not fixed here.

## Where the note applies, and where it deliberately does not

| Stage | Note applied? | Why |
| --- | --- | --- |
| `need_combination` — Need sentence | **Yes** — `build_summarize_need_prompt` | Writes prose. Guidance changes the wording. |
| `plo_synthesis` — PLO draft | **Yes** — `build_plo_from_need_prompt` | Writes prose. Guidance changes the wording. |
| `skill_extraction` | No | Extracts verbatim quotes verified against the source (`is_grounded`). Guidance here would push the model to invent spans that the groundedness check then drops. |
| `need_combination` — skill clustering | No | Mechanical grouping, not content. Also cache-relevant: `cluster_skill_names` is cached on a contract fingerprint (`llm_clustering._clustering_contract_fingerprint`), so a per-request note in that prompt would need to enter the cache key or serve stale groupings. |
| `plo_report` | No | Classifies generic/specific. Not authoring. |

`POST /needs/run` runs skill extraction **and** need combination back to back. The note reaches only `need_combination`; `skill_extraction` ignores it.

### SMART retry prompts

`_build_fix_prompt` (`plo_synthesis.py:120`) does **not** receive the note. Its instruction is to repair one named criterion while preserving the existing substance (`คงสาระสำคัญเดิม`), which already carries the note's effect forward through the draft it is repairing. Injecting fresh guidance into a repair prompt invites a rewrite where a repair was asked for.

## Safety

The note is free text from a user, placed in the **user** message (never the system message), and labelled as designer guidance. What it can and cannot reach:

**Cannot be influenced by the note — all code-owned:**

- `source_need_ids` — `_ensure_smart` pins these to `authoritative_need_ids` before the gate runs and after every retry (`plo_synthesis.py:160,173`).
- `source_evidence_ids` — derived in code from the contributing Needs (`plo_synthesis.py:259`). The model is never shown or asked for evidence ids.
- `plo_id` — assigned by `format_plo_id` / `next_plo_id`.
- Forbidden words — `hard_failures` checks `FORBIDDEN_WORDS_TH` in pure code, and `PLO.check_no_forbidden_words` rejects at model construction unless already escalated. A note asking for "เข้าใจ" produces a retry, then an escalated PLO flagged for human repair — not a silent violation.
- Verb-in-statement — `HardCriterion.S_VERB`, pure code.

**Can be influenced — and this is the point:** phrasing, emphasis, which aspect of a Need the statement foregrounds.

**Honest gap, unchanged by this feature:** "one Bloom verb per outcome" is enforced by prompt text only. `hard_failures` checks that `action_verb_th` appears in the statement, not that the statement contains a single verb. The soft judge checks object quality (`S_object`), not verb count. A note nudging toward two verbs would not be caught automatically. This gap predates the note and is not widened by it — but it is the one place where note text could degrade output without a code-level check catching it.

One stable line is added to both system prompts stating that a designer note is guidance on wording and does not override the rules above it. Stable, not conditional, so the prompt text does not vary per request.

## Backend

### `models.py`

```python
NOTE_MAX_CHARS = 500


class DesignerNoteRequest(BaseModel):
    """Optional free-text guidance a designer attaches when triggering a stage.

    Influences wording only. The evidence trail (source_need_ids,
    source_evidence_ids) and plo_id are code-owned and unreachable from here —
    see the stage code for where each is pinned.
    """

    note_th: str | None = Field(default=None, max_length=NOTE_MAX_CHARS)

    @field_validator("note_th", mode="before")
    @classmethod
    def _blank_is_absent(cls, v: object) -> object:
        """Strip before max_length runs (same reason as _SkillItem._strip_text),
        and treat a whitespace-only note as absent so a blank textarea does not
        append an empty guidance block to the prompt."""
        if isinstance(v, str):
            return v.strip() or None
        return v
```

`mode="before"` so the length limit applies to the stripped text, matching the existing pattern in `skill_extraction._SkillItem._strip_text`.

### `graph.py`

Add to `AgentState`:

```python
    # Optional per-request designer guidance, read by the stage that authors prose.
    # Not accumulated: each REST endpoint sets it from its own request body.
    designer_note: str
```

The existing dead `designer_notes: str` key stays as-is — removing it is a separate cleanup, and touching the LangGraph path is out of scope.

### Prompt builders

`prompts/summarize_need.py` — `build_summarize_need_prompt(skill_names, sample_evidence, ksec, note_th=None)`. Appends to the **user** message when `note_th` is truthy:

```
ข้อกำหนดเพิ่มเติมจากผู้ออกแบบหลักสูตร:
{note_th}
```

`prompts/stage_3_plo.py` — `build_plo_from_need_prompt(metadata, needs, note_th=None)`, same block appended to the user message.

Both system prompts gain the stable guidance-not-override line described under Safety.

The skill's mirror of these templates (`.claude/skills/curriculum-design-agent/references/prompts.md`) is updated to match, per the CLAUDE.md rule that prompts live in both places.

### Stages

`need_combination.run` reads `state.get("designer_note")` and passes it to `build_summarize_need_prompt`. The existing except-path fallback (`", ".join(group.skill_names[:5])`) is unaffected.

`plo_synthesis.synthesize_from_needs` gains a keyword-only `note_th: str | None = None` and forwards it to `build_plo_from_need_prompt`. Keyword-only with a default, so both existing call sites (`plo_synthesis.run`, `plos.py /from-needs`) keep working unchanged until each is updated. `plo_synthesis.run` reads `state.get("designer_note")` and passes it per Need.

### Routes

All three take the note as an **optional** body, so the current frontend calls that send no body at all keep working:

```python
# needs.py
@router.post("/run", response_model=NeedRunResult)
async def run_need_pipeline(
    program_id: str, body: DesignerNoteRequest | None = None
) -> NeedRunResult: ...

# plos.py
@router.post("/run", response_model=list[PLO])
async def run_plo_synthesis(
    program_id: str, body: DesignerNoteRequest | None = None
) -> list[PLO]: ...

# plos.py — MergeNeedsRequest inherits the field and its validator
class MergeNeedsRequest(DesignerNoteRequest):
    need_ids: list[str] = Field(min_length=2)
```

Each route sets `state["designer_note"]` only when the note is non-`None`. `AgentState` is `total=False`, so an absent key reads as `None` via `.get` and no empty string is stored.

## Frontend

New shared component `frontend/src/pages/components/DesignerNote.tsx`, alongside the existing `SkillTable.tsx` and `NeedCard.tsx`:

- Labelled textarea, `maxLength={500}`, character counter, Thai label "หมายเหตุถึง AI (ไม่บังคับ)" and a one-line hint that it guides wording only.
- Exports `NOTE_MAX = 500` so the limit is stated once on the client.

`SkillExtraction.tsx` — one `note` state. The textarea renders in both the empty state (above `Run Skill Extraction`) and the populated state (near `Re-run`), since both trigger the same call. `runStage` posts `{ note_th: note || null }`.

`PloSynthesis.tsx` — one `note` state for the page, used by **both** `runSynthesis` and `mergeSelected`. Both call sites end up in `build_plo_from_need_prompt`, so a single field is the honest model; two textareas on one page would be clutter for no gain. Because the field sits with the Run controls and the merge panel is further down, the merge panel shows a read-only echo of the current note when one is set, so the designer is not guided by a note they have scrolled past and forgotten.

## Testing

- **`tests/unit/test_models.py`** — `DesignerNoteRequest`: whitespace-only note becomes `None`; a 501-character note raises `ValidationError`; a 500-character note with trailing spaces passes (proving the strip runs before the limit).
- **New `tests/unit/test_designer_note_prompt.py`** — `build_summarize_need_prompt` and `build_plo_from_need_prompt`: note text appears in the user message and never in the system message; omitting the note leaves the user message free of the guidance header; the guidance-not-override line is present in the system message either way.
- **`tests/unit/test_needs_router.py`** — `POST /needs/run` with no body still succeeds (the backward-compatibility guarantee); with a note, the value reaches `need_combination` (assert on the state the patched stage received); an over-length note returns 422.
- **`tests/unit/test_api_plos.py`** — same three cases for `POST /plos/run`; `POST /from-needs` carries `note_th` into `synthesize_from_needs`.
- **`tests/unit/test_smart_retry_loop.py`** — assert `_build_fix_prompt` output contains no note text when a note was supplied to the draft call, pinning the deliberate decision above.

Each new assertion must fail if the corresponding line of production code is reverted — a test that passes with the feature removed pins nothing.

## Non-goals restated

No migration. No new table. No change to `is_grounded`, the SMART gate, the KSEC bucketing invariant, the 6–10 quota, or the evidence trail. No YLO/CLO. The note is an input to two prompts and nothing else.
