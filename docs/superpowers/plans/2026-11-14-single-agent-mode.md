# Single-Agent Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A program can be created in `single` mode and taken from evidence to an approved PLO report by one LLM tool loop with one system prompt, storing Needs and PLOs (no skills) in the existing tables.

**Architecture:** Mode is a column on the program. One generic loop (`stages/single_agent_loop.py`) drives one step schema and one system prompt; a *task handler* per job (needs half, PLO half, one-PLO redraft, Need merge) supplies the opening message and reacts to output actions. Code derives every Need statistic from cited evidence and applies the existing hard SMART check. The existing routes dispatch on the program's mode.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, Instructor, SQLAlchemy + Alembic, pytest (asyncio auto), React + TypeScript + Vite (no frontend test runner; `npm run build` is the typecheck).

**Spec:** `docs/superpowers/specs/2026-11-13-single-agent-mode-design.md`

## Global Constraints

- Branch `feat/four-agent-pipeline`. Run `git branch --show-current` before every commit; stage files by explicit path. Never commit `.env`, `.env.demo`, `dist/`.
- **A multi program's behaviour and stored rows must not change.** Every dispatch is `if program.agent_mode == "single": … else: <existing code untouched>`.
- Single calls **only** the `single_agent` slot (`complete_single_agent`). No `complete_need_combination`, `complete_plo_synthesis`, `complete_validation`, `complete_plo_review` on a single program.
- One system prompt for every single task: `build_single_agent_system()` takes no task-specific argument. Tasks differ only in the first user message.
- Temperature 0 on every single call.
- No LLM classifies evidence or Needs. `requirement` / `need` / `want` come from code.
- The pure-code hard check (`smart_rules.hard_failures`) runs on every final PLO statement and alone sets `smart_escalated`.
- Type hints on every signature, `from __future__ import annotations`, `loguru` (never stdlib `logging`), async stage handlers, prompts only under `src/curriculum_agent/prompts/`, Thai for designer-facing strings, English for code/comments/logs.
- Never run Alembic against the shared DB. Any migration run is `uv run alembic -x url=<copy-db-url> upgrade head` against `curriculum_phase1`. Do not run `scripts/start-services.ps1` (it migrates the shared DB). Never print a DSN or key.
- Checks before each commit: `uv run pytest <touched tests> -q`, `uv run ruff check src/ tests/ scripts/`, `uv run mypy src/`.
- Settings defaults (exact): `single_agent_max_turns=80`, `single_agent_timeout_seconds=1800`, `single_agent_evidence_part_chars=6000`, `single_agent_context_budget_ratio=0.7`, `single_agent_context_window_tokens=128000`.

## Review Focus

1. The agent cites an evidence id that is mistyped or belongs to another program → the save is refused with a Thai reason as an observation and the loop continues; nothing is stored under that id. (Task 7)
2. The agent hands in an action that does not belong to the current task (`SavePLO` during the needs half), or a PLO citing a Need already behind another PLO or absent from the input → refusal observation, never a crash or a stored row. (Tasks 6, 8)
3. `PUT /programs/{id}` on a single program (the intake edit form) → the stored `agent_mode` is kept, not reset to `multi`. (Task 2)
4. Rows that existed before the migration (no `agent_mode`, no `origin`) → read back as `multi`, and a multi Need with no skills is still rejected. (Task 1)
5. Re-running the needs half on a single program that already has PLOs → Needs are replaced and PLOs are left alone, exactly as the multi route behaves today; the run does not fail. (Task 9)

## File Structure

| File | Responsibility |
|---|---|
| `src/curriculum_agent/models.py` | `AgentMode`, `Program*.agent_mode`, `Need.origin`, `smart_validated_by` value, `JobKind` values |
| `migrations/versions/c8e3f4a5b627_agent_mode.py` | `programs.agent_mode`, `needs.origin` |
| `src/curriculum_agent/config.py`, `llm.py` | `single_agent` slot, settings, `complete_single_agent`, prompt-token sink |
| `src/curriculum_agent/stages/single_need_stats.py` | pure: Need statistics from cited evidence |
| `src/curriculum_agent/prompts/single_agent.py` | the one system prompt, task openers, observation texts |
| `src/curriculum_agent/stages/single_agent_tools.py` | the seven tools over a `SingleToolContext` |
| `src/curriculum_agent/stages/single_agent_loop.py` | step schema, history with evidence dropping, the loop |
| `src/curriculum_agent/stages/single_needs.py` | needs-half handler + `run_single_needs`, Need-merge handler |
| `src/curriculum_agent/stages/single_plos.py` | PLO-half handler + `run_single_plos`, one-PLO redraft/revalidate |
| `src/curriculum_agent/api/routes/{needs,plos,programs,sessions}.py`, `api/jobs.py` | dispatch by mode |
| `frontend/src/…` | mode choice, rail, Need page, PLO checkpoint |

---

### Task 1: Models and migration

**Files:**
- Modify: `src/curriculum_agent/models.py`, `src/curriculum_agent/data/orm.py`, `src/curriculum_agent/data/repositories.py` (`ProgramRepository.list_all`, ~193-250)
- Create: `migrations/versions/c8e3f4a5b627_agent_mode.py` (`revision='c8e3f4a5b627'`, `down_revision='b7d2e3f4a516'`)
- Test: `tests/unit/test_single_models.py`

**Interfaces — Produces:**
- `AgentMode = Literal["multi", "single"]`
- `ProgramCreateRequest.agent_mode: AgentMode = "multi"` (inherited by `ProgramMetadata`); `ProgramSummary.agent_mode: AgentMode = "multi"`
- `Need.origin: AgentMode = "multi"`; `member_skill_ids: list[str]` loses `min_length=1` and a model validator enforces "non-empty unless `origin == 'single'`"
- `PLO.smart_validated_by` gains `"single_agent"`
- `JobKind` gains `"single_needs"`, `"single_plos"`
- ORM: `ProgramTable.agent_mode = mapped_column(String(10), nullable=False, server_default="multi")`, `NeedTable.origin` the same

- [ ] **Step 1: Write the failing tests**

