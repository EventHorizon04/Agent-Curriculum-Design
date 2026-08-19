import { useState, useEffect, useCallback, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useProgram } from '../hooks/useProgram'
import api from '../api/client'
import { ksecColor, ksecLabel, stakeholderLabel, classStyle } from '../constants/stakeholder'

interface PLO {
  plo_id: string
  statement_th: string
  statement_en: string | null
  bloom_level: string
  source_need_ids: string[]
  rationale_th: string
  smart_retry_count: number
  smart_escalated: boolean
  soft_flags: string[]
  is_optional: boolean
}

interface NeedSummary {
  need_id: string
  ksec_category: string
}

interface ReportCounts {
  total: number
  core: number
  optional: number
  escalated: number
}

interface PLOReportResponse {
  plos: PLO[]
  counts: ReportCounts
  needs_by_id: Record<string, NeedSummary>
}

interface TraceNeed {
  need_id: string
  statement_th: string
  statement_en: string | null
  ksec_category: string
  bloom_level: string
  demand_score: number
  source_evidence_ids: string[]
}

interface TraceEvidence {
  evidence_id: string
  source_name: string
  stakeholder_type: string
  classification: string
  raw_text_th: string
}

interface PLOTrace {
  plo: PLO
  clusters: TraceNeed[]
  evidence: TraceEvidence[]
}

const BLOOM_LABEL: Record<string, string> = {
  remember: 'Remember',
  understand: 'Understand',
  apply: 'Apply',
  analyze: 'Analyze',
  evaluate: 'Evaluate',
  create: 'Create',
}

const SOFT_FLAG_TH: Record<string, string> = {
  S_object: 'กรรมของกริยากว้างเกินไป',
  A_level: 'ระดับ Bloom อาจสูง/ต่ำเกินไป',
  R_alignment: 'อาจไม่สอดคล้องวิสัยทัศน์',
}

function countsFrom(plos: PLO[]): ReportCounts {
  const core = plos.filter((p) => !p.is_optional).length
  return {
    total: plos.length,
    core,
    optional: plos.length - core,
    escalated: plos.filter((p) => p.smart_escalated).length,
  }
}

