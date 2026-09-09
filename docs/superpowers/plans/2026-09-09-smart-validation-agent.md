# SMART validation as a tool-using agent — plan

**Date:** 2026-09-09
**Design:** `specs/2026-09-09-smart-validation-agent-design.md`
**Branch:** `feat/smart-validation-agent`

Eleven commits, in this order. The first four land independently and are worth
landing whether or not the agent ships.

## Pre-work

1. **`fix(smart): stop จำแนก and รักษา failing the M hard check`**
   New leaf module `smart_vocabulary.py` — it has to be a leaf, because
   `smart_rules → models` already exists and putting the scan in either makes
   the other's import circular. `forbidden_words_in` masks a curated compound
   list longest-first, and both callers share it: two independent scans of one
   rule is how they came to disagree. Ordered by position, so the word the
   error quotes does not vary with set iteration order.
   Ships value alone, and removes a false-escalation source before anyone
   measures the agent.

2. **`test(plo): give the SMART gate one shared fixture instead of fifteen closures`**
   Pure test refactor, zero source change, and the biggest lever on the size of
   the feature diff. Fixes nine `relevant_alignment_ok` typos — a field renamed
   months ago, swallowed by `extra="ignore"`, so those tests had been asserting
   plain defaults. Collapses fifteen `fake_light` closures onto two helpers, and
   turns the integration harness's 4-tuple into a context manager over an
   `ExitStack` that yields its stubs by name.

3. **`feat(smart): add a Thai Bloom verb table for the validator to consult`**
   `stages/bloom_verbs.py`, wired to nothing. `levels_for_verb` returns a list
   because the rubric is explicit that cognitive demand fixes the level, not the
   verb. `scan_statement_verbs` needs the same word-boundary care as the
   forbidden words: `โครงสร้างข้อมูล` reads as the Create verb `สร้าง`, and
   โครงสร้าง appears in engineering outcomes constantly. Two table corrections
   the tests forced out: `ทวน` is gone (three characters, sits inside `ทบทวน`,
   nobody writes it in a Thai PLO) and `ควบคุม` is in.

4. **`feat(config): give SMART validation its own LLM slot`**
   `VALIDATION_PROVIDER`/`VALIDATION_MODEL` + `complete_validation`, plus four
   budget settings. `describe_target` and `warmup_models` now read one
   `_slots()` list instead of each enumerating by hand — five is where such a
   list stops looking obviously complete.

## Feature

5. **`feat(models): persist why a PLO failed SMART, not just that it did`**
   `SmartFinding` inside the existing `smart_check` JSONB (no migration for the
   richest field), plus `smart_validated_by` and `smart_diagnosis_th` as
   columns. Backward compatible on its own: nothing writes them yet, everything
   reads them, and a test validates a `PLO` from a pre-migration-shaped dict.

6. **`feat(plo): split drafting from validating`**
   Two phases, still calling the old gate. **No verdict changes** — the full
   suite passes untouched, which is what makes the concurrency and sibling
   plumbing reviewable apart from the agent.

7. **`feat(plo): validate every PLO with a tool-using agent`**
   The loop, the tools, the prompts. Deletes `_SmartSoftJudge`, `_SmartOutcome`,
   `_build_fix_prompt` and `prompts/smart_validator.py`. Rewrites
   `test_smart_retry_loop.py` as `test_smart_agent.py`.

8. **`test(smart): keep the rubric pinned against the agent's prompt`**
   Four assertions from the deleted `test_smart_soft_judge_prompt.py` were not
   prompt tests — they are how `obe-principles.md` is pinned in code. Retargeted
   rather than lost.

9. **`feat(api): let a designer re-run SMART on one PLO`**
   `POST /{plo_id}/revalidate`; `PUT` narrowed to `PLOStatementUpdate` and
   marking an edited statement `stale`; `stale`/`code_only` counts in
   `plo_report`. `PUT` had no test coverage at all, which is how it kept
   accepting a client-supplied verdict.

10. **`feat(ui): show what the SMART validator found`**
    `types/plo.ts` + `constants/smart.ts` replace the per-page copies, which had
    already drifted in both directions. Findings with reasons, the diagnosis in
    its own block, four provenance states, a revalidate button (without it the
    `stale` state is a dead end), and the Excel export's three-way status, Thai
    labels and `ข้อวินิจฉัย` column.

11. **`docs: record the SMART validation agent`**
    Last, so it describes what shipped.

## Verification

```bash
uv run pytest && uv run ruff check src/ tests/ && uv run mypy src/
cd frontend && npx tsc --noEmit -p tsconfig.app.json && npm run build
```

End to end, against real endpoints:

1. `describe_target()` at startup must print **five** slots, validation on OpenRouter.
2. `alembic upgrade head`, then `GET /programs/{id}/plos/` on an old program — pre-migration rows must read back as `legacy`.
3. `POST /plos/run`, then read the loguru trail: per PLO, a turn count, a repair count, the tools called, and a `code gate (authoritative)` line. **If every PLO finishes in one turn the system prompt is not making it investigate** — that is a prompt bug, not a pass.
4. UI: an escalated PLO shows its hard finding and a Thai diagnosis; edit a statement → `stale` badge → "ตรวจ SMART ซ้ำ" → the verdict changes with the sentence.
5. Negative: `เข้าใจ` through `PUT` then revalidate → escalated with `M_forbidden`; `รักษา` → **passes**; a `smart_escalated=False` body through `PUT` → does not clear the escalation.
6. `VALIDATION_PROVIDER=` empty → every PLO gets a code-only verdict, no error.
7. `VALIDATION_PROVIDER=opentyphoon` → the loop still works, proving it is not tied to OpenRouter's tool-calling.
8. `GET /export/matrix.xlsx` → three-way status, Thai findings, diagnosis column populated.

## Not done

- `bloom_lookup` stays a tool rather than moving into the system prompt (see the design's push-back section).
- No `validation` cache kind. The agent's input includes a draft that comes from an uncached, non-deterministic synthesis call, so a key would change on nearly every run — and a replayed verdict is the one thing that must not bypass the code gate. Composition recorded in the design if synthesis ever becomes reproducible.
- No program-level redundancy check in `plo_report` yet. Sibling overlap is a soft finding only; if it proves to matter, that is where it goes.