```python
def test_single_need_may_have_no_skills():
    need = Need(**_need_kwargs(origin="single", member_skill_ids=[]))
    assert need.member_skill_ids == [] and need.in_field_ratio == 1.0

def test_multi_need_without_skills_is_still_rejected():
    with pytest.raises(ValidationError):
        Need(**_need_kwargs(member_skill_ids=[]))

def test_old_rows_read_back_as_multi():
    assert Need(**_need_kwargs()).origin == "multi"
    assert ProgramMetadata(**_program_kwargs()).agent_mode == "multi"

def test_single_agent_is_a_valid_validator_label():
    assert PLO(**_plo_kwargs(smart_validated_by="single_agent")).smart_validated_by == "single_agent"
```
`_need_kwargs` / `_program_kwargs` / `_plo_kwargs`: minimal valid dicts, built from the fixtures already used in `tests/unit/test_models*.py`.

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_single_models.py -q` — expect FAIL (unknown field / validation).
- [ ] **Step 3: Implement** the model changes above. The ratio properties stay as they are (`count / total if total else 1.0`); `is_in_scope` already returns True for a member count of 0, so no scope code changes.
- [ ] **Step 4: ORM + migration.** `upgrade()` adds both columns with `server_default="multi"`; `downgrade()` drops them. Add `agent_mode=row.agent_mode` where `list_all` builds `ProgramSummary`.
- [ ] **Step 5: Run** the new tests and `uv run pytest tests/unit -q -k "models or program or need"` — PASS. `uv run mypy src/`.
- [ ] **Step 6: Commit** `feat(single): agent_mode on programs, origin on Needs`

---

### Task 2: Program routes carry the mode

**Files:**
- Modify: `src/curriculum_agent/api/routes/programs.py` (`ProgramCopyRequest` :89, `copy_program_route` :104, `update_program` :189-244), `src/curriculum_agent/data/program_copy.py` (`build_copy` :156, `copy_program` :287)
- Test: `tests/unit/test_single_program_routes.py`

**Interfaces — Produces:**
- `ProgramCopyRequest.agent_mode: AgentMode | None = None`
- `build_copy(src, new_id, *, now, new_uuid, mode="full", agent_mode: AgentMode | None = None)`, `copy_program(source_id, new_id, *, now=None, mode=..., agent_mode: AgentMode | None = None)` — `None` keeps the source's mode.

- [ ] **Step 1: Failing tests** (TestClient + `AsyncMock` repositories, the pattern of `tests/unit/test_needs_jobs.py`):

```python
def test_put_keeps_the_stored_mode(client, single_program):
    r = client.put(f"/programs/{single_program.program_id}", json=_edit_payload())  # payload has no agent_mode
    assert r.status_code == 200 and r.json()["agent_mode"] == "single"

def test_full_copy_that_changes_mode_is_refused(client, multi_program):
    r = client.post(f"/programs/{multi_program.program_id}/copy", json={"mode": "full", "agent_mode": "single"})
    assert r.status_code == 422

def test_evidence_only_copy_can_change_mode():
    copy = build_copy(_source(agent_mode="multi"), "p-run-1", now=NOW, new_uuid=_uuid, mode="evidence_only", agent_mode="single")
    assert copy.program["agent_mode"] == "single"

def test_copy_without_agent_mode_keeps_the_source_mode(): ...
```

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** `update_program` carries `agent_mode` over from the stored row the way it carries `copied_from`. The copy route returns 422 with `"สำเนาแบบเต็มเปลี่ยนโหมดไม่ได้ ให้ใช้สำเนาเฉพาะหลักฐาน"` when `mode == "full"` and `agent_mode` differs from the source.
- [ ] **Step 4: Run** — PASS. **Step 5: Commit** `feat(single): program create/copy/edit carry agent_mode`

---

### Task 3: Slot, settings, prompt-token sink

**Files:**
- Modify: `src/curriculum_agent/config.py` (`SLOTS` :122, settings near :293 and :324), `src/curriculum_agent/llm.py` (`_complete` :276, `_on_response` :207), `.env.example`
- Test: `tests/unit/test_single_slot.py` (and `tests/unit/test_llm_slots.py` must still pass)

**Interfaces — Produces:**
- `SlotSpec("single_agent", "single_agent_provider", "single_agent_model")`, appended last in `SLOTS`; fields `single_agent_provider: Literal["ollama","openrouter","opentyphoon"] | None = "opentyphoon"`, `single_agent_model: str = ""` (same defaults as `plo_synthesis`).
- The five settings in Global Constraints, each `Field(default=…, ge=1)` (`gt=0, le=1` for the ratio).
- `async def complete_single_agent(response_model: type[T], messages: list[dict[str, Any]], **kwargs: Any) -> T`
- `_complete(..., usage_sink: list[int] | None = None)`: when given, the prompt-token count of the attempt that produced the returned value is appended. `complete_single_agent` passes `usage_sink` through. Other wrappers are untouched.

- [ ] **Step 1: Failing tests**

```python
def test_single_agent_slot_follows_the_pipeline_pair(monkeypatch):
    s = _settings(PIPELINE_PROVIDER="openrouter", PIPELINE_MODEL="z-ai/glm-5.3-flash")
    assert (s.single_agent_provider, s.single_agent_model) == ("openrouter", "z-ai/glm-5.3-flash")

async def test_usage_sink_receives_prompt_tokens(fake_instructor_client):  # reuse the fake client fixture of test_llm_usage*.py
    sink: list[int] = []
    await llm.complete_single_agent(_Model, [{"role": "user", "content": "x"}], usage_sink=sink)
    assert sink == [fake_instructor_client.prompt_tokens]

def test_usage_is_recorded_under_the_single_agent_slot(usage_rows): ...
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** new tests + `tests/unit/test_llm_slots.py` — PASS. Add commented `# SINGLE_AGENT_PROVIDER=` / `# SINGLE_AGENT_MODEL=` to `.env.example`. **Step 5: Commit** `feat(single): single_agent slot, budgets, prompt-token sink`

---

### Task 4: Need statistics from cited evidence (pure)

**Files:**
- Create: `src/curriculum_agent/stages/single_need_stats.py`
- Test: `tests/unit/test_single_need_stats.py`

**Interfaces:**
- Consumes: `demand.build_scoring_corpus`, `demand.compute_demand_score`, `demand.is_optional_group`, `stakeholder_needs.classify_evidence_type`.
- Produces:

```python
class EvidenceNeedStats(BaseModel):
    source_stakeholder_types: list[StakeholderType]   # distinct, enum order
    stakeholder_coverage: dict[StakeholderType, int]  # cited items per type
    freq: int                                         # number of cited items
    demand_score: float
    classification: Literal["requirement", "need", "want"]
    classification_coverage: dict[str, int]           # {classification: 1}
    is_optional: bool

def scoring_corpus_for(cited_ids: Iterable[str], type_by_evidence: Mapping[str, StakeholderType]) -> dict[str, str]
def derive_need_stats(evidence_ids: Sequence[str], type_by_evidence: Mapping[str, StakeholderType], corpus: Mapping[str, str]) -> EvidenceNeedStats
```
`corpus` = `scoring_corpus_for(<every evidence id cited by any Need of the run>, …)`.