export default function PloReport() {
  const { programId } = useProgram()
  const [plos, setPlos] = useState<PLO[]>([])
  const [needsById, setNeedsById] = useState<Record<string, NeedSummary>>({})
  const [counts, setCounts] = useState<ReportCounts>({ total: 0, core: 0, optional: 0, escalated: 0 })
  // Derived, not read off the response: `fetchData` and `runReport` populate the
  // page by different routes, and a count that only one of them set would read as
  // "nothing was cut" on the other. Same rule the report stage applies server-side.
  const needsWithoutPlo = useMemo(() => {
    const cited = new Set(plos.flatMap((p) => p.source_need_ids))
    return Object.keys(needsById).filter((id) => !cited.has(id)).length
  }, [plos, needsById])
  const [exporting, setExporting] = useState(false)
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    if (!programId) return
    setLoading(true)
    setError('')
    try {
      const [ploRes, needRes] = await Promise.all([
        api.get<PLO[]>(`/programs/${programId}/plos/`),
        api.get<NeedSummary[]>(`/programs/${programId}/needs/`),
      ])
      setPlos(ploRes.data)
      setNeedsById(Object.fromEntries(needRes.data.map((n) => [n.need_id, n])))
      setCounts(countsFrom(ploRes.data))
    } catch {
      setError('โหลดข้อมูลไม่สำเร็จ')
    } finally {
      setLoading(false)
    }
  }, [programId])

  const runReport = useCallback(async () => {
    if (!programId) return
    setRunning(true)
    setError('')
    try {
      const res = await api.post<PLOReportResponse>(`/programs/${programId}/plos/report/run`)
      setPlos(res.data.plos)
      setCounts(res.data.counts)
      setNeedsById(res.data.needs_by_id)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'รัน PLO Report ไม่สำเร็จ')
    } finally {
      setRunning(false)
    }
  }, [programId])

  // Fetched as a blob through the api client rather than linked with a plain
  // anchor, so a 422 or 501 surfaces as an error message here instead of
  // navigating the designer to a raw JSON body.
  const exportMatrix = useCallback(async () => {
    if (!programId) return
    setExporting(true)
    setError('')
    try {
      const res = await api.get(`/programs/${programId}/plos/export/matrix.xlsx`, {
        responseType: 'blob',
      })
      const url = URL.createObjectURL(res.data as Blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `plo-matrix-${programId}.xlsx`
      link.click()
      URL.revokeObjectURL(url)
    } catch {
      setError('ส่งออก Excel ไม่สำเร็จ')
    } finally {
      setExporting(false)
    }
  }, [programId])

  useEffect(() => { fetchData() }, [fetchData])

  if (!programId) {
    return (
      <div className="max-w-2xl mx-auto py-16 text-center">
        <p className="text-gray-500 mb-4">ยังไม่ได้เลือกโปรแกรม</p>
        <Link to="/" className="text-blue-600 hover:underline">ไปหน้า Intake</Link>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto py-8 px-4">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">Stage 5: PLO Report</h1>
        <p className="text-gray-500 text-sm">
          รายงาน PLO ฉบับสมบูรณ์ พร้อมที่มาของแต่ละรายการ — ตรวจสอบก่อนส่งออก
        </p>
        <p className="text-xs text-gray-400 mt-1 font-mono">{programId}</p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6 text-red-700 text-sm">{error}</div>
      )}

      {loading ? (
        <div className="text-center py-16 text-gray-400">กำลังโหลด...</div>
      ) : running ? (
        <div className="text-center py-20">
          <div className="text-4xl mb-4 animate-spin">⚙️</div>
          <p className="text-gray-600 font-medium mb-1">กำลังประมวลผล PLO Report...</p>
        </div>
      ) : plos.length === 0 ? (
        <div className="text-center py-20">
          <div className="text-5xl mb-4">🗂️</div>
          <p className="text-gray-500 text-lg font-medium mb-1">ยังไม่มี PLO</p>
          <p className="text-gray-400 text-sm mb-6">รัน PLO Synthesis ก่อน แล้วกลับมาสร้างรายงานที่นี่</p>
          <button
            onClick={runReport}
            className="bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 font-medium"
          >
            Run PLO Report
          </button>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap justify-between items-center gap-3 mb-5">
            <div className="flex gap-4 text-sm text-gray-600">
              <span><b className="text-gray-700">{counts.total}</b> ทั้งหมด</span>
              <span><b className="text-gray-700">{counts.core}</b> หลัก</span>
              <span><b className="text-gray-700">{counts.optional}</b> เสริม</span>
              {counts.escalated > 0 && (
                <span className="text-amber-700"><b>{counts.escalated}</b> ต้องแก้ไข</span>
              )}
              {needsWithoutPlo > 0 && (
                <span
                  className="text-amber-700"
                  title="ความต้องการที่ไม่ได้ถูกแปลงเป็น PLO — เพดาน PLO หลักคือ 10 ข้อ เรียงตาม demand score"
                >
                  <b>{needsWithoutPlo}</b> Need ไม่ได้ใช้
                </span>
              )}
              <button onClick={runReport} className="text-xs text-gray-400 hover:text-blue-600 underline">
                Re-run
              </button>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={exportMatrix}
                disabled={exporting}
                className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 disabled:opacity-50"
              >
                {exporting ? 'กำลังส่งออก...' : 'ส่งออก Excel'}
              </button>
              {/* The CHECO and มคอ.2 exporters are stubs; their routes answer 501.
                  Shown disabled so the designer knows the outputs are planned
                  rather than missing. */}
              <button
                disabled
                title="อยู่ระหว่างพัฒนา"
                className="cursor-not-allowed rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-400"
              >
                CHECO (เร็วๆ นี้)
              </button>
              <button
                disabled
                title="อยู่ระหว่างพัฒนา"
                className="cursor-not-allowed rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-400"
              >
                มคอ.2 (เร็วๆ นี้)
              </button>
            </div>
          </div>

          <div className="space-y-3">
            {plos.map((p) => (
              <PLOCard key={p.plo_id} plo={p} programId={programId} needsById={needsById} />
            ))}
          </div>

          <div className="mt-8 text-sm text-gray-500 border-t border-gray-100 pt-4">
            เมื่อตรวจสอบเสร็จ ไปที่{' '}
            <Link to="/pipeline" className="text-blue-600 hover:underline">หน้า Pipeline</Link>{' '}
            เพื่อ Approve และจบ session
          </div>
        </>
      )}
    </div>
  )
}

