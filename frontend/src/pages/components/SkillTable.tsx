import { Fragment, useMemo, useState } from 'react'
import { classStyle, ksecColor, ksecLabel, stakeholderLabel } from '../../constants/stakeholder'

export interface SkillRow {
  skill_id: string
  skill_name_th: string
  skill_name_en: string | null
  ksec_category: string
  bloom_level: string
  evidence_span_th: string
  source_evidence_id: string
  source_stakeholder_type: string
  classification: string
}

export interface EvidenceMeta {
  source_name: string
  stakeholder_type: string
  classification: string
}

type SortKey = 'skill_name_th' | 'bloom_level' | 'ksec_category' | 'stakeholder' | 'classification'

const BLOOM_TH: Record<string, string> = {
  remember: 'จำได้ (Remember)',
  understand: 'เข้าใจ (Understand)',
  apply: 'ประยุกต์ (Apply)',
  analyze: 'วิเคราะห์ (Analyze)',
  evaluate: 'ประเมิน (Evaluate)',
  create: 'สร้างสรรค์ (Create)',
}

const COLUMNS: { key: SortKey; label: string; numeric?: boolean }[] = [
  { key: 'skill_name_th', label: 'Skill' },
  { key: 'bloom_level', label: "Bloom's" },
  { key: 'ksec_category', label: 'KSEC' },
  { key: 'stakeholder', label: 'ที่มา' },
  { key: 'classification', label: 'Class' },
]

export default function SkillTable({
  skills,
  evidenceById,
  droppedCount,
}: {
  skills: SkillRow[]
  evidenceById: Record<string, EvidenceMeta>
  droppedCount: number
}) {
  const [sortKey, setSortKey] = useState<SortKey>('skill_name_th')
  const [asc, setAsc] = useState(true)
  const [expanded, setExpanded] = useState<string | null>(null)

  const sorted = useMemo(() => {
    const value = (s: SkillRow): string | number =>
      sortKey === 'stakeholder' ? s.source_stakeholder_type : (s[sortKey] as string | number)
    return [...skills].sort((a, b) => {
      const av = value(a)
      const bv = value(b)
      const cmp = typeof av === 'number' && typeof bv === 'number'
        ? av - bv
        : String(av).localeCompare(String(bv), 'th')
      return asc ? cmp : -cmp
    })
  }, [skills, sortKey, asc])

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) setAsc(!asc)
    else {
      setSortKey(key)
      setAsc(true)
    }
  }

  const toggleRow = (skillId: string) => setExpanded(prev => (prev === skillId ? null : skillId))

  if (skills.length === 0) {
    return <p className="py-8 text-center text-sm text-gray-400">ยังไม่มีทักษะที่สกัดได้</p>
  }

  return (
    <div className="space-y-3">
      {droppedCount > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          ทิ้งไป {droppedCount} ทักษะ (ข้อความที่ยกอ้างไม่ตรงกับ evidence)
        </div>
      )}
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              {COLUMNS.map(c => (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={sortKey === c.key ? (asc ? 'ascending' : 'descending') : 'none'}
                  className={`px-1 py-1 text-xs font-semibold uppercase tracking-wide text-gray-500 ${c.numeric ? 'text-right' : 'text-left'}`}
                >
                  <button
                    type="button"
                    onClick={() => toggleSort(c.key)}
                    className={`w-full cursor-pointer select-none rounded px-2 py-1 hover:text-gray-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${c.numeric ? 'text-right' : 'text-left'}`}
                  >
                    {c.label}
                    {sortKey === c.key && <span className="ml-1">{asc ? '▲' : '▼'}</span>}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {sorted.map(s => {
              const ev = evidenceById[s.source_evidence_id]
              const open = expanded === s.skill_id
              return (
                <Fragment key={s.skill_id}>
                  <tr
                    role="button"
                    tabIndex={0}
                    aria-expanded={open}
                    aria-label={`${s.skill_name_th} — กด Enter เพื่อ${open ? 'ซ่อน' : 'ดู'}ข้อความอ้างอิงและที่มา`}
                    onClick={() => toggleRow(s.skill_id)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        toggleRow(s.skill_id)
                      }
                    }}
                    className="cursor-pointer hover:bg-gray-50 focus:outline-none focus-visible:bg-blue-50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500"
                  >
                    <td className="px-3 py-2">
                      <span className="font-medium text-gray-800">{s.skill_name_th}</span>
                      {s.skill_name_en && (
                        <span className="ml-2 text-xs text-gray-400 italic">{s.skill_name_en}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-600">
                      {BLOOM_TH[s.bloom_level] ?? s.bloom_level}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${ksecColor(s.ksec_category)}`}>
                        {ksecLabel(s.ksec_category)}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-600">
                      {stakeholderLabel(s.source_stakeholder_type)}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${classStyle(s.classification).cls}`}>
                        {classStyle(s.classification).label}
                      </span>
                    </td>
                  </tr>
                  {open && (
                    <tr className="bg-gray-50">
                      <td colSpan={COLUMNS.length} className="px-3 py-2">
                        <p className="text-xs text-gray-500">ข้อความที่ยกอ้างจาก evidence:</p>
                        <blockquote className="mt-1 border-l-2 border-gray-300 pl-2 text-xs text-gray-700">
                          {s.evidence_span_th}
                        </blockquote>
                        <p className="mt-1 text-xs text-gray-400">
                          จาก: {ev?.source_name ?? s.source_evidence_id}
                          {ev && <> · {ev.stakeholder_type}</>}
                        </p>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
