import { useEffect, useRef, useState } from 'react'
import api from '../../api/client'
import { ksecLabel, stakeholderLabel } from '../../constants/stakeholder'
import {
  DEMAND_LABEL_TH,
  DEMAND_SCORE_TITLE_TH,
  demandPercent,
} from '../../constants/demand'
import { SCOPE_REASON_TH, scopeCountsTh, scopeVerdict } from '../../constants/scope'
import {
  FALLBACK_ACTION_TH,
  FALLBACK_LABEL_TH,
  fallbackKind,
  withoutMarker,
} from '../../constants/needPolicy'

/**
 * `ksec_categories` and `bloom_level` stay on the row — the pipeline groups and
 * drafts PLOs from them — and are not rendered on an ordinary Need: they
 * describe how it was derived, not what the designer decides about it. A merged
 * Need is the exception, because its tags are the evidence that two buckets
 * were folded into one.
 */
export interface NeedRow {
  need_id: string
  statement_th: string
  statement_en: string | null
  /** Why the model grouped these skills into one demand. An explanation, not a
   *  trail: `source_evidence_ids` is what traceability rests on and is built in
   *  code, while this is free text nothing validates against the evidence — so
   *  it is labelled as the model's account wherever it is shown, and never sits
   *  inside the "ดูที่มา" panel, which is the trail. Empty on rows written
   *  before the field existed and on ones the migration backfilled a marker into. */
  rationale_th: string
  ksec_categories: string[]
  bloom_level: string
  member_skill_ids: string[]
  /** The member skills that carry the Need, shown as chips on a merged card. */
  top_skill_ids: string[]
  /** Originals Agent 2 folded into this Need; empty unless it is a merge. */
  merged_from: string[]
  /** Set on an original that has been folded away; such rows are not listed as
   *  Needs, only under the merged card that replaced them. */
  merged_into: string | null
  /** Who made the merge, so the card can say whether the AI or the designer
   *  folded these Needs together. Null on a Need that is not a merge. */
  merged_by: 'agent' | 'designer' | null
  /** Set while the designer has taken the Need out of the pool; null otherwise.
   *  An excluded Need is stored and traceable but no stage reads it. */
  excluded_at: string | null
  /** Why the model judged the originals duplicates. The model's account, like
   *  `rationale_th`, and labelled so; the trail is `source_evidence_ids`. */
  merge_reason_th: string
  source_evidence_ids: string[]
  source_stakeholder_types: string[]
  freq: number
  demand_score: number
  is_optional: boolean
  /** Members that cleared each scope axis. `scopeVerdict` reads them, and a
   *  missing one counts as passed — see constants/scope.ts for why absent and
   *  zero cannot mean the same thing here. */
  in_field_skill_count?: number
  graduate_capability_skill_count?: number
}

interface NeedTrace {
  need: NeedRow
  /** The route returns whole ExtractedSkill rows, so the two flags are already
   *  on the wire. They are what makes the panel answer the question the badge
   *  raises — which members got this Need held back — rather than only listing
   *  what is in the group. */
  skills: {
    skill_id: string
    skill_name_th: string
    bloom_level: string
    is_field_relevant?: boolean
    is_graduate_capability?: boolean
  }[]
  evidence: { evidence_id: string; source_name: string; classification: string }[]
}

/** A merged original that is itself a merge nests: its own originals sit under
 *  its own disclosure, so a designer's merge of an agent's merge reads top-down. */
function OriginalsList({
  originals,
  originalsOf,
}: {
  originals: NeedRow[]
  originalsOf: (needId: string) => NeedRow[]
}) {
  return (
    <ul className="mt-2 list-disc space-y-1 pl-4 text-graphite">
      {originals.map(o => (
        <OriginalItem key={o.need_id} need={o} originalsOf={originalsOf} />
      ))}
    </ul>
  )
}

function OriginalItem({
  need,
  originalsOf,
}: {
  need: NeedRow
  originalsOf: (needId: string) => NeedRow[]
}) {
  const [open, setOpen] = useState(false)
  const inner = need.merged_from.length > 0 ? originalsOf(need.need_id) : []
  return (
    <li>
      {withoutMarker(need.statement_th)}
      <span className="ml-1.5 text-lead">
        {need.ksec_categories.map(ksecLabel).join(' + ')}
      </span>
      {inner.length > 0 && (
        <>
          <button
            onClick={() => setOpen(v => !v)}
            aria-expanded={open}
            className="link ml-2"
          >
            {open ? 'ซ่อนข้อความเดิม' : `ดูข้อความเดิม (${inner.length})`}
          </button>
          {open && <OriginalsList originals={inner} originalsOf={originalsOf} />}
        </>
      )}
    </li>
  )
}

