"""The program's own place in the institution, as one Thai line for a prompt.

Read by the two calls in `need_combination` that group and name skills. It is
metadata the designer typed at intake — not evidence — so it frames how a skill
is read without adding anything to the evidence trail a Need carries.
"""

from __future__ import annotations

from typing import Any, get_args, get_type_hints

from curriculum_agent.models import ProgramCreateRequest

# The degree levels ProgramCreateRequest accepts, read off the model rather than
# retyped, so a level added there cannot silently miss a label here.
DEGREE_LEVELS: tuple[str, ...] = get_args(get_type_hints(ProgramCreateRequest)["degree_level"])

# Glossed because the prompts these lines go into are Thai; the raw code would
# be the one English token in an otherwise Thai instruction.
_DEGREE_LABEL_TH: dict[str, str] = {
    "bachelor": "ปริญญาตรี",
    "master": "ปริญญาโท",
    "doctoral": "ปริญญาเอก",
}

# A plain dict has no structural link to the Literal it mirrors. This turns a
# level added or renamed on the model into an import-time crash instead of a
# context line that quietly drops the degree.
_uncovered_degrees = set(DEGREE_LEVELS) - set(_DEGREE_LABEL_TH)
if _uncovered_degrees:
    raise AssertionError(f"_DEGREE_LABEL_TH is missing label(s) for: {sorted(_uncovered_degrees)}")


def build_program_context_th(metadata: dict[str, Any]) -> str | None:
    """One Thai line naming the program's field and degree level, or None.

    None means "say nothing": a program with no field gives the caller nothing to
    frame the skills with, and a stub line would be worse than the pre-context
    behaviour it replaces. An unrecognised degree level — a row written before a
    rename — drops the level and keeps the field, since the field is what carries
    the meaning.
    """
    field = str(metadata.get("field") or "").strip()
    if not field:
        return None
    level = _DEGREE_LABEL_TH.get(str(metadata.get("degree_level") or ""))
    if level is None:
        return f"หลักสูตรสาขา{field}"
    return f"หลักสูตรระดับ{level} สาขา{field}"
