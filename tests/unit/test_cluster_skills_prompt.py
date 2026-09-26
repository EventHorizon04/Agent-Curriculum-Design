from __future__ import annotations

from curriculum_agent.prompts.cluster_skills import (
    build_cluster_skills_prompt,
    build_merge_clusters_prompt,
)


def test_cluster_prompt_numbers_every_skill():
    msgs = build_cluster_skills_prompt(["Python", "SQL", "การสื่อสาร"])
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    user = msgs[1]["content"]
    assert "0: Python" in user
    assert "1: SQL" in user
    assert "2: การสื่อสาร" in user
    # system prompt must state the exactly-once rule and JSON shape
    system = msgs[0]["content"]
    assert "member_indices" in system
    assert "label_th" in system
    assert "Do not use indices that are not present in the list." in system
    # the instructions are English but the label reaches a Thai UI, so the
    # prompt has to say so outright — an English label_th is a silent regression
    assert "label_th MUST be written in Thai" in system


def test_merge_prompt_numbers_every_label():
    msgs = build_merge_clusters_prompt(["โปรแกรมมิ่ง", "Programming", "สื่อสาร"])
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    user = msgs[1]["content"]
    assert "0: โปรแกรมมิ่ง" in user
    assert "2: สื่อสาร" in user
    system = msgs[0]["content"]
    assert "groups" in system
    assert "Do not use indices that are not present in the list." in system


def test_cluster_prompt_carries_the_program_context() -> None:
    """The field frames how a skill name is read — 'การดูแล' means one thing in
    nursing and another in facility management."""
    system = build_cluster_skills_prompt(
        ["การดูแลผู้ป่วย", "SQL"],
        program_context="หลักสูตรระดับปริญญาตรี สาขาพยาบาลศาสตร์",
    )[0]["content"]
    assert "หลักสูตรระดับปริญญาตรี สาขาพยาบาลศาสตร์" in system


def test_cluster_prompt_forbids_dropping_off_field_skills() -> None:
    """Context must frame the grouping, never license a filter.

    Every skill reaching this call was extracted from real evidence, so a model
    that reads 'this program is nursing' as 'leave the SQL skills out' would drop
    market demand. validate_assignments repairs a partial cover, but the
    instruction must not invite one in the first place.
    """
    system = build_cluster_skills_prompt(["SQL"], program_context="หลักสูตรสาขาพยาบาลศาสตร์")[0][
        "content"
    ]
    assert "never drop" in system.lower()


def test_no_program_context_leaves_the_prompt_unchanged() -> None:
    """Programs created before intake collected a field keep the old prompt."""
    names = ["Python", "SQL"]
    assert build_cluster_skills_prompt(names, 4) == build_cluster_skills_prompt(
        names, 4, program_context=None
    )


def test_the_cluster_prompt_bounds_the_level_of_a_group_in_both_directions() -> None:
    """Two rules that only work as a pair.

    "Meaning before the count" licenses a group of one, and a model reading only
    that splits a professional function into its tasks. The level rule alone
    reads as "make fewer groups". Removing either leaves the other unopposed, so
    they are asserted together.
    """
    system = build_cluster_skills_prompt(["การแปลสัญญา", "การแปลเอกสารกฎหมาย"])[0]["content"]

    assert "class of work a graduate repeats" in system
    assert "a group of one is correct" in system


def test_the_cluster_prompt_keeps_a_specialised_group_out_of_a_generic_one() -> None:
    """The failure this catches is a partition, not a label: three translation
    skills folded under one generic heading is one group where the evidence
    supports a professional function."""
    system = build_cluster_skills_prompt(["การแปลสัญญา"])[0]["content"]

    assert "occupational identity" in system.lower()
    assert "การสื่อสาร" in system


def test_the_merge_prompt_separates_related_from_the_same() -> None:
    """The line the merge step ran without.

    "Some clusters share the same meaning and should be merged" was the whole
    instruction, and *related* is how a merge eats a competency — one profession
    translates documents and interprets negotiations, so a model asked only for
    shared meaning folds them together.
    """
    system = build_merge_clusters_prompt(["การแปลเอกสาร", "การล่าม"])[0]["content"]

    assert "SAME competency" in system
    assert "NOT a reason to merge" in system
    assert "การล่าม" in system


def test_the_merge_prompt_names_what_a_merge_costs() -> None:
    """A cluster here becomes a Need and then exactly one PLO, and nothing else
    in this prompt says so — without it "should these be one group?" is a
    question about wording rather than about an outcome the program loses."""
    system = build_merge_clusters_prompt(["ก", "ข"])[0]["content"]

    assert "one Need and then one PLO" in system


def test_the_merge_examples_are_answerable_from_labels_alone() -> None:
    """This step is handed cluster labels and nothing else — not the member
    skills, not the evidence. A rule whose example needs more than a label is a
    rule the model cannot act on."""
    system = build_merge_clusters_prompt(["ก", "ข"])[0]["content"]

    assert "member_indices" not in system
    assert "evidence" not in system.lower()
