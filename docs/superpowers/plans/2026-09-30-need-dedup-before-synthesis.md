# Fold Duplicate Needs Before PLO Synthesis — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Before `plo_synthesis` drafts anything, one LLM call finds in-scope Needs that ask for the same capability; pure code accepts or drops each group, and every accepted group becomes one PLO slot drafted from all its members.

**Architecture:** A new `need_dedup` LLM slot and a new `stages/need_dedup.py` (schema, labelling, pure-code acceptance, the call with its fallbacks). `plo_synthesis.run` calls it between the scope filter and slot selection; slot selection is refactored to work over *units* (a fold or a lone Need), with a merge floor of 4 core slots. The manual merge route's floor moves from `MIN_NEEDS` (6) to the same `MIN_CORE_AFTER_MERGE` (4). No schema change, no migration.

**Tech Stack:** Python 3.11, pydantic v2, Instructor (via `llm._complete`), loguru, pytest (`asyncio_mode=auto`), FastAPI TestClient.

**Spec:** `docs/superpowers/specs/2026-09-30-need-dedup-before-synthesis-design.md` — read it before starting; this plan argues from it.

## Global Constraints

- Every function signature has type hints; every module starts with `from __future__ import annotations`.
- Logging through `loguru` only (`from loguru import logger`); never stdlib `logging`.
- Code, comments, log messages: English. Prompt text and user-facing messages (HTTP 422 details): Thai.
- Prompts live in `src/curriculum_agent/prompts/`, one file per prompt, returned by a typed builder.
- No hand-parsing LLM JSON — Instructor + pydantic through `llm._complete`.
- Group size cap: **3** members (`MAX_GROUP_SIZE = 3`). Group members: **one KSEC tag**.
- Merge floor: **`MIN_CORE_AFTER_MERGE = 4`** in `stages/need_grouping.py`. `MIN_NEEDS = 6` and `MAX_CORE_PLOS = 10` are unchanged, and so is every warning built on them.
- Floor for automatic folds: while the core slot count is below `MIN_CORE_AFTER_MERGE`, unfold the lowest-top-demand group that has ≥2 core members; stop when none is left. (A set that starts below 4 therefore gets no core folds — the spec's `min(...)` target, which is behaviourally identical and so not written separately.)
- Kill switch: `NEED_DEDUP_PROVIDER=""` (empty) skips the call. `None` (unset) follows `LLM_PROVIDER` as every slot does.
- The dedupe call must never cost a PLO: any exception → warn, fold nothing.
- Tests must never reach a real endpoint.
- Frontend is owned by another session: do not stage or edit anything under `frontend/`. `frontend/src/constants/needPolicy.ts` mirrors `MIN_NEEDS` (6), which does not change, so nothing there needs editing.
- The working tree has unrelated dirty files (`frontend/**`, `.scratch/plo-scope-guard/eval/*`, `curriculum-design-agent.skill`). Stage files by explicit path only — never `git add -A` / `git add .`.
- Windows: run Python with `PYTHONIOENCODING=utf-8` when output contains Thai; any ad-hoc async script sets `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())`.
- Never read or print `.env` values. Running app code that reads `Settings` is fine.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File Structure

| File | Responsibility |
|---|---|
| `src/curriculum_agent/config.py` (modify) | `need_dedup_provider` / `need_dedup_model` fields; `SlotSpec("need_dedup", ...)` in `SLOTS` |
| `src/curriculum_agent/llm.py` (modify) | `complete_need_dedup` wrapper |
| `src/curriculum_agent/prompts/need_dedup.py` (create) | `build_need_dedup_prompt` — Thai prompt over labelled Need rows |
| `src/curriculum_agent/stages/need_dedup.py` (create) | `DuplicateGroup`, `DedupAnswer`, `FoldGroup`, `label_needs`, `accept_groups`, `find_duplicate_groups` |
| `src/curriculum_agent/stages/need_grouping.py` (modify) | `MIN_CORE_AFTER_MERGE = 4` beside the other bounds |
| `src/curriculum_agent/stages/plo_synthesis.py` (modify) | `build_units`, `core_slot_count`, `enforce_merge_floor`, `_select_slots`; `run` wiring; floor-warning cause |
| `src/curriculum_agent/api/routes/plos.py` (modify) | merge route floor → `MIN_CORE_AFTER_MERGE` |
| `tests/conftest.py` (modify) | autouse stub: dedupe call answers "no groups" unless a test says otherwise |
| `tests/unit/test_need_dedup_prompt.py` (create) | prompt builder |
| `tests/unit/test_need_dedup.py` (create) | acceptance rules, call fallbacks |
| `tests/unit/test_plo_synthesis_dedup.py` (create) | units, slot selection, floor, `run` wiring |
| `tests/unit/test_llm_slots.py`, `tests/unit/test_llm_target.py` (modify) | the sixth slot |
| `tests/unit/test_api_plos.py` (modify) | merge floor 4 |
| `scripts/dump_prompts.py`, `docs/prompt-inventory.md` (modify / regenerate) | inventory section 8 |
| `.env.example`, `CLAUDE.md`, `.claude/skills/curriculum-design-agent/references/prompts.md` (modify) | docs |

---

### Task 1: The `need_dedup` slot

**Files:**
- Modify: `src/curriculum_agent/config.py` (SLOTS tuple ~line 127; Settings fields ~line 203)
- Modify: `src/curriculum_agent/llm.py` (after `complete_need_combination`, ~line 241)
- Modify: `.env.example` (after the NEED_COMBINATION block, ~line 93)
- Test: `tests/unit/test_llm_slots.py`, `tests/unit/test_llm_target.py`

**Interfaces:**
- Produces: `settings.need_dedup_provider: Literal["ollama","openrouter","opentyphoon",""] | None` (default `"openrouter"`), `settings.need_dedup_model: str`, and
  `async def complete_need_dedup(response_model: type[T], messages: list[dict[str, Any]], **kwargs: Any) -> T` in `curriculum_agent.llm`.

- [ ] **Step 1: Update the slot tests to expect the new slot**

In `tests/unit/test_llm_slots.py`, replace `test_exactly_one_slot_can_be_switched_off` with:

```python
def test_only_the_optional_checks_can_be_switched_off() -> None:
    """`disableable` says "" is a meaningful value for this slot's provider: the
    slot is a check the pipeline can run without, and "" is its kill switch. That
    is true of the validation agent and of the duplicate check before synthesis —
    both fall back to pure code — and of nothing that *produces* the pipeline's
    output. A third disableable slot is a third provider field where empty and
    unset differ, and every reader of that field has to learn the distinction."""
    disableable = [slot.name for slot in SLOTS if slot.disableable]

    assert disableable == ["need_dedup", "validation"]
```

In `tests/unit/test_llm_target.py`, in `test_every_slot_is_reported_and_warmed_from_one_list`, change the expected list to:

```python
    assert labels == [
        "extraction",
        "clustering",
        "need_combination",
        "need_dedup",
        "plo_synthesis",
        "validation",
    ]
```

and in `test_describe_target_names_every_slot_and_no_key` add after the `need_combination` line:

```python
    assert "need_dedup: provider=openrouter" in described
```

and after `assert typhoon.validation_model in described` add:

```python
    assert typhoon.need_dedup_model in described
```

Then add this test to `tests/unit/test_llm_target.py` (it sits beside the existing `"validation: disabled"` test at ~line 101 — read that test first and build the Settings the same way it does, via the file's own fixture/monkeypatch pattern):

```python
def test_the_duplicate_check_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """"" is the need_dedup kill switch: the startup line says so rather than
    resolving it back to a live provider."""
    monkeypatch.setattr(llm.settings, "need_dedup_provider", "")

    assert "need_dedup: disabled" in llm.describe_target()
    assert llm._resolve("need_dedup")[0] == ""
```

- [ ] **Step 2: Run the tests — they fail**

Run: `uv run pytest tests/unit/test_llm_slots.py tests/unit/test_llm_target.py -q`
Expected: FAIL — `need_dedup` not in `SLOTS`, `Settings` has no `need_dedup_provider`.

- [ ] **Step 3: Add the Settings fields**

In `src/curriculum_agent/config.py`, directly after the line
`need_combination_provider: Literal["ollama", "openrouter", "opentyphoon"] | None = None` insert:

```python
    # The duplicate check before PLO synthesis: one call per synthesis run that
    # reads every in-scope Need's sentence and answers with groups of labels —
    # a grouping, not Thai prose, which is why it defaults to OpenRouter beside
    # clustering. Its own knob, so neither can move without the other.
    #
    # Disableable, like validation and for the same reason: the step is a check
    # the stage can run without. `NEED_DEDUP_PROVIDER=` (empty) skips the call
    # and every Need gets its own slot, which is also what an outage falls back
    # to — and the baseline any measurement of this step is taken against.
    need_dedup_provider: Literal["ollama", "openrouter", "opentyphoon", ""] | None = "openrouter"
    need_dedup_model: str = ""
```

- [ ] **Step 4: Declare the slot**

In `SLOTS`, directly after
`SlotSpec("need_combination", "need_combination_provider", "need_combination_model"),` insert:

```python
    # Runs at the start of plo_synthesis, before any draft, so it sits here in
    # pipeline order. Left on the provider default (llama-3.3-70b, the
    # clustering model) until the probe in the design doc says otherwise.
    SlotSpec(
        "need_dedup",
        "need_dedup_provider",
        "need_dedup_model",
        disableable=True,
    ),
```

Also update the `disableable` field comment in `SlotSpec` from
`# Only validation: "" is its kill switch, and "" must never resolve to` /
`# llm_provider. Every other slot's provider only selects an endpoint.` to:

```python
    # need_dedup and validation: "" is their kill switch, and "" must never
    # resolve to llm_provider. Every other slot's provider only selects an
    # endpoint.
```

- [ ] **Step 5: Add the completion wrapper**

In `src/curriculum_agent/llm.py`, directly after `complete_need_combination` insert:

```python
async def complete_need_dedup(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """The duplicate check before PLO synthesis — see Settings.need_dedup_provider.

    One caller, `stages.need_dedup.find_duplicate_groups`, once per synthesis
    run. It answers with labels, never with Thai a designer reads, and whatever
    it answers is judged again in pure code before anything is folded.
    """
    return await _complete(*_resolve("need_dedup"), response_model, messages, **kwargs)
```

- [ ] **Step 6: Document the env vars**

In `.env.example`, directly after the line `# NEED_COMBINATION_MODEL=typhoon-v2.5-30b-a3b-instruct` and its following `#` line, insert:

```
# The duplicate check at the start of PLO synthesis: one call per run that reads
# every in-scope Need and groups the ones asking for the same capability, so one
# PLO is drafted from each group instead of one per Need. It answers with
# labels, not Thai prose, and defaults to OpenRouter beside clustering on a knob
# of its own. Set NEED_DEDUP_PROVIDER to *nothing* to skip it — every Need then
# gets its own PLO, exactly as before this step existed:
#   NEED_DEDUP_PROVIDER=          <- off
# NEED_DEDUP_PROVIDER=openrouter
# NEED_DEDUP_MODEL=meta-llama/llama-3.3-70b-instruct
#
```

- [ ] **Step 7: Run the tests — they pass**

Run: `uv run pytest tests/unit/test_llm_slots.py tests/unit/test_llm_target.py -q`
Expected: PASS. `test_every_declared_field_exists_on_settings` also covers the new entry with no edit.

- [ ] **Step 8: Lint, type-check, full suite**

Run: `uv run ruff check src/ tests/ && uv run mypy src/ && uv run pytest -q`
Expected: all clean; same pass count as before plus the new test.

- [ ] **Step 9: Commit**

```bash
git add src/curriculum_agent/config.py src/curriculum_agent/llm.py .env.example tests/unit/test_llm_slots.py tests/unit/test_llm_target.py
git commit -m "feat(llm): a need_dedup slot for the duplicate check before synthesis

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The duplicate-check prompt

**Files:**
- Create: `src/curriculum_agent/prompts/need_dedup.py`
- Modify: `scripts/dump_prompts.py`, regenerate `docs/prompt-inventory.md`
- Test: `tests/unit/test_need_dedup_prompt.py`

**Interfaces:**
- Produces: `def build_need_dedup_prompt(rows: list[tuple[str, str, str]], *, program_context: str | None = None) -> list[dict[str, str]]` — each row is `(label, ksec_tag, statement_th)`; returns `[system, user]` messages.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_need_dedup_prompt.py`:

```python
from __future__ import annotations

from curriculum_agent.prompts.need_dedup import build_need_dedup_prompt

_ROWS = [
    ("N1", "S", "ต้องการบัณฑิตที่แปลเอกสารธุรกิจไทย-จีนโดยใช้ AI ช่วยตรวจคุณภาพ"),
    ("N2", "S", "ต้องการบัณฑิตที่ควบคุมคุณภาพงานแปลที่ผลิตด้วย AI"),
    ("N3", "EC", "ต้องการบัณฑิตที่ประพฤติตนอย่างมีจริยธรรมในการสื่อสารทางธุรกิจ"),
]


def _text(messages: list[dict[str, str]]) -> str:
    return "\n".join(m["content"] for m in messages)


def test_every_need_appears_once_as_label_tag_and_sentence() -> None:
    user = build_need_dedup_prompt(_ROWS)[-1]["content"]

    for label, tag, statement in _ROWS:
        assert f"{label} | {tag} | {statement}" in user


def test_rows_keep_the_order_they_were_given() -> None:
    """The caller labels in demand order; the prompt must not reshuffle it, or
    N1 stops being the most-demanded Need the model is reading."""
    user = build_need_dedup_prompt(_ROWS)[-1]["content"]

    assert user.index("N1 |") < user.index("N2 |") < user.index("N3 |")


def test_the_rules_the_code_enforces_are_also_told_to_the_model() -> None:
    """accept_groups drops a group that breaks these; telling the model first is
    what keeps a good grouping from being thrown away for a rule it never saw."""
    system = build_need_dedup_prompt(_ROWS)[0]["content"]

    assert "2-3" in system
    assert "KSEC" in system
    assert "ไม่เกินหนึ่งกลุ่ม" in system


def test_an_empty_answer_is_named_as_a_valid_one() -> None:
    """Without this a model asked to find duplicates finds some."""
    system = build_need_dedup_prompt(_ROWS)[0]["content"]

    assert "รายการว่าง" in system


def test_a_duplicate_is_defined_by_main_task_and_object() -> None:
    """The definition is the checkable one — task plus object — and the example
    pair shows that different wording and context do not make two Needs distinct."""
    system = build_need_dedup_prompt(_ROWS)[0]["content"]

    assert "งานหลักและวัตถุหลักเหมือนกัน" in system
    assert "แปลเอกสารธุรกิจโดยใช้เทคโนโลยี" in system
    assert "ประยุกต์ใช้เทคโนโลยีในการแปลเอกสารธุรกิจ" in system


def test_shared_topic_or_source_is_named_as_not_enough() -> None:
    """The failure the evidence-overlap measurement predicts: Needs from the same
    documents, or sharing a tool like AI, read as duplicates."""
    system = build_need_dedup_prompt(_ROWS)[0]["content"]

    assert "ยังไม่พอ" in system


def test_program_context_is_included_when_given_and_absent_otherwise() -> None:
    with_context = _text(build_need_dedup_prompt(_ROWS, program_context="หลักสูตรระดับปริญญาตรี สาขาภาษาจีน"))
    without = _text(build_need_dedup_prompt(_ROWS))

    assert "หลักสูตรระดับปริญญาตรี สาขาภาษาจีน" in with_context
    assert "หลักสูตร:" not in without
```

- [ ] **Step 2: Run — fails on import**

Run: `uv run pytest tests/unit/test_need_dedup_prompt.py -q`
Expected: FAIL — `ModuleNotFoundError: curriculum_agent.prompts.need_dedup`.

- [ ] **Step 3: Write the builder**

Create `src/curriculum_agent/prompts/need_dedup.py` (write it with the Write tool — Thai through a shell heredoc into Python gets mangled on this machine):

```python
from __future__ import annotations

_SYSTEM_TH = """คุณคือผู้เชี่ยวชาญการออกแบบหลักสูตรอุดมศึกษาไทยตามแนวทาง Outcome-Based Education

งานของคุณ: อ่านรายการความต้องการ (Need) ของหลักสูตรหนึ่ง แล้วหาว่าข้อใดถามหาสมรรถนะเดียวกันของบัณฑิต \
จนผลลัพธ์การเรียนรู้ระดับหลักสูตร (PLO) ข้อเดียวรองรับได้โดยไม่ทิ้งสิ่งที่ข้อใดข้อหนึ่งขอ

กติกา:
1. Need สองข้อซ้ำกันเมื่องานหลักและวัตถุหลักเหมือนกัน แม้ถ้อยคำหรือบริบทต่างกัน \
เช่น "แปลเอกสารธุรกิจโดยใช้เทคโนโลยี" กับ "ประยุกต์ใช้เทคโนโลยีในการแปลเอกสารธุรกิจ" \
การพูดถึงหัวข้อเดียวกัน ใช้เครื่องมือเดียวกัน (เช่น AI หรือเทคโนโลยีดิจิทัล) หรือมาจากกลุ่มผู้มีส่วนได้ส่วนเสียเดียวกัน ยังไม่พอ
2. Need หนึ่งข้ออยู่ได้ไม่เกินหนึ่งกลุ่ม
3. หนึ่งกลุ่มมี 2-3 ข้อ และทุกข้อในกลุ่มต้องอยู่ในหมวด KSEC เดียวกัน
4. ข้อที่ไม่ซ้ำกับข้อใดเลยไม่ต้องใส่ในกลุ่มใด ถ้าไม่มีข้อใดซ้ำกันเลย ให้ตอบ groups เป็นรายการว่าง \
ซึ่งเป็นคำตอบที่ถูกต้องสำหรับชุดที่แยกกันชัดเจน
5. บางข้ออาจเป็นรายชื่อทักษะที่ยังไม่ได้เรียบเรียงเป็นประโยค ให้ตัดสินจากงานที่รายชื่อนั้นบอก
6. อ้างถึง Need ด้วยป้ายกำกับ (N1, N2, ...) เท่านั้น
7. reason_th: หนึ่งประโยคภาษาไทย บอกงานหลักและวัตถุหลักที่สมาชิกในกลุ่มมีร่วมกัน

ตอบเป็น JSON ตาม schema ที่กำหนด"""


def build_need_dedup_prompt(
    rows: list[tuple[str, str, str]],
    *,
    program_context: str | None = None,
) -> list[dict[str, str]]:
    """Ask which Needs in one program ask for the same graduate capability.

    `rows` is `(label, ksec_tag, statement_th)` in the order the caller wants
    them read — demand order, so N1 is the most-demanded Need. Labels, not
    `need_id`s: a UUID is 36 characters the model has to copy exactly, and a
    miscopied one is a group the code cannot map back. `supporting_indices` in
    summarize_need showed short indices are what a model returns reliably.

    Every structural rule here (2-3 members, one KSEC tag, one group per Need)
    is enforced again by `stages.need_dedup.accept_groups`, which drops a group
    that breaks one. The prompt states them anyway, because a group dropped for
    a rule the model never saw is a duplicate that ships as two PLOs.

    Rule 1 defines a duplicate as the same main task and main object, the
    checkable definition the 2026-09-29 pipeline proposal gives for set-level
    redundancy, with its example pair. It also carries the lesson of the
    measurement in the design doc: on the stored run, Needs drawn from the same
    few documents shared up to 55% of their evidence while asking for different
    things, so "same topic, same tool, same source" is named as not enough. Rule 4 exists because a model
    asked to find duplicates otherwise finds some.

    `program_context` is `build_program_context_th`'s line; None says nothing.
    """
    context = f"หลักสูตร: {program_context}\n\n" if program_context else ""
    listing = "\n".join(f"{label} | {tag} | {statement}" for label, tag, statement in rows)
    user = f"{context}รายการความต้องการ (ป้ายกำกับ | หมวด KSEC | ประโยค):\n{listing}"
    return [
        {"role": "system", "content": _SYSTEM_TH},
        {"role": "user", "content": user},
    ]
```

- [ ] **Step 4: Run — passes**

Run: `uv run pytest tests/unit/test_need_dedup_prompt.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Add the prompt to the inventory**

In `scripts/dump_prompts.py`:

1. Add the import beside the others: `from curriculum_agent.prompts.need_dedup import build_need_dedup_prompt`
2. In `_build()`, after the `plo = _render(...)` block, add:

```python
    dedup = _render(
        build_need_dedup_prompt(
            [("N1", "S", "<ประโยคความต้องการ 1>"), ("N2", "S", "<ประโยคความต้องการ 2>")],
            program_context="<program context>",
        )
    )
```

3. Pass `dedup=dedup,` in the `TEMPLATE.format(...)` call.
4. In `TEMPLATE`, add a row to the summary table after row 7:

```
| 8 | หา Need ที่ซ้ำกันก่อนร่าง PLO | `build_need_dedup_prompt` | `stages/need_dedup.py` → `find_duplicate_groups` | `need_dedup` | `DedupAnswer` | ❌ |
```

5. In `TEMPLATE`, directly before the line `## ชิ้นส่วนที่ prompt หลายก้อนใช้ร่วมกัน`, add (note: literal braces in TEMPLATE must be doubled, `{{` `}}`; this block has none besides `{dedup}`):

```
## 8. หา Need ที่ถามหาสมรรถนะเดียวกันก่อนร่าง PLO

| | |
|---|---|
| **builder** | `prompts/need_dedup.py` → `build_need_dedup_prompt(rows, *, program_context=None)` |
| **ผู้เรียก** | `stages/need_dedup.py` → `find_duplicate_groups` (ครั้งเดียวต่อการรัน `plo_synthesis`) |
| **slot / wrapper** | `need_dedup` → `complete_need_dedup` · ปิดได้ด้วย `NEED_DEDUP_PROVIDER=` |
| **response model** | `DedupAnswer` (`groups: [{{labels, reason_th}}]`) |
| **cache** | ไม่มี |

ส่งป้าย `N1`, `N2`, ... แทน `need_id` เพราะ UUID ยาว 36 ตัวที่โมเดลต้องคัดลอกให้ตรง · กฎโครงสร้างทุกข้อ
(2-3 ข้อต่อกลุ่ม · KSEC เดียวกัน · หนึ่ง Need หนึ่งกลุ่ม) โค้ดตรวจซ้ำใน `accept_groups` และทิ้งทั้งกลุ่มที่ผิด
ไม่ตัดสมาชิกออก · กฎข้อ 1 นิยาม "ซ้ำ" ว่างานหลักและวัตถุหลักเหมือนกัน และบอกชัดว่าหัวข้อ เครื่องมือ หรือแหล่งที่มาเดียวกันยังไม่พอ เพราะ Need ที่มาจาก
เอกสารชุดเดียวกันใช้ evidence ร่วมกันสูงถึง 55% ทั้งที่ขอคนละเรื่อง

{dedup}

---

```

(If step 5 hits a `KeyError`/`IndexError` from `format`, a brace in the new text is undoubled.)

- [ ] **Step 6: Regenerate and check the inventory**

Run: `PYTHONIOENCODING=utf-8 uv run python scripts/dump_prompts.py && PYTHONIOENCODING=utf-8 uv run python scripts/dump_prompts.py --check`
Expected: the first rewrites `docs/prompt-inventory.md`; `--check` exits 0. Open the diff (`git diff docs/prompt-inventory.md`) and confirm only the new row and section 8 were added.

- [ ] **Step 7: Lint and commit**

Run: `uv run ruff check src/ tests/ scripts/ && uv run mypy src/`

```bash
git add src/curriculum_agent/prompts/need_dedup.py tests/unit/test_need_dedup_prompt.py scripts/dump_prompts.py docs/prompt-inventory.md
git commit -m "feat(prompts): ask which Needs ask for one capability

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `stages/need_dedup.py` — acceptance and the call

**Files:**
- Create: `src/curriculum_agent/stages/need_dedup.py`
- Modify: `tests/conftest.py`
- Test: `tests/unit/test_need_dedup.py`

**Interfaces:**
- Consumes: `complete_need_dedup` (Task 1), `build_need_dedup_prompt` (Task 2), `build_program_context_th(metadata: dict[str, Any]) -> str | None` from `curriculum_agent.prompts.program_context`.
- Produces (all in `curriculum_agent.stages.need_dedup`):
  - `MAX_GROUP_SIZE: int = 3`
  - `class DuplicateGroup(BaseModel)`: `labels: list[str]`, `reason_th: str`
  - `class DedupAnswer(BaseModel)`: `groups: list[DuplicateGroup]`
  - `@dataclass(frozen=True) class FoldGroup`: `needs: tuple[Need, ...]` (in the order the Needs were labelled), `reason_th: str`
  - `def label_needs(needs: list[Need]) -> dict[str, Need]` — `"N1"`, `"N2"`, … in the given order
  - `def accept_groups(answer: DedupAnswer, labelled: dict[str, Need]) -> list[FoldGroup]`
  - `async def find_duplicate_groups(needs: list[Need], metadata: ProgramMetadata) -> list[FoldGroup]` — `needs` must already be in synthesis (demand) order

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_need_dedup.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from curriculum_agent.models import BloomLevel, KSECCategory, Need, ProgramMetadata
from curriculum_agent.stages import need_dedup as nd
from curriculum_agent.stages.need_dedup import (
    DedupAnswer,
    DuplicateGroup,
    accept_groups,
    find_duplicate_groups,
    label_needs,
)

_METADATA = ProgramMetadata.model_validate(
    {
        "program_id": "test",
        "field": "ภาษาจีน",
        "degree_level": "bachelor",
        "duration_years": 4,
        "faculty": "มนุษยศาสตร์",
        "university": "Test University",
    }
)


def _need(nid: str, *, ksec: KSECCategory = KSECCategory.S, demand: float = 0.5) -> Need:
    return Need(
        need_id=nid,
        program_id="test",
        statement_th=f"ต้องการบัณฑิตที่ทำงาน {nid} ในสถานประกอบการจริงได้",
        ksec_category=ksec,
        bloom_level=BloomLevel.APPLY,
        member_skill_ids=[f"S-{nid}"],
        source_evidence_ids=[f"E-{nid}"],
        freq=1,
        demand_score=demand,
    )


def _answer(*groups: list[str]) -> DedupAnswer:
    return DedupAnswer(groups=[DuplicateGroup(labels=g, reason_th="งานเดียวกัน") for g in groups])


def _ids(folds: list[nd.FoldGroup]) -> list[list[str]]:
    return [[n.need_id for n in f.needs] for f in folds]


# --------------------------- labelling ---------------------------


def test_labels_follow_the_given_order() -> None:
    labelled = label_needs([_need("a"), _need("b"), _need("c")])

    assert {label: n.need_id for label, n in labelled.items()} == {"N1": "a", "N2": "b", "N3": "c"}


# --------------------------- accept_groups ---------------------------


def test_a_valid_pair_is_accepted_with_its_reason() -> None:
    labelled = label_needs([_need("a"), _need("b"), _need("c")])

    (fold,) = accept_groups(_answer(["N1", "N3"]), labelled)

    assert [n.need_id for n in fold.needs] == ["a", "c"]
    assert fold.reason_th == "งานเดียวกัน"


def test_members_come_back_in_label_order_whatever_order_the_model_wrote() -> None:
    labelled = label_needs([_need("a"), _need("b"), _need("c")])

    assert _ids(accept_groups(_answer(["N3", "N1"]), labelled)) == [["a", "c"]]


def test_labels_are_matched_after_trimming_and_uppercasing() -> None:
    labelled = label_needs([_need("a"), _need("b")])

    assert _ids(accept_groups(_answer([" n1", "N2 "]), labelled)) == [["a", "b"]]


def test_unknown_labels_are_removed_before_counting() -> None:
    """N9 does not exist: what is left is one Need, which is not a group."""
    labelled = label_needs([_need("a"), _need("b")])

    assert accept_groups(_answer(["N1", "N9"]), labelled) == []


def test_a_repeated_label_counts_once() -> None:
    labelled = label_needs([_need("a"), _need("b")])

    assert accept_groups(_answer(["N1", "N1"]), labelled) == []


def test_a_need_already_in_an_accepted_group_drops_the_later_group_whole() -> None:
    labelled = label_needs([_need("a"), _need("b"), _need("c"), _need("d")])

    folds = accept_groups(_answer(["N1", "N2"], ["N2", "N3", "N4"]), labelled)

    assert _ids(folds) == [["a", "b"]], "the second group is dropped, not trimmed to N3+N4"


def test_a_group_spanning_two_ksec_tags_is_dropped() -> None:
    """A K Need folded into an S sentence is the knowledge disappearing."""
    labelled = label_needs([_need("a", ksec=KSECCategory.K), _need("b", ksec=KSECCategory.S)])

    assert accept_groups(_answer(["N1", "N2"]), labelled) == []


def test_a_group_of_four_is_dropped_not_trimmed() -> None:
    labelled = label_needs([_need(x) for x in "abcd"])

    assert accept_groups(_answer(["N1", "N2", "N3", "N4"]), labelled) == []


def test_a_group_of_three_is_the_largest_accepted() -> None:
    labelled = label_needs([_need(x) for x in "abc"])

    assert _ids(accept_groups(_answer(["N1", "N2", "N3"]), labelled)) == [["a", "b", "c"]]


def test_a_dropped_group_does_not_reserve_its_members() -> None:
    """Only an *accepted* group takes its members: a group dropped for mixing
    KSEC must not stop a later, valid group from using one of them."""
    labelled = label_needs([_need("a"), _need("b", ksec=KSECCategory.K), _need("c")])

    folds = accept_groups(_answer(["N1", "N2"], ["N1", "N3"]), labelled)

    assert _ids(folds) == [["a", "c"]]


def test_an_empty_answer_accepts_nothing() -> None:
    assert accept_groups(DedupAnswer(), label_needs([_need("a"), _need("b")])) == []


def test_the_answer_is_summarised_in_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """Accepted and dropped counts, for the per-stage figures a study reports."""
    logger = Mock()
    monkeypatch.setattr(nd, "logger", logger)
    labelled = label_needs([_need("a"), _need("b"), _need("c", ksec=KSECCategory.K)])

    accept_groups(_answer(["N1", "N2"], ["N2", "N3"]), labelled)

    lines = [c.args[0] for c in logger.info.call_args_list]
    assert "need_dedup: 1 group(s) accepted, 1 dropped by rule" in lines


# --------------------------- find_duplicate_groups ---------------------------


async def test_the_call_is_mapped_back_to_needs(monkeypatch: pytest.MonkeyPatch) -> None:
    call = AsyncMock(return_value=_answer(["N2", "N1"]))
    monkeypatch.setattr(nd, "complete_need_dedup", call)

    folds = await find_duplicate_groups([_need("a"), _need("b"), _need("c")], _METADATA)

    assert _ids(folds) == [["a", "b"]]
    messages = call.await_args.args[1]
    user = messages[-1]["content"]
    assert "N1 | S | " in user and "need_id" not in user
    assert "สาขาภาษาจีน" in user, "the program context line reaches the prompt"
    assert call.await_args.kwargs["temperature"] == 0


async def test_the_kill_switch_makes_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    call = AsyncMock(return_value=_answer(["N1", "N2"]))
    monkeypatch.setattr(nd, "complete_need_dedup", call)
    monkeypatch.setattr(nd.settings, "need_dedup_provider", "")

    assert await find_duplicate_groups([_need("a"), _need("b")], _METADATA) == []
    call.assert_not_awaited()


async def test_fewer_than_two_needs_makes_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    call = AsyncMock(return_value=DedupAnswer())
    monkeypatch.setattr(nd, "complete_need_dedup", call)

    assert await find_duplicate_groups([_need("a")], _METADATA) == []
    call.assert_not_awaited()


async def test_a_failing_call_folds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The step can only fold; its absence is the behaviour before it existed,
    so an outage costs duplicates and never a PLO."""
    monkeypatch.setattr(nd, "complete_need_dedup", AsyncMock(side_effect=RuntimeError("down")))

    assert await find_duplicate_groups([_need("a"), _need("b")], _METADATA) == []
```

- [ ] **Step 2: Run — fails on import**

Run: `uv run pytest tests/unit/test_need_dedup.py -q`
Expected: FAIL — `ModuleNotFoundError: curriculum_agent.stages.need_dedup`.

- [ ] **Step 3: Write the module**

Create `src/curriculum_agent/stages/need_dedup.py`:

```python
"""Find Needs that ask for one capability, before plo_synthesis drafts any.

`plo_synthesis` gives every Need its own slot, and the "one PLO per Need"
invariant only stops one Need being cited twice — two Needs that mean the same
thing still became two PLOs. This module asks one model, once per run, which
in-scope Needs ask for the same graduate capability, and hands back the groups
the code accepts. Each accepted group becomes one slot drafted from all its
members, exactly as a designer's manual merge would be.

Evidence overlap is not the similarity, and it was measured before this was
written: on the stored run a marketing Need and an ethics Need shared 55% of
their evidence while the one pair that truly duplicated shared under 20%. A
small corpus puts every Need on the same few documents. See the design doc,
`docs/superpowers/specs/2026-09-30-need-dedup-before-synthesis-design.md`.

The structural rules live in `accept_groups`, not in pydantic validators: a
validator failure makes instructor retry and then fail the whole call, which
discards every good group in an answer for one bad one. The schema only has to
parse. And a rule-breaking group is dropped whole, never trimmed — which member
to cut is the judgement the model was asked for, and code cutting by position
would make a decision nobody made.
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger
from pydantic import BaseModel, Field

from curriculum_agent.config import settings
from curriculum_agent.llm import complete_need_dedup
from curriculum_agent.models import Need, ProgramMetadata
from curriculum_agent.prompts.need_dedup import build_need_dedup_prompt
from curriculum_agent.prompts.program_context import build_program_context_th

# One sentence has to carry every member. Past three it stops being able to,
# which is ticket 18's fifteen-name group over again at the PLO level.
MAX_GROUP_SIZE = 3

# Instructor attempts in total (an int max_retries is attempts, not retries).
_ATTEMPTS = 2


class DuplicateGroup(BaseModel):
    labels: list[str] = Field(default_factory=list)
    reason_th: str = ""


class DedupAnswer(BaseModel):
    groups: list[DuplicateGroup] = Field(default_factory=list)


@dataclass(frozen=True)
class FoldGroup:
    """Needs the check found to ask for one capability, in label (demand) order."""

    needs: tuple[Need, ...]
    reason_th: str


def label_needs(needs: list[Need]) -> dict[str, Need]:
    """`N1`, `N2`, ... in the order given — the caller passes demand order."""
    return {f"N{i}": need for i, need in enumerate(needs, start=1)}


def _rejection(known: list[str], taken: set[str], labelled: dict[str, Need]) -> str | None:
    if len(known) < 2:
        return "fewer than two known Needs"
    if taken.intersection(known):
        return "a member is already in an accepted group"
    if len({labelled[label].ksec_category for label in known}) > 1:
        return "members span more than one KSEC tag"
    if len(known) > MAX_GROUP_SIZE:
        return f"more than {MAX_GROUP_SIZE} members"
    return None


def accept_groups(answer: DedupAnswer, labelled: dict[str, Need]) -> list[FoldGroup]:
    """The groups that break no structural rule, first group winning a contested Need."""
    order = {label: i for i, label in enumerate(labelled)}
    taken: set[str] = set()
    accepted: list[FoldGroup] = []
    for group in answer.groups:
        raw = [label.strip().upper() for label in group.labels]
        known = list(dict.fromkeys(label for label in raw if label in labelled))
        rejection = _rejection(known, taken, labelled)
        if rejection:
            logger.warning(f"need_dedup: dropped group {raw} — {rejection}")
            continue
        known.sort(key=order.__getitem__)
        taken.update(known)
        accepted.append(
            FoldGroup(
                needs=tuple(labelled[label] for label in known),
                reason_th=group.reason_th.strip(),
            )
        )
    logger.info(
        f"need_dedup: {len(accepted)} group(s) accepted, "
        f"{len(answer.groups) - len(accepted)} dropped by rule"
    )
    return accepted


async def find_duplicate_groups(needs: list[Need], metadata: ProgramMetadata) -> list[FoldGroup]:
    """One call over the in-scope Needs, already in synthesis order.

    Returns no groups — today's one-slot-per-Need behaviour — when the slot is
    switched off, when there is nothing to compare, and when the call fails for
    any reason. The step can only fold, so its absence never costs a PLO.
    """
    if not settings.need_dedup_provider:
        logger.info("need_dedup: disabled — every Need gets its own slot")
        return []
    if len(needs) < 2:
        return []

    labelled = label_needs(needs)
    messages = build_need_dedup_prompt(
        [(label, n.ksec_category.value, n.statement_th) for label, n in labelled.items()],
        program_context=build_program_context_th(metadata.model_dump()),
    )
    try:
        answer = await complete_need_dedup(
            DedupAnswer, messages, max_retries=_ATTEMPTS, temperature=0
        )
    except Exception as exc:
        logger.warning(f"need_dedup: call failed, folding nothing: {exc}")
        return []
    return accept_groups(answer, labelled)
```

- [ ] **Step 4: Run — passes**

Run: `uv run pytest tests/unit/test_need_dedup.py -q`
Expected: PASS (17 tests).

- [ ] **Step 5: Stub the call for every other test**

In `tests/conftest.py`, add after `_default_api_key_disabled` (add `from unittest.mock import AsyncMock` to the imports if absent):

```python
@pytest.fixture(autouse=True)
def _no_need_dedup_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """The duplicate check before synthesis is on by default, so every test that
    runs `plo_synthesis.run` would otherwise make a real network call. Stubbed at
    the one call site to answer "no duplicates", which is exactly the behaviour
    those tests were written against. A test about folding patches it again —
    a later `setattr` wins."""
    from curriculum_agent.stages import need_dedup  # noqa: PLC0415

    monkeypatch.setattr(
        need_dedup, "complete_need_dedup", AsyncMock(return_value=need_dedup.DedupAnswer())
    )
```

- [ ] **Step 6: Full suite, lint, types**

Run: `uv run ruff check src/ tests/ && uv run mypy src/ && uv run pytest -q`
Expected: clean; all pass.

- [ ] **Step 7: Mutation check (do not commit the mutants)**

For each mutant below: apply it by hand, run `uv run pytest tests/unit/test_need_dedup.py -q`, confirm at least one test FAILS, then revert (`git diff src/curriculum_agent/stages/need_dedup.py` must be empty before the next).

1. `if len(known) < 2:` → `if len(known) < 1:`
2. delete the `taken.intersection(known)` branch
3. `> 1` in the KSEC branch → `> 2`
4. `MAX_GROUP_SIZE = 3` → `MAX_GROUP_SIZE = 4`
5. `taken.update(known)` moved *above* the `if rejection:` check (a dropped group then reserves its members)
6. `temperature=0` removed

Any mutant that survives: add the missing test, then re-run that mutant.

- [ ] **Step 8: Commit**

```bash
git add src/curriculum_agent/stages/need_dedup.py tests/unit/test_need_dedup.py tests/conftest.py
git commit -m "feat(needs): find Needs asking for one capability, and judge the answer in code

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Fold in `plo_synthesis`, with the merge floor

**Files:**
- Modify: `src/curriculum_agent/stages/need_grouping.py` (after `MAX_CORE_PLOS = 10`, line 23)
- Modify: `src/curriculum_agent/stages/plo_synthesis.py` (imports lines 21-26; slot selection lines ~440-467; floor warning ~line 539)
- Test: `tests/unit/test_plo_synthesis_dedup.py`

**Interfaces:**
- Consumes: `FoldGroup`, `find_duplicate_groups` (Task 3).
- Produces:
  - `curriculum_agent.stages.need_grouping.MIN_CORE_AFTER_MERGE: int = 4`
  - in `curriculum_agent.stages.plo_synthesis`:
    - `def build_units(needs: list[Need], folds: Sequence[FoldGroup]) -> list[list[Need]]`
    - `def core_slot_count(units: list[list[Need]]) -> int`
    - `def enforce_merge_floor(needs: list[Need], folds: Sequence[FoldGroup]) -> list[FoldGroup]`
    - `def _select_slots(units: list[list[Need]]) -> list[_Slot]`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_plo_synthesis_dedup.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from curriculum_agent.graph import AgentState
from curriculum_agent.models import BloomLevel, KSECCategory, Need
from curriculum_agent.stages import plo_synthesis as ps
from curriculum_agent.stages.need_dedup import FoldGroup
from tests.support.smart_agent import set_soft_judge

_METADATA = {
    "program_id": "test",
    "field": "CS",
    "degree_level": "bachelor",
    "duration_years": 4,
    "faculty": "Engineering",
    "university": "Test University",
}


def _need(nid: str, demand: float, *, optional: bool = False) -> Need:
    return Need(
        need_id=nid,
        program_id="test",
        statement_th=f"ต้องการบัณฑิตที่ทำงาน {nid} ในสถานประกอบการจริงได้",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.APPLY,
        member_skill_ids=[f"S-{nid}"],
        source_evidence_ids=[f"E-{nid}"],
        freq=1,
        demand_score=demand,
        is_optional=optional,
        in_field_skill_count=1,
        graduate_capability_skill_count=1,
    )


def _fold(*needs: Need) -> FoldGroup:
    return FoldGroup(needs=tuple(ps.synthesis_order(list(needs))), reason_th="งานเดียวกัน")


def _slots(needs: list[Need], folds: list[FoldGroup]) -> list[tuple[str, list[str]]]:
    ordered = ps.synthesis_order(needs)
    slots = ps._select_slots(ps.build_units(ordered, folds))
    return [(s.plo_id, [n.need_id for n in s.needs]) for s in slots]


# --------------------------- units and slot selection ---------------------------


def test_without_folds_every_need_keeps_its_own_slot() -> None:
    needs = [_need("A", 0.9), _need("B", 0.5)]

    assert _slots(needs, []) == [("PLO1", ["A"]), ("PLO2", ["B"])]


def test_a_fold_is_one_slot_with_its_members_in_demand_order() -> None:
    a, b, c = _need("A", 0.9), _need("B", 0.5), _need("C", 0.3)

    assert _slots([a, b, c], [_fold(c, a)]) == [("PLO1", ["A", "C"]), ("PLO2", ["B"])]


def test_a_unit_ranks_by_its_top_member() -> None:
    """A low-demand Need folded into a high-demand one rides at the top."""
    a, b, c = _need("A", 0.2), _need("B", 0.5), _need("C", 0.9)

    assert _slots([a, b, c], [_fold(a, c)])[0] == ("PLO1", ["C", "A"])


def test_a_fold_frees_a_slot_the_next_need_below_the_cut_takes() -> None:
    """Eleven core Needs: without a fold the lowest loses the ceiling cut; with
    the top two folded, it gets the slot the fold freed."""
    needs = [_need(f"N{i:02d}", i / 100) for i in range(1, 12)]

    without = {nid for _, ids in _slots(needs, []) for nid in ids}
    with_fold = _slots(needs, [_fold(needs[10], needs[9])])

    assert "N01" not in without
    assert len(with_fold) == ps.MAX_CORE_PLOS
    assert "N01" in {nid for _, ids in with_fold for nid in ids}


def test_an_optional_need_folded_into_a_core_one_is_core() -> None:
    core, opt = _need("C", 0.5), _need("O", 0.1, optional=True)

    assert _slots([core, opt], [_fold(core, opt)]) == [("PLO1", ["C", "O"])]


def test_two_optional_needs_fold_into_one_optional_slot() -> None:
    o1, o2 = _need("O1", 0.2, optional=True), _need("O2", 0.1, optional=True)

    assert _slots([o1, o2], [_fold(o1, o2)]) == [("OPT1", ["O1", "O2"])]


# --------------------------- the merge floor ---------------------------


def _kept(needs: list[Need], folds: list[FoldGroup]) -> list[list[str]]:
    ordered = ps.synthesis_order(needs)
    return [[n.need_id for n in f.needs] for f in ps.enforce_merge_floor(ordered, folds)]


def test_a_fold_leaving_exactly_the_floor_is_kept() -> None:
    needs = [_need(f"N{i}", i / 10) for i in range(1, 6)]  # 5 core

    assert _kept(needs, [_fold(needs[0], needs[1])]) == [["N2", "N1"]]


def test_a_fold_leaving_less_than_the_floor_is_unfolded() -> None:
    needs = [_need(f"N{i}", i / 10) for i in range(1, 5)]  # 4 core

    assert _kept(needs, [_fold(needs[0], needs[1])]) == []


def test_the_lowest_demand_fold_is_unfolded_first() -> None:
    """Five core Needs, two pair folds → 3 slots. Unfolding one restores 4; it
    is the fold whose top member has the lower demand."""
    needs = [_need(f"N{i}", i / 10) for i in range(1, 6)]
    low = _fold(needs[0], needs[1])  # top demand 0.2
    high = _fold(needs[3], needs[4])  # top demand 0.5

    assert _kept(needs, [low, high]) == [["N5", "N4"]]


def test_a_set_already_below_the_floor_gets_no_core_folds() -> None:
    """Not blocked, just unable to shrink: the fold is unfolded, the set stays at 3."""
    needs = [_need(f"N{i}", i / 10) for i in range(1, 4)]  # 3 core

    assert _kept(needs, [_fold(needs[0], needs[1])]) == []


def test_optional_folds_are_never_unfolded_for_the_floor() -> None:
    core = [_need(f"N{i}", i / 10) for i in range(1, 4)]  # 3 core, below the floor
    o1, o2 = _need("O1", 0.05, optional=True), _need("O2", 0.04, optional=True)
    mixed = _fold(core[0], _need("O3", 0.03, optional=True))

    kept = _kept([*core, o1, o2, mixed.needs[1]], [_fold(o1, o2), mixed])

    assert ["O1", "O2"] in kept, "an all-optional fold does not touch the core count"
    assert ["N1", "O3"] in kept, "an optional-into-core fold does not lower it either"


# --------------------------- run ---------------------------


def _patch_llm(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Drafts keyed by the first Need id in the prompt; records which Needs each
    synthesis call was handed."""
    seen: dict[str, str] = {}

    async def fake_synthesis(model, messages, **kw):  # noqa: ANN001, ANN003
        body = messages[-1]["content"]
        ids = [line.split("need_id: ")[1] for line in body.splitlines() if "need_id: " in line]
        seen[ids[0]] = ",".join(ids)
        return ps._SingleDraftResponse(
            plo=ps._PLODraft(
                statement_th=f"วิเคราะห์งาน {ids[0]} เพื่อเสนอแนวทางแก้ปัญหาได้",
                bloom_level=BloomLevel.ANALYZE,
                action_verb_th="วิเคราะห์",
                source_need_ids=ids,
                rationale_th="ตรงกับความต้องการของตลาด",
            )
        )

    monkeypatch.setattr(ps, "complete_plo_synthesis", fake_synthesis)
    set_soft_judge(monkeypatch)
    monkeypatch.setattr(ps.PLORepository, "delete_by_program", AsyncMock(return_value=0))
    monkeypatch.setattr(ps.PLORepository, "bulk_insert", AsyncMock())
    return seen


async def test_run_drafts_one_plo_from_every_member_of_a_fold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    needs = [_need(f"N{i}", i / 10) for i in range(1, 7)]  # 6 core
    _patch_llm(monkeypatch)
    fold = _fold(needs[5], needs[4])
    finder = AsyncMock(return_value=[fold])
    monkeypatch.setattr(ps, "find_duplicate_groups", finder)

    state: AgentState = {
        "program_id": "test",
        "metadata": _METADATA,
        "needs": [n.model_dump(mode="json") for n in needs],
    }
    result = await ps.run(state)

    plos = result["plos"]
    assert len(plos) == 5
    assert plos[0]["plo_id"] == "PLO1"
    assert plos[0]["source_need_ids"] == ["N6", "N5"]
    assert set(plos[0]["source_evidence_ids"]) == {"E-N6", "E-N5"}
    handed = [n.need_id for n in finder.await_args.args[0]]
    assert handed == ["N6", "N5", "N4", "N3", "N2", "N1"], "the finder sees demand order"


async def test_run_logs_the_core_count_before_and_after_folding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    needs = [_need(f"N{i}", i / 10) for i in range(1, 7)]  # 6 core
    _patch_llm(monkeypatch)
    monkeypatch.setattr(
        ps, "find_duplicate_groups", AsyncMock(return_value=[_fold(needs[5], needs[4])])
    )
    logger = Mock()
    monkeypatch.setattr(ps, "logger", logger)

    await ps.run(
        {
            "program_id": "test",
            "metadata": _METADATA,
            "needs": [n.model_dump(mode="json") for n in needs],
        }
    )

    lines = [c.args[0] for c in logger.info.call_args_list]
    assert "need_dedup: 1 fold(s) kept, 0 unfolded for the floor — core PLO slots 6 → 5" in lines


async def test_run_applies_the_floor_to_what_the_finder_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    needs = [_need(f"N{i}", i / 10) for i in range(1, 5)]  # 4 core
    _patch_llm(monkeypatch)
    monkeypatch.setattr(
        ps, "find_duplicate_groups", AsyncMock(return_value=[_fold(needs[3], needs[2])])
    )

    result = await ps.run(
        {
            "program_id": "test",
            "metadata": _METADATA,
            "needs": [n.model_dump(mode="json") for n in needs],
        }
    )

    assert len(result["plos"]) == 4, "folding would leave 3, below the merge floor"
```

(`build_plo_from_need_prompt` renders every Need as a `need_id: <id>` line — `stage_3_plo.py:52` — in both the single and the plural branch, which is what `fake_synthesis` reads.)

- [ ] **Step 2: Run — fails**

Run: `uv run pytest tests/unit/test_plo_synthesis_dedup.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute '_select_slots'` (and `build_units`, `enforce_merge_floor`, `find_duplicate_groups`).

- [ ] **Step 3: Add the floor constant**

In `src/curriculum_agent/stages/need_grouping.py`, directly after `MAX_CORE_PLOS = 10` insert:

```python

# How far a merge may take the core set: below MIN_NEEDS, never below this. Two
# PLOs that say one thing are not two outcomes, so folding duplicates is allowed
# to leave a set short of the policy band — the band's own warning still fires
# and tells the designer so. Four is where the set stops looking like a
# programme's outcomes, and a model's grouping or a hurried click should not be
# what gets it there. One floor for both paths: plo_synthesis's automatic folds
# (`enforce_merge_floor`) and the manual merge route, so nothing the stage folds
# on its own is a merge the designer would be refused by hand.
MIN_CORE_AFTER_MERGE = 4
```

- [ ] **Step 4: Add the unit helpers to `plo_synthesis.py`**

Change the `need_grouping` import to:

```python
from curriculum_agent.stages.need_grouping import (
    MAX_CORE_PLOS,
    MIN_CORE_AFTER_MERGE,
    MIN_NEEDS,
    SCOPE_PASS_RATIO,
    is_in_scope,
)
```

and add, after the `smart_rules` import block:

```python
from curriculum_agent.stages.need_dedup import FoldGroup, find_duplicate_groups
```

Directly after `synthesis_order` (line ~108) insert:

```python
def build_units(needs: list[Need], folds: Sequence[FoldGroup]) -> list[list[Need]]:
    """What slot selection chooses among: each fold as one unit, every other
    Need alone. Members are in synthesis order, so a unit's first Need is its
    most-demanded one — what it ranks by, and what its prompt lists first."""
    folded = {n.need_id for fold in folds for n in fold.needs}
    units = [synthesis_order(list(fold.needs)) for fold in folds]
    units += [[n] for n in needs if n.need_id not in folded]
    return units


def _unit_is_optional(unit: list[Need]) -> bool:
    # The same rule validate_and_build applies to the PLO the unit becomes.
    return all(n.is_optional for n in unit)


def _core_members(fold: FoldGroup) -> int:
    return sum(1 for n in fold.needs if not n.is_optional)


def core_slot_count(units: list[list[Need]]) -> int:
    """Core PLO slots these units would fill, after the ceiling."""
    return min(sum(1 for u in units if not _unit_is_optional(u)), MAX_CORE_PLOS)


def enforce_merge_floor(needs: list[Need], folds: Sequence[FoldGroup]) -> list[FoldGroup]:
    """Unfold groups until the core slots reach the merge floor.

    A set that starts below the floor is not blocked: every fold that would
    shrink it is unfolded, the loop runs out of candidates, and the set stays
    as it was — the merge route's own "only when this merge causes the
    shortfall". (Writing the target as `min(floor, unfolded count)` changes
    nothing: below the floor, every lowering fold goes either way.)
    Lowest top-member demand goes first, because the most-demanded outcomes are
    the ones the numbering and the report lead with. Only a fold with two or more
    core members lowers the count, so only those are ever unfolded.
    """
    kept = list(folds)
    while core_slot_count(build_units(needs, kept)) < MIN_CORE_AFTER_MERGE:
        lowering = [f for f in kept if _core_members(f) >= 2]
        if not lowering:
            break
        victim = min(
            lowering,
            key=lambda f: (
                synthesis_order(list(f.needs))[0].demand_score,
                synthesis_order(list(f.needs))[0].need_id,
            ),
        )
        kept.remove(victim)
        logger.warning(
            f"need_dedup: unfolded {', '.join(n.need_id for n in victim.needs)} — "
            f"folding it would leave fewer than {MIN_CORE_AFTER_MERGE} core PLOs (floor)"
        )
    return kept


def _select_slots(units: list[list[Need]]) -> list[_Slot]:
    """Number the units, most-demanded first, capping the core series.

    Pure code, and no awaits: the ceiling and the id scheme are decided before a
    single draft goes out, so PLO1 is the capability the market asked for most
    and the numbering is reproducible across re-runs on the same Needs.
    """
    slots: list[_Slot] = []
    for is_optional in (False, True):
        series = sorted(
            (u for u in units if _unit_is_optional(u) is is_optional),
            key=lambda u: (-u[0].demand_score, u[0].need_id),
        )
        if not is_optional and len(series) > MAX_CORE_PLOS:
            # Logged, not silent: a designer looking at 22 Needs and 10 PLOs has to
            # be able to find out which lost and why. plo_report shows the same
            # set on the review page.
            dropped = [n.need_id for u in series[MAX_CORE_PLOS:] for n in u]
            logger.warning(
                f"{len(series)} core PLO candidates exceed the {MAX_CORE_PLOS}-PLO "
                f"ceiling — synthesizing the {MAX_CORE_PLOS} highest-demand ones and "
                f"leaving {len(dropped)} Need(s) unused: {', '.join(dropped)}"
            )
            series = series[:MAX_CORE_PLOS]
        slots += [
            _Slot(
                plo_id=format_plo_id(index, is_optional=is_optional),
                needs=unit,
                is_optional=is_optional,
            )
            for index, unit in enumerate(series, start=1)
        ]
    return slots
```

`_Slot` is defined later in the file (line ~147); these functions only reference it at call time, so the order is fine. `Sequence` is already imported from `collections.abc`.

Before editing, run `uv run pytest -q -k "ceiling or exceed"` and grep the tests for the old warning text (`grep -rn "core Needs exceed" tests/`); none are expected. If one asserts it, update the assertion to the new wording.

- [ ] **Step 5: Wire it into `run`**

In `run`, replace everything from the line
`    logger.info(f"Stage 4: synthesizing one PLO per Need ({len(needs)} Needs)")`
through the end of the `for is_optional in (False, True):` loop (the line `            for index, need in enumerate(series, start=1)` and its closing `        ]`) with:

```python
    logger.info(f"Stage 4: synthesizing PLOs from {len(needs)} Needs")

    # Duplicates are folded before the ceiling, for the same reason the scope
    # filter runs before it: two slots spent on one capability are a slot a
    # distinct Need below the cut never got.
    ordered = synthesis_order(needs)
    found = await find_duplicate_groups(ordered, metadata)
    folds = enforce_merge_floor(ordered, found)
    for fold in folds:
        logger.info(
            f"Stage 4: one PLO from Needs {', '.join(n.need_id for n in fold.needs)} — "
            f"{fold.reason_th or 'no reason given'}"
        )
    units = build_units(ordered, folds)
    # One line a before/after comparison can be read off, with or without the
    # kill switch: the same run with NEED_DEDUP_PROVIDER= is this step's baseline.
    logger.info(
        f"need_dedup: {len(folds)} fold(s) kept, {len(found) - len(folds)} unfolded "
        f"for the floor — core PLO slots {core_slot_count(build_units(ordered, []))} → "
        f"{core_slot_count(units)}"
    )
    slots = _select_slots(units)
```

Then replace the floor-warning `cause` block near the end of `run`:

```python
        cause = (
            f"กรอง Need นอกขอบเขตออก {len(filtered)} ใบก่อนร่าง (หลักฐานในขอบเขตไม่พอ)"
            if filtered
            else "need_combination should have enforced this"
        )
```

with:

```python
        folded_core = sum(max(0, _core_members(f) - 1) for f in folds)
        causes = []
        if filtered:
            causes.append(
                f"กรอง Need นอกขอบเขตออก {len(filtered)} ใบก่อนร่าง (หลักฐานในขอบเขตไม่พอ)"
            )
        if folded_core:
            # Said here so a shortfall from duplicates reads differently from one
            # from missing evidence.
            causes.append(f"รวม Need หลักที่ถามหาสมรรถนะเดียวกันเข้าด้วยกัน {folded_core} ใบ")
        cause = " · ".join(causes) or "need_combination should have enforced this"
```

- [ ] **Step 6: Run the new tests, then the whole synthesis area**

Run: `uv run pytest tests/unit/test_plo_synthesis_dedup.py -q`
Expected: PASS (16 tests).

Run: `uv run pytest -q tests/unit/test_plo_synthesis_guard.py tests/unit/test_plo_synthesis_phases.py tests/unit/test_plo_id_scheme.py`
Expected: PASS — the autouse stub answers "no groups", so behaviour is unchanged.

- [ ] **Step 7: Full suite, lint, types**

Run: `uv run ruff check src/ tests/ && uv run mypy src/ && uv run pytest -q`
Expected: clean; all pass.

- [ ] **Step 8: Mutation check (do not commit the mutants)**

Apply each by hand, run `uv run pytest tests/unit/test_plo_synthesis_dedup.py -q`, confirm a FAIL, revert:

1. `< MIN_CORE_AFTER_MERGE` in the `while` → `< MIN_CORE_AFTER_MERGE - 1`
2. `min(lowering, ...)` → `max(lowering, ...)`
3. `_core_members(f) >= 2` → `_core_members(f) >= 1`
4. `MIN_CORE_AFTER_MERGE = 4` → `= 3`
5. in `_select_slots`, key `-u[0].demand_score` → `-u[-1].demand_score`
6. in `build_units`, `synthesis_order(list(fold.needs))` → `list(fold.needs)[::-1]`
7. `_unit_is_optional`: `all(` → `any(`

Any survivor: add the missing test and re-run it.

- [ ] **Step 9: Commit**

```bash
git add src/curriculum_agent/stages/need_grouping.py src/curriculum_agent/stages/plo_synthesis.py tests/unit/test_plo_synthesis_dedup.py
git commit -m "feat(plo): draft one PLO per capability, not per Need, down to a floor of four

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The merge route's floor

**Files:**
- Modify: `src/curriculum_agent/api/routes/plos.py:218-290`
- Test: `tests/unit/test_api_plos.py:197-230`

**Interfaces:**
- Consumes: `MIN_CORE_AFTER_MERGE` (Task 4).

- [ ] **Step 1: Rewrite the floor tests**

In `tests/unit/test_api_plos.py`, replace `test_the_floor_still_refuses_a_merge_that_causes_the_shortfall` and `test_out_of_scope_needs_do_not_change_which_bound_applies` with:

```python
def test_a_merge_may_take_the_set_below_the_policy_band(
    merge_env: Callable[..., PLO],
) -> None:
    """Six core PLOs, three folded into one, leaves four: under the 6-10 band,
    at the merge floor. Two PLOs that say one thing are not two outcomes."""
    needs = [_need(f"N{i}") for i in range(1, 7)]
    existing = [_plo(f"PLO{i}", [f"N{i}"]) for i in range(1, 7)]
    merge_env(needs, existing)

    with patch.object(plos_route, "logger"):
        response = client.post(
            "/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "N2", "N3"]}
        )

    assert response.status_code == 200, response.text


def test_the_merge_floor_refuses_a_merge_that_causes_the_shortfall(
    merge_env: Callable[..., PLO],
) -> None:
    """Four core PLOs, two folded into one, leaves three — below the merge floor,
    and this merge is what caused it."""
    needs = [_need(f"N{i}") for i in range(1, 5)]
    existing = [_plo(f"PLO{i}", [f"N{i}"]) for i in range(1, 5)]
    merge_env(needs, existing)

    with patch.object(plos_route, "logger"):
        response = client.post(
            "/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "N2"]}
        )

    assert response.status_code == 422
    assert "ต่ำกว่าขั้นต่ำของการรวม" in response.json()["detail"]
    assert "4" in response.json()["detail"]


def test_a_set_already_below_the_floor_can_still_grow(
    merge_env: Callable[..., PLO],
) -> None:
    """Two core PLOs, and a merge of two Needs nothing cites adds a third: still
    below the floor, but this merge did not cause the shortfall."""
    needs = [_need(f"N{i}") for i in range(1, 5)]
    existing = [_plo("PLO1", ["N1"]), _plo("PLO2", ["N2"])]
    merge_env(needs, existing)

    with patch.object(plos_route, "logger"):
        response = client.post(
            "/programs/cs-test/plos/from-needs", json={"need_ids": ["N3", "N4"]}
        )

    assert response.status_code == 200, response.text


def test_out_of_scope_needs_do_not_change_which_bound_applies(
    merge_env: Callable[..., PLO],
) -> None:
    """Same shortfall, same refusal, whether the Needs being merged are in scope or
    not. The guard does not get to relax the count policy in either direction, and
    the override path does not get to bypass it."""
    needs = [_need(f"X{i}", in_scope=False) for i in range(1, 5)]
    existing = [_plo(f"PLO{i}", [f"X{i}"]) for i in range(1, 5)]
    merge_env(needs, existing)

    with patch.object(plos_route, "logger"):
        response = client.post(
            "/programs/cs-test/plos/from-needs", json={"need_ids": ["X1", "X2"]}
        )

    assert response.status_code == 422
    assert "ต่ำกว่าขั้นต่ำของการรวม" in response.json()["detail"]
```

- [ ] **Step 2: Run — the refusal tests fail, the 200 test fails**

Run: `uv run pytest tests/unit/test_api_plos.py -q -k "floor or below or bound"`
Expected: FAIL — six-to-four is refused today (MIN_NEEDS 6) and the message text differs.

- [ ] **Step 3: Change the route**

In `create_plo_from_needs`, change the local import to:

```python
    from curriculum_agent.stages.need_grouping import (  # noqa: PLC0415
        MAX_CORE_PLOS,
        MIN_CORE_AFTER_MERGE,
        is_in_scope,
    )
```

Replace the floor block (the comment starting `# Only when this merge is what takes the count below the floor.` and the `if projected_core < MIN_NEEDS ...` statement) with:

```python
    # The merge floor, not the policy floor: a merge may leave the set under the
    # 6-10 band — two PLOs that say one thing are not two outcomes, and the band's
    # own warning still tells the designer — but not under MIN_CORE_AFTER_MERGE.
    # plo_synthesis folds duplicates down to the same number, so nothing the stage
    # does on its own is refused here by hand. Only when this merge causes the
    # shortfall: a program that is already short must not have every further
    # merge refused for a shortfall it did not cause.
    if projected_core < MIN_CORE_AFTER_MERGE and projected_core < current_core:
        raise HTTPException(
            status_code=422,
            detail=(
                f"การรวมนี้จะเหลือ PLO หลัก {projected_core} ข้อ ต่ำกว่าขั้นต่ำของการรวม "
                f"{MIN_CORE_AFTER_MERGE} ข้อ รวม Need ที่ยังไม่มี PLO ขึ้นมาเป็นข้อใหม่ก่อน "
                "แล้วจึงรวมข้อที่ซ้ำซ้อนกัน"
            ),
        )
```

Also update the comment above the ceiling check (`# The 6-10 policy is a property of the stored set...`) so its last sentences read: `Both bounds are therefore checked here — the ceiling at MAX_CORE_PLOS, the floor at MIN_CORE_AFTER_MERGE below. Optional PLOs are outside the count, for the same reason they are in synthesis.`

Check the route's docstring and the `MIN_NEEDS` mention in the comment at `plos.py:54` still read truthfully; that one is about the Need pool and stays.

- [ ] **Step 4: Run — passes**

Run: `uv run pytest tests/unit/test_api_plos.py -q`
Expected: PASS.

- [ ] **Step 5: Full suite, lint, types, commit**

Run: `uv run ruff check src/ tests/ && uv run mypy src/ && uv run pytest -q`

```bash
git add src/curriculum_agent/api/routes/plos.py tests/unit/test_api_plos.py
git commit -m "feat(plo): a manual merge may take the core set down to four, like the automatic one

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Probe on the stored Needs (read-only, no commit of code)

**Files:**
- Create (scratchpad only, not committed): `<scratchpad>/probe_need_dedup.py`
- Modify: `docs/superpowers/specs/2026-09-30-need-dedup-before-synthesis-design.md` (append a "Measured" section)

This is the spec's "Measurement before commit". It calls the real `need_dedup` slot three times and writes nothing to the database.

- [ ] **Step 1: Write the probe**

```python
import asyncio
import sys

from curriculum_agent import llm
from curriculum_agent.data.repositories import NeedRepository, ProgramRepository
from curriculum_agent.stages.need_dedup import find_duplicate_groups
from curriculum_agent.stages.need_grouping import is_in_scope
from curriculum_agent.stages.plo_synthesis import enforce_merge_floor, synthesis_order

PID = "program"


async def main() -> None:
    print([line for line in llm.describe_target().splitlines() if "need_dedup" in line])
    program = await ProgramRepository().get(PID)
    needs = synthesis_order([n for n in await NeedRepository().list_by_program(PID) if is_in_scope(n)])
    for i, n in enumerate(needs, start=1):
        print(f"N{i} {n.need_id[:4]} {n.ksec_category} opt={n.is_optional} d={n.demand_score:.3f} {n.statement_th[:70]}")
    for run in range(3):
        folds = await find_duplicate_groups(needs, program)
        kept = enforce_merge_floor(needs, folds)
        print(f"run {run + 1}: accepted={[[n.need_id[:4] for n in f.needs] for f in folds]} "
              f"after_floor={[[n.need_id[:4] for n in f.needs] for f in kept]}")
        for f in folds:
            print("   ", [n.need_id[:4] for n in f.needs], f.reason_th)


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
asyncio.run(main())
```

(`ProgramRepository().get` returns `ProgramMetadata` — confirm with `grep -n "async def get" src/curriculum_agent/data/repositories.py`; if it returns something else, build `ProgramMetadata` from it.)

- [ ] **Step 2: Run it**

Run: `PYTHONIOENCODING=utf-8 uv run python <scratchpad>/probe_need_dedup.py 2>&1 | grep -v "| DEBUG\|| INFO"`
Expected: the `need_dedup: provider=openrouter ... model=meta-llama/llama-3.3-70b-instruct` line (no key shown), the labelled Needs, three runs.

- [ ] **Step 3: Judge against the spec's criteria**

- must fold: `252f`+`6a45` (with or without `d7c4`), `afe6`+`befb`, `5dd3`+`1b4f` (only if `1b4f` is in scope)
- must not fold: `1fe0` with `252f` or `afe6`
- stable across three runs

If the default model fails: set the slot to the validation model *for the probe only* — `monkeypatch`-style inside the script, `llm.settings.need_dedup_model = "z-ai/glm-5.3-flash"` before `main()` — rerun, and compare. If glm passes and llama does not, change the slot's `default_models` in `SLOTS` to `{"openrouter": "z-ai/glm-5.3-flash"}` with a comment giving both results, update the `.env.example` model line, rerun `uv run pytest tests/unit/test_llm_slots.py tests/unit/test_llm_target.py -q`, and commit that change separately (`fix(llm): run the duplicate check on glm-5.3-flash`). If neither passes, stop and report to the user with the raw outputs — do not tune the prompt without their say.

- [ ] **Step 4: Record the result in the spec**

Append to the spec a `## Measured (2026-09-30)` section: the model, each run's accepted groups and post-floor groups, pass/fail per criterion, and any drop warnings `accept_groups` logged. Commit:

```bash
git add docs/superpowers/specs/2026-09-30-need-dedup-before-synthesis-design.md
git commit -m "docs(spec): what the duplicate check found on the stored Needs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.claude/skills/curriculum-design-agent/references/prompts.md`

- [ ] **Step 1: CLAUDE.md — the slot list**

In the **Stack → LLM** bullet: change "five slots" to "six slots"; in the in-order list "**extraction**, **clustering**, **need_combination**, **plo_synthesis**, **validation**" insert **need_dedup** after need_combination. After the `NEED_COMBINATION_PROVIDER/...` sentence group add:

> **`NEED_DEDUP_PROVIDER`/`NEED_DEDUP_MODEL`** (default OpenRouter, `complete_need_dedup`) is the duplicate check at the start of `plo_synthesis`: one call per run that reads every in-scope Need and groups the ones asking for one capability. It returns labels, not Thai prose, and `accept_groups` judges the answer in code. Like validation it is `disableable` — `NEED_DEDUP_PROVIDER=` (empty) skips it and every Need gets its own slot.

Update the validation passage's claim "This is the one slot where empty and unset differ" / "it is the only slot with `disableable=True`" to say need_dedup and validation are the two.

- [ ] **Step 2: CLAUDE.md — rule 6**

In immutable rule 6, change "**6-10 main PLOs per program, each drafted from one Need.**" to "**6-10 main PLOs per program, each drafted from one Need — or from up to three same-KSEC Needs the duplicate check found to ask for one capability.**" and add after the merge-route sentences:

> Merging — the automatic fold in `plo_synthesis` (`enforce_merge_floor`) and the merge route alike — may take the core count below 6 but not below `MIN_CORE_AFTER_MERGE` (4), unless the set was already below it; the 6-10 band and its warnings are unchanged. The fold is chosen before the ceiling, like the scope filter, so a slot freed by a fold goes to the next Need below the cut.

and change the merge-route text "so the route refuses above `MAX_CORE_PLOS` and below `MIN_NEEDS`" to "so the route refuses above `MAX_CORE_PLOS` and below `MIN_CORE_AFTER_MERGE`".

- [ ] **Step 3: CLAUDE.md — the pitfall**

Add to **Common pitfalls**:

> - **Two Needs sharing evidence are not two Needs asking for one thing.** The duplicate check before synthesis (`stages/need_dedup.py`) reads the Need *sentences* through a model, because the free signal measured useless: on the stored run a marketing Need and an ethics Need shared 55% of their evidence while the one true duplicate pair shared under 20% — a small corpus puts every Need on the same few documents. The model's answer is judged in `accept_groups`, not by pydantic validators (a validator failure fails the whole call and loses every good group with the bad one), and a group that breaks a rule — mixed KSEC, more than three members, a Need already taken — is dropped whole, never trimmed, since which member to cut is the judgement the model was asked for. The step can only fold: switched off, failing, or given one Need, it returns nothing and synthesis behaves as it did before it existed.

- [ ] **Step 4: Skill reference**

In `.claude/skills/curriculum-design-agent/references/prompts.md`, add a section after "## Stage 5 (plo_synthesis): one Need → one PLO (the most important prompt)" and before "## SMART validation agent prompts":

```markdown
## plo_synthesis: the duplicate check before drafting

`prompts/need_dedup.py`. The text is in `docs/prompt-inventory.md` §8; this is why it says what it says.

- **Labels, not ids.** Needs are sent as `N1`, `N2`, … in demand order. A UUID is 36 characters the model has to copy exactly; short indices are what a model returns reliably (`supporting_indices` showed the same).
- **A duplicate is the same main task and main object**, whatever the wording or context — the checkable definition the 2026-09-29 pipeline proposal gives for set-level redundancy, with its example pair.
- **"Same topic, same tool, same source is not enough."** The evidence-overlap measurement is why: Needs drawn from the same documents share much of their evidence while asking for different things, and a model left to its own reading groups them the same way.
- **An empty answer is named as valid.** A model asked to find duplicates otherwise finds some.
- **The structural rules are stated and then enforced again in code** (`accept_groups`). Stating them keeps a good grouping from being thrown away for a rule the model never saw; enforcing them keeps a bad one from reaching synthesis.
```

- [ ] **Step 5: Check and commit**

Run: `PYTHONIOENCODING=utf-8 uv run python scripts/dump_prompts.py --check && uv run pytest -q`
Expected: inventory current; all pass.

```bash
git add CLAUDE.md .claude/skills/curriculum-design-agent/references/prompts.md
git commit -m "docs: the duplicate check before synthesis, and the merge floor of four

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After the plan

The end-to-end check is the designer's: re-run need_combination (to pick up the Bloom fix, `7d5d2a0`) and then plo_synthesis on program `program`. That **replaces the stored Needs and PLOs** and is not part of this plan — ask the user before running it.
