# Run comparison: a per-run validator switch and program copies

Date: 2026-10-06. Status: approved in chat, spec under review.

## Why

The designer wants to compare PLO synthesis **with** and **without** the SMART
validation agent on the same program. Two things stand in the way today:

1. The agent can only be switched off in `.env` (`VALIDATION_PROVIDER=`), which
   needs a backend restart and an `.env` edit — and an empty
   `$env:VALIDATION_PROVIDER = ""` in PowerShell *deletes* the variable, so the
   obvious shell override silently does nothing.
2. `POST /plos/run` replaces the program's PLO set. The first run's PLOs are
   gone the moment the second run starts.

So: a per-run switch the UI can set, and a way to copy a program
(`program-2` → `program-2-run-1`) so one run's results survive the next.

Known limit, accepted: synthesis drafts differ run to run, so two runs differ by
the validator **and** by the drafts. A same-draft comparison needs a probe
script; that is out of scope here.

## Part 1 — per-run validator switch

### API

- `POST /programs/{id}/plos/run` takes a new body model
  `PLOSynthesisRunRequest(DesignerNoteRequest)` with
  `run_validation: bool = True`. The default keeps every existing client
  (and the graph path) unchanged. The Need routes keep `DesignerNoteRequest`.
- New `GET /programs/{id}/plos/validation` → `ValidationStatusResponse`
  `{enabled: bool, model: str}`. `enabled` is `bool(settings.validation_provider)`;
  `model` is `settings.validation_model` when enabled, else `""`. 404 when the
  program does not exist (same check as the other plos routes). It lets the UI
  disable the checkbox and say why when `.env` has the agent off.

### Stage

- The route sets `state["run_validation"] = False` only when the body says so.
  `AgentState` gains `run_validation: bool` (the TypedDict is `total=False`).
- `plo_synthesis._run` reads `state.get("run_validation", True)` and passes it to
  every `validate_and_build` call as a new keyword `run_validation: bool = True`,
  which passes it to `run_smart_agent(..., enabled: bool = True)`.
- `run_smart_agent` checks, in this order:
  1. `not settings.validation_provider` → `ValidationReason.DISABLED` (unchanged).
     The `.env` switch wins: a request cannot turn on an agent with no endpoint.
  2. `not enabled` → new `ValidationReason.SKIPPED = "skipped"`, note
     `"ไม่ได้ตรวจ (ปิดการตรวจในรอบนี้)"`, via `code_only_result`.
- Both give `smart_validated_by="code_only"`; the diagnosis text tells them
  apart on the stored PLO.
- **The pure-code gate is untouched.** `validate_and_build` still runs
  `hard_failures` on the final statement and sets `smart_escalated` (immutable
  rule 5). Only the agent is skipped.
- Not changed: the graph path (`POST /sessions`) and `POST /{plo_id}/revalidate`
  always run the agent. Revalidating with the agent off would be a no-op.
- One log line per run when skipped:
  `plo_synthesis: validation agent skipped for this run (run_validation=false)`.

## Part 2 — program copy

### API

`POST /programs/{id}/copy`, `dependencies=[Depends(require_api_key)]` (same as
`POST /programs/`), no body. Returns `ProgramMetadata` of the copy (status 200, like `POST /programs/`).

- 404 if the source does not exist.
- 409 if a PLO synthesis run is in flight for the source
  (`plo_synthesis._SYNTHESIS_IN_FLIGHT`): synthesis deletes then inserts, so a
  copy taken mid-run holds half a set. need_combination has no single-flight
  guard, so a copy taken during it is not prevented — documented, not fixed.
- New id: `{source_id}-run-{n}`, the smallest `n ≥ 1` not taken
  (`ProgramRepository.exists`). Retry on an insert collision the way
  `create_program` does (`_MAX_ID_ATTEMPTS`). Copying a copy gives
  `program-2-run-1-run-1` — accepted, keeps the rule simple.

### What is copied

| Copied | Not copied | Why not |
|---|---|---|
| `programs` row (new id, `created_at` = now, `copied_from` = source id) | `sessions`, `checkpoints`, LangGraph threads | A copy is a snapshot; it has no suspended run to resume. Stage routes load from the repositories and work without a thread. |
| `evidence` | `llm_cache` | Shared by key already; the copy hits the source's cached extraction. |
| `skills` | | |
| `needs` | | |
| `plos` | | |
| `plo_reviews` (fingerprint recomputed) | | |

### Ids