const MERGED_BY_LABEL_TH = { agent: 'รวมโดย AI', designer: 'รวมโดยผู้ออกแบบ' } as const

export default function NeedCard({
  programId,
  need,
  originals = [],
  originalsOf = () => [],
  skillNames = {},
  onSplit,
  onExclude,
  onRestore,
  selected,
  onSelect,
  actionError = '',
  disabled = false,
}: {
  programId: string
  need: NeedRow
  /** The stored originals of a merged Need, matched on `merged_into`. */
  originals?: NeedRow[]
  /** The originals of any Need, for a merged original that is itself a merge. */
  originalsOf?: (needId: string) => NeedRow[]
  /** skill_id to name, for the top-skill chips. */
  skillNames?: Record<string, string>
  /** Split the merge back. The page owns the request and its error notice. */
  onSplit?: (need: NeedRow) => void
  /** Take the Need out of the pool, after a second press to confirm. */
  onExclude?: (need: NeedRow) => void
  /** Bring an excluded Need back. Given only to cards in the excluded section. */
  onRestore?: (need: NeedRow) => void
  /** Present on a selectable card: whether it is ticked, and how to tick it. */
  selected?: boolean
  onSelect?: (need: NeedRow, selected: boolean) => void
  /** Why the last split, exclude or restore of THIS card was refused, shown on
   *  the card: the page-level notice is off-screen for a designer scrolled down. */
  actionError?: string
  disabled?: boolean
}) {
  const [trace, setTrace] = useState<NeedTrace | null>(null)
  const [open, setOpen] = useState(false)
  const [showOriginals, setShowOriginals] = useState(false)
  const isMerged = need.merged_from.length > 0
  // Same two-step confirm as deleting evidence: the first press arms the button
  // and it disarms itself after a few seconds.
  const [confirmingExclude, setConfirmingExclude] = useState(false)
  const revertTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => () => { if (revertTimer.current) clearTimeout(revertTimer.current) }, [])
  const excludeClick = () => {
    if (revertTimer.current) clearTimeout(revertTimer.current)
    if (confirmingExclude) {
      setConfirmingExclude(false)
      onExclude?.(need)
      return
    }
    setConfirmingExclude(true)
    revertTimer.current = setTimeout(() => setConfirmingExclude(false), 3000)
  }
  const [error, setError] = useState('')
  // The guard runs at plo_synthesis, not here — so the badge says "จะไม่ถูกส่งต่อ",
  // future tense. This checkpoint is the last point at which fixing the scope
  // statement costs only a re-extraction instead of a re-extraction plus every
  // synthesis call that was already paid for.
  const verdict = scopeVerdict(need)
  // A Need the pipeline could not write. Two kinds, kept apart because the
  // designer does opposite things about them: one needs a sentence written by
  // hand, the other needs the stage run again. The marker is read off the
  // statement because that is the only place it exists — no flag records it.
  const fallback = fallbackKind(need.statement_th)

  const toggle = async () => {
    const next = !open
    setOpen(next)
    if (next && !trace) {
      try {
        const res = await api.get<NeedTrace>(`/programs/${programId}/needs/${need.need_id}/trace`)
        setTrace(res.data)
      } catch {
        setError('โหลด trace ไม่สำเร็จ')
      }
    }
  }

  return (
    <div className="panel p-4">
      <div className="flex flex-wrap items-start gap-2">
        {onSelect && (
          <input
            type="checkbox"
            checked={selected ?? false}
            onChange={e => onSelect(need, e.target.checked)}
            disabled={disabled}
            aria-label="เลือก Need นี้เพื่อรวม"
            className="mt-1 shrink-0"
          />
        )}
        <p
          className={`record min-w-0 flex-1 basis-64 ${
            fallback ? 'italic text-pencil' : ''
          }`}
        >
          {/* The marker comes off the sentence because the badge beside it now
              says the same thing, and what is left is the skill list the
              fallback wrote — which is what the designer has to replace. */}
          {withoutMarker(need.statement_th)}
        </p>
        {fallback && (
          <span className="chip chip-marker shrink-0">
            {FALLBACK_LABEL_TH[fallback]}
          </span>
        )}
        {verdict !== 'in_scope' && (
          <span
            title={scopeCountsTh(need)}
            className="chip chip-mandate shrink-0"
          >
            {SCOPE_REASON_TH[verdict]}
          </span>
        )}
        {need.is_optional && (
          <span className="chip chip-neutral shrink-0">
            เสริม
          </span>
        )}
        {isMerged && (
          <span className="chip chip-marker shrink-0">รวมจาก {need.merged_from.length} ข้อ</span>
        )}
        {isMerged && need.merged_by && (
          <span className="chip chip-neutral shrink-0">{MERGED_BY_LABEL_TH[need.merged_by]}</span>
        )}
      </div>
      {isMerged && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
          {need.ksec_categories.map(k => (
            <span key={k} className="chip chip-neutral">{ksecLabel(k)}</span>
          ))}
          {need.top_skill_ids.map(id =>
            skillNames[id] ? (
              <span key={id} className="chip chip-neutral">{skillNames[id]}</span>
            ) : null,
          )}
        </div>
      )}
      {isMerged && need.merge_reason_th && (
        <p className="mt-2 border-l-2 border-hair pl-2.5 text-xs leading-relaxed text-pencil">
          {/* null is a row merged before merged_by existed — Agent 2's. */}
          <span className="eyebrow mr-1">
            {need.merged_by === 'designer' ? 'เหตุผลของผู้ออกแบบ: ' : 'เหตุผลของโมเดล: '}
          </span>
          {need.merge_reason_th}
        </p>
      )}
      {fallback && (
        <p className="notice notice-warn mt-2 text-xs">
          {FALLBACK_ACTION_TH[fallback]}
        </p>
      )}
      {need.rationale_th && (
        <p className="mt-2 border-l-2 border-hair pl-2.5 text-xs leading-relaxed text-pencil">
          <span className="eyebrow mr-1">เหตุผลการจัดกลุ่ม (คำอธิบายของโมเดล): </span>
          {need.rationale_th}
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-pencil">
        {need.source_stakeholder_types.map(t => (
          <span key={t} className="chip chip-neutral">
            {stakeholderLabel(t)}
          </span>
        ))}
        <span title="จำนวนครั้งที่ถูกกล่าวถึง" className="data">Freq {need.freq}</span>
        <span title={DEMAND_SCORE_TITLE_TH} className="data">
          {DEMAND_LABEL_TH} {demandPercent(need.demand_score)}
        </span>
        <button
          onClick={toggle}
          aria-expanded={open}
          className="link ml-auto"
        >
          {open ? 'ซ่อนที่มา' : 'ดูที่มา'}
        </button>
        {onExclude && (
          <button
            onClick={excludeClick}
            disabled={disabled}
            className={`btn btn-sm ${confirmingExclude ? 'btn-danger' : 'btn-danger-quiet'}`}
          >
            {confirmingExclude ? 'ยืนยันตัดออก?' : 'ตัดออก'}
          </button>
        )}
        {onRestore && (
          <button
            onClick={() => onRestore(need)}
            disabled={disabled}
            className="btn btn-sm btn-secondary"
          >
            คืน
          </button>
        )}
      </div>
      {actionError && (
        <p role="alert" className="notice notice-error mt-2 text-xs">
          {actionError}
        </p>
      )}
      {isMerged && (
        <div className="mt-3 border-t border-hair pt-3 text-xs">
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={() => setShowOriginals(v => !v)}
              aria-expanded={showOriginals}
              className="link"
            >
              {showOriginals ? 'ซ่อนข้อความเดิม' : `ดูข้อความเดิม (${originals.length})`}
            </button>
            {onSplit && (
              <button
                onClick={() => onSplit(need)}
                disabled={disabled}
                className="btn btn-sm btn-secondary ml-auto"
              >
                แยกกลับ
              </button>
            )}
          </div>
          {showOriginals && <OriginalsList originals={originals} originalsOf={originalsOf} />}
        </div>
      )}
      {open && (
        <div className="mt-3 space-y-2 border-t border-hair pt-3 text-xs">
          {error && <p className="text-mandate">{error}</p>}
          {!trace && !error && <p className="text-lead">กำลังโหลด...</p>}
          {trace && (
            <>
              <div>
                <p className="eyebrow">ทักษะในกลุ่ม ({trace.skills.length})</p>
                <ul className="mt-1 list-disc pl-4 text-graphite">
                  {trace.skills.map(s => (
                    <li key={s.skill_id}>
                      {s.skill_name_th}
                      {s.is_field_relevant === false && (
                        <span className="chip chip-mandate ml-1.5">นอกสาขา</span>
                      )}
                      {s.is_graduate_capability === false && (
                        <span className="chip chip-mandate ml-1.5">ไม่ใช่สมรรถนะบัณฑิต</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="eyebrow">
                  Evidence ({trace.evidence.length})
                </p>
                <ul className="mt-1 list-disc pl-4 text-graphite">
                  {trace.evidence.map(e => (
                    <li key={e.evidence_id}>{e.source_name}</li>
                  ))}
                </ul>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