- [ ] **Step 1: Failing tests**

```python
def test_requirement_when_any_cited_item_is_council_or_institutional():
    s = derive_need_stats(["e1", "e2"], {"e1": "professional_council", "e2": "employer"}, CORPUS)
    assert s.classification == "requirement" and s.is_optional is False

def test_two_general_items_is_need_one_is_want_and_optional():
    assert derive_need_stats(["e2", "e3"], TYPES, CORPUS).classification == "need"
    one = derive_need_stats(["e2"], TYPES, CORPUS)
    assert (one.classification, one.is_optional, one.freq) == ("want", True, 1)

def test_demand_score_equals_compute_demand_score():
    assert derive_need_stats(ids, TYPES, CORPUS).demand_score == compute_demand_score(list(ids), dict(CORPUS))

def test_duplicate_ids_count_once(): ...
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** (dedupe ids preserving order first). **Step 4: Run** — PASS. **Step 5: Commit** `feat(single): derive Need statistics from cited evidence`

---

### Task 5: The prompt

**Files:**
- Create: `src/curriculum_agent/prompts/single_agent.py`
- Modify: `scripts/dump_prompts.py` (import, `_build()`, `TEMPLATE` section + summary-table row), regenerate `docs/prompt-inventory.md`
- Test: `tests/unit/test_single_agent_prompt.py`

**Interfaces — Produces:**

```python
def build_single_agent_system() -> str
def build_needs_task(*, program_context: str, scope_th: str | None, evidence_index: Sequence[EvidenceIndexRow]) -> str
def build_plos_task(*, program_context: str, scope_th: str | None, core_needs: Sequence[NeedBrief], optional_needs: Sequence[NeedBrief], unused_needs: Sequence[NeedBrief], note_th: str | None) -> str
def build_one_plo_task(*, program_context: str, scope_th: str | None, needs: Sequence[NeedBrief], current_statement_th: str | None, note_th: str | None) -> str
def build_merge_need_task(*, program_context: str, needs: Sequence[NeedBrief], reason_th: str | None) -> str
def build_observation(tool: str, payload_json: str) -> str
def build_refusal(reason_th: str) -> str
def build_dropped_marker(evidence_id: str, note_th: str | None) -> str
def build_turns_left_note(turns_left: int) -> str
def build_closing_instruction() -> str
```
`EvidenceIndexRow(evidence_id, stakeholder_type, source_name, classification, total_chars, parts)` and `NeedBrief(need_id, statement_th, ksec_categories, bloom_level, demand_score, stakeholder_types, evidence_ids)` are small frozen dataclasses defined in this file. `program_context` comes from the existing `prompts/program_context.py` builder.

**What the system prompt must contain** (Thai; the builder writes the wording, reading `docs/prompt-inventory.md` and skill `references/obe-principles.md` for the rules multi's prompts state): the role (one agent doing the whole job, checking its own work); KSEC definitions including the S vs E/C "judge by the core of the phrase" rule; Bloom levels and the instruction to confirm a verb with `bloom_lookup`; the forbidden words รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก; one declared verb, statement opens with it; the seven soft SMART criteria by name (`S_object`, `M_assessable`, `A_level`, `A_actor`, `A_scope`, `R_needs`, `T_horizon`); Need-writing rules (a capability the graduate has, inside the program's field, grounded in the cited evidence, one Need per distinct capability, aim for 6-10 core); every tool and every output action with when to use it; the rule "after reading an evidence item, hand in a `Note` before reading the next"; "read every evidence item before finishing the needs task"; cite only ids you were shown. It must **not** contain `vision_th` or any stage name of the multi pipeline.

- [ ] **Step 1: Failing tests**

```python
def test_system_prompt_takes_no_arguments_and_is_stable():
    assert build_single_agent_system() == build_single_agent_system()
    assert inspect.signature(build_single_agent_system).parameters == {}

@pytest.mark.parametrize("token", ["get_evidence", "get_need", "need_detail", "list_sibling_plos", "check_hard",
                                   "bloom_lookup", "check_verbs", "save_need", "drop_need", "save_plo", "drop_plo",
                                   "note", "finish", *FORBIDDEN_WORDS, *SOFT_CODES])
def test_system_prompt_names_every_tool_action_and_rule(token):
    assert token in build_single_agent_system()

def test_needs_task_lists_every_evidence_item_without_its_text():
    msg = build_needs_task(program_context="ctx", scope_th=None, evidence_index=[ROW_A, ROW_B])
    assert ROW_A.evidence_id in msg and ROW_B.evidence_id in msg and "RAW TEXT" not in msg

def test_plos_task_names_core_optional_and_unused_needs(): ...
```
`FORBIDDEN_WORDS` / `SOFT_CODES` imported from `smart_vocabulary.py`.

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4:** register in `scripts/dump_prompts.py` (system prompt + one sample of each task opener), run `uv run python scripts/dump_prompts.py`, then `uv run python scripts/dump_prompts.py --check` — exit 0. **Step 5: Run tests** — PASS. **Step 6: Commit** `feat(single): the single-agent prompt`

---

### Task 6: Tools and the loop

**Files:**
- Create: `src/curriculum_agent/stages/single_agent_tools.py`, `src/curriculum_agent/stages/single_agent_loop.py`
- Test: `tests/unit/test_single_agent_tools.py`, `tests/unit/test_single_agent_loop.py`

**Interfaces — Produces (tools):**

```python
ToolName = Literal["get_evidence", "get_need", "need_detail", "list_sibling_plos", "check_hard", "bloom_lookup", "check_verbs"]

@dataclass
class SingleToolContext:
    evidence_by_id: dict[str, StakeholderEvidence]
    needs_by_id: dict[str, NeedBrief]      # drafts (needs half) or approved input (PLO half); handler keeps it current
    plos: list[SiblingSummary]             # saved so far; handler keeps it current
    part_chars: int
    read_parts: set[tuple[str, int]] = field(default_factory=set)

