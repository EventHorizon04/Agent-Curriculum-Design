# Run Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a designer run PLO synthesis with the SMART validation agent switched off for one run, and copy a program (`program-2` → `program-2-run-1`) so one run's results survive the next.

**Architecture:** Part 1 threads a `run_validation` flag from a new request field through `AgentState` into `validate_and_build` and `run_smart_agent`, which returns a new `SKIPPED` code-only verdict; the pure-code gate is untouched. Part 2 adds a `copied_from` column and a `data/program_copy.py` module: a pure `build_copy` that clones ORM rows under fresh evidence/skill/Need uuids and rewrites every reference through one id map, and a thin `copy_program` that loads and inserts in one session; a `POST /programs/{id}/copy` route names the copy `{id}-run-{n}`.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, pytest (asyncio_mode=auto), uv.

**Spec:** `docs/superpowers/specs/2026-10-06-run-comparison-design.md`

## Global Constraints

- Work on `main` (user-approved). Stage by explicit path only. Never stage `frontend/**`, `.scratch/plo-scope-guard/**`, the deleted `curriculum-design-agent.skill`, or untracked `.claude/skills/*`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
- Never read `.env`. Do not touch the live database (the controller migrates it). Do not call any LLM endpoint. Do not dispatch subagents.
- Mutation checks use Edit, never `git checkout --` / `git restore` / `git stash`.
- `from __future__ import annotations`, type hints on every signature, `loguru` not `logging`, English code/comments/logs, Thai for user-facing strings.
- The pure-code SMART gate (`hard_failures` in `validate_and_build`) must still run on every PLO whether or not the agent ran (immutable rule 5).
- `.env` off wins: with `VALIDATION_PROVIDER` empty the reason is `DISABLED` even when the request asks for validation.
- Verify each task with: `uv run pytest -q`, `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`, `uv run mypy src/`. On Windows set `PYTHONIOENCODING=utf-8`.
- There is no real-DB test fixture in this repo: repository/I-O code is tested with mocked sessions (see `tests/unit/test_plo_composite_primary_key.py::_fake_session_ctx`), and pure logic is tested directly.

---

### Task 1: Per-run validator switch

**Files:**
- Modify: `src/curriculum_agent/stages/smart_agent.py` (`ValidationReason`, `run_smart_agent`)
- Modify: `src/curriculum_agent/stages/plo_synthesis.py` (`validate_and_build`, `_run`)
- Modify: `src/curriculum_agent/graph.py` (`AgentState`)
- Modify: `src/curriculum_agent/api/routes/plos.py` (`run_plo_synthesis`, new `GET /validation`)
- Modify: `tests/support/smart_agent.py` (`ScriptedAgent.__call__`)
- Test: `tests/unit/test_validation_switch.py` (new)

**Interfaces:**
- Produces: `ValidationReason.SKIPPED = "skipped"`; `run_smart_agent(draft, ctx, metadata, *, enabled: bool = True)`; `validate_and_build(..., run_validation: bool = True)`; `AgentState["run_validation"]: bool`; `PLOSynthesisRunRequest(DesignerNoteRequest)` with `run_validation: bool = True`; `ValidationStatusResponse(enabled: bool, model: str)`; `GET /programs/{program_id}/plos/validation`.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_validation_switch.py`

```python
"""A per-run switch for the SMART validation agent.

The designer compares synthesis with and without the agent. `.env`
(`VALIDATION_PROVIDER=`) could already turn it off, but only with a restart,
and PowerShell's `$env:X = ""` deletes the variable instead of emptying it. So
`POST /plos/run` takes `run_validation`, which reaches `run_smart_agent` as
`enabled`. Two invariants: the `.env` switch still wins (a request cannot turn
on an agent with no endpoint), and the pure-code gate runs either way.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import plos as plos_route
from curriculum_agent.config import settings as live_settings
from curriculum_agent.models import BloomLevel, KSECCategory, Need, ProgramMetadata
from curriculum_agent.stages import plo_synthesis as ps
from curriculum_agent.stages import smart_agent as sa
from tests.support.smart_agent import set_agent

client = TestClient(app)

_META = ProgramMetadata(
    program_id="cs-test",
    name_th="วิทยาการคอมพิวเตอร์",
    name_en="Computer Science",
    field="วิทยาการคอมพิวเตอร์",
    degree_level="bachelor",
    duration_years=4,
    faculty="คณะวิทยาศาสตร์",
    university="มหาวิทยาลัยทดสอบ",
)


def _need(need_id: str = "N1") -> Need:
    return Need(
        need_id=need_id,
        program_id="cs-test",
        statement_th=f"ต้องการบัณฑิตที่ทำงานด้าน {need_id} ได้ตามมาตรฐานอุตสาหกรรม",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.CREATE,
        member_skill_ids=[f"S-{need_id}"],
        source_evidence_ids=[f"E-{need_id}"],
        freq=1,
        demand_score=0.8,
    )


def _draft(statement_th: str = "ออกแบบระบบสารสนเทศตามมาตรฐานอุตสาหกรรมได้") -> ps._PLODraft:
    return ps._PLODraft(
        statement_th=statement_th,
        bloom_level=BloomLevel.CREATE,
        action_verb_th="ออกแบบ",
        source_need_ids=["N1"],
        rationale_th="ทักษะที่ตลาดต้องการ",
    )


async def _must_not_be_called(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("the validation agent ran on a run that switched it off")


# --------------------------- run_smart_agent ---------------------------


async def test_enabled_false_skips_the_agent_without_calling_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_settings, "validation_provider", "openrouter")
    monkeypatch.setattr(sa, "complete_validation", _must_not_be_called)
    ctx = _ctx_for(_draft())

    result = await sa.run_smart_agent(_draft(), ctx, _META, enabled=False)

    assert result.reason is sa.ValidationReason.SKIPPED
    assert result.ran is False
    assert result.soft_findings == []
    assert "ปิดการตรวจในรอบนี้" in result.diagnosis_th


async def test_the_env_switch_wins_over_a_request_to_validate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_settings, "validation_provider", "")
    monkeypatch.setattr(sa, "complete_validation", _must_not_be_called)

    result = await sa.run_smart_agent(_draft(), _ctx_for(_draft()), _META, enabled=True)

    assert result.reason is sa.ValidationReason.DISABLED


# --------------------------- validate_and_build ---------------------------


async def test_validate_and_build_passes_the_switch_to_the_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = set_agent(monkeypatch)
    await ps.validate_and_build(
        _draft(),
        metadata=_META,
        needs=[_need()],
        program_id="cs-test",
        plo_id="PLO1",
        known_need_ids={"N1"},
        run_validation=False,
    )
    assert stub.enabled_flags == [False]


async def test_the_code_gate_still_escalates_when_the_agent_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Immutable rule 5: skipping the agent never skips `hard_failures`."""
    monkeypatch.setattr(live_settings, "validation_provider", "openrouter")
    monkeypatch.setattr(sa, "complete_validation", _must_not_be_called)
    bad = _draft("ออกแบบระบบสารสนเทศที่ผู้ใช้เข้าใจได้ตามมาตรฐานอุตสาหกรรม")

    plo = await ps.validate_and_build(
        bad,
        metadata=_META,
        needs=[_need()],
        program_id="cs-test",
        plo_id="PLO1",
        known_need_ids={"N1"},
        run_validation=False,
    )

    assert plo is not None
    assert plo.smart_escalated is True
    assert plo.smart_validated_by == "code_only"


