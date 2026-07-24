# Delete Program — Design Spec

**Goal:** Let a user permanently delete a program (and everything under it) from the program history page (`/`).

**Scope:** Hard delete, cascading across all Postgres tables scoped by `program_id`. No soft-delete, no audit trail, no undo — consistent with the existing program-history spec's PoC stance (no pagination, no audit table).

## Data model

No new tables, no migration. `programs` already has six FK-dependent tables, none with `ON DELETE CASCADE` or ORM `relationship()` cascade configured:

- `evidence` (FK `program_id`)
- `skills` (FK `program_id`, and FK `source_evidence_id` → `evidence.evidence_id`)
- `clusters` (FK `program_id`)
- `plos` (FK `program_id`)
- `checkpoints` (FK `program_id`)
- `sessions` (FK `program_id`)

Delete order matters only because `skills.source_evidence_id` references `evidence`: skills must go before evidence. Everything else can go in any order relative to each other, before the `programs` row itself.

MinIO (`evidence-files`, `exports` buckets) and Qdrant (`evidence`, `skills` collections) are declared but nothing in the current codebase writes program-scoped objects into them — confirmed by search, no `put_object`/`upsert` calls outside `ensure_buckets()`. Out of scope: nothing to clean up there today. If a future PoC starts writing to these stores, this delete path will need a follow-up pass.

## Backend

### `ProgramRepository.delete_cascade(program_id: str) -> bool`

`src/curriculum_agent/data/repositories.py`, added after `list_all`.

One `AsyncSessionLocal` transaction, using SQLAlchemy Core `delete()` statements filtered by `program_id` (skills additionally need no extra filter — deleting by `program_id` already scopes them):

```python
await session.execute(delete(SkillTable).where(SkillTable.program_id == program_id))
await session.execute(delete(ClusterTable).where(ClusterTable.program_id == program_id))
await session.execute(delete(PLOTable).where(PLOTable.program_id == program_id))
await session.execute(delete(CheckpointTable).where(CheckpointTable.program_id == program_id))
await session.execute(delete(SessionTable).where(SessionTable.program_id == program_id))
await session.execute(delete(EvidenceTable).where(EvidenceTable.program_id == program_id))
result = await session.execute(delete(ProgramTable).where(ProgramTable.program_id == program_id))
await session.commit()
return result.rowcount > 0
```

Returns `True` if the program existed (and was deleted), `False` if `program_id` didn't match any row — in which case the six prior deletes were no-ops, which is fine.

### `DELETE /programs/{program_id}` route

`src/curriculum_agent/api/routes/programs.py`, placed after `get_program`.

```python
@router.delete("/{program_id}", status_code=204, dependencies=[Depends(require_api_key)])
async def delete_program(program_id: str) -> None:
    repo = ProgramRepository()
    deleted = await repo.delete_cascade(program_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="ไม่พบหลักสูตรนี้")
```

Requires `require_api_key` — same as every other mutating route (`POST /programs/`, `DELETE /evidence/{id}`). `GET /programs/` and `GET /programs/{id}` stay key-free; this is the first mutating verb on the `/programs` router's collection-level resource.

## Frontend

`frontend/src/pages/Programs.tsx`:

- Add a "ลบ" (delete) button in a new table column, one per row.
- `onClick` calls `e.stopPropagation()` first (row itself has an `onClick` that navigates to resume the program — the delete button must not trigger that), then:
  ```ts
  if (!window.confirm(`ลบหลักสูตร "${p.name_th}" ทั้งหมด? ข้อมูลจะหายถาวรและกู้คืนไม่ได้`)) return
  await api.delete(`/programs/${p.program_id}`)
  load() // re-fetch the list
  ```
- On failure, reuse the existing `error` state / retry affordance already on the page (same pattern as the initial list-load failure).
- No new component — `window.confirm` is sufficient for a PoC destructive-action gate, matches the "browser confirm" decision.

## Testing

- `tests/unit/test_program_repository.py`: append cases for `delete_cascade` —
  - deletes a program with no sessions/evidence/etc. → returns `True`, program gone
  - deletes a program with rows in all six dependent tables → all rows gone, no FK error
  - deletes a program that has skills referencing evidence (the one FK-order-sensitive case) → succeeds without `IntegrityError`
  - deletes a nonexistent `program_id` → returns `False`, no side effects
- `tests/unit/test_api_programs.py`: append cases for the route —
  - `DELETE /programs/{id}` on an existing program → `204`
  - `DELETE /programs/{id}` on a missing program → `404`
  - (existing test infra already covers the `require_api_key` dependency pattern via other routes — no new auth test needed, mirror how `test_api_programs.py` currently tests `POST /`)

No frontend test runner in this repo (per program-history plan's existing note) — verification is `npm run lint && npm run build` plus manual click-through.

## Out of scope

- Soft delete / `deleted_at` / recovery
- Deleting from MinIO or Qdrant (nothing there to delete yet, see Data model section)
- Bulk delete / multi-select
- Confirmation beyond `window.confirm`
