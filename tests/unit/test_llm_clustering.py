from __future__ import annotations

from curriculum_agent.stages.llm_clustering import (
    dedupe_names,
    normalize_name,
    split_batches,
    validate_assignments,
)


def test_normalize_name_lowercases_and_collapses_whitespace() -> None:
    assert normalize_name("  Python   Programming ") == "python programming"
    assert normalize_name("การสื่อสาร") == "การสื่อสาร"


def test_dedupe_names_collapses_duplicates_and_tracks_indices() -> None:
    names = ["Python", "  python ", "SQL", "การสื่อสาร", "sql"]
    unique, groups = dedupe_names(names)
    # sorted by normalized form; Thai sorts after latin here
    assert unique == ["Python", "SQL", "การสื่อสาร"]
    assert groups == [[0, 1], [2, 4], [3]]


def test_dedupe_names_empty() -> None:
    assert dedupe_names([]) == ([], [])


def test_split_batches_splits_at_size() -> None:
    items = [str(i) for i in range(250)]
    batches = split_batches(items, size=100)
    assert [len(b) for b in batches] == [100, 100, 50]
    assert batches[2][0] == "200"


def test_validate_assignments_passes_clean_input_through() -> None:
    names = ["a", "b", "c"]
    clusters = [("g1", [0, 2]), ("g2", [1])]
    assert validate_assignments(clusters, names) == [("g1", [0, 2]), ("g2", [1])]


def test_validate_assignments_drops_hallucinated_and_duplicate_indices() -> None:
    names = ["a", "b"]
    clusters = [("g1", [0, 5, -1]), ("g2", [0, 1])]
    # index 5 and -1 out of range; second 0 already seen
    assert validate_assignments(clusters, names) == [("g1", [0]), ("g2", [1])]


def test_validate_assignments_missing_index_becomes_singleton() -> None:
    names = ["a", "b", "c"]
    clusters = [("g1", [0])]
    result = validate_assignments(clusters, names)
    assert ("g1", [0]) in result
    assert ("b", [1]) in result
    assert ("c", [2]) in result
    assert len(result) == 3


def test_validate_assignments_empty_group_dropped() -> None:
    names = ["a"]
    clusters = [("empty", []), ("g1", [0])]
    assert validate_assignments(clusters, names) == [("g1", [0])]