`evidence_id`, `skill_id` and `need_id` are single-column global primary keys,
so the copy gets a fresh `uuid4` for every one of them. One old→new map covers
all three kinds, and every reference is rewritten through it:

- `skills.source_evidence_id`
- `needs.member_skill_ids`, `needs.source_evidence_ids`
- `plos.source_need_ids`, `plos.source_evidence_ids`
- JSONB blobs `plos.smart_check` and `plo_reviews.review`: walked recursively;
  any **string value exactly equal** to an old id is replaced. Free text that
  merely contains an id is left alone.
- Any other JSONB column (`evidence.extra_metadata`, `needs.stakeholder_coverage`,
  ...) gets the same recursive walk — cheap, and it means a future column that
  starts carrying an id is covered without a code change.

`plo_id` is kept: a PLO's identity is `(program_id, plo_id)` since migration
`e4b6d19a3f72`.

The review's `plo_fingerprint` hashes `source_need_ids`, so the copied review
would read as stale. The copy recomputes it with `plo_review.plo_fingerprint`
over the copied PLOs and stores that.

### Transaction

The whole copy runs in one `get_session()` transaction: rows are read from the
source and the new rows added in the same session, committed once. Any failure
rolls back and leaves nothing behind. Insert order respects the FKs: program,
evidence, skills, needs, PLOs, review.

### Where the code lives

`src/curriculum_agent/data/program_copy.py`: `async def copy_program(source_id: str,
new_id: str) -> ProgramMetadata`, plus a pure helper
`remap_ids(value: Any, id_map: Mapping[str, str]) -> Any` (recursive over
dict/list/str, unit-tested alone). It works at ORM level, so a column added
later is copied by default (`{c.key: getattr(row, c.key) for c in table.columns}`)
rather than silently dropped.

### Provenance

- Migration adds `programs.copied_from` (`Text`, nullable, **not** an FK —
  deleting the source must not touch its copies).
- `ProgramMetadata.copied_from: str | None = None` — on `ProgramMetadata`, not
  `ProgramCreateRequest`, so a client cannot set it.
- `ProgramSummary.copied_from: str | None = None`, so the list page can say
  "สำเนาของ program-2".
- Deleting a copy uses the existing `delete_cascade`. Source and copy share no
  rows, so neither delete reaches the other.

## Tests

Part 1:
- `run_validation=false` → the agent loop is never entered; reason `SKIPPED`;
  `smart_validated_by == "code_only"`.
- `.env` off + `run_validation=true` → `DISABLED` (the `.env` switch wins).
- Agent skipped and a forbidden word in the draft → still escalated (code gate).
- No body / body without the field → agent runs (default `True`).
- `GET /plos/validation` reports `enabled`/`model` for both settings; 404 for an
  unknown program.

Part 2:
- `remap_ids`: nested dict/list, exact-match only, non-id strings untouched,
  non-string scalars untouched.
- Copy of a populated program: row counts equal per table; no old
  evidence/skill/need id appears anywhere in the copy; every reference in the
  copy resolves to a row of the copy; `plo_id`s equal.
- The copied review is not stale (`is_stale` false against the copied PLOs).
- Mutating or deleting the copy leaves the source unchanged, and vice versa.
- Naming: `-run-1`, then `-run-2` when `-run-1` exists.
- 409 while the source's synthesis is in flight; 404 for an unknown source;
  401 without the API key.
- A failure mid-copy (e.g. the PLO insert raises) leaves no program, evidence,
  skill or Need row for the new id.

Integration tests that touch the DB follow the existing repository tests'
setup; unit tests stub the session like the current route tests do.

## Docs

- `CLAUDE.md`: one pitfall paragraph — a copy re-keys evidence/skill/Need ids
  and why; the per-run switch is SKIPPED, distinct from DISABLED, and never
  touches the code gate.
- Skill `references/data-schemas.md`: `copied_from`.
- Frontend handoff note (frontend is owned by another session):
  `.scratch/handoffs/2026-10-06-run-comparison-frontend.md` — checkbox on the
  PLO synthesis page (default on, disabled with a reason when
  `GET /plos/validation` says `enabled=false`), a "ไม่ได้ตรวจ" badge for
  `code_only`, a copy button on the program list/detail, and "สำเนาของ X" from
  `copied_from`.

## Out of scope

- A same-draft with/without probe script.
- Per-run switches for `need_dedup` and `plo_review`.
- A single-flight guard for need_combination.
- Any frontend code in this session.