def evidence_parts(text: str, part_chars: int) -> list[str]           # word-boundary split, [] never returned for non-empty text
def run_single_tool(ctx: SingleToolContext, call: CallTool) -> ToolResult   # ToolResult(ok: bool, payload_json: str, error_th: str | None, evidence_id: str | None)
```
`get_evidence(evidence_id, part=1)` returns `{evidence_id, stakeholder_type, source_name, part, parts, text}`; no cited-only rule and no read cap. `check_hard`, `bloom_lookup`, `check_verbs` delegate to the existing implementations in `smart_agent_tools.py` / `plo_review_agent.py` (import and call; do not copy). `get_need` and `need_detail` share one implementation.

**Interfaces — Produces (loop):**

```python
class CallTool(BaseModel):   kind: Literal["call_tool"]; tool: ToolName; evidence_id: str | None; part: int = 1; need_id: str | None; statement_th: str | None; action_verb_th: str | None; verb_th: str | None
class Note(BaseModel):       kind: Literal["note"]; evidence_id: str; points_th: str = Field(min_length=1, max_length=1200)
class SaveNeed(BaseModel):   kind: Literal["save_need"]; need_id: str | None = None; statement_th: str; rationale_th: str = ""; ksec_categories: list[KSECCategory] = Field(min_length=1); bloom_level: BloomLevel; source_evidence_ids: list[str] = Field(min_length=1)
class DropNeed(BaseModel):   kind: Literal["drop_need"]; need_id: str
class SoftVerdict(BaseModel): specific_object_ok: bool; measurable_ok: bool; achievable_ok: bool; actor_ok: bool; scope_ok: bool; relevant_needs_ok: bool; time_bound_ok: bool; findings_th: dict[str, str] = {}   # keys: soft codes
class SavePLO(BaseModel):    kind: Literal["save_plo"]; plo_ref: str | None = None; statement_th: str; statement_en: str | None = None; action_verb_th: str; bloom_level: BloomLevel; source_need_ids: list[str] = Field(min_length=1, max_length=5); rationale_th: str; soft: SoftVerdict
class DropPLO(BaseModel):    kind: Literal["drop_plo"]; plo_ref: str
class Finish(BaseModel):     kind: Literal["finish"]; summary_th: str = ""
class SingleStep(BaseModel): reasoning_th: str; action: Annotated[CallTool | Note | SaveNeed | DropNeed | SavePLO | DropPLO | Finish, Field(discriminator="kind")]
class ClosingStep(BaseModel): reasoning_th: str; action: Finish

OutputAction = Note | SaveNeed | DropNeed | SavePLO | DropPLO
StopReason = Literal["finished", "turn_cap", "timeout", "context_full"]

class TaskHandler(Protocol):
    tool_ctx: SingleToolContext
    def opening_message(self) -> str: ...
    def handle(self, action: OutputAction) -> str: ...        # returns the observation text (acceptance or build_refusal(...))
    def note_for(self, evidence_id: str) -> str | None: ...

class LoopOutcome(BaseModel): stop_reason: StopReason; turns: int; dropped_evidence_count: int; opened_evidence_ids: list[str]

class History:   # messages + bookkeeping of which user messages are raw evidence text
    def messages(self) -> list[dict[str, str]]
    def add_assistant(self, step_json: str) -> None
    def add_observation(self, text: str, *, evidence_id: str | None = None) -> None
    def drop_oldest_evidence(self, marker_for: Callable[[str], str]) -> int | None   # chars freed, None when nothing left
    @property
    def dropped_evidence_ids(self) -> set[str]

async def run_single_agent(handler: TaskHandler) -> LoopOutcome
```

**Loop rules** (the body follows `smart_agent._run_judge`, :820-970):
- messages start `[system = build_single_agent_system(), user = handler.opening_message()]`; each turn appends the assistant's `step.model_dump_json()` then a user observation.
- call `complete_single_agent(SingleStep, history.messages(), temperature=0, usage_sink=sink)`.
- `CallTool` → `run_single_tool`; an identical `(tool, args)` call is refused unless it is `get_evidence` on an item in `history.dropped_evidence_ids`.
- `OutputAction` → `handler.handle(action)`.
- `Finish` → stop `finished`.
- malformed step (Instructor/validation error): tolerated `_MAX_MALFORMED = 2` times in a row with a refusal observation, then the closing call.
- after each call, with `p = sink[-1]`: while `p > ratio * window` and `drop_oldest_evidence(...)` frees `c` chars, set `p -= p * c / total_chars_before`. If nothing is left to drop and the real `p > 0.95 * window` → stop `context_full`.
- turn `single_agent_max_turns` reached → one closing call with `ClosingStep` → stop `turn_cap`. The whole loop is under `asyncio.timeout(single_agent_timeout_seconds)` → stop `timeout`. An exception from the LLM other than a malformed step propagates.
- `build_turns_left_note` is appended to the observation when 5 or fewer turns remain.

- [ ] **Step 1: Failing tool tests**

```python
def test_get_evidence_pages_through_the_whole_text():
    ctx = _ctx(text="ก" * 250 + " " + "ข" * 250, part_chars=300)
    first = run_single_tool(ctx, _call("get_evidence", evidence_id="e1", part=1))
    second = run_single_tool(ctx, _call("get_evidence", evidence_id="e1", part=2))
    assert json.loads(first.payload_json)["parts"] == 2 and "ข" in json.loads(second.payload_json)["text"]

def test_get_evidence_unknown_id_is_an_error_not_an_exception():
    r = run_single_tool(_ctx(), _call("get_evidence", evidence_id="nope"))
    assert r.ok is False and r.error_th

def test_get_need_and_need_detail_agree(): ...
def test_check_hard_matches_smart_rules(): ...
```

- [ ] **Step 2: Failing loop tests** — fake LLM in the style of `FakeToolModel` (`tests/unit/test_smart_agent.py:141-193`), installed with `monkeypatch.setattr(loop, "complete_single_agent", fake)`; the fake appends a scripted token count to `kwargs["usage_sink"]`.

```python
async def test_reads_notes_and_finishes(fake, handler):
    fake.script(_tool("get_evidence", evidence_id="e1"), _note("e1", "ต้องการนักแปล"), _finish())
    out = await run_single_agent(handler)
    assert (out.stop_reason, out.turns, out.opened_evidence_ids) == ("finished", 3, ["e1"])
    assert handler.handled == [Note(kind="note", evidence_id="e1", points_th="ต้องการนักแปล")]

async def test_turn_cap_makes_a_closing_call(fake, handler, monkeypatch):
    monkeypatch.setattr(loop.settings, "single_agent_max_turns", 2)
    fake.script(_tool("bloom_lookup", verb_th="วิเคราะห์"), _tool("bloom_lookup", verb_th="ประเมิน")); fake.closing(_finish())
    assert (await run_single_agent(handler)).stop_reason == "turn_cap"

async def test_timeout_is_a_stop_reason_not_an_exception(...): ...            # fake sleeps; timeout patched to 0.01
async def test_repeated_identical_tool_call_is_refused(...): ...
async def test_two_malformed_steps_then_closing(...): ...