# --------------------------- stage ---------------------------


async def test_the_stage_reads_the_switch_from_state(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = set_agent(monkeypatch)
    monkeypatch.setattr(ps.PLORepository, "delete_by_program", AsyncMock(return_value=0))
    monkeypatch.setattr(ps.PLORepository, "bulk_insert", AsyncMock())
    monkeypatch.setattr(ps, "draft_from_needs", AsyncMock(return_value=_draft()))

    await ps.run(
        {
            "program_id": "cs-test",
            "metadata": _META.model_dump(mode="json"),
            "needs": [_need().model_dump(mode="json")],
            "run_validation": False,
        }
    )

    assert stub.enabled_flags and all(flag is False for flag in stub.enabled_flags)


async def test_the_stage_validates_when_the_key_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = set_agent(monkeypatch)
    monkeypatch.setattr(ps.PLORepository, "delete_by_program", AsyncMock(return_value=0))
    monkeypatch.setattr(ps.PLORepository, "bulk_insert", AsyncMock())
    monkeypatch.setattr(ps, "draft_from_needs", AsyncMock(return_value=_draft()))

    await ps.run(
        {
            "program_id": "cs-test",
            "metadata": _META.model_dump(mode="json"),
            "needs": [_need().model_dump(mode="json")],
        }
    )

    assert stub.enabled_flags and all(flag is True for flag in stub.enabled_flags)


# --------------------------- routes ---------------------------


def _route_env(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_META))
    monkeypatch.setattr(
        plos_route.NeedRepository, "list_by_program", AsyncMock(return_value=[_need()])
    )
    run = AsyncMock(return_value={"plos": []})
    monkeypatch.setattr(ps, "run", run)
    return run


def test_run_route_puts_the_switch_in_state_only_when_off(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _route_env(monkeypatch)

    assert client.post("/programs/cs-test/plos/run", json={"run_validation": False}).status_code == 200
    assert run.await_args.args[0]["run_validation"] is False

    assert client.post("/programs/cs-test/plos/run", json={}).status_code == 200
    assert "run_validation" not in run.await_args.args[0]

    assert client.post("/programs/cs-test/plos/run").status_code == 200
    assert "run_validation" not in run.await_args.args[0]


def test_validation_status_reports_on_and_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_META))

    monkeypatch.setattr(live_settings, "validation_provider", "openrouter")
    monkeypatch.setattr(live_settings, "validation_model", "z-ai/glm-5.3-flash")
    on = client.get("/programs/cs-test/plos/validation")
    assert on.status_code == 200
    assert on.json() == {"enabled": True, "model": "z-ai/glm-5.3-flash"}

    monkeypatch.setattr(live_settings, "validation_provider", "")
    off = client.get("/programs/cs-test/plos/validation")
    assert off.json() == {"enabled": False, "model": ""}


def test_validation_status_404s_for_an_unknown_program(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=None))
    assert client.get("/programs/nope/plos/validation").status_code == 404
```

`_ctx_for` is the `ValidationContext` builder the agent tests already use. Copy the `_ctx` helper from `tests/unit/test_smart_agent.py` into this file as `_ctx_for(draft)` (read that file for its exact construction — it takes the draft's statement and the Need list); do not import a private helper across test modules. If `plo_synthesis.run` reaches `need_dedup` or the PLO review in the stage tests, `tests/conftest.py`'s autouse fixtures already stub them. If the stage path needs `EvidenceRepository` or similar for the evidence index, patch it the way `tests/unit/test_plo_synthesis_phases.py` does.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_validation_switch.py -v`
Expected: FAIL — `ValidationReason` has no `SKIPPED`, `run_smart_agent` takes no `enabled`, `ScriptedAgent` has no `enabled_flags`, route 404/422 for `/validation`.

- [ ] **Step 3: Teach the test stub the new keyword** — `tests/support/smart_agent.py`

```python
    def __init__(self, *verdicts: Any) -> None:
        self._verdicts = list(verdicts)
        self.calls: list[tuple[Any, Any]] = []
        self.enabled_flags: list[bool] = []

    async def __call__(
        self,
        draft: Any,
        ctx: Any,
        metadata: Any,
        *,
        need_statements_th: Any = (),
        enabled: bool = True,
    ) -> SmartAgentResult:
        self.calls.append((draft, ctx))
        self.enabled_flags.append(enabled)
        ...  # rest unchanged
```

- [ ] **Step 4: Implement the agent side** — `src/curriculum_agent/stages/smart_agent.py`

Add to `ValidationReason` after `DISABLED`:

```python
    SKIPPED = "skipped"
```

Change `run_smart_agent`'s signature to add `*, enabled: bool = True` (keep any existing keyword parameters), and right after the existing kill-switch block:

```python
    # The per-run switch (POST /plos/run, run_validation=false). Checked after
    # the .env kill switch on purpose: a request can turn the agent off for one
    # run, never on when no endpoint is configured. Distinct from DISABLED so a
    # stored PLO says which of the two produced its code-only verdict.
    if not enabled:
        return code_only_result(
            draft, ValidationReason.SKIPPED, "ไม่ได้ตรวจ (ปิดการตรวจในรอบนี้)"
        )
```

Mention `enabled` in the docstring in one sentence.

- [ ] **Step 5: Implement the synthesis side** — `src/curriculum_agent/stages/plo_synthesis.py`

Add `run_validation: bool = True` as the last keyword parameter of `validate_and_build`, document it in one line, and pass it on: `result = await run_smart_agent(draft, ctx, metadata, enabled=run_validation)` (keep any other keyword already passed there). In `_run`, next to `note_th = state.get("designer_note")`:

```python
    run_validation = state.get("run_validation", True)
    if not run_validation:
        logger.info(
            "plo_synthesis: validation agent skipped for this run (run_validation=false)"
        )
```

