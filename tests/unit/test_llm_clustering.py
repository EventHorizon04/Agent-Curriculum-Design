from __future__ import annotations

from unittest.mock import AsyncMock, patch

from curriculum_agent.config import settings
from curriculum_agent.stages.llm_clustering import (
    ClusterAssignment,
    ClusterAssignmentsResponse,
    MergeGroupsResponse,
    cluster_skill_names,
    dedupe_names,
    normalize_name,
    split_batches,
    validate_assignments,
)


def test_normalize_name_lowercases_and_collapses_whitespace():
    assert normalize_name("  Python   Programming ") == "python programming"
    assert normalize_name("การสื่อสาร") == "การสื่อสาร"


def test_dedupe_names_collapses_duplicates_and_tracks_indices():
    names = ["Python", "  python ", "SQL", "การสื่อสาร", "sql"]
    unique, groups = dedupe_names(names)
    # sorted by normalized form; Thai sorts after latin here
    assert unique == ["Python", "SQL", "การสื่อสาร"]
    assert groups == [[0, 1], [2, 4], [3]]


def test_dedupe_names_empty():
    assert dedupe_names([]) == ([], [])


def test_dedupe_names_skips_blank_names():
    assert dedupe_names(["Python", "   ", ""]) == (["Python"], [[0]])


def test_split_batches_splits_at_size():
    items = [str(i) for i in range(250)]
    batches = split_batches(items, size=100)
    assert [len(b) for b in batches] == [100, 100, 50]
    assert batches[2][0] == "200"


def test_validate_assignments_passes_clean_input_through():
    names = ["a", "b", "c"]
    clusters = [("g1", [0, 2]), ("g2", [1])]
    assert validate_assignments(clusters, names) == [("g1", [0, 2]), ("g2", [1])]


def test_validate_assignments_drops_hallucinated_and_duplicate_indices():
    names = ["a", "b"]
    clusters = [("g1", [0, 5, -1]), ("g2", [0, 1])]
    # index 5 and -1 out of range; second 0 already seen
    assert validate_assignments(clusters, names) == [("g1", [0]), ("g2", [1])]


def test_validate_assignments_missing_index_becomes_singleton():
    names = ["a", "b", "c"]
    clusters = [("g1", [0])]
    result = validate_assignments(clusters, names)
    assert ("g1", [0]) in result
    assert ("b", [1]) in result
    assert ("c", [2]) in result
    assert len(result) == 3


def test_validate_assignments_drops_within_cluster_duplicate_indices():
    names = ["a", "b"]
    clusters = [("g1", [0, 0])]
    # the second 0 is a duplicate within the same cluster's own index list
    assert validate_assignments(clusters, names) == [("g1", [0]), ("b", [1])]


def test_validate_assignments_empty_group_dropped():
    names = ["a"]
    clusters = [("empty", []), ("g1", [0])]
    assert validate_assignments(clusters, names) == [("g1", [0])]


def _mock_cache(hit: str | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=(settings.clustering_model, hit) if hit is not None else None)
    repo.set = AsyncMock()
    return repo


async def test_cluster_skill_names_empty_and_singleton_short_circuit():
    with patch(
        "curriculum_agent.stages.llm_clustering.complete_clustering", new=AsyncMock()
    ) as llm:
        assert await cluster_skill_names([]) == []
        assert await cluster_skill_names(["Python"]) == [[0]]
    llm.assert_not_called()


async def test_single_pass_clusters_validates_and_caches():
    resp = ClusterAssignmentsResponse(
        clusters=[
            ClusterAssignment(label_th="โปรแกรมมิ่ง", member_indices=[0, 1]),
            ClusterAssignment(label_th="สื่อสาร", member_indices=[2, 99]),  # 99 hallucinated
        ]
    )
    cache = _mock_cache()
    with (
        patch(
            "curriculum_agent.stages.llm_clustering.complete_clustering",
            new=AsyncMock(return_value=resp),
        ) as llm,
        patch(
            "curriculum_agent.stages.llm_clustering.LLMCacheRepository",
            return_value=cache,
        ),
    ):
        groups = await cluster_skill_names(["Python", "SQL", "การสื่อสาร"])

    assert groups == [[0, 1], [2]]
    assert llm.call_args.kwargs.get("temperature") == 0
    cache.set.assert_called_once()