async def test_oldest_evidence_text_is_dropped_first_and_replaced_by_the_note(fake, handler, monkeypatch):
    monkeypatch.setattr(loop.settings, "single_agent_context_window_tokens", 1000)
    fake.script(_tool("get_evidence", evidence_id="e1"), _note("e1", "โน้ต e1"),
                _tool("get_evidence", evidence_id="e2"), _finish(), tokens=[100, 200, 900, 300])
    out = await run_single_agent(handler)
    sent = fake.messages_seen[-1]
    assert out.dropped_evidence_count == 1
    assert not any(E1_TEXT in m["content"] for m in sent) and any("โน้ต e1" in m["content"] for m in sent)
    assert any(E2_TEXT in m["content"] for m in sent)

async def test_a_dropped_item_may_be_read_again(...): ...
async def test_small_corpus_drops_nothing(...): ...                          # tokens well under 0.7 * window
async def test_context_full_when_nothing_is_left_to_drop(...): ...           # stop_reason == "context_full"
```

- [ ] **Step 3: Run both files** — FAIL. **Step 4: Implement tools, then loop.** **Step 5: Run** — PASS; `uv run mypy src/`. **Step 6: Commit** `feat(single): tool bag and the single-agent loop`

---

### Task 7: Needs half

**Files:**
- Create: `src/curriculum_agent/stages/single_needs.py`
- Modify: `src/curriculum_agent/data/repositories.py` (add `NeedRepository.replace_by_program`)
- Test: `tests/unit/test_single_needs.py`

**Interfaces:**
- Consumes: Task 4 `derive_need_stats`, `scoring_corpus_for`; Task 5 builders; Task 6 loop, actions.
- Produces:

```python
class SingleNeedsResult(BaseModel):
    needs: list[Need]
    stop_reason: StopReason
    turns: int
    dropped_evidence_count: int
    unread_evidence_ids: list[str]      # never opened with get_evidence
    uncited_evidence_ids: list[str]     # cited by no stored Need
    unnoted_evidence_ids: list[str]     # opened, no Note handed in

class NeedsHandler:                      # implements TaskHandler
    def __init__(self, program: ProgramMetadata, evidence: list[StakeholderEvidence]) -> None
    def drafts(self) -> list[SaveNeed]   # current drafts, each with its assigned need_id

def build_single_needs(program_id: str, drafts: Sequence[SaveNeed], evidence: Sequence[StakeholderEvidence]) -> list[Need]   # pure
async def run_single_needs(program_id: str) -> SingleNeedsResult
async def NeedRepository.replace_by_program(self, program_id: str, needs: list[Need]) -> None   # delete + insert in ONE session/commit
```

**Rules:**
- `handle(SaveNeed)`: every `source_evidence_ids` entry must be in the program's evidence, else `build_refusal("ไม่พบหลักฐานรหัส … ในหลักสูตรนี้")` and nothing changes. `need_id=None` → mint `str(uuid.uuid4())`; a known `need_id` replaces that draft; an unknown one is refused. The acceptance observation states the id.
- `handle(DropNeed)`: unknown id refused. `handle(Note)`: stored per `evidence_id` (last wins); unknown evidence id refused. `handle(SavePLO | DropPLO)`: refused with `"ขั้นนี้ยังไม่ใช่ขั้นเขียน PLO"`.
- `build_single_needs`: one `Need` per draft with `origin="single"`, `member_skill_ids=[]`, `top_skill_ids=[]`, both skill counts 0, statistics from `derive_need_stats` with the corpus built from the union of all drafts' cited ids.
- `run_single_needs`: load program + evidence; no evidence → `HTTPException(422)` like the multi route; run the loop; **no drafts → raise `HTTPException(502, "ตัวแทนไม่ได้เขียน Need เลย (<stop_reason>)")` and store nothing**; otherwise `replace_by_program` and return. Log (loguru, warning) when fewer than `MIN_NEEDS` (6) non-optional Needs.

- [ ] **Step 1: Failing tests**

```python
def test_save_with_unknown_evidence_is_refused_and_keeps_no_draft():
    h = NeedsHandler(PROGRAM, [E1, E2])
    obs = h.handle(_save_need(source_evidence_ids=["e1", "ghost"]))
    assert "ghost" in obs and h.drafts() == []

def test_save_again_with_the_same_id_replaces(): ...
def test_save_plo_in_the_needs_half_is_refused(): ...

def test_built_needs_are_single_origin_with_code_derived_statistics():
    needs = build_single_needs("p", [_draft(ids=["council", "emp1"]), _draft(ids=["emp2"])], EVIDENCE)
    a, b = needs
    assert a.origin == "single" and a.member_skill_ids == [] and a.freq == 2
    assert a.is_optional is False and a.classification_coverage == {"requirement": 1}
    assert b.is_optional is True and b.classification_coverage == {"want": 1}
    assert a.demand_score == compute_demand_score(["council", "emp1"], CORPUS)

async def test_run_stores_and_reports_unread_and_uncited(fake_loop, repos):
    # fake_loop: monkeypatch single_needs.run_single_agent to feed scripted actions into the handler
    res = await run_single_needs("p")
    assert res.stop_reason == "finished" and res.unread_evidence_ids == ["e3"] and "e3" in res.uncited_evidence_ids
    repos.need.replace_by_program.assert_awaited_once()

async def test_turn_cap_with_drafts_still_stores(...): ...           # stop_reason == "turn_cap", stored
async def test_no_drafts_fails_and_touches_nothing(fake_loop, repos):
    with pytest.raises(HTTPException): await run_single_needs("p")
    repos.need.replace_by_program.assert_not_awaited()
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS. **Step 5: Commit** `feat(single): needs half — evidence to Needs`

---

### Task 8: PLO half

**Files:**
- Create: `src/curriculum_agent/stages/single_plos.py`
- Test: `tests/unit/test_single_plos.py`

**Interfaces:**
- Consumes: `plo_synthesis.synthesis_order`, `plo_synthesis._select_slots` (rename-free reuse; if private access is awkward, expose it as `select_slots` in `plo_synthesis` without changing behaviour), `format_plo_id`, `is_unwritten_need`, `smart_rules.hard_failures`, `smart_agent.hard_findings_for`, `need_grouping.MAX_CORE_PLOS`, `MIN_NEEDS`.
- Produces:

