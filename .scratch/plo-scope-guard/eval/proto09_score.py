"""Ticket 09 scoring. Same CORE/NOISE ground truth as ticket 02.

T1 carries no flag: its rule tells the model not to propose institution-side
skills at all, so its signal is a *drop in count* on the NOISE items with the
CORE count intact. T2/T3/T4 carry a flag and are scored as recall/precision.
T3 additionally reports how often it rewrote rather than flagged.
"""

from __future__ import annotations

import io
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
CORE = {"ev06", "ev07", "ev08", "ev09", "ev14"}
NOISE = {"ev10", "ev11"}
INSTITUTIONAL = {"ev01", "ev02", "ev03", "ev04", "ev05"}


def load() -> dict[str, list[dict]]:
    rows: list[dict] = []
    for path, keep in (("proto02_results_ollama.json", {"A_none"}), ("proto09_results.json", None)):
        p = HERE / path
        if not p.exists():
            continue
        for r in json.loads(p.read_text(encoding="utf-8")):
            if r.get("error"):
                continue
            if keep and r["variant"] not in keep:
                continue
            rows.append(r)
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[r["variant"]].append(r)
    return by


def main() -> None:
    by = load()
    order = ["A_none", "T1_rule", "T2_field", "T3_rewrite", "T4_combo"]
    out = io.StringIO()
    out.write("variant       CORE_n  CORE_notgrad   NOISE_n  NOISE_notgrad   INST_n  rewrites\n")
    out.write("-" * 82 + "\n")
    for v in order:
        rows = by.get(v, [])
        if not rows:
            continue
        counts = {"core": [0, 0], "noise": [0, 0], "inst": [0, 0]}
        rewrites = 0
        for r in rows:
            key = (
                "core"
                if r["evidence_id"] in CORE
                else "noise"
                if r["evidence_id"] in NOISE
                else "inst"
                if r["evidence_id"] in INSTITUTIONAL
                else None
            )
            for s in r["skills"]:
                if s.get("original"):
                    rewrites += 1
                if key is None:
                    continue
                counts[key][0] += 1
                if s.get("graduate") is False:
                    counts[key][1] += 1
        c, n, i = counts["core"], counts["noise"], counts["inst"]
        cn = f"{c[1]}/{c[0]}" + (f" ({c[1] / c[0]:.0%})" if c[0] else "")
        nn = f"{n[1]}/{n[0]}" + (f" ({n[1] / n[0]:.0%})" if n[0] else "")
        out.write(f"{v:13} {c[0]:6}  {cn:14} {n[0]:7}  {nn:14}  {i[0]:5}  {rewrites}\n")

    out.write("\n\n=== ev10 (ผู้บริหาร) + ev11 (อ.ผู้รับผิดชอบ) รายตัว ===\n")
    for v in order:
        out.write(f"\n--- {v}\n")
        for r in by.get(v, []):
            if r["evidence_id"] not in NOISE:
                continue
            for s in r["skills"]:
                g = s.get("graduate")
                tag = "  " if g is None else ("NOT-GRAD" if g is False else "grad    ")
                extra = f"   <- {s['original']}" if s.get("original") else ""
                out.write(f"  {tag} [{s['ksec']}] {s['name']}{extra}\n")

    out.write("\n\n=== false positives: CORE ที่ถูกตั้ง is_graduate_capability=false ===\n")
    for v in order:
        hits = [
            f"    [{r['evidence_id']}] {s['name']}"
            for r in by.get(v, [])
            if r["evidence_id"] in CORE
            for s in r["skills"]
            if s.get("graduate") is False
        ]
        out.write(f"\n--- {v} ({len(hits)})\n" + ("\n".join(hits) + "\n" if hits else ""))

    (HERE / "proto09_score.txt").write_text(out.getvalue(), encoding="utf-8")
    print("wrote proto09_score.txt")


if __name__ == "__main__":
    main()
