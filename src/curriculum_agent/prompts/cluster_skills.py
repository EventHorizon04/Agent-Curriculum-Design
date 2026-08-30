from __future__ import annotations


def build_cluster_skills_prompt(
    skill_names: list[str],
    target_clusters: int | None = None,
) -> list[dict[str, str]]:
    """Group one KSEC bucket's skill names by meaning.

    `target_clusters` is this bucket's share of the program's Need budget, worked
    out by need_grouping.allocate_cluster_targets. Without it the instruction was
    "typically 4–12 groups" per bucket with no notion of how many buckets there
    were, so three buckets asked for 12–36 Needs against a ceiling of ten. It
    stays optional because the contract fingerprint calls this with names alone.
    """
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
        "should be grouped together.\n\n"
        "Rules:\n"
        "- Every index must be assigned to exactly one group (no duplicates, no omissions).\n"
        "- Do not use indices that are not present in the list.\n"
        + count_rule
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
        "Rules:\n"
        "- Every index must appear in 'groups' exactly once.\n"
        "- Do not use indices that are not present in the list.\n"
        "- A cluster that overlaps with no other stays on its own, as a group of one.\n"
        + count_rule
        + "\n"
        "Respond as a JSON object:\n"
        '{ "groups": [ [indices of clusters to be merged] ] }'
    )
    numbered = "\n".join(f"{i}: {label}" for i, label in enumerate(cluster_labels))
    user = f"List of skill clusters (index: cluster_label):\n{numbered}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