```python
class SinglePlosResult(BaseModel):
    plos: list[PLO]
    stop_reason: StopReason
    turns: int
    uncited_core_need_ids: list[str]

class PlosHandler:                       # implements TaskHandler
    def __init__(self, program: ProgramMetadata, core: list[Need], optional: list[Need], unused: list[Need], evidence: list[StakeholderEvidence], note_th: str | None) -> None
    def drafts(self) -> list[SavePLO]    # each with its plo_ref

def select_single_input(needs: Sequence[Need]) -> tuple[list[Need], list[Need], list[Need]]   # (core ≤ 10, optional, lost the cut); active, not merged-away, written
def build_single_plo(program_id: str, plo_id: str, draft: SavePLO, needs_by_id: Mapping[str, Need], *, is_optional: bool, designer_edited_at: datetime | None = None, version: int = 1) -> PLO   # pure
async def run_single_plos(program_id: str, *, note_th: str | None = None) -> SinglePlosResult
```

**Rules:**
- `handle(SavePLO)`: every `source_need_ids` entry must be in core ∪ optional, else refusal. A Need already cited by a *different* draft → refusal `"Need … อยู่เบื้องหลัง PLO อื่นแล้ว"`. Accepted: store under `plo_ref` (minted `d1`, `d2`, … when None), run `hard_failures(statement_th, action_verb_th, source_need_ids, known_need_ids)` and put the failures with their `CRITERION_FIX_HINTS_TH` in the observation (`"ผ่าน hard check"` when none). Mixed core+optional citations make the PLO core.
- `handle(SaveNeed | DropNeed)`: refused. `handle(Note)`: accepted.
- `build_single_plo`: `source_evidence_ids` = union of the cited Needs' evidence; `failures = hard_failures(...)`; `smart_escalated = bool(failures)`; findings = `hard_findings_for(failures, …)` + one soft `SmartFinding` per False soft verdict (`note_th` from `findings_th[code]`, falling back to `FINDING_LABEL_TH[code]`); `soft_flags` = those soft codes; `SMARTCheck` fields mapped exactly as `plo_synthesis.validate_and_build` maps `Finish` (:345-363) and additionally False where a hard criterion of that letter failed; `smart_validated_by="single_agent"`; `smart_retry_count=0`.
- `run_single_plos`: no active Needs → 422 as the multi route. Number core drafts `PLO1…` and optional `OPT1…` in `synthesis_order` of their highest-demand cited Need. No drafts → `HTTPException(502)` and nothing stored; otherwise `PLORepository.delete_by_program` + `bulk_insert` exactly as `plo_synthesis` stores (:698-705). Warn (loguru) when core count is outside 6-10.

- [ ] **Step 1: Failing tests**

```python
def test_select_takes_ten_highest_core_and_names_the_rest():
    core, optional, unused = select_single_input([_need(score=i / 20) for i in range(12)] + [_need(optional=True)])
    assert len(core) == 10 and len(unused) == 2 and len(optional) == 1
    assert min(n.demand_score for n in core) > max(n.demand_score for n in unused)

def test_need_behind_two_plos_is_refused():
    h = _handler(); h.handle(_save_plo(source_need_ids=["n1"]))
    assert "n1" in h.handle(_save_plo(source_need_ids=["n1", "n2"])) and len(h.drafts()) == 1

def test_need_outside_the_input_is_refused(): ...
def test_save_observation_reports_hard_failures():
    assert "S_VERB" in _handler().handle(_save_plo(statement_th="มีความสามารถวิเคราะห์ข้อมูล", action_verb_th="วิเคราะห์"))

def test_hard_failure_escalates_whatever_the_agent_claimed():
    plo = build_single_plo("p", "PLO1", _save_plo(statement_th="เข้าใจหลักการแปล", action_verb_th="เข้าใจ", soft=_all_ok()), NEEDS, is_optional=False)
    assert plo.smart_escalated is True and plo.smart_validated_by == "single_agent"

def test_soft_verdicts_become_flags_and_findings():
    plo = build_single_plo("p", "PLO1", _save_plo(soft=_all_ok(actor_ok=False, findings_th={"A_actor": "ผู้กระทำคือสถาบัน"})), NEEDS, is_optional=False)
    assert plo.soft_flags == ["A_actor"] and plo.smart_check.achievable is False and plo.smart_escalated is False

def test_evidence_trail_is_the_union_of_the_cited_needs(): ...
async def test_run_numbers_core_and_optional_separately_and_stores(...): ...
async def test_no_drafts_fails_and_touches_nothing(...): ...
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS; also `uv run pytest tests/unit -q -k plo_synthesis` (unchanged behaviour). **Step 5: Commit** `feat(single): PLO half — approved Needs to PLOs`

---

### Task 9: Run routes, jobs, sessions

**Files:**
- Modify: `src/curriculum_agent/api/routes/needs.py` (`POST /needs/run` :404, `POST /needs/combine/run`), `api/routes/plos.py` (`POST /plos/run` :251, `POST /plos/report/run`), `api/routes/sessions.py` (`create_session` after :81, approve :138), `api/jobs.py` (`JOB_KIND_LABEL_TH` :55)
- Test: `tests/unit/test_single_run_routes.py`

**Rules:**
- `/needs/run` on a single program: `start_job_or_409(program_id, "single_needs", {}, work)` where `work` awaits `run_single_needs(program_id)`; **no `on_success`**. `/needs/combine/run` on a single program does the same (so the Need page's re-run button works whichever path it calls).
- `/plos/run` on a single program: `start_job_or_409(program_id, "single_plos", {"note_th": …}, work)` with `run_single_plos`; **no review chained**. `run_validation` in the body is ignored.
- `/plos/report/run` on a single program must work with no stored review. Read the route first; if it requires a current review, bypass that requirement only when `agent_mode == "single"`.
- `create_session` and session approve: single program → `409` `"หลักสูตรโหมด single ใช้การรันทีละขั้นจากหน้าเว็บ ไม่ใช้ session"`.
- Labels: `"single_needs": "วิเคราะห์ Need (single agent)"`, `"single_plos": "สังเคราะห์ PLO (single agent)"`.

- [ ] **Step 1: Failing tests** (fixtures of `tests/unit/test_needs_jobs.py`: `client`, `spawned`, `jobs_store`, patched repositories; patch `curriculum_agent.stages.single_needs.run_single_needs` / `single_plos.run_single_plos` with `AsyncMock`)

```python
def test_needs_run_on_a_single_program_starts_single_needs_and_chains_nothing(client, spawned, single_program, stages):
    r = client.post(f"/programs/{PID}/needs/run")
    assert r.status_code == 202 and r.json()["kind"] == "single_needs"
    spawned.drain()
    stages.single_needs.assert_awaited_once(); stages.skill_extraction.assert_not_awaited(); stages.need_combination.assert_not_awaited()

def test_needs_run_on_a_multi_program_is_unchanged(client, spawned, multi_program, stages):
    assert client.post(f"/programs/{PID}/needs/run").json()["kind"] == "skill_extraction"
    spawned.drain(); stages.single_needs.assert_not_awaited()

