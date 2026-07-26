import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useProgram } from '../hooks/useProgram'
import api from '../api/client'

interface SMARTCheck {
  specific: boolean
  measurable: boolean
  achievable: boolean
  relevant: boolean
  timely: boolean
  notes_th: string | null
}

interface PLO {
  plo_id: string
  program_id: string
  statement_th: string
  statement_en: string | null
  bloom_level: string
  is_subject_specific: boolean
  action_verb_th: string
  smart_check: SMARTCheck
  source_need_ids: string[]
  source_evidence_ids: string[]
  rationale_th: string
  distinctive_feature_th: string | null
  version: number
  classification: 'generic' | 'specific' | null
  classification_method: 'ksec' | 'llm' | 'manual' | null
  classification_rationale_th: string | null
  smart_retry_count: number
  smart_escalated: boolean
  soft_flags: string[]
  is_optional: boolean
}

interface SkillCluster {
  cluster_id: string
  canonical_name_th: string
  canonical_name_en: string | null
}

const METHOD_LABEL: Record<string, string> = {
  ksec: 'field',
  llm: 'LLM',
  manual: 'manual',
}

const METHOD_COLOR: Record<string, string> = {
  ksec: 'bg-gray-100 text-gray-600',
  llm: 'bg-blue-100 text-blue-700',
  manual: 'bg-amber-100 text-amber-700',
}

function effectiveClass(p: PLO): 'generic' | 'specific' {
  if (p.classification) return p.classification
  return p.is_subject_specific ? 'specific' : 'generic'
}

