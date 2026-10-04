from __future__ import annotations


def build_cluster_skills_prompt(
    skill_names: list[str],
    target_clusters: int | None = None,
    program_context: str | None = None,
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

    A fourth constraint answers the opposite failure, where the target itself is
    too thin to hold what the data has. On the tourism program (`program-2`) the
    K bucket held 6 graduate-level knowledge areas against a target of 1 —
    `allocate_cluster_targets` giving it a floor of one bucket, not one group —
    and with only "depart from that only where the data clearly will not support
    it" to go on, llama folded wellness-tourism industry knowledge, health/
    tourism/business integration, marketing-cost-revenue-business models,
    standards/quality/safety/ethics, applying wellness knowledge at work, and
    starting one's own business into a single group: a Need no sentence could
    summarize and a PLO that reads as a list. This is not rule 6 come back —
    rule 6 licensed a singleton for any skill that merely looked distinct, with
    no ceiling, which is what drove 11/15 to 16/48. This one licenses a
    departure only to keep different subject areas or different kinds of work
    apart, bounds it at `target_clusters + 2`, and says outright that the
    allowance may not be spent splitting one area into near-duplicate groups or
    giving a lone skill its own group. The fix sits here rather than in
    `allocate_cluster_targets` by the user's choice: the target stays a target
    in code, and how coarse one group may get is a judgment only the prompt can
    state.
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
    # The example areas (marketing/cost management, safety/ethics, starting a
    # business) mirror the measured tourism-program failure on purpose — see the
    # docstring's fourth-constraint paragraph.
    count_rule = (
        f"- Produce about {target_clusters} groups. You may produce up to "
        f"{target_clusters + 2} only to keep apart skills that belong to "
        "different subject areas or different kinds of work: a group's members "
        "must share one area or one kind of work. Never put unrelated areas "
        "into one group to reach the number — e.g. marketing and cost "
        "management, safety standards and ethics, and starting one's own "
        "business are three areas, not one. Do not use the allowance to split "
        "one area into near-duplicate groups or to give a single skill its own "
        "group when it fits an existing one.\n"
        if target_clusters
        else "- Choose an appropriate number of clusters based on the data "
        "(typically 4–12 groups).\n"
    )
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
