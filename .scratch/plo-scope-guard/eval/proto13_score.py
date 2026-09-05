"""Score ticket 13: contamination and recall by scope-statement position."""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "proto13_score.txt"
RES = json.loads((HERE / "proto13_results.json").read_text(encoding="utf-8"))
EV = {e["evidence_id"]: e["raw_text_th"] for e in json.loads((HERE / "evidence.json").read_text(encoding="utf-8"))}

CORE = {"ev06", "ev07", "ev08", "ev09", "ev14"}
NOISE = {"ev10", "ev11"}

# Phrases that appear in the scope statement and nowhere else by default.
SCOPE_PHRASES = ["แปลเอกสารธุรกิจ", "ล่ามการเจรจา", "ตรวจแก้งานแปล", "มารยาททางธุรกิจ", "post-editing"]


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


lines: list[str] = []
w = lines.append

for variant in ("U_user", "S_system"):
    rows = [r for r in RES if r["variant"] == variant]
    total = sum(len(r["skills"]) for r in rows)
    scope_named: list[str] = []
    ungrounded: list[str] = []
    for r in rows:
        body = norm(EV[r["evidence_id"]])
        for s in r["skills"]:
            if any(p in s["name"] for p in SCOPE_PHRASES):
                scope_named.append(f'{r["evidence_id"]}  {s["name"]}')
            if norm(s["span"]) not in body:
                ungrounded.append(f'{r["evidence_id"]}  {s["name"]}  <- span: {s["span"][:50]}')

    nz = [r for r in rows if r["evidence_id"] in NOISE]
    cz = [r for r in rows if r["evidence_id"] in CORE]
    n_sk = [s for r in nz for s in r["skills"]]
    c_sk = [s for r in cz for s in r["skills"]]
    off = lambda sk: sum(1 for s in sk if s["relevant"] is False or s["graduate"] is False)

    w(f"=== {variant} — {total} skills, {len(rows)} calls")
    w(f"  ชื่อทักษะลอกวลีจาก scope statement : {len(scope_named)}")
    w(f"  span ไม่พบในข้อความหลักฐาน (แต่ง)   : {len(ungrounded)}")
    w(f"  NOISE ติดธง (recall)               : {off(n_sk)}/{len(n_sk)}")
    w(f"  CORE  ติดธง (false positive)       : {off(c_sk)}/{len(c_sk)}")
    for label, items in (("scope-named", scope_named), ("ungrounded", ungrounded)):
        for it in items:
            w(f"    [{label}] {it}")
    w("")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("done")
