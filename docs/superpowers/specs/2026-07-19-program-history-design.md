# Program History — Design

**Date:** 2026-07-19
**Branch:** main
**Status:** Approved (approach A)

## Goal

Let users see every curriculum (program) ever created and resume work on any of them. Today the UI only tracks the single `program_id` stored in localStorage; there is no way to list or reopen past programs.

## Approach

Reuse existing data. No DB migration.

- `programs` table already stores metadata + `created_at`.
- `sessions` table already stores `status` + `current_stage` per program.
- A new list endpoint joins the two; a new frontend landing page renders the list.

Rejected alternatives: a dedicated audit-log table (overkill for "what exists"), and a denormalized `current_stage` column on `programs` (duplicates what `sessions` already records).

## Backend

### Model (`src/curriculum_agent/models.py`)

```python
class ProgramSummary(BaseModel):
    program_id: str
    name_th: str
    name_en: str
    degree_level: str
    created_at: datetime
    current_stage: str | None   # from latest session; None = no session yet
    session_status: str | None  # from latest session; None = no session yet
```

Summary model, not full `ProgramMetadata` — the list page doesn't need mission/philosophy text blobs.

### Repository (`src/curriculum_agent/data/repositories.py`)

`ProgramRepository.list_all() -> list[ProgramSummary]`

- LEFT JOIN each program to its **latest** session (max `created_at` per `program_id`).
- Order: `programs.created_at` DESC.
- No pagination (PoC scale).

### Route (`src/curriculum_agent/api/routes/programs.py`)

`GET /programs/` → `list[ProgramSummary]`

- No API key (read-only, same policy as `GET /programs/{program_id}`).
- Registered before the `/{program_id}` route so `/` is not captured as a path param (FastAPI matches exact paths first, but keep declaration order explicit for readability).

## Frontend

### New page `frontend/src/pages/Programs.tsx`

- Fetches `GET /programs/` on mount.
- Table columns: ชื่อหลักสูตร (th, en subtitle), ระดับปริญญา, วันที่สร้าง (Thai locale), stage badge.
- Stage badge: Thai label per stage; "ยังไม่เริ่ม" when `current_stage` is null.
- Row click → `setProgramId(program_id)` (existing `useProgram` hook) → navigate to the stage's route.
- "สร้างหลักสูตรใหม่" button → clears nothing, navigates to `/intake`.
- Empty state: message + the same create button.

### Stage → route mapping

| current_stage | route |
|---|---|
| null / `intake` | `/intake` |
| `stakeholder_needs` | `/stakeholder-needs` |
| `skill_extraction` | `/skill-extraction` |
| `plo_synthesis` | `/plo-synthesis` |
| `plo_report` | `/plo-report` |
| unknown value | `/pipeline` (fallback) |

### Routing changes (`frontend/src/App.tsx`)

- Index route (`/`) → `Programs`.
- `Intake` moves to `/intake`.
- Any nav links referencing the old index update accordingly.

## Error handling

- API list failure → page shows Thai error message with retry button.
- A program whose latest session errored still lists normally; badge shows the session status.

## Testing

- **Unit:** `ProgramSummary` schema; `list_all()` ordering + latest-session join (program with 0, 1, N sessions).
- **Integration (API):** `GET /programs/` empty DB; multiple programs sorted by `created_at` DESC; program without sessions returns null stage fields.
- **Frontend:** lint + build pass; manual check of row-click resume flow.

## Out of scope

- Delete/archive programs.
- Pagination, search, filters.
- Audit timeline of stage transitions.
