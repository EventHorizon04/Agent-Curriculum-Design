"""Ticket 02 prototype, part 3: score each scope variant against the human artifact.

Ground truth is Data/Needs_to_PLO_TCISM.xlsx, which turns this exact evidence
into 4 themes (A language/translation, B AI post-editing, C cross-cultural
ethics, D entrepreneurship/international). Two evidence items produce nothing a
graduate does — the administrator's and the program committee's operational
asks — so a scope statement that works must flag those without flagging the
employers' and alumni's asks, which are the themes' whole substance.
"""

from __future__ import annotations

import io
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
RESULTS = json.loads((HERE / "proto02_results_ollama.json").read_text(encoding="utf-8"))

# Evidence the human artifact turned into theme A/B/C content. Flagging a skill
# here is a false positive: the program loses the capability it exists to teach.
CORE = {"ev06", "ev07", "ev08", "ev09", "ev14"}
# Evidence that is entirely about running the college, not about a graduate.
# Nothing here survived into any of the four human PLOs.
NOISE = {"ev10", "ev11"}
# Everything else: institutional direction and applicant aspiration, which the
# human kept but reframed. Reported, not scored — the right answer is arguable.
VARIANT_ORDER = ["A_none", "B_broad", "C_narrow", "D_with_exclusions", "E_vague"]


def main() -> None:
    by_variant: dict[str, list[dict]] = defaultdict(list)
    for row in RESULTS:
        if row.get("error"):
            continue
        by_variant[row["variant"]].append(row)

    out = io.StringIO()
    out.write("variant            total  OFF   core_FP        noise_TP       other_OFF\n")
    out.write("-" * 74 + "\n")
    for variant in VARIANT_ORDER:
        rows = by_variant.get(variant, [])
        total = off = 0
        core_n = core_off = noise_n = noise_off = other_off = 0
        for r in rows:
            for s in r["skills"]:
                total += 1
                is_off = not s["relevant"]
                off += is_off
                if r["evidence_id"] in CORE:
                    core_n += 1
                    core_off += is_off
                elif r["evidence_id"] in NOISE:
                    noise_n += 1
                    noise_off += is_off
                else:
                    other_off += is_off
        fp = f"{core_off}/{core_n}" + (f" ({core_off / core_n:.0%})" if core_n else "")
        tp = f"{noise_off}/{noise_n}" + (f" ({noise_off / noise_n:.0%})" if noise_n else "")
        out.write(f"{variant:18} {total:5}  {off:3}   {fp:14} {tp:14} {other_off}\n")

    # Which skills each variant actually caught in the noise items.
    out.write("\n\n=== ทักษะจาก ev10 (ผู้บริหาร) + ev11 (อ.ผู้รับผิดชอบ) รายตัว ===\n")
    for variant in VARIANT_ORDER:
        out.write(f"\n--- {variant}\n")
        for r in by_variant.get(variant, []):
            if r["evidence_id"] not in NOISE:
                continue
            for s in r["skills"]:
                tag = "OFF" if not s["relevant"] else "in "
                out.write(f"  {tag} [{s['ksec']}] {s['name']}\n")

    out.write("\n\n=== false positives: ทักษะใน CORE ที่ถูกติดธง OFF ===\n")
    for variant in VARIANT_ORDER:
        hits = [
            f"    [{r['evidence_id']}] {s['name']}"
            for r in by_variant.get(variant, [])
            if r["evidence_id"] in CORE
            for s in r["skills"]
            if not s["relevant"]
        ]
        out.write(f"\n--- {variant} ({len(hits)})\n" + ("\n".join(hits) + "\n" if hits else ""))

    (HERE / "proto02_score.txt").write_text(out.getvalue(), encoding="utf-8")
    print("wrote proto02_score.txt")


if __name__ == "__main__":
    main()