function PLOCard({
  plo: p,
  programId,
  needsById,
}: {
  plo: PLO
  programId: string
  needsById: Record<string, NeedSummary>
}) {
  const [traceOpen, setTraceOpen] = useState(false)

  const ksecTags = [...new Set(
    p.source_need_ids.map((id) => needsById[id]?.ksec_category).filter((c): c is string => Boolean(c)),
  )]

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
      <div className="flex items-center gap-2 flex-wrap mb-2">
        <span className="text-xs font-mono text-gray-400 bg-gray-50 px-2 py-0.5 rounded">{p.plo_id}</span>
        <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 font-medium">
          {BLOOM_LABEL[p.bloom_level] ?? p.bloom_level}
        </span>
        {ksecTags.map((cat) => (
          <span key={cat} className={`text-xs px-2 py-0.5 rounded-full font-medium ${ksecColor(cat)}`}>
            {ksecLabel(cat)}
          </span>
        ))}
        {p.is_optional && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 font-medium">
            เสริม
          </span>
        )}
      </div>

      {p.smart_escalated && (
        <div className="mb-2 rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-xs text-red-700">
          ไม่ผ่าน SMART หลัง retry {p.smart_retry_count} ครั้ง — ต้องแก้ด้วยมือ
        </div>
      )}

      {p.soft_flags.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1">
          {p.soft_flags.map((f) => (
            <span key={f} className="rounded-full bg-yellow-100 px-2 py-0.5 text-xs text-yellow-800">
              {SOFT_FLAG_TH[f] ?? f}
            </span>
          ))}
        </div>
      )}

      <p className="text-gray-900 font-medium leading-relaxed">{p.statement_th}</p>
      {p.statement_en && (
        <p className="text-gray-400 text-sm mt-1 italic">{p.statement_en}</p>
      )}
      {p.rationale_th && (
        <p className="text-gray-500 text-sm mt-2 leading-relaxed">{p.rationale_th}</p>
      )}

      <div className="mt-3 pt-3 border-t border-gray-100 flex items-center gap-4 text-xs text-gray-400">
        <span>{p.source_need_ids.length} needs</span>
        <button
          onClick={() => setTraceOpen((v) => !v)}
          aria-expanded={traceOpen}
          className="ml-auto text-xs text-blue-500 hover:text-blue-700 font-medium transition-colors flex items-center gap-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
        >
          {traceOpen ? '▲ ซ่อนที่มา' : '▼ ดูที่มา'}
        </button>
      </div>
      {traceOpen && <TracePanel programId={programId} ploId={p.plo_id} />}
    </div>
  )
}

function TracePanel({ programId, ploId }: { programId: string; ploId: string }) {
  const [trace, setTrace] = useState<PLOTrace | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get<PLOTrace>(`/programs/${programId}/plos/${ploId}/trace`)
      .then((r) => setTrace(r.data))
      .catch(() => setError('โหลด trace ไม่สำเร็จ'))
      .finally(() => setLoading(false))
  }, [programId, ploId])

  if (loading) return <div className="py-4 text-center text-sm text-gray-400">กำลังโหลด trace...</div>
  if (error) return <div className="py-3 text-sm text-red-600">{error}</div>
  if (!trace) return null

  return (
    <div className="mt-4 pt-4 border-t border-gray-100 space-y-4">
      <div>
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Needs ({trace.clusters.length})
        </h4>
        <div className="space-y-2">
          {trace.clusters.map((c) => (
            <div key={c.need_id} className="bg-gray-50 rounded-lg px-3 py-2.5 border border-gray-100">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-800 leading-snug">{c.statement_th}</p>
                  {c.statement_en && (
                    <p className="text-xs text-gray-400 italic">{c.statement_en}</p>
                  )}
                </div>
                <span className="shrink-0 text-xs font-mono bg-white border border-gray-200 rounded px-1.5 py-0.5 text-gray-600">
                  {(c.demand_score * 100).toFixed(0)}%
                </span>
              </div>
              <p className="text-xs text-gray-400 mt-1.5">
                {c.source_evidence_ids.length} evidence ·{' '}
                <span className={`rounded px-1 ${ksecColor(c.ksec_category)}`}>{ksecLabel(c.ksec_category)}</span>
                {' '}· {c.bloom_level}
              </p>
            </div>
          ))}
        </div>
      </div>

      <div>
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Evidence ({trace.evidence.length})
        </h4>
        <div className="space-y-2">
          {trace.evidence.map((e) => (
            <div key={e.evidence_id} className="bg-white rounded-lg px-3 py-2.5 border border-gray-100">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-medium text-gray-700">{e.source_name}</span>
                <span className="text-xs text-gray-400">{stakeholderLabel(e.stakeholder_type)}</span>
                <span className={`ml-auto text-xs px-2 py-0.5 rounded-full font-medium ${classStyle(e.classification).cls}`}>
                  {classStyle(e.classification).label}
                </span>
              </div>
              <p className="text-xs text-gray-600 leading-relaxed line-clamp-3">{e.raw_text_th}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
