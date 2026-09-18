"""Shared fixtures for the Need statement contract.

`_NeedStatement.rationale_th` is required, so every stub standing in for the
summarize call has to carry one. Keeping the sample here rather than retyping it
means a future change to what the field accepts is one edit, not fourteen — and
the sample is a *valid* one on purpose: a stub that silently stopped satisfying
the validators would make the stage's own guard untested everywhere at once.
"""

from __future__ import annotations

# Long enough for MIN_RATIONALE_CHARS, short enough for MAX, and free of the
# head+modifier pairs find_vague_phrase rejects.
RATIONALE_TH = "ทักษะในกลุ่มนี้ใช้ทำงานเดียวกันคือการดูแลระบบสารสนเทศขององค์กรให้ทำงานต่อเนื่อง"
