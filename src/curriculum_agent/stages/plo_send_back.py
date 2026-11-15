"""The designer's send-back of single PLOs: redraft each one with the designer's reason.

Each item goes through `redraft_from_needs` (every bound, the supersede and the
replace are shared with the designer's merge) with `cause="send_back"`, and the new
draft is stamped as sent back so the review loop never rewrites it on its own.
Takes no lock: the caller holds the program busy through its job registration.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException
from loguru import logger
from pydantic import BaseModel, Field, field_validator, model_validator

from curriculum_agent.data.repositories import PLORepository
from curriculum_agent.models import NOTE_MAX_CHARS, PLO, ProgramMetadata
from curriculum_agent.stages.plo_redraft import RedraftFailed, RedraftRefused, redraft_from_needs

REASON_PLO_GONE_TH = "ไม่พบ PLO นี้แล้ว — ชุด PLO เปลี่ยนไป"
REASON_REDRAFT_FAILED_TH = "AI เขียนข้อนี้ใหม่ไม่สำเร็จ"


class PloSendBackItem(BaseModel):
    plo_id: str
    reason_th: str = Field(min_length=1, max_length=NOTE_MAX_CHARS)

    @field_validator("reason_th", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v


class PloSendBackRequest(BaseModel):
    items: list[PloSendBackItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_plo_ids(self) -> PloSendBackRequest:
        ids = [i.plo_id for i in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("plo_id ซ้ำกันในคำขอเดียว")
        return self


class PloSendBackOutcome(BaseModel):
    plo_id: str
    status: Literal["rewritten", "refused", "failed"]
    detail_th: str = ""
    result_plo_id: str | None = None
    result_statement_th: str | None = None


class PloSendBackResult(BaseModel):
    outcomes: list[PloSendBackOutcome]


async def send_back_plos(
    program: ProgramMetadata,
    program_id: str,
    items: Sequence[PloSendBackItem],
    *,
    drafter: Callable[..., Awaitable[PLO | None]],
) -> PloSendBackResult:
    """Redraft each sent-back PLO in request order; one item's refusal or failure
    never stops the rest."""
    outcomes: list[PloSendBackOutcome] = []
    for item in items:
        stored = await PLORepository().list_by_program(program_id)
        plo = next((p for p in stored if p.plo_id == item.plo_id), None)
        if plo is None:
            outcomes.append(
                PloSendBackOutcome(
                    plo_id=item.plo_id, status="refused", detail_th=REASON_PLO_GONE_TH
                )
            )
            continue

        async def stamped(
            *args: object, _reason: str = item.reason_th, **kwargs: object
        ) -> PLO | None:
            draft = await drafter(*args, **kwargs)
            if draft is None:
                return None
            return draft.model_copy(
                update={
                    "designer_sent_back_at": datetime.now(UTC).replace(tzinfo=None),
                    "designer_send_back_reason_th": _reason,
                }
            )

        try:
            new, _replaced = await redraft_from_needs(
                program,
                program_id,
                list(plo.source_need_ids),
                note_th=item.reason_th,
                cause="send_back",
                drafter=stamped,
            )
        except RedraftRefused as exc:
            outcomes.append(
                PloSendBackOutcome(plo_id=item.plo_id, status="refused", detail_th=exc.detail_th)
            )
        except RedraftFailed:
            outcomes.append(
                PloSendBackOutcome(
                    plo_id=item.plo_id, status="failed", detail_th=REASON_REDRAFT_FAILED_TH
                )
            )
        except HTTPException as exc:
            logger.warning(f"send-back: {item.plo_id} failed with HTTP {exc.status_code}")
            outcomes.append(
                PloSendBackOutcome(
                    plo_id=item.plo_id,
                    status="failed",
                    detail_th=exc.detail if isinstance(exc.detail, str) else REASON_REDRAFT_FAILED_TH,
                )
            )
        except Exception:
            logger.exception(f"send-back: {item.plo_id} failed unexpectedly")
            outcomes.append(
                PloSendBackOutcome(
                    plo_id=item.plo_id, status="failed", detail_th=REASON_REDRAFT_FAILED_TH
                )
            )
        else:
            logger.info(f"send-back: {item.plo_id} rewritten as {new.plo_id}")
            outcomes.append(
                PloSendBackOutcome(
                    plo_id=item.plo_id,
                    status="rewritten",
                    result_plo_id=new.plo_id,
                    result_statement_th=new.statement_th,
                )
            )
    return PloSendBackResult(outcomes=outcomes)
