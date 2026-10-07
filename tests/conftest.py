from __future__ import annotations

import sys
from collections.abc import Iterator
from unittest.mock import AsyncMock

if sys.platform == "win32":
    # Block `import magic` (python-magic) on Windows. Under Git Bash the PATH
    # contains C:\Program Files\Git\usr\bin, so python-magic's loader picks up
    # msys-magic-1.dll — an MSYS2 build whose runtime is incompatible with
    # native CPython. Loading it segfaults or hangs the whole pytest process.
    # Forcing ImportError instead makes unstructured take its extension-based
    # fallback (LIBMAGIC_AVAILABLE = False), which is deterministic across
    # shells. Remove this once a native libmagic (e.g. python-magic-bin) is a
    # project dependency.
    sys.modules["magic"] = None  # type: ignore[assignment]

import pytest

from curriculum_agent.config import Settings, settings
from curriculum_agent.models import (
    PLO,
    BloomLevel,
    KSECCategory,
    Need,
    ProgramMetadata,
    SMARTCheck,
)
from tests.support.jobs import InMemoryJobs, SpawnRecorder

SMART_PASS = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)
SMART_FAIL = SMARTCheck(
    specific=True, measurable=False, achievable=True, relevant=True, timely=True
)


@pytest.fixture(autouse=True)
def _settings_env_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every Settings field from the process environment before a test
    runs. `Settings(_env_file=None)` stops pydantic-settings reading `.env`, but
    it never stopped it reading `os.environ` — so a test asserting a *default*
    passed or failed depending on what the developer's shell happened to carry.
    `scripts/start-demo.ps1` sets SERVE_FRONTEND and CORS_ORIGINS in the session
    it runs in, which is enough to fail four config tests in the same terminal
    afterwards. A test that wants an env var sets it itself with
    `monkeypatch.setenv`, which still works: this clears at setup, not during
    the test body."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _default_api_key_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests assume auth is disabled (settings.api_key is None) unless a test
    explicitly monkeypatches it otherwise. Without this, a developer's local
    .env with a real API_KEY leaks into the whole suite via pydantic-settings'
    env loading, turning every unauthenticated-request test into a spurious
    401."""
    monkeypatch.setattr(settings, "api_key", None)


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


class _NoStoredReview:
    async def get(self, program_id: str) -> None:
        return None

    async def upsert(self, review: object) -> None:
        return None


@pytest.fixture(autouse=True)
def _plo_review_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """The set review runs before every report, and both reach the network and
    the database. Off by default in tests — the same answer as the kill switch,
    so every report test sees `review=None` exactly as before the review existed.
    The review's own tests turn it back on and fake each boundary themselves."""
    from curriculum_agent.stages import plo_review  # noqa: PLC0415

    monkeypatch.setattr(settings, "plo_review_provider", "")
    monkeypatch.setattr(plo_review, "PLOReviewRepository", _NoStoredReview)


@pytest.fixture(autouse=True)
def jobs_store(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemoryJobs]:
    """Every test runs jobs against memory and records spawned bodies instead
    of starting tasks. No running graph session unless a test says so."""
    from curriculum_agent.api import jobs as jobs_mod  # noqa: PLC0415

    store = InMemoryJobs()
    recorder = SpawnRecorder()
    monkeypatch.setattr(jobs_mod, "JobRepository", lambda: store)
    monkeypatch.setattr(jobs_mod, "spawn", recorder)
    monkeypatch.setattr(jobs_mod, "_running_session", AsyncMock(return_value=False))
    jobs_mod._LOCKS.clear()
    store.recorder = recorder  # type: ignore[attr-defined]
    yield store
    recorder.close()


@pytest.fixture
def spawned(jobs_store: InMemoryJobs) -> SpawnRecorder:
    return jobs_store.recorder  # type: ignore[attr-defined, no-any-return]


@pytest.fixture
def program_metadata() -> ProgramMetadata:
    return ProgramMetadata(
        program_id="cs-test",
        name_th="วิทยาการคอมพิวเตอร์",
        name_en="Computer Science",
        field="Computer Science",
        degree_level="bachelor",
        duration_years=4,
        faculty="วิศวกรรมศาสตร์",
        university="มหาวิทยาลัยทดสอบ",
        program_goals_th=["เป้าหมายหลักสูตรที่ 1"],
        program_objectives_th=["ผลิตบัณฑิตที่มีทักษะด้านซอฟต์แวร์"],
    )


@pytest.fixture
def need() -> Need:
    return Need(
        need_id="N1",
        program_id="cs-test",
        statement_th="สามารถเขียนและออกแบบโปรแกรมตามความต้องการของธุรกิจ",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.CREATE,
        member_skill_ids=["S1", "S2"],
        source_evidence_ids=["E1"],
        freq=2,
        demand_score=0.9,
    )


@pytest.fixture
def valid_plo(need: Need) -> PLO:
    return PLO(
        plo_id="PLO1",
        program_id="cs-test",
        statement_th="ออกแบบและพัฒนาซอฟต์แวร์ที่มีคุณภาพได้",
        bloom_level=BloomLevel.CREATE,
        action_verb_th="ออกแบบ",
        smart_check=SMART_PASS,
        source_need_ids=[need.need_id],
        source_evidence_ids=need.source_evidence_ids,
        rationale_th="ทักษะหลักที่นายจ้างต้องการ",
    )


@pytest.fixture
def sample_metadata() -> ProgramMetadata:
    return ProgramMetadata(
        program_id="cs-test",
        name_th="วิทยาการคอมพิวเตอร์",
        name_en="Computer Science",
        field="Computer Science",
        degree_level="bachelor",
        duration_years=4,
        faculty="วิศวกรรมศาสตร์",
        university="มหาวิทยาลัยทดสอบ",
        program_goals_th=["เป้าหมายหลักสูตรที่ 1"],
        program_objectives_th=["ผลิตบัณฑิตที่มีทักษะด้านซอฟต์แวร์"],
    )


@pytest.fixture
def sample_needs(sample_metadata: ProgramMetadata) -> list[Need]:
    return [
        Need(
            need_id="C1",
            program_id=sample_metadata.program_id,
            statement_th="สามารถเขียนและออกแบบโปรแกรมตามความต้องการของธุรกิจ",
            ksec_category=KSECCategory.S,
            bloom_level=BloomLevel.CREATE,
            member_skill_ids=["S1", "S2"],
            source_evidence_ids=["E1"],
            freq=2,
            demand_score=0.9,
        )
    ]
