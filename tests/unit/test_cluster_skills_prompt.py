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


def test_the_cluster_prompt_bounds_how_narrow_a_group_may_be() -> None:
    """One task is not a group; a class of work is.

    The counterweight is the bucket target, not a second prompt rule. A "meaning
    comes before the count" rule sat here for a day as that counterweight and
    was taken out: it licensed a group of one wherever a skill looked distinct,
    and group counts went from 11 and 15 to 16 and 48 against a budget of ten.
    The target is already soft in the only place that matters — code —
    since `validate_assignments` accepts whatever partition comes back.
    """
    system = build_cluster_skills_prompt(["การแปลสัญญา", "การแปลเอกสารกฎหมาย"], 4)[0]["content"]

    assert "class of work a graduate repeats" in system
    assert "Produce about 4 groups" in system
    assert "meaning comes before the count" not in system.lower()


def test_the_cluster_prompt_bounds_the_departure_above_the_target() -> None:
    """A bucket target of 1 is what folded six unrelated tourism knowledge areas
    into one group on program-2's K bucket. The allowance has to be bounded
    (target + 2) and licensed only by area/kind-of-work, or it reopens the door
    guidances rule 6 was removed for."""
    system = build_cluster_skills_prompt(["a", "b", "c"], 1)[0]["content"]

    assert "up to 3" in system
    assert "different subject areas or different kinds of work" in system


def test_the_cluster_prompt_forbids_singletons_and_near_duplicate_splits() -> None:
    """The allowance exists to keep unrelated areas apart, not to license a
    group of one for every skill that looks distinct — that is guidances rule
    6, already tried and removed for taking group counts to 16/48 against a
    budget of ten."""
    system = build_cluster_skills_prompt(["a", "b"], 2)[0]["content"]

    assert "near-duplicate groups" in system
    assert "single skill its own group when it fits an existing one" in system


def test_the_untargeted_cluster_prompt_carries_no_allowance_text() -> None:
    """The contract fingerprint calls this with names alone, so the untargeted
    form must stay exactly what it was."""
    system = build_cluster_skills_prompt(["a", "b"])[0]["content"]

    assert "typically 4–12 groups" in system
    assert "near-duplicate" not in system
    assert "different subject areas" not in system


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


def test_the_merge_prompt_says_what_the_target_is_for() -> None:
    """Every merge rule is a reason NOT to merge, and stacked in front of a bare
    "aim for about N" they read as permission to return the list unchanged —
    which is what happened: 15 groups became 35-48 against a budget of ten.

    The number is not a style preference. These groups become Needs, synthesis
    keeps the ten highest-scoring, and a capability split across four
    near-duplicates divides its own demand_score four ways.
    """
    system = build_merge_clusters_prompt(["ก", "ข"], 3)[0]["content"]

    assert "Produce about 3 groups" in system
    assert "at most ten outcomes" in system
    assert "compete with each other" in system


def test_the_merge_target_is_stated_before_the_reasons_not_to_merge() -> None:
    """Order is the point, not presence. The target used to sit last, after six
    rules explaining when a merge would destroy something."""
    system = build_merge_clusters_prompt(["ก", "ข"], 3)[0]["content"]

    assert system.index("Produce about 3 groups") < system.index("Do not merge merely related")


def test_the_target_never_licenses_merging_two_different_competencies() -> None:
    """The count rule was strengthened, so it needs a bound of its own.

    Stated as a precedence, not as a second soft rule: a soft rule ("meaning
    comes before the count") sat here for a day and licensed a group of one
    wherever a *skill* looked distinct, which is how a professional function gets
    split into its tasks. This one licenses nothing at the skill level — it only
    refuses a merge of two things already established as different competencies,
    which is the same line `allocate_cluster_targets` draws in code.
    """
    system = build_merge_clusters_prompt(["การแปลเอกสาร", "การล่าม"], 1)[0]["content"]

    assert "stay two groups even when that leaves more groups than the target" in system
    assert "never makes two different competencies one" in system