async def test_cache_hit_skips_llm():
    cache = _mock_cache(hit="[[0, 2], [1]]")
    with (
        patch("curriculum_agent.stages.llm_clustering.complete_clustering", new=AsyncMock()) as llm,
        patch(
            "curriculum_agent.stages.llm_clustering.LLMCacheRepository",
            return_value=cache,
        ),
    ):
        groups = await cluster_skill_names(["a", "b", "c"])
    assert groups == [[0, 2], [1]]
    llm.assert_not_called()
    cache.set.assert_not_called()


async def test_cache_disabled_skips_get_and_set_and_calls_the_model(monkeypatch):
    monkeypatch.setattr(settings, "llm_cache_enabled", False)
    resp = ClusterAssignmentsResponse(
        clusters=[ClusterAssignment(label_th="x", member_indices=[0, 1, 2])]
    )
    cache = _mock_cache(hit="[[0, 2], [1]]")
    with (
        patch(
            "curriculum_agent.stages.llm_clustering.complete_clustering",
            new=AsyncMock(return_value=resp),
        ) as llm,
        patch(
            "curriculum_agent.stages.llm_clustering.LLMCacheRepository",
            return_value=cache,
        ),
    ):
        groups = await cluster_skill_names(["a", "b", "c"])
    assert groups == [[0, 1, 2]]
    llm.assert_called_once()
    cache.get.assert_not_called()
    cache.set.assert_not_called()


async def test_map_reduce_path_batches_then_merges():
    names = [f"skill-{i}" for i in range(160)]  # > SINGLE_PASS_MAX → 2 batches (100+60)
    batch_sizes = iter([100, 60])

    async def dispatch(response_model, messages, **kwargs):
        if response_model is ClusterAssignmentsResponse:
            size = next(batch_sizes)
            return ClusterAssignmentsResponse(
                clusters=[ClusterAssignment(label_th="กลุ่ม", member_indices=list(range(size)))]
            )
        if response_model is MergeGroupsResponse:
            return MergeGroupsResponse(groups=[[0, 1]])
        raise AssertionError(f"unexpected response_model {response_model}")

    cache = _mock_cache()
    with (
        patch(
            "curriculum_agent.stages.llm_clustering.complete_clustering",
            new=AsyncMock(side_effect=dispatch),
        ) as llm,
        patch(
            "curriculum_agent.stages.llm_clustering.LLMCacheRepository",
            return_value=cache,
        ),
    ):
        groups = await cluster_skill_names(names)

    assert llm.call_count == 3  # 2 batch passes + 1 merge
    assert groups == [sorted(range(160))]
    cache.set.assert_called_once()


async def test_both_clustering_calls_bound_hidden_reasoning():
    names = [f"skill-{i}" for i in range(160)]  # 2 batch passes + 1 merge
    batch_sizes = iter([100, 60])

    async def dispatch(response_model, messages, **kwargs):
        if response_model is ClusterAssignmentsResponse:
            size = next(batch_sizes)
            return ClusterAssignmentsResponse(
                clusters=[ClusterAssignment(label_th="กลุ่ม", member_indices=list(range(size)))]
            )
        return MergeGroupsResponse(groups=[[0, 1]])

    with (
        patch(
            "curriculum_agent.stages.llm_clustering.complete_clustering",
            new=AsyncMock(side_effect=dispatch),
        ) as llm,
        patch(
            "curriculum_agent.stages.llm_clustering.LLMCacheRepository",
            return_value=_mock_cache(),
        ),
    ):
        await cluster_skill_names(names)

    models = [c.args[0] for c in llm.call_args_list]
    assert ClusterAssignmentsResponse in models and MergeGroupsResponse in models
    assert all(c.kwargs.get("reasoning_max_tokens") == 1024 for c in llm.call_args_list)
