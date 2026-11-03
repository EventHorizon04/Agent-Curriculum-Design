import { plosCiting } from './plosCiting'
import { MAX_MERGE_NEEDS, withoutMarker } from '../../constants/needPolicy'
import { unwrittenReason, type PickerNeed } from './pickerNeed'
import type { PLO } from '../../types/plo'

function citingIds(plos: PLO[], needId: string): string[] {
  return plosCiting(plos, [needId]).map((p) => p.plo_id)
}

/** The merge panel: unused Needs first, then those already behind an outcome,
 *  and under the list what ticking them will replace. */
export default function MergeNeedPicker({
  needs,
  plos,
  selected,
  onToggle,
  note,
  busy,
  merging,
  onSubmit,
}: {
  needs: PickerNeed[]
  plos: PLO[]
  selected: Set<string>
  onToggle: (needId: string) => void
  note: string
  busy: boolean
  merging: boolean
  onSubmit: () => void
}) {
  const cited = new Set(plos.flatMap((p) => p.source_need_ids))
  const unused = needs
    .filter((n) => !cited.has(n.need_id))
    .sort((a, b) => (b.demand_score ?? 0) - (a.demand_score ?? 0))
  const used = needs.filter((n) => cited.has(n.need_id))

  const replaced = plosCiting(plos, selected)
  const replacedIds = new Set(replaced.map((p) => p.plo_id))
  const keptCited = new Set(plos.filter((p) => !replacedIds.has(p.plo_id)).flatMap((p) => p.source_need_ids))
  // Needs that lose their only outcome: cited by a replaced PLO, not chosen,
  // and not behind any outcome that stays.
  const freed = needs.filter(
    (n) =>
      !selected.has(n.need_id) &&
      !keptCited.has(n.need_id) &&
      replaced.some((p) => p.source_need_ids.includes(n.need_id)),
  )
  const full = selected.size >= MAX_MERGE_NEEDS

  const row = (n: PickerNeed, label: string, highlight: boolean) => {
    const isSel = selected.has(n.need_id)
    const reason = unwrittenReason(n)
    const off = Boolean(reason) || (full && !isSel)
    return (
      <label
        key={n.need_id}
        title={reason ?? (full && !isSel ? `รวมได้ไม่เกิน ${MAX_MERGE_NEEDS} Need` : undefined)}
        className={`flex items-start gap-2.5 rounded-[3px] border p-3 transition-colors ${
          off ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'
        } ${isSel ? 'border-stamp bg-stamp-wash' : 'border-hair bg-sheet hover:border-hair-strong'}`}
      >
        <input
          type="checkbox"
          checked={isSel}
          disabled={off || busy}
          onChange={() => onToggle(n.need_id)}
          className="mt-1.5 accent-stamp"
        />
        <span className="min-w-0 flex-1">
          <span className="record block text-base">{withoutMarker(n.statement_th)}</span>
          {reason && <span className="mt-0.5 block text-xs text-pencil">{reason}</span>}
        </span>
        <span className={`chip shrink-0 ${highlight ? 'chip-stamp' : 'chip-neutral'}`}>{label}</span>
      </label>
    )
  }

  return (
    <div className="panel mt-8 bg-sunk p-5">
      <h2 className="section-title mb-1">รวม Need หลายรายการเป็น PLO เดียว</h2>
      <p className="mb-3 text-xs text-pencil">
        เลือก Need ตั้งแต่ 2 รายการที่ต้องการให้ AI สังเคราะห์รวมเป็น PLO เดียว
        <span className="ml-2">รวมได้ไม่เกิน {MAX_MERGE_NEEDS} Need</span>
      </p>
      {note.trim() && (
        <p className="notice notice-info mb-3 text-xs">
          ใช้หมายเหตุด้านบน: <span className="text-graphite">{note.trim()}</span>
        </p>
      )}
      <div className="mb-4 space-y-2">
        {unused.map((n) => row(n, 'ยังไม่มี PLO', true))}
        {used.map((n) => row(n, `อยู่ใน ${citingIds(plos, n.need_id).join(', ')}`, false))}
      </div>
      {selected.size > 0 && (
        <div className="mb-4 space-y-1 text-sm text-graphite" aria-live="polite">
          <p>
            {replaced.length > 0
              ? `จะแทนที่: ${replaced.map((p) => p.plo_id).join(', ')}`
              : 'ไม่แทนที่ PLO เดิม — เพิ่มเป็นข้อใหม่'}
          </p>
          {freed.length > 0 && (
            <p className="text-pencil">
              Need ที่จะไม่มี PLO หลังรวม: {freed.map((n) => withoutMarker(n.statement_th)).join(' · ')}
            </p>
          )}
        </div>
      )}
      <button onClick={onSubmit} disabled={selected.size < 2 || busy} className="btn btn-primary">
        {merging ? 'กำลังร่าง PLO ใหม่...' : `รวมเป็น PLO เดียว (${selected.size})`}
      </button>
    </div>
  )
}
