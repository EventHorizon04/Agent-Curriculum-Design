import { useState } from 'react'
import api from '../../api/client'
import { stakeholderLabel } from '../../constants/stakeholder'
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
 * `ksec_category` and `bloom_level` stay on the row — the pipeline groups and
 * drafts PLOs from them — but they are not rendered. They describe how a Need
 * was derived, not what the designer decides about it; the statement, who asked
 * for it, and how often carry that.
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
  ksec_category: string
  bloom_level: string
  member_skill_ids: string[]
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

export default function NeedCard({ programId, need }: { programId: string; need: NeedRow }) {
  const [trace, setTrace] = useState<NeedTrace | null>(null)
  const [open, setOpen] = useState(false)
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
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="flex items-start gap-2">
        <p
          className={`flex-1 text-sm font-medium leading-relaxed ${
            fallback ? 'text-gray-500 italic' : 'text-gray-800'
          }`}
        >
          {/* The marker comes off the sentence because the badge beside it now
              says the same thing, and what is left is the skill list the
              fallback wrote — which is what the designer has to replace. */}
          {withoutMarker(need.statement_th)}
        </p>
        {fallback && (
          <span className="shrink-0 rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-900">
            {FALLBACK_LABEL_TH[fallback]}
          </span>
        )}
        {verdict !== 'in_scope' && (
          <span
            title={scopeCountsTh(need)}
            className="shrink-0 rounded-full bg-rose-100 px-2 py-0.5 text-xs font-medium text-rose-800"
          >
            {SCOPE_REASON_TH[verdict]}
          </span>
        )}
        {need.is_optional && (
          <span className="shrink-0 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
            เสริม
          </span>
        )}
      </div>
      {fallback && (
        <p className="mt-2 rounded border-l-2 border-orange-300 bg-orange-50 px-2 py-1.5 text-xs leading-relaxed text-orange-900">
          {FALLBACK_ACTION_TH[fallback]}
        </p>
      )}
      {need.rationale_th && (
        <p className="mt-2 text-xs leading-relaxed text-gray-500">
          <span className="font-semibold text-gray-400">เหตุผลการจัดกลุ่ม (คำอธิบายของโมเดล): </span>
          {need.rationale_th}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-600">
        {need.source_stakeholder_types.map(t => (
          <span key={t} className="rounded bg-gray-100 px-1.5 py-0.5 text-gray-700">
            {stakeholderLabel(t)}
          </span>
        ))}
        <span title="จำนวนครั้งที่ถูกกล่าวถึง">Freq {need.freq}</span>
        <span title={DEMAND_SCORE_TITLE_TH}>
          {DEMAND_LABEL_TH} {demandPercent(need.demand_score)}
        </span>
        <button
          onClick={toggle}
          aria-expanded={open}
          className="ml-auto text-blue-600 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
        >
          {open ? 'ซ่อนที่มา' : 'ดูที่มา'}
        </button>
      </div>
      {open && (
        <div className="mt-3 space-y-2 border-t border-gray-100 pt-3 text-xs">
          {error && <p className="text-red-600">{error}</p>}
          {!trace && !error && <p className="text-gray-400">กำลังโหลด...</p>}
          {trace && (
            <>
              <div>
                <p className="font-semibold text-gray-500">ทักษะในกลุ่ม ({trace.skills.length})</p>
                <ul className="mt-1 list-disc pl-4 text-gray-700">
                  {trace.skills.map(s => (
                    <li key={s.skill_id}>
                      {s.skill_name_th}
                      {s.is_field_relevant === false && (
                        <span className="ml-1.5 text-rose-700">นอกสาขา</span>
                      )}
                      {s.is_graduate_capability === false && (
                        <span className="ml-1.5 text-rose-700">ไม่ใช่สมรรถนะบัณฑิต</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="font-semibold text-gray-500">
                  Evidence ({trace.evidence.length})
                </p>
                <ul className="mt-1 list-disc pl-4 text-gray-700">
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
