import { useState } from 'react'
import { MAX_MERGE_NEEDS, withoutMarker } from '../../constants/needPolicy'
import { unwrittenReason, type PickerNeed } from './pickerNeed'

/** "เพิ่ม Need" on a PLO card: pick one unused Need and have the PLO redrafted
 *  from its current Needs plus that one, through the page's merge path. */
export default function AttachNeed({
  citedCount,
  unused,
  busy,
  onAttach,
}: {
  citedCount: number
  unused: PickerNeed[]
  busy: boolean
  onAttach: (needId: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [choice, setChoice] = useState('')
  const usable = unused.filter((n) => !unwrittenReason(n))
  const blocked =
    citedCount >= MAX_MERGE_NEEDS
      ? `PLO นี้มี Need ครบ ${MAX_MERGE_NEEDS} ข้อแล้ว`
      : usable.length === 0
        ? 'ไม่มี Need ที่ยังไม่มี PLO'
        : null

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        disabled={busy || blocked !== null}
        title={blocked ?? undefined}
        className="btn btn-sm btn-secondary"
      >
        เพิ่ม Need
      </button>
    )
  }
  return (
    <div className="mt-3 space-y-2 rounded-[3px] border border-hair bg-sunk p-3">
      <label className="field-label" htmlFor="attach-need">เลือก Need ที่ยังไม่มี PLO</label>
      <select id="attach-need" className="input" value={choice} onChange={(e) => setChoice(e.target.value)} disabled={busy}>
        <option value="">— เลือก —</option>
        {usable.map((n) => (
          <option key={n.need_id} value={n.need_id}>{withoutMarker(n.statement_th)}</option>
        ))}
      </select>
      <p className="field-hint">PLO นี้จะถูกร่างใหม่จาก Need เดิมรวมกับข้อที่เลือก และข้อเดิมจะไปอยู่ในส่วนที่ถูกแทนที่</p>
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => { onAttach(choice); setOpen(false); setChoice('') }}
          disabled={!choice || busy}
          className="btn btn-sm btn-primary"
        >
          ยืนยัน
        </button>
        <button onClick={() => { setOpen(false); setChoice('') }} className="btn btn-sm btn-secondary">ยกเลิก</button>
      </div>
    </div>
  )
}
