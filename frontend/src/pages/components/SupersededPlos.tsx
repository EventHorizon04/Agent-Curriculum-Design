import { withoutMarker } from '../../constants/needPolicy'
import type { PickerNeed } from './pickerNeed'
import type { SupersededPLO } from '../../types/plo'

function localTime(iso: string): string {
  const t = Date.parse(iso)
  return Number.isNaN(t) ? iso : new Date(t).toLocaleString('th-TH')
}

/** The outcomes a merge replaced, kept for reading only: muted, no actions. */
export default function SupersededPlos({ items, needs }: { items: SupersededPLO[]; needs: PickerNeed[] }) {
  if (items.length === 0) return null
  const statementOf = new Map(needs.map((n) => [n.need_id, withoutMarker(n.statement_th)]))
  return (
    <details className="panel mt-8 p-4 sm:p-5">
      <summary className="section-title cursor-pointer">PLO ที่ถูกแทนที่ ({items.length})</summary>
      <div className="mt-4 space-y-3">
        {items.map((s) => (
          <div key={s.id} className="rounded-[3px] border border-hair bg-sunk px-3 py-2.5 text-pencil">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              <span className="data font-semibold">{s.plo.plo_id}</span>
              <span>
                แทนที่โดย <span className="data">{s.superseded_by}</span>
                {s.superseded_by === s.plo.plo_id && ' ฉบับใหม่'}
              </span>
              <span className="data ml-auto text-lead">{localTime(s.superseded_at)}</span>
            </div>
            <p className="record mt-1.5 text-sm">{s.plo.statement_th}</p>
            <ul className="mt-1.5 space-y-0.5 text-xs text-lead">
              {s.plo.source_need_ids.map((id) => {
                const text = statementOf.get(id)
                return text ? (
                  <li key={id} className="truncate" title={text}>{text}</li>
                ) : (
                  <li key={id} className="truncate">
                    Need ที่ไม่อยู่ในชุดปัจจุบันแล้ว <span className="data text-lead/70">{id.slice(0, 8)}</span>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </div>
    </details>
  )
}