def test_plos_run_on_a_single_program_starts_single_plos_without_a_review(client, spawned, single_program, stages, review_chain_calls):
    assert client.post(f"/programs/{PID}/plos/run", json={}).json()["kind"] == "single_plos"
    spawned.drain(); assert review_chain_calls == []

def test_rerun_of_the_needs_half_leaves_plos_alone(...): ...            # PLORepository.delete_by_program not called
def test_report_runs_for_a_single_program_with_no_review(...): ...
def test_session_for_a_single_program_is_refused(client, single_program):
    assert client.post("/sessions/", json={"program_id": PID}).status_code == 409
```
Use the status code and response shape the existing multi tests assert for the same routes (202 above is a placeholder for whatever they return).

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** the new file plus `tests/unit/test_needs_jobs.py` and the plos job tests — PASS. **Step 5: Commit** `feat(single): run routes dispatch by agent_mode`

---

### Task 10: Designer actions on a single program

**Files:**
- Modify: `src/curriculum_agent/stages/single_needs.py` (merge), `stages/single_plos.py` (one-PLO), `api/routes/needs.py` (`merge_needs` :172-265), `api/routes/plos.py` (`revalidate` :615, `from-needs` :451), `stages/plo_redraft.py` (`redraft_from_needs` :141 — add an injectable drafter)
- Test: `tests/unit/test_single_designer_actions.py`

**Interfaces — Produces:**

```python
# single_needs.py
async def merge_single_needs(program: ProgramMetadata, originals: Sequence[Need], all_active: Sequence[Need], evidence: Sequence[StakeholderEvidence], *, reason_th: str | None) -> Need
# single_plos.py
async def draft_single_plo(program: ProgramMetadata, needs: Sequence[Need], evidence: Sequence[StakeholderEvidence], *, plo_id: str, known_need_ids: set[str], siblings: Sequence[SiblingSummary], note_th: str | None, current: PLO | None = None) -> PLO
```

**Rules:**
- `merge_single_needs`: runs the loop with a `MergeNeedHandler` whose opening message is `build_merge_need_task(...)`; it accepts exactly one `SaveNeed` (later saves replace it) and refuses every other output action. The result: statement, rationale, Bloom level from the agent; `ksec_categories` = sorted union of the originals' tags (the agent's tags are ignored); `source_evidence_ids` = union of the originals' evidence (the agent's list is ignored); statistics from `derive_need_stats` with the corpus over `all_active`; `origin="single"`, `merged_from` = original ids, `merged_by="designer"`, `merge_reason_th=reason_th or ""`. No saved Need → `HTTPException(502)`.
- `merge_needs` route on a single program: keep every existing refusal up to and including the `MIN_CORE_AFTER_MERGE` floor, **skip the skills check** (:244) and the skill corpus, call `merge_single_needs`, then `_repo.write_merge` as today. Split, exclude, restore need no change.
- `draft_single_plo`: loop with a `OnePloHandler` (opening `build_one_plo_task`, `current_statement_th=current.statement_th` when revalidating); one `SavePLO`, whose `source_need_ids` are overridden with the given Needs; result built with `build_single_plo`. For `current` set: keep `plo_id`, `is_optional`, `designer_edited_at`; **when `current.designer_edited_at` is set, keep the designer's `statement_th`, `statement_en`, `action_verb_th`, `bloom_level` and take only the soft verdicts from the agent** (a hand-edited PLO is judged, never rewritten).
- `revalidate` on a single program: job `plo_revalidate` whose work calls `draft_single_plo(..., current=match)` then `update_if_version` as today.
- `redraft_from_needs(..., drafter: Callable[..., Awaitable[PLO | None]] | None = None)`: `None` keeps `synthesize_from_needs`; the `from-needs` route passes a closure over `draft_single_plo` for a single program. All bounds, supersede and trail logic in `plo_redraft` stay shared.

- [ ] **Step 1: Failing tests**

```python
async def test_single_merge_uses_evidence_union_and_ignores_the_agents_trail(fake_loop):
    fake_loop.actions(_save_need(source_evidence_ids=["e1"], ksec_categories=["K"]))
    merged = await merge_single_needs(PROGRAM, [N1, N2], ACTIVE, EVIDENCE, reason_th="ซ้ำกัน")
    assert set(merged.source_evidence_ids) == set(N1.source_evidence_ids) | set(N2.source_evidence_ids)
    assert merged.ksec_categories == sorted({*N1.ksec_categories, *N2.ksec_categories}, key=KSEC_ORDER.index)
    assert merged.merged_from == [N1.need_id, N2.need_id] and merged.origin == "single" and merged.merged_by == "designer"

def test_merge_route_on_a_single_program_never_touches_skills_or_the_need_combination_slot(client, single_program, monkeypatch):
    forbidden = AsyncMock(side_effect=AssertionError("multi slot called")); monkeypatch.setattr("curriculum_agent.stages.need_merge.complete_need_combination", forbidden)
    assert client.post(f"/programs/{PID}/needs/merge", json={"need_ids": [A, B]}).status_code == 200

async def test_revalidating_a_hand_edited_plo_keeps_the_designers_statement(fake_loop):
    fake_loop.actions(_save_plo(statement_th="ถ้อยคำใหม่ของตัวแทน", soft=_all_ok(measurable_ok=False)))
    plo = await draft_single_plo(PROGRAM, [N1], EVIDENCE, plo_id="PLO1", known_need_ids={"n1"}, siblings=[], note_th=None, current=EDITED)
    assert plo.statement_th == EDITED.statement_th and plo.soft_flags == ["M_assessable"] and plo.smart_validated_by == "single_agent"

def test_from_needs_on_a_single_program_uses_the_single_drafter_and_keeps_the_bounds(...): ...   # validate_and_build / complete_plo_synthesis patched to raise
def test_from_needs_on_a_multi_program_is_unchanged(...): ...
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** new file + `uv run pytest tests/unit -q -k "merge or redraft or revalidate"` — PASS. **Step 5: Commit** `feat(single): merge, redraft and revalidate through the single agent`

---

### Task 11: Frontend

**Files:**
- Modify: `frontend/src/pages/Intake.tsx`, `pages/Programs.tsx`, `components/StageLayout.tsx`, `constants/stages.ts`, `pages/NeedAnalysis.tsx`, `pages/components/NeedCard.tsx`, `pages/PloSynthesis.tsx`, `types/plo.ts`, `constants/smart.ts`, `api/jobs.ts`, `mock/handlers.ts`, `mock/scenarios.ts`

