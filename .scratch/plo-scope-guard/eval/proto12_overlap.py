"""Measure how much the two scope axes overlap, from data already collected.

No LLM calls: proto09's _Base carried is_field_relevant alongside
is_graduate_capability, so T2_field holds both flags per extracted skill.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "proto12_overlap.txt"

CORE = {"ev06", "ev07", "ev08", "ev09", "ev14"}
NOISE = {"ev10", "ev11"}

t9 = json.loads((HERE / "proto09_results.json").read_text(encoding="utf-8"))
t2 = json.loads((HERE / "proto02_results_ollama.json").read_text(encoding="utf-8"))

lines: list[str] = []
w = lines.append


def cells(rows: list[dict]) -> dict[str, list[str]]:
    """Skill names bucketed by which axes flagged them OFF."""
    out: dict[str, list[str]] = {"field_only": [], "grad_only": [], "both": [], "neither": []}
    for r in rows:
        for s in r["skills"]:
            f_off = s["relevant"] is False
            g_off = s["graduate"] is False
            key = (
                "both" if f_off and g_off
                else "field_only" if f_off
                else "grad_only" if g_off
                else "neither"
            )
            out[key].append(f'{r["evidence_id"]}  {s["name"]}')
    return out


t2f = [r for r in t9 if r["variant"] == "T2_field"]
noise_rows = [r for r in t2f if r["evidence_id"] in NOISE]
core_rows = [r for r in t2f if r["evidence_id"] in CORE]

for label, rows in (("NOISE (ev10, ev11)", noise_rows), ("CORE (ev06-09, ev14)", core_rows)):
    c = cells(rows)
    total = sum(len(v) for v in c.values())
    w(f"=== {label} — T2_field, {total} skills")
    w(f"  OFF ทั้งสองแกน : {len(c['both']):3d}")
    w(f"  OFF แกนสาขาเท่านั้น : {len(c['field_only']):3d}")
    w(f"  OFF แกนบัณฑิตเท่านั้น: {len(c['grad_only']):3d}")
    w(f"  ไม่ติดธงเลย      : {len(c['neither']):3d}")
    w("")
    for k in ("both", "field_only", "grad_only"):
        for name in c[k]:
            w(f"    [{k}] {name}")
    w("")

w("=== กฎรวม: กรองได้กี่ตัว")
w(f"{'rule':12s} {'NOISE กรองได้':>16s} {'CORE โดนกรอง (FP)':>20s}")
nc = cells(noise_rows)
cc = cells(core_rows)
n_total = sum(len(v) for v in nc.values())
c_total = sum(len(v) for v in cc.values())
for rule, keys in (
    ("field only", ("both", "field_only")),
    ("grad only", ("both", "grad_only")),
    ("or", ("both", "field_only", "grad_only")),
    ("and", ("both",)),
):
    n = sum(len(nc[k]) for k in keys)
    f = sum(len(cc[k]) for k in keys)
    w(f"{rule:12s} {f'{n}/{n_total} ({n/n_total:.0%})':>16s} {f'{f}/{c_total} ({f/c_total:.0%})':>20s}")

w("")
w("=== ฝั่งที่มี scope statement (C_narrow, มีเฉพาะธงสาขา)")
for label, ids in (("NOISE", NOISE), ("CORE", CORE)):
    rows = [r for r in t2 if r["variant"] == "C_narrow" and r["evidence_id"] in ids]
    sk = [s for r in rows for s in r["skills"]]
    off = [s for s in sk if s["relevant"] is False]
    w(f"  {label}: {len(off)}/{len(sk)} ติดธงนอกสาขา")
    for r in rows:
        for s in r["skills"]:
            if s["relevant"] is False:
                w(f'    {r["evidence_id"]}  {s["name"]}')

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"done -> {OUT}")

# --- follow-up: does naming the graduate axis move the field flag itself? ---
tail: list[str] = ["", "=== ธงสาขา (relevant=false) แยกตาม treatment"]
for src, name in ((t9, "T09"), (t2, "T02")):
    for variant in sorted({r["variant"] for r in src}):
        for label, ids in (("NOISE", NOISE), ("CORE", CORE)):
            rows = [r for r in src if r["variant"] == variant and r["evidence_id"] in ids]
            sk = [s for r in rows for s in r["skills"]]
            off = sum(1 for s in sk if s["relevant"] is False)
            tail.append(f"  {name} {variant:18s} {label:5s} {off}/{len(sk)}")
OUT.write_text("\n".join(lines + tail), encoding="utf-8")
print("appended")
