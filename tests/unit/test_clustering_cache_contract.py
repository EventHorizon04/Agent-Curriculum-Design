"""The clustering cache must not replay a grouping it cannot vouch for.

Two gaps, both the same class as the extraction-cache defect that killed Stage 3:
the key did not cover the response schemas or the prompts, so changing either
left old entries matching; and a cached grouping was replayed raw, bypassing the
`validate_assignments` repair that every freshly computed grouping goes through.
A stale or malformed entry could hand the caller an out-of-range index (it does
`bucket[i]`) or a partial cover, losing skills silently.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from curriculum_agent.stages import llm_clustering as lc

_NAMES = ["เขียนโปรแกรมเว็บ", "ออกแบบฐานข้อมูล", "ทดสอบซอฟต์แวร์"]


def test_valid_partition_accepts_an_exact_cover():
    assert lc.is_valid_partition([[0, 1], [2]], 3) is True
    assert lc.is_valid_partition([[2], [1], [0]], 3) is True


@pytest.mark.parametrize(
    ("groups", "why"),
    [
        ([[0, 1]], "index 2 never assigned — the skill would vanish"),
        ([[0, 1], [1, 2]], "index 1 assigned twice"),
        ([[0, 1], [2, 3]], "index 3 is out of range — IndexError in the caller"),
        ([[0, 1], [-1]], "negative index silently reads from the end of the list"),
        ([], "nothing assigned at all"),
    ],
)
def test_valid_partition_rejects_a_bad_cover(groups: list[list[int]], why: str):
    assert lc.is_valid_partition(groups, 3) is False, why


def test_contract_fingerprint_is_stable_across_calls():
    assert lc._clustering_contract_fingerprint() == lc._clustering_contract_fingerprint()


def test_contract_fingerprint_changes_when_a_prompt_changes(monkeypatch: pytest.MonkeyPatch):
    before = lc._clustering_contract_fingerprint()

    def _reworded(
        names: list[str],
        target: int | None = None,
        program_context: str | None = None,
        ksec: object = None,
    ) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": "cluster them however you like"},
            {"role": "user", "content": ""},
        ]

    monkeypatch.setattr(lc, "build_cluster_skills_prompt", _reworded)
    assert lc._clustering_contract_fingerprint() != before


def test_contract_fingerprint_changes_when_a_response_schema_changes(
    monkeypatch: pytest.MonkeyPatch,
):
    before = lc._clustering_contract_fingerprint()

    class _Widened(lc.MergeGroupsResponse):
        rationale: str | None = None

    monkeypatch.setattr(lc, "MergeGroupsResponse", _Widened)
    assert lc._clustering_contract_fingerprint() != before


async def test_cache_key_actually_incorporates_the_contract(monkeypatch: pytest.MonkeyPatch):
    """The fingerprint must be used in the key, not merely computed.

    Drop it from the key and the fingerprint tests above still pass while stale
    entries start matching again — so capture the key the code really looks up.
    """
    seen: list[str] = []

    async def capture(self, key: str):  # noqa: ANN001, ANN202
        seen.append(key)
        return None

    monkeypatch.setattr(lc.LLMCacheRepository, "get", capture)
    monkeypatch.setattr(lc.LLMCacheRepository, "set", AsyncMock())
    monkeypatch.setattr(lc, "_cluster_pass", AsyncMock(return_value=[("g", [0, 1, 2])]))

    monkeypatch.setattr(lc, "_CLUSTERING_CONTRACT", "contract-one")
    await lc.cluster_skill_names(list(_NAMES))
    monkeypatch.setattr(lc, "_CLUSTERING_CONTRACT", "contract-two")
    await lc.cluster_skill_names(list(_NAMES))

    assert len(seen) == 2
    assert seen[0] != seen[1], "cache key ignores the contract fingerprint"


async def test_cached_partial_cover_is_discarded_and_recomputed(
    monkeypatch: pytest.MonkeyPatch,
):
    """A cached grouping that drops a name must not be handed back."""
    monkeypatch.setattr(
        lc.LLMCacheRepository,
        "get",
        AsyncMock(return_value=("stub-heavy", json.dumps([[0, 1]]))),  # index 2 missing
    )
    setter = AsyncMock()
    monkeypatch.setattr(lc.LLMCacheRepository, "set", setter)
    monkeypatch.setattr(lc.settings, "clustering_model", "stub-heavy")
    recompute = AsyncMock(return_value=[("g", [0, 1, 2])])
    monkeypatch.setattr(lc, "_cluster_pass", recompute)

    groups = await lc.cluster_skill_names(list(_NAMES))

    recompute.assert_awaited_once()
    assert lc.is_valid_partition(groups, len(_NAMES))


async def test_cached_out_of_range_index_is_discarded(monkeypatch: pytest.MonkeyPatch):
    """An out-of-range cached index would be an IndexError in the caller."""
    monkeypatch.setattr(
        lc.LLMCacheRepository,
        "get",
        AsyncMock(return_value=("stub-heavy", json.dumps([[0, 1], [2, 99]]))),
    )
    monkeypatch.setattr(lc.LLMCacheRepository, "set", AsyncMock())
    monkeypatch.setattr(lc.settings, "clustering_model", "stub-heavy")
    recompute = AsyncMock(return_value=[("g", [0, 1, 2])])
    monkeypatch.setattr(lc, "_cluster_pass", recompute)

    groups = await lc.cluster_skill_names(list(_NAMES))

    recompute.assert_awaited_once()
    assert max(i for g in groups for i in g) < len(_NAMES)


async def test_valid_cached_grouping_is_reused_without_recomputing(
    monkeypatch: pytest.MonkeyPatch,
):
    """The guard must not defeat the cache for well-formed entries."""
    monkeypatch.setattr(
        lc.LLMCacheRepository,
        "get",
        AsyncMock(return_value=("stub-heavy", json.dumps([[0, 2], [1]]))),
    )
    monkeypatch.setattr(lc.LLMCacheRepository, "set", AsyncMock())
    monkeypatch.setattr(lc.settings, "clustering_model", "stub-heavy")
    recompute = AsyncMock(return_value=[("g", [0, 1, 2])])
    monkeypatch.setattr(lc, "_cluster_pass", recompute)

    groups = await lc.cluster_skill_names(list(_NAMES))

    recompute.assert_not_awaited()
    assert groups == [[0, 2], [1]]


async def test_cache_key_separates_programs_with_different_contexts(
    monkeypatch: pytest.MonkeyPatch,
):
    """The context goes into the prompt, so it has to go into the key.

    Same reasoning as target_clusters: the contract fingerprint covers only the
    instructions that do not vary per call, so without this a nursing program
    would be served the grouping computed for an engineering one — the same skill
    names, read against a different field.
    """
    seen: list[str] = []

    async def capture(self, key: str):  # noqa: ANN001, ANN202
        seen.append(key)
        return None

    monkeypatch.setattr(lc.LLMCacheRepository, "get", capture)
    monkeypatch.setattr(lc.LLMCacheRepository, "set", AsyncMock())
    monkeypatch.setattr(lc, "_cluster_pass", AsyncMock(return_value=[("g", [0, 1, 2])]))

    await lc.cluster_skill_names(list(_NAMES), None, "หลักสูตรสาขาพยาบาลศาสตร์")
    await lc.cluster_skill_names(list(_NAMES), None, "หลักสูตรสาขาวิศวกรรมซอฟต์แวร์")
    await lc.cluster_skill_names(list(_NAMES))

    assert len(seen) == 3
    assert len(set(seen)) == 3, "cache key ignores the program context"


async def test_program_context_reaches_the_clustering_prompt(monkeypatch: pytest.MonkeyPatch):
    """Threading it through the key is not enough — the model has to see it."""
    captured: dict[str, str | None] = {}

    async def capture_pass(names, target, program_context=None, ksec=None):  # noqa: ANN001, ANN202
        captured["context"] = program_context
        return [("g", list(range(len(names))))]

    monkeypatch.setattr(lc.LLMCacheRepository, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(lc.LLMCacheRepository, "set", AsyncMock())
    monkeypatch.setattr(lc, "_cluster_pass", capture_pass)

    await lc.cluster_skill_names(list(_NAMES), None, "หลักสูตรสาขาพยาบาลศาสตร์")
    assert captured["context"] == "หลักสูตรสาขาพยาบาลศาสตร์"


def test_contract_fingerprint_covers_the_context_branch(monkeypatch: pytest.MonkeyPatch):
    """Rewording the context instructions must invalidate old entries too.

    The fingerprint samples the prompts by building them. Build them only without
    a program context and half the instructions never reach the hash: entries
    produced under an older context rule keep matching, which is the exact defect
    the fingerprint exists to prevent.
    """
    before = lc._clustering_contract_fingerprint()
    real = lc.build_cluster_skills_prompt

    def _reworded_context(names, target=None, program_context=None, ksec=None):  # noqa: ANN001, ANN202
        messages = real(names, target, program_context, ksec)
        if program_context:
            messages[0] = {"role": "system", "content": "group them however the field suggests"}
        return messages

    monkeypatch.setattr(lc, "build_cluster_skills_prompt", _reworded_context)
    assert lc._clustering_contract_fingerprint() != before


async def test_cache_key_differs_by_ksec(monkeypatch: pytest.MonkeyPatch):
    """The prompt varies by bucket now, so the bucket has to be in the key."""
    from curriculum_agent.models import KSECCategory

    seen: list[str] = []

    async def capture(self, key: str):  # noqa: ANN001, ANN202
        seen.append(key)
        return None

    monkeypatch.setattr(lc.LLMCacheRepository, "get", capture)
    monkeypatch.setattr(lc.LLMCacheRepository, "set", AsyncMock())
    monkeypatch.setattr(lc, "_cluster_pass", AsyncMock(return_value=[("g", [0, 1, 2])]))

    await lc.cluster_skill_names(list(_NAMES), None, None, KSECCategory.EC)
    await lc.cluster_skill_names(list(_NAMES), None, None, KSECCategory.K)
    await lc.cluster_skill_names(list(_NAMES))

    assert len(set(seen)) == 3, "cache key ignores the KSEC bucket"


async def test_ksec_reaches_the_single_pass(monkeypatch: pytest.MonkeyPatch):
    from curriculum_agent.models import KSECCategory

    got: list[KSECCategory | None] = []

    async def capture_pass(names, target, program_context=None, ksec=None):  # noqa: ANN001, ANN202
        got.append(ksec)
        return [("g", list(range(len(names))))]

    monkeypatch.setattr(lc.LLMCacheRepository, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(lc.LLMCacheRepository, "set", AsyncMock())
    monkeypatch.setattr(lc, "_cluster_pass", capture_pass)
    await lc.cluster_skill_names(list(_NAMES), None, None, KSECCategory.EC)
    assert got == [KSECCategory.EC]


def test_contract_fingerprint_covers_the_ec_variant(monkeypatch: pytest.MonkeyPatch):
    before = lc._clustering_contract_fingerprint()
    real = lc.build_cluster_skills_prompt

    def _reworded_ec(names, target=None, program_context=None, ksec=None):  # noqa: ANN001, ANN202
        messages = real(names, target, program_context, ksec)
        if ksec is not None and ksec.value == "EC":
            messages[0] = {"role": "system", "content": "group traits however"}
        return messages

    monkeypatch.setattr(lc, "build_cluster_skills_prompt", _reworded_ec)
    assert lc._clustering_contract_fingerprint() != before


async def test_ksec_reaches_every_map_reduce_batch_and_not_the_merge(
    monkeypatch: pytest.MonkeyPatch,
):
    from curriculum_agent.models import KSECCategory
    from curriculum_agent.prompts.cluster_skills import build_merge_clusters_prompt

    got: list[KSECCategory | None] = []
    merge_prompts: list[object] = []

    async def capture_pass(names, target, program_context=None, ksec=None):  # noqa: ANN001, ANN202
        got.append(ksec)
        return [("g", list(range(len(names))))]

    async def capture_merge(schema, messages, **kwargs):  # noqa: ANN001, ANN202
        merge_prompts.append(messages)
        return lc.MergeGroupsResponse(groups=[[0, 1]])

    names = [f"skill {i}" for i in range(lc.SINGLE_PASS_MAX + 1)]
    monkeypatch.setattr(lc.LLMCacheRepository, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(lc.LLMCacheRepository, "set", AsyncMock())
    monkeypatch.setattr(lc, "_cluster_pass", capture_pass)
    monkeypatch.setattr(lc, "complete_clustering", capture_merge)

    await lc.cluster_skill_names(names, None, None, KSECCategory.EC)

    assert len(got) == len(lc.split_batches(names)) >= 2
    assert got == [KSECCategory.EC] * len(got)
    assert merge_prompts == [build_merge_clusters_prompt(["g"] * len(got), None)]