There is no frontend test runner. Verification is `npm run build` (typecheck) and `npm run lint`, both clean, plus a manual pass in mock mode (`npm run dev:mock`) through one single program.

**Interfaces — Consumes:** `agent_mode` on `GET /programs/` rows and on the program GET; job kinds `single_needs`, `single_plos`; `smart_validated_by: "single_agent"`; `Need.origin`.

- [ ] **Step 1: Types and constants.** `export type AgentMode = 'multi' | 'single'` in `constants/stages.ts`; `agent_mode` on `ProgramRow`, `ProgramSummary`, Intake's `FormState` (default `'multi'`); `origin?: AgentMode` on `NeedRow`; `'single_agent'` in `ValidatedBy` with `VALIDATED_BY_TH.single_agent = 'ตัวแทนตรวจเอง (ไม่มีการโหวต)'`; the two job kinds in `JobKind` and `JOB_PAGE` (`single_needs → need-analysis page`, `single_plos → plo-synthesis page`).
- [ ] **Step 2: Rail.** `export function stagesFor(mode: AgentMode): StageDef[]` — `multi` returns `STAGES`; `single` returns `STAGES` without `skill_extraction` and `plo_review`, with the `plo_synthesis` entry's label `'ตรวจ PLO'` and the `plo_review` gate note moved onto it. `StageRail`, `gateStateFor` and `stageIndex` take the filtered list (index within that list).
- [ ] **Step 3: Intake.** A select `agent_mode` under the duration field, rendered like `degree_level` (:259-271), **disabled in edit mode**. Options: `multi` — `หลายตัวแทน (4 agents): แต่ละขั้นมีตัวแทนของตัวเอง มีการโหวตและตรวจซ้ำ`; `single` — `ตัวแทนเดียว: LLM ตัวเดียวทำทุกขั้นและตรวจงานตัวเอง`. Sent in the POST payload only.
- [ ] **Step 4: Programs.** The mode shown on each row (`หลายตัวแทน` / `ตัวแทนเดียว`). The copy choice gains a mode select defaulting to the source's mode; choosing a different mode disables the "full" button. `copyProgram` posts `{ mode, agent_mode }`.
- [ ] **Step 5: Need page for a single program.** Do not fetch `/needs/skills`. Empty state: `ยังไม่มี Need — ให้ตัวแทนอ่านหลักฐานแล้วเขียน Need` with a run button posting `/needs/run`; the re-run button posts `/needs/run` too. After a run, show the job result's `stop_reason` when not `finished`, and the unread / uncited evidence counts when non-zero. `NeedCard` for `origin === 'single'`: hide the "ทักษะในกลุ่ม" section and the top-skill chips; label `freq` as `จำนวนหลักฐานที่อ้าง`.
- [ ] **Step 6: PLO checkpoint for a single program** (`PloSynthesis.tsx`). Hide `ValidationToggle`, the feedback trail and the superseded-by-review notes. The `VALIDATED_BY_TH` badge shows the self-judged label; soft-flag chips get the caption `ตัวแทนประเมินเอง`. Add the approve button the review page has (:170-186): `อนุมัติและออกรายงาน` → `startJob('/plos/report/run')` → navigate to `/plo-report`; disabled while a job runs or when there are no PLOs. Escalated PLOs stay visible as today.
- [ ] **Step 7: Mock.** One single-mode program in `mock/scenarios.ts` (Needs with `origin: 'single'`, no skills; PLOs with `smart_validated_by: 'single_agent'`); handlers return `agent_mode` and accept it on create/copy.
- [ ] **Step 8: Verify** `cd frontend && npm run build && npm run lint` — both exit 0. **Step 9: Commit** `feat(single): UI — mode choice, rail, Need page and PLO checkpoint`

---

### Task 12: Docs and one real run

**Files:**
- Modify: `CLAUDE.md` (Stack: eighth slot `single_agent`; rules 5 and 7 and the two pitfalls get a short "single mode" relaxation note dated 2026-11-13, per the spec's "Decisions that relax a project rule"), `.claude/rules/llm-slots.md`, `.claude/skills/curriculum-design-agent/references/prompts.md` (why the single prompt says what it says), `.claude/skills/curriculum-design-agent/references/data-schemas.md` (`agent_mode`, `Need.origin`, `single_agent` label)
- Create: `.scratch/reports/2026-11-14-single-agent-first-run.md`

- [ ] **Step 1: Docs.** Write the notes above. `uv run python scripts/dump_prompts.py --check` — exit 0.
- [ ] **Step 2: Full checks.** `uv run pytest -q`, `uv run ruff check src/ tests/ scripts/`, `uv run mypy src/` — all clean. Record the test count.
- [ ] **Step 3: Migrate the copy DB only.** `uv run alembic -x url=<curriculum_phase1 url from the environment, never printed> upgrade head`; confirm with a `select agent_mode from programs limit 1` through a script that prints only the value.
- [ ] **Step 4: Real run.** Backend pointed at the copy DB on port 8011. Make an `evidence_only` copy of `program` with `agent_mode="single"`; `POST /needs/run`, wait for the job; `POST /plos/run`, wait; `POST /plos/report/run`. No designer edits in between.
- [ ] **Step 5: Report** to `.scratch/reports/2026-11-14-single-agent-first-run.md`: for each half — stop reason, turns, wall time, prompt and completion tokens (from `GET /programs/{id}/usage`, slot `single_agent`), dropped/unread/uncited evidence; then Need count (core/optional), PLO count, escalated count, soft flags raised, whether every PLO has a full trail; and whether the 80-turn / 1800 s budgets and the 128000 window setting were adequate (the spec leaves the numbers to this run). State plainly anything that failed.
- [ ] **Step 6: Commit** `docs(single): rules, slot notes, first real run`

---

## Self-review notes

- Spec coverage: mode on program (T1-2, T11) · one slot (T3) · tools (T6) · needs half incl. statistics, unread/uncited, partial-result rule (T4, T7) · context handling (T6) · Need model without skills + audit (T1; audit findings folded into T9-T11: merge skills check, `_write_merged`, combine re-run button, empty state, skills section, freq label) · Need checkpoint actions (T10) · PLO half (T8) · checkpoint + report (T9, T11) · revalidate / from-needs (T10) · budgets (T3, T12) · sessions refusal (T9) · prompt inventory (T5) · real run (T12).
- Two spec lines were corrected while planning (see the spec's commit): the skill ratios stay 1.0 for a skill-less Need (returning 0 would mark it off-scope in a log line), and the designer merge's statement is written by the agent, not taken from the dialog, because today's merge already writes it with an LLM.
