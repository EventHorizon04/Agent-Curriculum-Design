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