and add `run_validation=run_validation,` to the `validate_and_build(...)` call inside `gather_bounded`. Leave `synthesize_from_needs` (the merge route's entry) and the revalidate path on the default `True`.

In `src/curriculum_agent/graph.py`, add to `AgentState` next to `designer_note: str`:

```python
    # Per-run switch for the SMART validation agent (POST /plos/run). Absent
    # means validate; only the REST route ever sets it, and only to False.
    run_validation: bool
```

- [ ] **Step 6: Implement the routes** — `src/curriculum_agent/api/routes/plos.py`

```python
class PLOSynthesisRunRequest(DesignerNoteRequest):
    """`POST /plos/run` body. `run_validation=False` skips the SMART validation
    agent for this run only; the pure-code gate still runs."""

    run_validation: bool = True


class ValidationStatusResponse(BaseModel):
    enabled: bool
    model: str
```

Change `run_plo_synthesis(program_id: str, body: PLOSynthesisRunRequest | None = None)` and after the designer-note lines:

```python
    if body is not None and not body.run_validation:
        state["run_validation"] = False
```

New route (place it before any `/{plo_id}` route so the path is not shadowed):

```python
@router.get("/validation", response_model=ValidationStatusResponse)
async def get_validation_status(program_id: str) -> ValidationStatusResponse:
    """Whether the SMART validation agent can run at all — `.env` decides.

    The synthesis page uses it to disable its per-run checkbox, with a reason,
    when `VALIDATION_PROVIDER` is empty: the request can only switch the agent
    off, never on.
    """
    if await ProgramRepository().get(program_id) is None:
        raise HTTPException(status_code=404, detail="Program not found")
    enabled = bool(settings.validation_provider)
    return ValidationStatusResponse(
        enabled=enabled, model=settings.validation_model if enabled else ""
    )
```

Import `settings` from `curriculum_agent.config` and `BaseModel` from pydantic if the module does not already.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/unit/test_validation_switch.py -v` → PASS. Then the full suite, ruff, format, mypy (Global Constraints).

- [ ] **Step 8: Mutation check** — remove the `if not enabled:` block with Edit; `test_enabled_false_skips_the_agent_without_calling_anything` must fail. Restore with Edit.

- [ ] **Step 9: Commit**

```bash
git add src/curriculum_agent/stages/smart_agent.py src/curriculum_agent/stages/plo_synthesis.py src/curriculum_agent/graph.py src/curriculum_agent/api/routes/plos.py tests/support/smart_agent.py tests/unit/test_validation_switch.py
git commit -m "feat(plo_synthesis): switch the validation agent off for one run

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `copied_from` provenance column

**Files:**
- Create: `migrations/versions/c0f1e2d3a4b5_program_copied_from.py`
- Modify: `src/curriculum_agent/data/orm.py` (`ProgramTable`)
- Modify: `src/curriculum_agent/models.py` (`ProgramMetadata`, `ProgramSummary`)
- Modify: `src/curriculum_agent/data/repositories.py` (`ProgramRepository.list_all`)
- Modify: `src/curriculum_agent/api/routes/programs.py` (`update_program`)
- Test: `tests/unit/test_program_copied_from.py` (new)

**Interfaces:**
- Produces: `ProgramTable.copied_from: Mapped[str | None]`; `ProgramMetadata.copied_from: str | None = None`; `ProgramSummary.copied_from: str | None = None`. Not on `ProgramCreateRequest`.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_program_copied_from.py`

```python
"""`copied_from` says which program a copy was made from.

It lives on ProgramMetadata (the stored entity), never on ProgramCreateRequest
(what a client sends), so no client can claim a program is a copy. It is not a
foreign key: deleting the source must leave its copies alone.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.data.orm import ProgramTable
from curriculum_agent.data.repositories import ProgramRepository
from curriculum_agent.models import ProgramCreateRequest, ProgramMetadata, ProgramSummary

client = TestClient(app)


def test_the_column_is_nullable_text_with_no_foreign_key() -> None:
    col = ProgramTable.__table__.columns["copied_from"]
    assert col.nullable is True
    assert not col.foreign_keys


def test_the_entity_carries_it_and_the_request_does_not() -> None:
    assert "copied_from" in ProgramMetadata.model_fields
    assert ProgramMetadata.model_fields["copied_from"].default is None
    assert "copied_from" not in ProgramCreateRequest.model_fields
    assert "copied_from" in ProgramSummary.model_fields


def test_the_migration_adds_and_drops_the_column() -> None:
    path = next(Path("migrations/versions").glob("*_program_copied_from.py"))
    spec = importlib.util.spec_from_file_location("m", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    op = MagicMock()
    with patch.dict("sys.modules", {"alembic.op": op}):
        spec.loader.exec_module(module)
        module.op = op
        module.upgrade()
        module.downgrade()
    assert module.down_revision == "117059107855"
    added = op.add_column.call_args
    assert added.args[0] == "programs"
    assert added.args[1].name == "copied_from"
    assert added.args[1].nullable is True
    op.drop_column.assert_called_once_with("programs", "copied_from")


async def test_list_all_carries_copied_from() -> None:
    row = ProgramTable(
        program_id="program-2-run-1",
        name_th="",
        name_en="",
        field="การท่องเที่ยว",
        degree_level="bachelor",
        duration_years=4,
        faculty="คณะ",
        university="มหาวิทยาลัย",
        program_goals_th=[],
        program_objectives_th=[],
        created_at=datetime(2026, 10, 6),
        copied_from="program-2",
    )
    # Follow the mocked-session pattern of tests/unit/test_program_repository.py
    # (`_mock_db`): one execute for programs, one for sessions, and the
    # `_programs_with_rows` calls returning empty sets.
    ...
    summaries = await ProgramRepository().list_all()
    assert summaries[0].copied_from == "program-2"


def test_put_keeps_copied_from(monkeypatch) -> None:  # noqa: ANN001
    """PUT rebuilds ProgramMetadata from a ProgramCreateRequest, which has no
    copied_from — without carrying it over, editing a copy's metadata would
    erase where it came from."""
    from curriculum_agent.api.routes import programs as programs_route

    existing = ProgramMetadata(
        program_id="program-2-run-1",
        field="การท่องเที่ยว",
        degree_level="bachelor",
        duration_years=4,
        faculty="คณะ",
        university="มหาวิทยาลัย",
        copied_from="program-2",
    )
    upsert = AsyncMock()
    monkeypatch.setattr(programs_route.ProgramRepository, "get", AsyncMock(return_value=existing))
    monkeypatch.setattr(programs_route.ProgramRepository, "upsert", upsert)
    app.state.graph = MagicMock(aupdate_state=AsyncMock())

    body = existing.model_dump(mode="json", include=set(ProgramCreateRequest.model_fields))
    response = client.put("/programs/program-2-run-1", json=body)

    assert response.status_code == 200
    assert upsert.await_args.args[0].copied_from == "program-2"
```

Fill the `...` in `test_list_all_carries_copied_from` by reading `_mock_db` in `tests/unit/test_program_repository.py` and reusing its shape (copy the helper in; don't import it). If `ProgramMetadata`'s required fields differ from the ones used above, read `ProgramCreateRequest` and supply what it requires. If `app.state.graph` is already set up differently in `tests/unit/test_api_programs.py`, follow that.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_program_copied_from.py -v` → FAIL (no column / field / migration).

- [ ] **Step 3: Migration** — `migrations/versions/c0f1e2d3a4b5_program_copied_from.py`

```python
"""programs.copied_from: which program a copy was made from

Revision ID: c0f1e2d3a4b5
Revises: 117059107855
Create Date: 2026-10-06 00:00:00.000000

Nullable and not a foreign key: every existing program is an original, and
deleting a source must leave its copies alone. See
docs/superpowers/specs/2026-10-06-run-comparison-design.md.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c0f1e2d3a4b5"
down_revision: str | None = "117059107855"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("programs", sa.Column("copied_from", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("programs", "copied_from")
```

- [ ] **Step 4: ORM, models, repository, route**

`orm.py`, in `ProgramTable` after `program_objectives_th`:

```python
    # Set only by POST /programs/{id}/copy. Not a ForeignKey: deleting the
    # source program must not reach its copies.
    copied_from: Mapped[str | None] = mapped_column(Text, nullable=True)
```

`models.py`, in `ProgramMetadata` after `created_at`:

```python
    # Which program this one was copied from (POST /programs/{id}/copy). On the
    # entity, not on ProgramCreateRequest, so a client cannot set it.
    copied_from: str | None = None
```

and in `ProgramSummary` after `session_status`: `copied_from: str | None = None`.

`repositories.py`, `list_all`: add `copied_from=p.copied_from,` to the `ProgramSummary(...)` construction.

`programs.py`, `update_program`: add `copied_from=existing.copied_from,` to the `ProgramMetadata(...)` construction, with a one-line comment that the request model does not carry it.

- [ ] **Step 5: Run tests** — the new file, then full suite + ruff + format + mypy.

- [ ] **Step 6: Mutation check** — remove `copied_from=existing.copied_from,` with Edit; `test_put_keeps_copied_from` must fail. Restore.

- [ ] **Step 7: Commit**

```bash
git add migrations/versions/c0f1e2d3a4b5_program_copied_from.py src/curriculum_agent/data/orm.py src/curriculum_agent/models.py src/curriculum_agent/data/repositories.py src/curriculum_agent/api/routes/programs.py tests/unit/test_program_copied_from.py
git commit -m "feat(programs): record which program a copy was made from

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Pure copy builder

**Files:**
- Create: `src/curriculum_agent/data/program_copy.py`
- Test: `tests/unit/test_program_copy_build.py` (new)

**Interfaces:**
- Consumes: `ProgramTable.copied_from` (Task 2); `plo_review.plo_fingerprint(plos: Sequence[PLO]) -> str`; `repositories._row_to_dict`.
- Produces:
  - `remap_ids(value: Any, id_map: Mapping[str, str]) -> Any`
  - `@dataclass(frozen=True) class ProgramRows: program: ProgramTable; evidence: list[EvidenceTable]; skills: list[SkillTable]; needs: list[NeedTable]; plos: list[PLOTable]; review: PLOReviewTable | None`
  - `build_copy(src: ProgramRows, new_id: str, *, now: datetime, new_uuid: Callable[[], str] = _uuid4) -> ProgramRows`

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_program_copy_build.py`

```python
"""build_copy: clone a program's rows under fresh ids, rewiring every reference.

evidence_id, skill_id and need_id are single-column global primary keys, so a
copy cannot reuse them. One old->new map covers all three, and every value in
every column — JSONB included — that exactly equals an old id is rewritten.
plo_id is kept: a PLO's identity is (program_id, plo_id).
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime

from curriculum_agent.data.orm import (
    EvidenceTable,
    NeedTable,
    PLOReviewTable,
    PLOTable,
    ProgramTable,
    SkillTable,
)
from curriculum_agent.data.program_copy import ProgramRows, build_copy, remap_ids
from curriculum_agent.data.repositories import _row_to_dict
from curriculum_agent.models import PLO
from curriculum_agent.stages.plo_review import plo_fingerprint

NOW = datetime(2026, 10, 6, 12, 0, 0)


def _ids() -> itertools.count[int]:
    return itertools.count(1)


def _new_uuid_factory():  # noqa: ANN202
    counter = _ids()
    return lambda: f"new-{next(counter)}"


def test_remap_ids_rewrites_exact_matches_at_any_depth() -> None:
    id_map = {"a": "A", "b": "B"}
    value = {"x": ["a", {"y": "b", "z": "ab"}], "a": 1, "n": None, "f": 0.5, "t": True}
    assert remap_ids(value, id_map) == {
        "x": ["A", {"y": "B", "z": "ab"}],
        "A": 1,
        "n": None,
        "f": 0.5,
        "t": True,
    }


def test_remap_ids_leaves_free_text_containing_an_id_alone() -> None:
    assert remap_ids("ดู a ประกอบ", {"a": "A"}) == "ดู a ประกอบ"


def _source() -> ProgramRows:
    program = ProgramTable(
        program_id="program-2",
        name_th="",
        name_en="",
        field="การท่องเที่ยว",
        degree_level="bachelor",
        duration_years=4,
        faculty="คณะ",
        university="มหาวิทยาลัย",
        scope_th="",
        program_goals_th=[],
        program_objectives_th=[],
        created_at=datetime(2026, 9, 1),
        copied_from=None,
    )
    evidence = [
        EvidenceTable(
            evidence_id="ev-1",
            program_id="program-2",
            stakeholder_type="employer",
            source_name="โรงแรม",
            raw_text_th="ต้องการพนักงานที่สื่อสารภาษาอังกฤษได้",
            collected_at=datetime(2026, 9, 1),
            classification="general",
            extra_metadata={},
        )
    ]
    skills = [
        SkillTable(
            skill_id="sk-1",
            program_id="program-2",
            skill_name_th="การสื่อสารภาษาอังกฤษ",
            ksec_category="S",
            bloom_level="apply",
            evidence_span_th="สื่อสารภาษาอังกฤษได้",
            source_evidence_id="ev-1",
            source_stakeholder_type="employer",
            classification="want",
            is_field_relevant=True,
            is_graduate_capability=True,
            extraction_method="llm",
            confidence=0.9,
            importance_score=0.5,
        )
    ]
    needs = [
        NeedTable(
            need_id="nd-1",
            program_id="program-2",
            statement_th="ต้องการบัณฑิตที่สื่อสารภาษาอังกฤษกับนักท่องเที่ยวได้",
            rationale_th="ทุกทักษะในกลุ่มเป็นการสื่อสารกับลูกค้า",
            ksec_category="S",
            bloom_level="apply",
            member_skill_ids=["sk-1"],
            source_evidence_ids=["ev-1"],
            stakeholder_coverage={"employer": 1},
            source_stakeholder_types=["employer"],
            freq=1,
            demand_score=0.5,
            is_optional=False,
            classification_coverage={"want": 1},
            in_field_skill_count=1,
            graduate_capability_skill_count=1,
        )
    ]
    plos = [
        PLOTable(
            plo_id="PLO1",
            program_id="program-2",
            statement_th="สื่อสารภาษาอังกฤษกับนักท่องเที่ยวในงานบริการได้",
            bloom_level="apply",
            action_verb_th="สื่อสาร",
            smart_check={
                "specific": True,
                "measurable": True,
                "achievable": True,
                "relevant": True,
                "timely": True,
                "findings": [{"code": "R_answers", "need_id": "nd-1", "note_th": "ดู nd-1"}],
            },
            source_need_ids=["nd-1"],
            source_evidence_ids=["ev-1"],
            rationale_th="เหตุผล",
            version=1,
            smart_retry_count=0,
            smart_escalated=False,
            soft_flags=[],
            smart_validated_by="agent",
            is_optional=False,
        )
    ]
    return ProgramRows(program=program, evidence=evidence, skills=skills, needs=needs, plos=plos, review=None)


def _with_review(src: ProgramRows, *, fingerprint: str) -> ProgramRows:
    review = PLOReviewTable(
        program_id="program-2",
        plo_fingerprint=fingerprint,
        model="z-ai/glm-5.3-flash",
        created_at=datetime(2026, 10, 5),
        review={"redundancies": [], "ksec": [{"plo_id": "PLO1"}], "bloom": [], "summary_th": "ok"},
    )
    return ProgramRows(**{**src.__dict__, "review": review})


def _fingerprint(rows: list[PLOTable]) -> str:
    return plo_fingerprint([PLO.model_validate(_row_to_dict(r)) for r in rows])


def _dump(rows: ProgramRows) -> str:
    every = [rows.program, *rows.evidence, *rows.skills, *rows.needs, *rows.plos]
    if rows.review is not None:
        every.append(rows.review)
    return json.dumps([_row_to_dict(r) for r in every], default=str, ensure_ascii=False)


def test_every_row_moves_to_the_new_program_with_its_counts() -> None:
    copy = build_copy(_source(), "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())
    assert copy.program.program_id == "program-2-run-1"
    assert copy.program.copied_from == "program-2"
    assert copy.program.created_at == NOW
    for row in [*copy.evidence, *copy.skills, *copy.needs, *copy.plos]:
        assert row.program_id == "program-2-run-1"
    assert (len(copy.evidence), len(copy.skills), len(copy.needs), len(copy.plos)) == (1, 1, 1, 1)


def test_no_old_id_survives_anywhere_in_the_copy() -> None:
    copy = build_copy(_source(), "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())
    text = _dump(copy)
    for old in ("ev-1", "sk-1", "nd-1"):
        assert f'"{old}"' not in text


def test_every_reference_resolves_inside_the_copy() -> None:
    copy = build_copy(_source(), "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())
    evidence_ids = {e.evidence_id for e in copy.evidence}
    skill_ids = {s.skill_id for s in copy.skills}
    need_ids = {n.need_id for n in copy.needs}
    assert {s.source_evidence_id for s in copy.skills} <= evidence_ids
    for n in copy.needs:
        assert set(n.member_skill_ids) <= skill_ids
        assert set(n.source_evidence_ids) <= evidence_ids
    for p in copy.plos:
        assert set(p.source_need_ids) <= need_ids
        assert set(p.source_evidence_ids) <= evidence_ids
        assert p.smart_check["findings"][0]["need_id"] in need_ids
        assert p.smart_check["findings"][0]["note_th"] == "ดู nd-1", "free text is left alone"


def test_plo_ids_are_kept() -> None:
    copy = build_copy(_source(), "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())
    assert [p.plo_id for p in copy.plos] == ["PLO1"]


def test_the_source_rows_are_not_mutated() -> None:
    src = _source()
    before = _dump(src)
    build_copy(src, "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())
    assert _dump(src) == before


def test_a_current_review_stays_current_in_the_copy() -> None:
    src = _source()
    src = _with_review(src, fingerprint=_fingerprint(src.plos))
    copy = build_copy(src, "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())
    assert copy.review is not None
    assert copy.review.program_id == "program-2-run-1"
    assert copy.review.plo_fingerprint == _fingerprint(copy.plos)


def test_a_stale_review_stays_stale_in_the_copy() -> None:
    src = _with_review(_source(), fingerprint="0" * 64)
    copy = build_copy(src, "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())
    assert copy.review is not None
    assert copy.review.plo_fingerprint != _fingerprint(copy.plos)


def test_no_review_means_no_review() -> None:
    copy = build_copy(_source(), "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())
    assert copy.review is None
```

If constructing a `PLO` from the PLOTable fixture fails validation (e.g. the `smart_check` dict shape or the finding code), adjust the fixture to a shape `SMARTCheck` accepts — read `SmartFinding` in `models.py` — while keeping a JSONB value that equals a Need id somewhere inside `smart_check`. If `SmartFinding` has no id-valued field, put the id in a field it does have that holds a string verbatim, or in `soft_flags`' sibling the test can still read; the point is a JSONB string equal to an old id.

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/unit/test_program_copy_build.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement** — `src/curriculum_agent/data/program_copy.py`

```python
"""Copy a program: every row it owns, under fresh ids, in one transaction.

A copy exists so one synthesis run's results survive the next (the run
comparison spec, docs/superpowers/specs/2026-10-06-run-comparison-design.md).

evidence_id, skill_id and need_id are single-column, global primary keys, so a
copy cannot reuse them; plo_id is per program since migration e4b6d19a3f72 and
is kept. One old->new map covers the three id kinds, and `remap_ids` rewrites
every value in every column that exactly equals an old id — the named
reference columns and the JSONB blobs alike, so a column that starts carrying
an id later is covered without a change here. Free text that merely contains
an id is left alone.

Rows are cloned column by column from the table definition, so a column added
later is copied by default rather than silently dropped.

Not copied: sessions, checkpoints and LangGraph threads (a copy has no
suspended run to resume), and llm_cache (shared by key already).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, TypeVar

from loguru import logger

from curriculum_agent.data.orm import (
    Base,
    EvidenceTable,
    NeedTable,
    PLOReviewTable,
    PLOTable,
    ProgramTable,
    SkillTable,
)
from curriculum_agent.data.repositories import _row_to_dict
from curriculum_agent.models import PLO
from curriculum_agent.stages.plo_review import plo_fingerprint

_Row = TypeVar("_Row", bound=Base)


@dataclass(frozen=True)
class ProgramRows:
    program: ProgramTable
    evidence: list[EvidenceTable]
    skills: list[SkillTable]
    needs: list[NeedTable]
    plos: list[PLOTable]
    review: PLOReviewTable | None


def _uuid4() -> str:
    return str(uuid.uuid4())


def remap_ids(value: Any, id_map: Mapping[str, str]) -> Any:
    """Rewrite every string exactly equal to an old id, at any depth.

    Dict keys too: a JSONB map keyed by an id must follow the id. Only an exact
    match is replaced — an id inside free text stays as written.
    """
    if isinstance(value, str):
        return id_map.get(value, value)
    if isinstance(value, list):
        return [remap_ids(v, id_map) for v in value]
    if isinstance(value, tuple):
        return tuple(remap_ids(v, id_map) for v in value)
    if isinstance(value, dict):
        return {remap_ids(k, id_map): remap_ids(v, id_map) for k, v in value.items()}
    return value


def _clone(row: _Row, id_map: Mapping[str, str], **overrides: Any) -> _Row:
    data = {k: remap_ids(v, id_map) for k, v in _row_to_dict(row).items()}
    data.update(overrides)
    return type(row)(**data)


def _fingerprint(rows: list[PLOTable]) -> str | None:
    """The review fingerprint of a PLO row set, or None if a row won't parse."""
    try:
        return plo_fingerprint([PLO.model_validate(_row_to_dict(r)) for r in rows])
    except Exception as exc:  # noqa: BLE001 - a legacy row only costs freshness
        logger.warning(f"program copy: PLO rows did not parse for the fingerprint: {exc}")
        return None


def build_copy(
    src: ProgramRows,
    new_id: str,
    *,
    now: datetime,
    new_uuid: Callable[[], str] = _uuid4,
) -> ProgramRows:
    """New ORM rows for `new_id`, every evidence/skill/Need id fresh and rewired.

    Pure: reads `src`, mutates nothing, touches no session.
    """
    id_map: dict[str, str] = {}
    for e in src.evidence:
        id_map[e.evidence_id] = new_uuid()
    for s in src.skills:
        id_map[s.skill_id] = new_uuid()
    for n in src.needs:
        id_map[n.need_id] = new_uuid()

    program = _clone(src.program, id_map, program_id=new_id, created_at=now, copied_from=src.program.program_id)
    evidence = [_clone(e, id_map, program_id=new_id) for e in src.evidence]
    skills = [_clone(s, id_map, program_id=new_id) for s in src.skills]
    needs = [_clone(n, id_map, program_id=new_id) for n in src.needs]
    plos = [_clone(p, id_map, program_id=new_id) for p in src.plos]

    review: PLOReviewTable | None = None
    if src.review is not None:
        # The fingerprint hashes source_need_ids, which just changed. A review
        # that was current for the source is recomputed so it stays current for
        # the copy; a stale one keeps its old fingerprint and so stays stale.
        source_fp = _fingerprint(src.plos)
        copied_fp = _fingerprint(plos)
        fingerprint = src.review.plo_fingerprint
        if source_fp is not None and copied_fp is not None and fingerprint == source_fp:
            fingerprint = copied_fp
        review = _clone(src.review, id_map, program_id=new_id, plo_fingerprint=fingerprint)

    return ProgramRows(
        program=program, evidence=evidence, skills=skills, needs=needs, plos=plos, review=review
    )
```

(`replace` is unused here — drop it from the import if ruff flags it. Wrap the long `program = ...` line per ruff format.)

- [ ] **Step 4: Run tests** — new file, then full suite + ruff + format + mypy.

- [ ] **Step 5: Mutation checks** — (a) make `remap_ids` return `value` for `str` unchanged → `test_no_old_id_survives_anywhere_in_the_copy` fails; (b) drop the fingerprint recompute (always keep `src.review.plo_fingerprint`) → `test_a_current_review_stays_current_in_the_copy` fails. Restore both with Edit.

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/data/program_copy.py tests/unit/test_program_copy_build.py
git commit -m "feat(data): build a program copy under fresh ids with every reference rewired

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Copy I/O and `POST /programs/{id}/copy`

**Files:**
- Modify: `src/curriculum_agent/data/program_copy.py` (add `load_rows`, `copy_program`)
- Modify: `src/curriculum_agent/stages/plo_synthesis.py` (add `is_synthesis_running`)
- Modify: `src/curriculum_agent/api/routes/programs.py` (add `_generate_copy_id`, `copy_program_route`)
- Test: `tests/unit/test_program_copy_route.py` (new)

**Interfaces:**
- Consumes: `ProgramRows`, `build_copy` (Task 3); `ProgramMetadata.copied_from` (Task 2).
- Produces: `async def load_rows(session: AsyncSession, program_id: str) -> ProgramRows | None`; `async def copy_program(source_id: str, new_id: str, *, now: datetime | None = None) -> bool` (False when the source is gone); `plo_synthesis.is_synthesis_running(program_id: str) -> bool`; `POST /programs/{program_id}/copy -> ProgramMetadata`.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_program_copy_route.py`

```python
"""POST /programs/{id}/copy and the one-session copy behind it."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError

from curriculum_agent import config as cfg
from curriculum_agent.api.main import app
from curriculum_agent.api.routes import programs as programs_route
from curriculum_agent.data import program_copy as pc
from curriculum_agent.models import ProgramMetadata
from curriculum_agent.stages import plo_synthesis as ps

client = TestClient(app)

_COPY = ProgramMetadata(
    program_id="program-2-run-1",
    field="การท่องเที่ยว",
    degree_level="bachelor",
    duration_years=4,
    faculty="คณะ",
    university="มหาวิทยาลัย",
    copied_from="program-2",
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    taken: set[str] = {"program-2"}

    async def exists(self, program_id: str) -> bool:  # noqa: ANN001
        return program_id in taken

    copy = AsyncMock(return_value=True)
    get = AsyncMock(return_value=_COPY)
    monkeypatch.setattr(programs_route.ProgramRepository, "exists", exists)
    monkeypatch.setattr(programs_route.ProgramRepository, "get", get)
    monkeypatch.setattr(programs_route, "copy_program", copy)
    graph = MagicMock(aupdate_state=AsyncMock())
    app.state.graph = graph
    ps._SYNTHESIS_IN_FLIGHT.clear()
    return {"copy": copy, "get": get, "taken": taken, "graph": graph}  # type: ignore[dict-item]


def test_copy_names_the_first_free_run_number(env) -> None:  # noqa: ANN001
    r = client.post("/programs/program-2/copy")
    assert r.status_code == 200
    assert env["copy"].await_args.args[:2] == ("program-2", "program-2-run-1")

    env["taken"].add("program-2-run-1")
    client.post("/programs/program-2/copy")
    assert env["copy"].await_args.args[:2] == ("program-2", "program-2-run-2")


def test_copy_returns_the_copy_metadata(env) -> None:  # noqa: ANN001
    r = client.post("/programs/program-2/copy")
    assert r.json()["program_id"] == "program-2-run-1"
    assert r.json()["copied_from"] == "program-2"


def test_copy_seeds_the_copy_thread_like_create_does(env) -> None:  # noqa: ANN001
    client.post("/programs/program-2/copy")
    config = env["graph"].aupdate_state.await_args.args[0]
    assert config == {"configurable": {"thread_id": "program-2-run-1"}}


def test_copy_of_an_unknown_program_is_404(env) -> None:  # noqa: ANN001
    assert client.post("/programs/nope/copy").status_code == 404
    env["copy"].assert_not_awaited()


def test_copy_while_synthesis_runs_is_409(env) -> None:  # noqa: ANN001
    ps._SYNTHESIS_IN_FLIGHT.add("program-2")
    try:
        assert client.post("/programs/program-2/copy").status_code == 409
    finally:
        ps._SYNTHESIS_IN_FLIGHT.clear()
    env["copy"].assert_not_awaited()


def test_copy_retries_with_the_next_id_on_a_collision(env) -> None:  # noqa: ANN001
    calls: list[str] = []

    async def collide_once(source_id: str, new_id: str, **_: object) -> bool:
        calls.append(new_id)
        if len(calls) == 1:
            env["taken"].add(new_id)
            raise IntegrityError("insert", {}, Exception("duplicate"))
        return True

    env["copy"].side_effect = collide_once
    assert client.post("/programs/program-2/copy").status_code == 200
    assert calls == ["program-2-run-1", "program-2-run-2"]


def test_copy_requires_the_api_key(env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(cfg.settings, "api_key", SecretStr("secret-key"))
    assert client.post("/programs/program-2/copy").status_code == 401


# --------------------------- copy_program (mocked session) ---------------------------


def _session_ctx(session: AsyncMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


async def test_copy_program_adds_every_group_and_commits_once(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    session.add_all = MagicMock()
    session.add = MagicMock()
    src = MagicMock()
    built = pc.ProgramRows(
        program=MagicMock(), evidence=[MagicMock()], skills=[MagicMock()],
        needs=[MagicMock()], plos=[MagicMock()], review=MagicMock(),
    )
    monkeypatch.setattr(pc, "load_rows", AsyncMock(return_value=src))
    monkeypatch.setattr(pc, "build_copy", MagicMock(return_value=built))
    with patch.object(pc, "AsyncSessionLocal", return_value=_session_ctx(session)):
        assert await pc.copy_program("program-2", "program-2-run-1", now=datetime(2026, 10, 6)) is True
    session.commit.assert_awaited_once()
    added = [c.args[0] for c in session.add.call_args_list]
    assert added == [built.program, built.review]
    groups = [c.args[0] for c in session.add_all.call_args_list]
    assert groups == [built.evidence, built.skills, built.needs, built.plos]


async def test_copy_program_commits_nothing_when_an_insert_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    session.add_all = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock(side_effect=[None, None, None, RuntimeError("needs insert failed")])
    built = pc.ProgramRows(
        program=MagicMock(), evidence=[], skills=[], needs=[], plos=[], review=None,
    )
    monkeypatch.setattr(pc, "load_rows", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(pc, "build_copy", MagicMock(return_value=built))
    with patch.object(pc, "AsyncSessionLocal", return_value=_session_ctx(session)):
        with pytest.raises(RuntimeError):
            await pc.copy_program("program-2", "program-2-run-1")
    session.commit.assert_not_awaited()


async def test_copy_program_returns_false_when_the_source_is_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(pc, "load_rows", AsyncMock(return_value=None))
    with patch.object(pc, "AsyncSessionLocal", return_value=_session_ctx(session)):
        assert await pc.copy_program("gone", "gone-run-1") is False
    session.commit.assert_not_awaited()
```

`copy_program` flushes once after each group (program, evidence, skills, needs, plos) before adding the review and committing — the rollback test counts on flush being awaited per group, so keep the flush order exactly: program → evidence → skills → needs → plos.

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/unit/test_program_copy_route.py -v` → FAIL.

- [ ] **Step 3: Implement I/O** — append to `src/curriculum_agent/data/program_copy.py`

```python
async def load_rows(session: AsyncSession, program_id: str) -> ProgramRows | None:
    program = await session.get(ProgramTable, program_id)
    if program is None:
        return None

    async def _all(table: type[_Row], column: Any) -> list[_Row]:
        return list((await session.execute(select(table).where(column == program_id))).scalars().all())

    return ProgramRows(
        program=program,
        evidence=await _all(EvidenceTable, EvidenceTable.program_id),
        skills=await _all(SkillTable, SkillTable.program_id),
        needs=await _all(NeedTable, NeedTable.program_id),
        plos=await _all(PLOTable, PLOTable.program_id),
        review=await session.get(PLOReviewTable, program_id),
    )


async def copy_program(source_id: str, new_id: str, *, now: datetime | None = None) -> bool:
    """Copy `source_id` to `new_id` in one session. False if the source is gone.

    One commit at the end, so a failure anywhere leaves nothing behind. A flush
    after each group puts the parent rows in before the rows whose foreign keys
    point at them; the ORM declares no relationships to order them otherwise.
    An IntegrityError on the program row (id taken concurrently) propagates for
    the route to retry under the next id.
    """
    async with AsyncSessionLocal() as session:
        src = await load_rows(session, source_id)
        if src is None:
            return False
        copy = build_copy(src, new_id, now=now or datetime.utcnow())
        session.add(copy.program)
        await session.flush()
        for group in (copy.evidence, copy.skills, copy.needs, copy.plos):
            session.add_all(group)
            await session.flush()
        if copy.review is not None:
            session.add(copy.review)
        await session.commit()
    logger.info(
        f"program copy: {source_id} -> {new_id} ({len(copy.evidence)} evidence, "
        f"{len(copy.skills)} skills, {len(copy.needs)} Needs, {len(copy.plos)} PLOs, "
        f"review={'yes' if copy.review is not None else 'no'})"
    )
    return True
```

Imports to add: `from sqlalchemy import select`, `from sqlalchemy.ext.asyncio import AsyncSession`, `from curriculum_agent.data.postgres import AsyncSessionLocal`. Note the rollback test makes the 4th flush (needs) raise — program, evidence, skills flushes succeed, the needs flush raises, and commit must never run.

`src/curriculum_agent/stages/plo_synthesis.py`, next to `_SYNTHESIS_IN_FLIGHT`:

```python
def is_synthesis_running(program_id: str) -> bool:
    """Whether this process has a synthesis run in flight for the program."""
    return program_id in _SYNTHESIS_IN_FLIGHT
```

`src/curriculum_agent/api/routes/programs.py`:

```python
async def _generate_copy_id(source_id: str, repo: ProgramRepository) -> str:
    """`{source}-run-{n}`, smallest n >= 1 not taken. A copy of a copy nests
    (`program-2-run-1-run-1`) — accepted, the rule stays one line."""
    n = 1
    while await repo.exists(f"{source_id}-run-{n}"):
        n += 1
    return f"{source_id}-run-{n}"


@router.post(
    "/{program_id}/copy",
    response_model=ProgramMetadata,
    dependencies=[Depends(require_api_key)],
)
async def copy_program_route(program_id: str, request: Request) -> ProgramMetadata:
    """Copy a program with everything it owns, so one run survives the next.

    Refused while the source has a synthesis run in flight: synthesis deletes
    and then inserts, so a copy taken mid-run would hold half a set.
    need_combination has no such guard, so a copy taken during it is not
    prevented.
    """
    from curriculum_agent.stages.plo_synthesis import is_synthesis_running  # noqa: PLC0415

    repo = ProgramRepository()
    if not await repo.exists(program_id):
        raise HTTPException(status_code=404, detail="ไม่พบหลักสูตรนี้")
    if is_synthesis_running(program_id):
        raise HTTPException(
            status_code=409,
            detail="หลักสูตรนี้กำลังสังเคราะห์ PLO อยู่ — รอให้เสร็จก่อนจึงคัดลอก",
        )

    for _ in range(_MAX_ID_ATTEMPTS):
        new_id = await _generate_copy_id(program_id, repo)
        try:
            copied = await copy_program(program_id, new_id)
        except IntegrityError:
            logger.warning(f"program_id '{new_id}' taken concurrently, retrying")
            continue
        if not copied:
            raise HTTPException(status_code=404, detail="ไม่พบหลักสูตรนี้")
        metadata = await repo.get(new_id)
        if metadata is None:  # pragma: no cover - just committed
            raise HTTPException(status_code=500, detail="คัดลอกแล้วแต่อ่านกลับไม่ได้")
        # Seed the copy's own thread the way create_program does, so every path
        # that works on a new program works on a copy.
        graph = request.app.state.graph
        await graph.aupdate_state(
            {"configurable": {"thread_id": new_id}},
            {"program_id": new_id, "metadata": metadata.model_dump(mode="json")},
            as_node=START,
        )
        return metadata
    raise HTTPException(status_code=409, detail="สร้างรหัสสำเนาไม่สำเร็จ กรุณาลองใหม่อีกครั้ง")
```

Import `copy_program` at module top: `from curriculum_agent.data.program_copy import copy_program`. If that creates an import cycle at app start (program_copy → stages.plo_review → repositories), import it inside the route instead and patch `curriculum_agent.data.program_copy.copy_program` in the tests — say which you did in the report.

- [ ] **Step 4: Run tests** — new file, then full suite + ruff + format + mypy.

- [ ] **Step 5: Mutation checks** — (a) remove the `is_synthesis_running` check → `test_copy_while_synthesis_runs_is_409` fails; (b) move `await session.commit()` above the group loop → `test_copy_program_commits_nothing_when_an_insert_fails` fails. Restore both.

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/data/program_copy.py src/curriculum_agent/stages/plo_synthesis.py src/curriculum_agent/api/routes/programs.py tests/unit/test_program_copy_route.py
git commit -m "feat(programs): POST /programs/{id}/copy copies a program for run comparison

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Docs and the frontend handoff

**Files:**
- Modify: `CLAUDE.md` (Common pitfalls: one paragraph)
- Modify: `.claude/skills/curriculum-design-agent/references/data-schemas.md` (`copied_from`)
- Create: `.scratch/handoffs/2026-10-06-run-comparison-frontend.md`

- [ ] **Step 1: CLAUDE.md** — add one pitfall after "The set review advises; nothing reads it back.":

```markdown
- **A program copy re-keys every evidence, skill and Need id; the validator
  switch skips only the agent.** `POST /programs/{id}/copy` (`data/program_copy.py`)
  exists so one synthesis run survives the next. `evidence_id`, `skill_id` and
  `need_id` are global single-column keys, so the copy mints fresh uuids and
  `remap_ids` rewrites every value equal to an old id — reference columns and
  JSONB alike; `plo_id` is kept, since a PLO is `(program_id, plo_id)`. Rows are
  cloned from the table's columns, so a new column is copied by default. A
  review current for the source is re-fingerprinted to stay current; a stale
  one stays stale. `copied_from` is on `ProgramMetadata`, not the create request,
  and `PUT` carries it over. `POST /plos/run` with `run_validation=false` gives
  `ValidationReason.SKIPPED` — distinct from `.env`'s `DISABLED`, which wins —
  and `hard_failures` still runs: immutable rule 5 is untouched.
```

- [ ] **Step 2: data-schemas.md** — in the program/ProgramMetadata section add one bullet: `copied_from: str | None` — set only by `POST /programs/{id}/copy`; nullable, not a foreign key; not accepted from clients. Edit nothing else under `.claude/skills`.

- [ ] **Step 3: Handoff note** — `.scratch/handoffs/2026-10-06-run-comparison-frontend.md`, in Thai, for the frontend session:
  - PLO synthesis page: checkbox "ตรวจด้วย validation agent" next to the run button, default on; sends `run_validation` in the `POST /programs/{id}/plos/run` body together with `note_th`. On page load call `GET /programs/{id}/plos/validation` → `{enabled, model}`; when `enabled=false` disable the checkbox (unchecked) with "ปิดไว้ในการตั้งค่าระบบ (VALIDATION_PROVIDER)"; when enabled show the model name.
  - PLO card: badge "ไม่ได้ตรวจ" when `smart_validated_by === "code_only"`, with `smart_diagnosis_th` as its tooltip (it says whether the run switched it off or the system did).
  - Programs list/detail: a "คัดลอก" button calling `POST /programs/{id}/copy` (needs the API key header like create/delete); on success navigate to or highlight the returned `program_id`; 409 shows the Thai `detail`.
  - Programs list: "สำเนาของ {copied_from}" under a copy's row (`ProgramSummary.copied_from`).
  - Exact response shapes (`ValidationStatusResponse`, `ProgramMetadata.copied_from`, `ProgramSummary.copied_from`).

- [ ] **Step 4: Verify and commit** — `uv run python scripts/dump_prompts.py --check` (no prompt changed) and the full suite.

```bash
git add CLAUDE.md .claude/skills/curriculum-design-agent/references/data-schemas.md
git commit -m "docs: program copies and the per-run validator switch

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

The handoff note is under `.scratch/handoffs/` — check `git check-ignore -v .scratch/handoffs/x.md`; if `.scratch` is tracked, add the note to the commit by explicit path, otherwise leave it uncommitted and say so.

---

### Task 6 (controller): live migration and smoke

Done by the controller, not a subagent.

- [ ] `uv run alembic upgrade head` → `c0f1e2d3a4b5`.
- [ ] Restart the backend is the user's step; instead run the copy directly: a short script calling `copy_program("program-2", "program-2-run-1")` (selector event loop on Windows), then read back counts per table for both ids and check: equal counts; no shared evidence/skill/Need id between them; every copied reference resolves inside the copy; the copied review is not stale.
- [ ] Leave `program-2-run-1` in place for the user's comparison (it is the snapshot of the current tourism run).
