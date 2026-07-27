import { useState } from 'react'
import api from '../../api/client'

export interface NeedRow {
  need_id: string
  statement_th: string
  statement_en: string | null
  ksec_category: string
  bloom_level: string
  member_skill_ids: string[]
  source_evidence_ids: string[]
  freq: number
  demand_score: number
  is_optional: boolean
  sample_quotes_th: string[]
}

interface NeedTrace {
  need: NeedRow
  skills: { skill_id: string; skill_name_th: string; bloom_level: string }[]
  evidence: { evidence_id: string; source_name: string; classification: string }[]
}

const KSEC_LABEL: Record<string, string> = {
  K: 'K · ความรู้',
  GS: 'GS · ทักษะทั่วไป',
  SS: 'SS · ทักษะเฉพาะสาขา',
  C: 'C · คุณลักษณะ',
  E: 'E · จริยธรรม',
}

export default function NeedCard({ programId, need }: { programId: string; need: NeedRow }) {
  const [trace, setTrace] = useState<NeedTrace | null>(null)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')

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
        <p className="flex-1 text-sm font-medium leading-relaxed text-gray-800">
          {need.statement_th}
        </p>
        {need.is_optional && (
          <span className="shrink-0 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
            เสริม
          </span>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-600">
        <span className="rounded bg-gray-100 px-1.5 py-0.5">
          {KSEC_LABEL[need.ksec_category] ?? need.ksec_category}
        </span>
        <span className="rounded bg-indigo-100 px-1.5 py-0.5 text-indigo-800">
          {need.bloom_level}
        </span>
        <span title="จำนวนครั้งที่ถูกกล่าวถึง">Freq {need.freq}</span>
        <span title="คะแนนถ่วงน้ำหนักตามความถี่และความกว้างของ stakeholder">
          Demand {(need.demand_score * 100).toFixed(0)}%
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
                      {s.skill_name_th} <span className="text-gray-400">· {s.bloom_level}</span>
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
                    <li key={e.evidence_id}>
                      {e.source_name} <span className="text-gray-400">· {e.classification}</span>
                    </li>
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
