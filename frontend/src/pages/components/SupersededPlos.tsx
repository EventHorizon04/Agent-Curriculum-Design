import type { SupersededPLO } from '../../types/plo'

function localTime(iso: string): string {
  const t = Date.parse(iso)
  return Number.isNaN(t) ? iso : new Date(t).toLocaleString('th-TH')
}

/** The outcomes a merge replaced, kept for reading only: muted, no actions. */
export default function SupersededPlos({ items }: { items: SupersededPLO[] }) {
  if (items.length === 0) return null
  return (
    <details className="panel mt-8 p-4 sm:p-5">
      <summary className="section-title cursor-pointer">PLO ที่ถูกแทนที่ ({items.length})</summary>
      <div className="mt-4 space-y-3">
        {items.map((s) => (
          <div key={s.id} className="rounded-[3px] border border-hair bg-sunk px-3 py-2.5 text-pencil">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              <span className="data font-semibold">{s.plo.plo_id}</span>
              <span>แทนที่โดย <span className="data">{s.superseded_by}</span></span>
              <span className="data ml-auto text-lead">{localTime(s.superseded_at)}</span>
            </div>
            <p className="record mt-1.5 text-sm">{s.plo.statement_th}</p>
            <p className="data mt-1.5 text-xs text-lead">{s.plo.source_need_ids.join(', ')}</p>
          </div>
        ))}
      </div>
    </details>
  )
}
