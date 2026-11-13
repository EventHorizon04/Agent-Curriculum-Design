from __future__ import annotations

from curriculum_agent.models import KSECCategory

_EC_RULE = (
    "- These skills are attitudes (E) and adaptability or self-development traits (C). "
    "Do not gather them into one general 'good character' group. Group each trait by "
    "where the graduate shows it: in the quality of and accountability for their own "
    "work (accuracy, care, owning errors, professional integrity); toward other people "
    "and cultures (ethical conduct across cultures, respect for diversity, working "
    "relationships); or toward change and their own career (adapting to technology and "
    "society, lifelong learning, leadership, entrepreneurship). A trait that fits none "
    "of these may form a group of its own.\n"
)


def build_cluster_skills_prompt(
    skill_names: list[str],
    target_clusters: int | None = None,
    program_context: str | None = None,
    ksec: KSECCategory | None = None,
) -> list[dict[str, str]]:
    """Group one KSEC bucket's skill names by meaning.

    `program_context` is the program's field and degree level, from intake. It
    disambiguates the skill names: "การดูแล" groups with clinical work in a
    nursing program and with facility operations in an engineering one, and
    nothing else in this prompt says which program these skills belong to.

    `target_clusters` is this bucket's share of the program's Need budget, worked
    out by need_grouping.allocate_cluster_targets. Without it the instruction was
    "typically 4–12 groups" per bucket with no notion of how many buckets there
    were, so three buckets asked for 12–36 Needs against a ceiling of ten. It
    stays optional because the contract fingerprint calls this with names alone.

    Two rules come from `guidances/skill_clustering.md` (4) and from the
    curriculum-level boundary already written into `summarize_need`: occupational
    identity, and the level a group sits at. They push where a bucket target
    cannot — `allocate_cluster_targets` says how *many* groups, and nothing said
    how *coarse* one may be.

    A third was landed beside them and taken out again. `guidances` rule 6,
    "meaning comes before the count", licensed a group of one wherever a skill
    was genuinely distinct — true of the code (the target is a target, and
    `validate_assignments` accepts whatever comes back) and ruinous as an
    instruction. Group counts on the TCISM corpus went from 11 and 15 to 16 and
    48 against a budget of ten, which spreads `demand_score` across near-
    duplicates and makes the top-ten cut in `plo_synthesis` arbitrary. The model
    does not need to be told the target is soft; `allocate_cluster_targets`
    already refuses to trade a skill for a number, and that refusal lives in code
    where no prompt can talk it into anything.

    A bounded version was also tried and reverted (2026-10-04): "up to target + 2,
    only to keep different subject areas or kinds of work apart, never for
    near-duplicate splits or singletons". Measured with llama, three runs per
    bucket, cache bypassed, against this rule: on the tourism program's K bucket
    (6 names, target 1) — the case it was written for — the old rule split
    health/wellness from business/standards in 2 of 3 runs and the bounded rule
    merged all six in 3 of 3; on the translation program's S bucket (53 names,
    target 7) groups fell from 4/4/6 to 3/3/4, further under target. Raising that
    K target to 2 under this rule did not help either (1/2/2 groups, and the
    splits were 5+1). The lumped tourism Need came from llama's run-to-run
    variance on short Thai names, not from this wording; a fix belongs to the
    clustering model or method, not to the count rule.

    `ksec` is the bucket being clustered, and only EC changes the prompt, for the
    graduate side only: the rule was measured on graduate-side skills, so
    `skill_grouping` passes `None` for the institutional population (2026-11-11
    A/B, `.scratch/reports/2026-11-11-ec-k-grouping-ab.md`). Without a rule the EC
    bucket came back as two groups of which one was a grab-bag ("development,
    ethics and adaptation") that split differently on every run. Told to group each
    trait by where the graduate shows it — own work, other people and cultures,
    change and career — GLM returned those three dimensions with near-identical
    labels in 7 of 9 runs (one partition 3 of 3), one group over the target, which
    `validate_assignments` accepts. A parallel K rule (group knowledge by subject,
    not by verb) was tried in the same experiment and dropped: the K buckets are 4-6
    names, too small for it to matter, and it made one input steadier and another
    noisier. Every other bucket, and a call without `ksec`, gets the prompt as
    before, byte for byte.
    """
    # The context frames how a name is read; it must not become a filter. Every
    # skill reaching this call was extracted from evidence a stakeholder actually
    # produced, so an "off-field" skill is market demand the program did not
    # expect, not noise. validate_assignments repairs a partial cover, but a
    # prompt that invites one throws away the repair's honesty.
    context_lines = (
        f"Program context: {program_context}\n"
        "Read each skill as it is used in that field, and group by that reading.\n\n"
        if program_context
        else ""
    )
    context_rule = (
        "- The context frames the reading only. Every skill listed comes from real "
        "market evidence: never drop, exclude, or set aside a skill for looking "
        "off-field — it still belongs to exactly one group.\n"
        if program_context
        else ""
    )
    count_rule = (
        f"- Produce about {target_clusters} groups. Depart from that only where "
        "the data clearly will not support it.\n"
        if target_clusters
        else "- Choose an appropriate number of clusters based on the data "
        "(typically 4–12 groups).\n"
    )
    ec_rule = _EC_RULE if ksec is KSECCategory.EC else ""
    system = (
        "You are an expert in labor skill analysis.\n"
        "Group the following skills based on their meaning and usage context. "
        "Skills used in similar roles or with closely related meanings "
        "should be grouped together.\n\n" + context_lines + "Rules:\n"
        "- Every index must be assigned to exactly one group (no duplicates, no omissions).\n"
        "- Do not use indices that are not present in the list.\n"
        + context_rule
        + count_rule
        + "- Preserve the occupational identity the names carry: never fold a "
        "specialised group into a generic one. 'การแปลเอกสารธุรกิจ / การแปลสัญญา / "
        "การแปลเอกสารกฎหมาย' is 'การแปลเอกสารวิชาชีพ', never 'การสื่อสาร'.\n"
        "- Group at the level of a class of work a graduate repeats across "
        "situations, not at the level of one task inside it. Each group can become "
        "one of the program's ten outcomes, so splitting 'translating sales "
        "contracts' from 'translating legal contracts' spends two of them on one "
        "professional function.\n"
        + ec_rule
        + "- label_th MUST be written in Thai, not English — it is shown to Thai users.\n\n"
        "Respond as a JSON object:\n"
        '{ "clusters": [ { "label_th": "ชื่อกลุ่มภาษาไทยสั้นๆ", '
        '"member_indices": [indices of skills in this group] } ] }'
    )
    numbered = "\n".join(f"{i}: {name}" for i, name in enumerate(skill_names))
    user = f"List of skills (index: skill_name):\n{numbered}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_merge_clusters_prompt(
    cluster_labels: list[str],
    target_groups: int | None = None,
) -> list[dict[str, str]]:
    """Fold equivalent cluster labels from separate batches into one grouping.

    The target lands here rather than on the batches: a batch sees a slice of the
    bucket and is meant to over-produce, and this step is where the bucket's
    final Need count is actually decided.

    Which made "Some clusters share the same meaning and should be merged" the
    whole of the instruction at the step that decides how many competencies
    survive. It drew no line between *related* and *the same*, and related is how
    a merge eats a competency: one profession translates documents and interprets
    negotiations, so a model asked only for shared meaning folds them together and
    the program loses an outcome it had evidence for. The rules from
    `guidances/cluster_merging.md` (2, 3, 8) draw that line, and the merge
    decision test states the consequence the model cannot otherwise see — a
    cluster here becomes a Need and then exactly one PLO.

    The examples are all label-only ("การแปลเอกสาร" vs "การล่าม") because labels
    are all this step is handed. A rule this prompt could not act on would be
    worse than none.

    Those rules land with the count rule ahead of them rather than after, and the
    count rule now says what the number is for. Every one of them is a reason not
    to merge, and stacked in front of a bare "aim for about N" they read as
    permission to return the list unchanged: group counts went from 15 to 35-48
    against a budget of ten. The budget is not a style preference — the groups
    become Needs, `plo_synthesis` keeps the ten highest-scoring ones, and a
    capability split across four near-duplicate Needs divides its own
    `demand_score` four ways and can lose the cut to a single coarser one. The
    "meaning comes before the count" rule that sat here (guidances rule 6) is
    gone for the same reason: it is a true statement about the code that the
    model reads as licence.

    Which leaves the target needing a bound of its own, and it is stated as a
    precedence rather than as a second soft rule: two different competencies stay
    two groups even over budget. That is the same line `allocate_cluster_targets`
    draws in code — a skill traded away to hit a number is worse than a Need over
    budget — and the difference from the rule that was removed is where each one
    applies. Rule 6 licensed a group of one wherever a *skill* looked distinct,
    which is how a professional function ends up split into its tasks; this
    licenses nothing at the skill level and only refuses a merge of two things
    that are already established as different competencies.
    """
    count_rule = (
        f"- Produce about {target_groups} groups in total. That number is this "
        "competency domain's share of the whole program's outcome budget, and the "
        "program keeps at most ten outcomes: a list far longer than "
        f"{target_groups} means several of its groups describe one capability and "
        "compete with each other for the same place.\n"
        if target_groups
        else ""
    )
    system = (
        "You are an expert in labor skill analysis.\n"
        "The following list contains skill cluster names generated from batched clustering. "
        "Some clusters share the same meaning and should be merged into a single cluster.\n\n"
        "Merge two clusters only when they name the SAME competency — "
        "interchangeable in professional use, near-identical in meaning.\n"
        "Being related, being used together, or belonging to one profession is "
        "NOT a reason to merge.\n\n"
        "Rules:\n"
        "- Every index must appear in 'groups' exactly once.\n"
        "- Do not use indices that are not present in the list.\n"
        + count_rule
        + "- A cluster that overlaps with no other stays on its own, as a group of one.\n"
        "- Do not merge merely related competencies. 'การแปลเอกสาร' and 'การล่าม' "
        "stay apart though one profession does both; so do 'การวิเคราะห์ข้อมูล' and "
        "'การสร้างภาพข้อมูล'.\n"
        "- Two different competencies stay two groups even when that leaves more "
        "groups than the target. The target says how many groups this domain "
        "should be aiming for; it never makes two different competencies one.\n"
        "- Preserve the occupational identity the labels carry: merging must not "
        "produce a group so general it could belong to any field.\n"
        "- Before merging, ask: if these two became one Need and then one PLO, "
        "would the distinct capability still be visible? If the merge loses a "
        "distinction that matters, do not merge.\n"
        "\n"
        "Respond as a JSON object:\n"
        '{ "groups": [ [indices of clusters to be merged] ] }'
    )
    numbered = "\n".join(f"{i}: {label}" for i, label in enumerate(cluster_labels))
    user = f"List of skill clusters (index: cluster_label):\n{numbered}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
