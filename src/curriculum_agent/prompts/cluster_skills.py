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

    Three rules come from `guidances/skill_clustering.md` (4, 6) and from the
    curriculum-level boundary already written into `summarize_need`:

    - Occupational identity, and the level of a group, push the same way a bucket
      target does not: `allocate_cluster_targets` says how *many* groups, and
      nothing said how *coarse* one may be.
    - The level rule and the size rule are stated as one pair on purpose. "Meaning
      before the count" licenses a group of one, and a model reading only that
      will split a professional function into its tasks; the level rule alone
      reads as "make fewer groups". Each is the other's bound.
    - "Meaning before the count" is not new policy — `allocate_cluster_targets`
      documents the target as a target rather than a cap, and
      `validate_assignments` accepts whatever partition comes back. The prompt had
      simply never told the model any of that.
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
        "- Meaning comes before the count. That bound is about the *level* of a "
        "group, not its size: a group of one is correct when a skill is genuinely "
        "distinct from every other.\n"
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
    """
    count_rule = (
        f"- Aim for about {target_groups} groups in total. Depart from that only "
        "where the labels clearly will not support it.\n"
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
        "- A cluster that overlaps with no other stays on its own, as a group of one.\n"
        "- Do not merge merely related competencies. 'การแปลเอกสาร' and 'การล่าม' "
        "stay apart though one profession does both; so do 'การวิเคราะห์ข้อมูล' and "
        "'การสร้างภาพข้อมูล'.\n"
        "- Preserve the occupational identity the labels carry: merging must not "
        "produce a group so general it could belong to any field.\n"
        "- Before merging, ask: if these two became one Need and then one PLO, "
        "would the distinct capability still be visible? If the merge loses a "
        "distinction that matters, do not merge.\n"
        "- Meaning comes before the count: leaving two clusters apart is the right "
        "answer whenever merging them would lose a competency.\n" + count_rule + "\n"
        "Respond as a JSON object:\n"
        '{ "groups": [ [indices of clusters to be merged] ] }'
    )
    numbered = "\n".join(f"{i}: {label}" for i, label in enumerate(cluster_labels))
    user = f"List of skill clusters (index: cluster_label):\n{numbered}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