export default function PloReport() {
  const { programId } = useProgram()
  const [plos, setPlos] = useState<PLO[]>([])
  const [clusters, setClusters] = useState<SkillCluster[]>([])
  const [view, setView] = useState<'list' | 'matrix'>('list')
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    if (!programId) return
    setLoading(true)
    setError('')
    try {
      const [ploRes, clusterRes] = await Promise.all([
        api.get<PLO[]>(`/programs/${programId}/plos/`),
        api.get<SkillCluster[]>(`/programs/${programId}/clusters/`),
      ])
      setPlos(ploRes.data)
      setClusters(clusterRes.data)
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
      const res = await api.post<PLO[]>(`/programs/${programId}/plos/report/run`)
      setPlos(res.data)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'รัน PLO Report ไม่สำเร็จ')
    } finally {
      setRunning(false)
    }
  }, [programId])

  useEffect(() => { fetchData() }, [fetchData])

  const flip = async (p: PLO) => {
    const next = effectiveClass(p) === 'specific' ? 'generic' : 'specific'
    const body: PLO = {
      ...p,
      classification: next,
      is_subject_specific: next === 'specific',
    }
    try {
      const res = await api.put<PLO>(`/programs/${programId}/plos/${p.plo_id}`, body)
      setPlos(prev => prev.map(x => (x.plo_id === p.plo_id ? res.data : x)))
    } catch {
      setError('สลับประเภทไม่สำเร็จ')
    }
  }

  if (!programId) {
    return (
      <div className="max-w-2xl mx-auto py-16 text-center">
        <p className="text-gray-500 mb-4">ยังไม่ได้เลือกโปรแกรม</p>
        <Link to="/" className="text-blue-600 hover:underline">ไปหน้า Intake</Link>
      </div>
    )
  }

  const mainPlos = plos.filter(p => !p.is_optional)
  const optionalPlos = plos.filter(p => p.is_optional)
  const generic = mainPlos.filter(p => effectiveClass(p) === 'generic')
  const specific = mainPlos.filter(p => effectiveClass(p) === 'specific')
  const referencedClusters = clusters.filter(c =>
    mainPlos.some(p => p.source_need_ids.includes(c.cluster_id))
  )

  return (
    <div className="max-w-5xl mx-auto py-8 px-4">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">Stage 5: PLO Report</h1>
        <p className="text-gray-500 text-sm">
          จำแนก PLO เป็นทักษะทั่วไป (generic) หรือเฉพาะสาขา (specific) — ตรวจสอบและแก้ไขได้
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
          <p className="text-gray-600 font-medium mb-1">กำลังจำแนก PLO...</p>
        </div>
      ) : plos.length === 0 ? (
        <div className="text-center py-20">
          <div className="text-5xl mb-4">🗂️</div>
          <p className="text-gray-500 text-lg font-medium mb-1">ยังไม่มี PLO</p>
          <p className="text-gray-400 text-sm mb-6">รัน PLO Synthesis ก่อน แล้วกลับมาจำแนกที่นี่</p>
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
            <div className="flex items-center gap-4 text-sm text-gray-500">
              <span><b className="text-gray-700">{generic.length}</b> generic</span>
              <span><b className="text-gray-700">{specific.length}</b> specific</span>
              <button onClick={runReport} className="text-xs text-gray-400 hover:text-blue-600 underline">
                Re-run
              </button>
            </div>
            <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
              <button
                onClick={() => setView('list')}
                className={`text-sm px-3 py-1 rounded-md ${view === 'list' ? 'bg-white shadow-sm font-medium' : 'text-gray-500'}`}
              >
                List
              </button>
              <button
                onClick={() => setView('matrix')}
                className={`text-sm px-3 py-1 rounded-md ${view === 'matrix' ? 'bg-white shadow-sm font-medium' : 'text-gray-500'}`}
              >
                Matrix
              </button>
            </div>
          </div>

          {view === 'list' ? (
            <div className="space-y-8">
              <ReportGroup title="Generic Skills" plos={generic} onFlip={flip} />
              <ReportGroup title="Specific Skills" plos={specific} onFlip={flip} />
            </div>
          ) : (
            <ReportMatrix plos={mainPlos} clusters={referencedClusters} />
          )}

          {optionalPlos.length > 0 && (
            <div className="mt-8 border border-amber-200 rounded-xl p-5 bg-amber-50/40">
              <h2 className="text-sm font-semibold text-amber-800 uppercase tracking-wide mb-1">
                PLO เสริม (จากความต้องการประเภท want)
              </h2>
              <p className="text-xs text-amber-700 mb-4">
                รายการเหล่านี้ไม่นับใน PLO หลัก 6-10 ข้อ — เลือกใช้ได้ตามดุลยพินิจของหลักสูตร
              </p>
              <div className="space-y-3">
                {optionalPlos.map(p => (
                  <div key={p.plo_id} className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
                    <div className="flex items-start gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap mb-1.5">
                          <span className="text-xs font-mono text-gray-400 bg-gray-50 px-2 py-0.5 rounded">{p.plo_id}</span>
                          <ClassBadge value={effectiveClass(p)} />
                          <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 font-medium">
                            เสริม
                          </span>
                        </div>
                        <p className="text-gray-900 font-medium leading-relaxed">{p.statement_th}</p>
                        {p.rationale_th && (
                          <p className="text-gray-500 text-sm mt-1 italic">{p.rationale_th}</p>
                        )}
                      </div>
                      <button
                        onClick={() => flip(p)}
                        className="shrink-0 text-sm border border-gray-200 px-3 py-1.5 rounded-lg hover:bg-gray-50 text-gray-600"
                      >
                        → {effectiveClass(p) === 'specific' ? 'generic' : 'specific'}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

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

function ClassBadge({ value }: { value: 'generic' | 'specific' }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
      value === 'specific' ? 'bg-indigo-100 text-indigo-700' : 'bg-teal-100 text-teal-700'
    }`}>
      {value}
    </span>
  )
}

function ReportGroup({
  title,
  plos,
  onFlip,
}: {
  title: string
  plos: PLO[]
  onFlip: (p: PLO) => void
}) {
  return (
    <div>
      <h2 className="text-sm font-semibold text-gray-600 uppercase tracking-wide mb-3">
        {title} ({plos.length})
      </h2>
      {plos.length === 0 ? (
        <p className="text-gray-400 text-sm">— ไม่มี —</p>
      ) : (
        <div className="space-y-3">
          {plos.map(p => {
            const cls = effectiveClass(p)
            return (
              <div key={p.plo_id} className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap mb-1.5">
                      <span className="text-xs font-mono text-gray-400 bg-gray-50 px-2 py-0.5 rounded">{p.plo_id}</span>
                      <ClassBadge value={cls} />
                      {p.classification_method && (
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${METHOD_COLOR[p.classification_method]}`}>
                          {METHOD_LABEL[p.classification_method]}
                        </span>
                      )}
                    </div>
                    <p className="text-gray-900 font-medium leading-relaxed">{p.statement_th}</p>
                    {p.classification_rationale_th && (
                      <p className="text-gray-500 text-sm mt-1 italic">{p.classification_rationale_th}</p>
                    )}
                  </div>
                  <button
                    onClick={() => onFlip(p)}
                    className="shrink-0 text-sm border border-gray-200 px-3 py-1.5 rounded-lg hover:bg-gray-50 text-gray-600"
                  >
                    → {cls === 'specific' ? 'generic' : 'specific'}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function ReportMatrix({ plos, clusters }: { plos: PLO[]; clusters: SkillCluster[] }) {
  if (clusters.length === 0) {
    return <p className="text-gray-400 text-sm">ไม่มี cluster ที่ PLO อ้างอิง</p>
  }
  return (
    <div className="overflow-x-auto border border-gray-200 rounded-xl">
      <table className="text-sm border-collapse">
        <thead>
          <tr className="bg-gray-50">
            <th className="sticky left-0 bg-gray-50 text-left px-3 py-2 font-semibold text-gray-600 border-b border-gray-200">
              PLO / Class
            </th>
            {clusters.map(c => (
              <th
                key={c.cluster_id}
                className="px-3 py-2 font-medium text-gray-500 border-b border-gray-200 whitespace-nowrap text-xs"
                title={c.canonical_name_th}
              >
                {c.canonical_name_en ?? c.canonical_name_th}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {plos.map(p => (
            <tr key={p.plo_id} className="hover:bg-gray-50">
              <td className="sticky left-0 bg-white hover:bg-gray-50 px-3 py-2 border-b border-gray-100 whitespace-nowrap">
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-xs text-gray-600">{p.plo_id}</span>
                  <ClassBadge value={effectiveClass(p)} />
                </div>
              </td>
              {clusters.map(c => (
                <td key={c.cluster_id} className="px-3 py-2 border-b border-gray-100 text-center">
                  {p.source_need_ids.includes(c.cluster_id)
                    ? <span className="text-green-600 font-bold">✓</span>
                    : <span className="text-gray-200">·</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
