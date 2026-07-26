import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useProgram } from '../hooks/useProgram'
import api from '../api/client'

interface SkillCluster {
  cluster_id: string
  program_id: string
  canonical_name_th: string
  canonical_name_en: string | null
  description_th: string
  skill_type: string
  is_subject_specific: boolean
  member_skill_ids: string[]
  source_evidence_ids: string[]
  stakeholder_coverage: Record<string, number>
  demand_score: number
  is_common_need: boolean
  sample_quotes_th: string[]
  bloom_level: string | null
  is_optional: boolean
  classification_coverage: Record<string, number>
}

interface EvidenceItem {
  evidence_id: string
  source_name: string
  stakeholder_type: string
  classification: string
  raw_text_th: string
  classification_rationale_th: string | null
}

interface DemandSignal {
  total_program_evidence: number
  unique_evidence_count: number
  freq_score: number
  stakeholder_type_count: number
  max_stakeholder_types: number
  breadth_score: number
  demand_score: number
  stakeholder_breakdown: Record<string, number>
}

interface ExtractedSkill {
  skill_id: string
  skill_name_th: string
  skill_name_en: string | null
  ksec_category: string
  bloom_level: string
  evidence_span_th: string
  source_evidence_id: string
  extraction_method: string
  confidence: number
  importance_score: number
}

interface ClusterTrace {
  cluster: SkillCluster
  skills: ExtractedSkill[]
  evidence: EvidenceItem[]
  demand_signal: DemandSignal
}

const CLASSIFICATION_COLOR: Record<string, string> = {
  need: 'bg-blue-100 text-blue-700',
  requirement: 'bg-green-100 text-green-700',
  want: 'bg-amber-100 text-amber-700',
  unclassified: 'bg-gray-100 text-gray-500',
}

const STAKEHOLDER_LABEL: Record<string, string> = {
  employer: 'นายจ้าง',
  alumni: 'ศิษย์เก่า',
  student: 'นักศึกษา',
  faculty: 'อาจารย์',
  professional_council: 'สภาวิชาชีพ',
  community: 'ชุมชน',
  accreditation_body: 'หน่วยงานประเมิน',
  university: 'มหาวิทยาลัย',
  subject_benchmark: 'มาตรฐานสาขา',
  peer_program: 'หลักสูตรเทียบเคียง',
}

function ClusterTracePanel({ programId, clusterId }: { programId: string; clusterId: string }) {
  const [trace, setTrace] = useState<ClusterTrace | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get<ClusterTrace>(`/programs/${programId}/clusters/${clusterId}/trace`)
      .then(r => setTrace(r.data))
      .catch(() => setError('โหลด trace ไม่สำเร็จ'))
      .finally(() => setLoading(false))
  }, [programId, clusterId])

  if (loading) return <div className="py-3 text-center text-sm text-gray-400">กำลังโหลด trace...</div>
  if (error) return <div className="py-2 text-sm text-red-600">{error}</div>
  if (!trace) return null

  // first 3 evidence IDs are what the LLM used to generate quotes
  const sampleEvidenceIds = new Set(trace.cluster.source_evidence_ids.slice(0, 3))
  const sampleEvidence = trace.evidence.filter(e => sampleEvidenceIds.has(e.evidence_id))

  const ds = trace.demand_signal

  return (
    <div className="mt-3 pt-3 border-t border-gray-100 space-y-4">

      {/* Demand Signal Breakdown */}
      <div>
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Demand Signal
        </h4>
        <div className="bg-gray-50 rounded-lg p-3 border border-gray-100 space-y-3">

          {/* Formula row */}
          <div className="flex items-center gap-2 text-xs flex-wrap">
            <span className="font-mono bg-white border border-gray-200 rounded px-2 py-1 text-gray-700">
              demand = freq × 0.6 + breadth × 0.4
            </span>
            <span className="text-gray-400">=</span>
            <span className="font-mono text-gray-600">
              {(ds.freq_score * 0.6).toFixed(3)} + {(ds.breadth_score * 0.4).toFixed(3)}
            </span>
            <span className="text-gray-400">=</span>
            <span className="font-mono font-bold text-blue-700">{ds.demand_score.toFixed(3)}</span>
          </div>

          {/* Freq bar */}
          <div>
            <div className="flex justify-between text-xs text-gray-600 mb-1">
              <span>
                Frequency <span className="text-gray-400">(evidence coverage)</span>
              </span>
              <span className="font-mono">
                {ds.unique_evidence_count} / {ds.total_program_evidence} = <strong>{(ds.freq_score * 100).toFixed(1)}%</strong>
              </span>
            </div>
            <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-400 rounded-full transition-all"
                style={{ width: `${ds.freq_score * 100}%` }}
              />
            </div>
          </div>

          {/* Breadth bar */}
          <div>
            <div className="flex justify-between text-xs text-gray-600 mb-1">
              <span>
                Breadth <span className="text-gray-400">(stakeholder coverage)</span>
              </span>
              <span className="font-mono">
                {ds.stakeholder_type_count} / {ds.max_stakeholder_types} types = <strong>{(ds.breadth_score * 100).toFixed(1)}%</strong>
              </span>
            </div>
            <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
              <div
                className="h-full bg-indigo-400 rounded-full transition-all"
                style={{ width: `${ds.breadth_score * 100}%` }}
              />
            </div>
          </div>

          {/* Stakeholder breakdown */}
          {Object.keys(ds.stakeholder_breakdown).length > 0 && (
            <div>
              <p className="text-xs text-gray-500 mb-1.5">Stakeholder breakdown</p>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(ds.stakeholder_breakdown)
                  .sort(([, a], [, b]) => b - a)
                  .map(([type, count]) => (
                    <span key={type} className="text-xs bg-white border border-gray-200 rounded-full px-2.5 py-0.5 text-gray-600">
                      {STAKEHOLDER_LABEL[type] ?? type}
                      <span className="ml-1 font-mono font-medium text-indigo-600">{count}</span>
                    </span>
                  ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Extracted Skills */}
      <div>
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Extracted Skills ({(trace.skills ?? []).length})
        </h4>
        {(trace.skills ?? []).length === 0 ? (
          <div className="bg-amber-50 border border-amber-100 rounded-lg px-3 py-2.5 text-xs text-amber-700">
            ไม่มีข้อมูล skills — cluster นี้ถูกสร้างก่อนเพิ่ม skill persistence
            กรุณากด <strong>Re-run</strong> Skill Extraction เพื่อ populate ข้อมูล
          </div>
        ) : (
          <div className="space-y-1.5">
            {(trace.skills ?? [])
              .slice()
              .sort((a, b) => b.confidence - a.confidence)
              .map(s => {
                const srcEvidence = trace.evidence.find(e => e.evidence_id === s.source_evidence_id)
                return (
                  <div key={s.skill_id} className="flex items-start gap-2 bg-white rounded-lg px-3 py-2 border border-gray-100">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-medium text-gray-800">{s.skill_name_en ?? s.skill_name_th}</span>
                        {s.skill_name_en && s.skill_name_en !== s.skill_name_th && (
                          <span className="text-xs text-gray-400 italic">{s.skill_name_th}</span>
                        )}
                      </div>
                      {srcEvidence && (
                        <span className="text-xs text-gray-400 mt-0.5 block truncate">
                          จาก: {srcEvidence.source_name}
                          <span className="ml-1 text-gray-300">·</span>
                          <span className="ml-1">{STAKEHOLDER_LABEL[srcEvidence.stakeholder_type] ?? srcEvidence.stakeholder_type}</span>
                        </span>
                      )}
                    </div>
                    <div className="shrink-0 flex items-center gap-1.5">
                      <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${KSEC_COLOR[s.ksec_category] ?? 'bg-gray-100 text-gray-600'}`}>
                        {KSEC_LABEL[s.ksec_category] ?? s.ksec_category}
                      </span>
                      {s.bloom_level && (
                        <span className="text-xs px-1.5 py-0.5 rounded font-medium bg-indigo-100 text-indigo-800">
                          {LEVEL_TH[s.bloom_level] ?? s.bloom_level}
                        </span>
                      )}
                      <span className="text-xs font-mono text-gray-400 bg-gray-50 border border-gray-100 rounded px-1.5 py-0.5">
                        {s.extraction_method}
                      </span>
                      <span
                        title="importance_score (demand ก่อน cluster)"
                        className={`text-xs font-mono px-1.5 py-0.5 rounded ${s.importance_score >= 0.7 ? 'text-green-700 bg-green-50' : s.importance_score >= 0.4 ? 'text-amber-700 bg-amber-50' : 'text-red-700 bg-red-50'}`}
                      >
                        ★{(s.importance_score * 100).toFixed(0)}%
                      </span>
                      <span className={`text-xs font-mono px-1.5 py-0.5 rounded ${s.confidence >= 0.7 ? 'text-green-700 bg-green-50' : s.confidence >= 0.4 ? 'text-amber-700 bg-amber-50' : 'text-red-700 bg-red-50'}`}>
                        {(s.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>
                )
              })}
          </div>
        )}
      </div>

      {/* Evidence */}
      <div>
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Evidence ({trace.evidence.length})
        </h4>
        <div className="space-y-2">
          {trace.evidence.map(e => {
            const isQuoteSource = sampleEvidenceIds.has(e.evidence_id)
            return (
              <div
                key={e.evidence_id}
                className={`rounded-lg px-3 py-2.5 border ${isQuoteSource ? 'bg-blue-50 border-blue-100' : 'bg-white border-gray-100'}`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-medium text-gray-700">{e.source_name}</span>
                  <span className="text-xs text-gray-400">{STAKEHOLDER_LABEL[e.stakeholder_type] ?? e.stakeholder_type}</span>
                  {isQuoteSource && (
                    <span className="text-xs bg-blue-100 text-blue-700 border border-blue-200 rounded px-1.5 py-0.5 font-medium">
                      quote source
                    </span>
                  )}
                  <span className={`ml-auto text-xs px-2 py-0.5 rounded-full font-medium ${CLASSIFICATION_COLOR[e.classification] ?? 'bg-gray-100 text-gray-500'}`}>
                    {e.classification}
                  </span>
                </div>
                <p className="text-xs text-gray-600 leading-relaxed line-clamp-3">{e.raw_text_th}</p>
              </div>
            )
          })}
        </div>
        {sampleEvidence.length > 0 && (
          <p className="text-xs text-gray-400 italic mt-2">
            Evidence ที่ marked "quote source" คือแหล่งที่ LLM ใช้ generate quotes
          </p>
        )}
      </div>
    </div>
  )
}

const SKILL_TYPE_LABEL: Record<string, string> = {
  knowledge: 'ความรู้',
  psychomotor: 'ทักษะปฏิบัติ',
  affective: 'คุณลักษณะ',
  mixed: 'ผสม',
}

const SKILL_TYPE_COLOR: Record<string, string> = {
  knowledge: 'bg-blue-100 text-blue-800',
  psychomotor: 'bg-green-100 text-green-800',
  affective: 'bg-purple-100 text-purple-800',
  mixed: 'bg-orange-100 text-orange-800',
}

const KSEC_LABEL: Record<string, string> = {
  K: 'K · ความรู้',
  GS: 'GS · ทักษะทั่วไป',
  SS: 'SS · ทักษะเฉพาะสาขา',
  C: 'C · คุณลักษณะ',
  E: 'E · จริยธรรม',
}

const KSEC_COLOR: Record<string, string> = {
  K: 'bg-sky-100 text-sky-800',
  GS: 'bg-teal-100 text-teal-800',
  SS: 'bg-emerald-100 text-emerald-800',
  C: 'bg-amber-100 text-amber-800',
  E: 'bg-rose-100 text-rose-800',
}

const BLOOM_ORDER = ['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create'] as const
const PSYCHOMOTOR_ORDER = ['imitate', 'manipulate', 'precise', 'articulate', 'naturalize'] as const
const LEVEL_ORDER = [...BLOOM_ORDER, ...PSYCHOMOTOR_ORDER] as readonly string[]
const LEVEL_TH: Record<string, string> = {
  remember: 'จำได้ (Remember)', understand: 'เข้าใจ (Understand)', apply: 'ประยุกต์ (Apply)',
  analyze: 'วิเคราะห์ (Analyze)', evaluate: 'ประเมิน (Evaluate)', create: 'สร้างสรรค์ (Create)',
  imitate: 'ทำตามแบบ (Imitate)', manipulate: 'ทำตามคำสั่ง (Manipulate)', precise: 'ทำได้แม่นยำ (Precise)',
  articulate: 'ทำได้ต่อเนื่อง (Articulate)', naturalize: 'ทำได้เป็นธรรมชาติ (Naturalize)',
}

function groupByBloom(clusters: SkillCluster[]): [string, SkillCluster[]][] {
  const groups = new Map<string, SkillCluster[]>()
  for (const level of LEVEL_ORDER) groups.set(level, [])
  groups.set('untagged', [])
  for (const c of clusters) {
    const level = c.bloom_level
    const key = level && LEVEL_ORDER.includes(level) ? level : 'untagged'
    groups.get(key)!.push(c)
  }
  return [...groups.entries()].filter(([, v]) => v.length > 0)
}

export default function SkillExtraction() {
  const { programId } = useProgram()
  const [clusters, setClusters] = useState<SkillCluster[]>([])
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  const fetchClusters = useCallback(async () => {
    if (!programId) return
    setLoading(true)
    setError('')
    try {
      const res = await api.get<SkillCluster[]>(`/programs/${programId}/clusters/`)
      setClusters(res.data)
    } catch {
      setError('โหลด skill clusters ไม่สำเร็จ')
    } finally {
      setLoading(false)
    }
  }, [programId])

  const runExtraction = useCallback(async () => {
    if (!programId) return
    setRunning(true)
    setError('')
    try {
      const res = await api.post<SkillCluster[]>(`/programs/${programId}/clusters/run`)
      setClusters(res.data)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'รัน Skill Extraction ไม่สำเร็จ')
    } finally {
      setRunning(false)
    }
  }, [programId])

  useEffect(() => { fetchClusters() }, [fetchClusters])

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
        <h1 className="text-2xl font-bold text-gray-900 mb-1">Stage 3: Skill Extraction</h1>
        <p className="text-gray-500 text-sm">Skill clusters ที่ extract ได้จาก job market data และ stakeholder evidence</p>
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
          <p className="text-gray-600 font-medium mb-1">กำลัง extract skills...</p>
          <p className="text-gray-400 text-sm">อาจใช้เวลา 1-5 นาที ขึ้นกับจำนวน evidence</p>
        </div>
      ) : clusters.length === 0 ? (
        <div className="text-center py-20">
          <div className="text-5xl mb-4">🔍</div>
          <p className="text-gray-500 text-lg font-medium mb-1">ยังไม่มี skill clusters</p>
          <p className="text-gray-400 text-sm mb-6">กดปุ่มด้านล่างเพื่อ extract skills จาก evidence ที่มีอยู่</p>
          <button
            onClick={runExtraction}
            className="bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 font-medium transition-colors"
          >
            Run Skill Extraction
          </button>
        </div>
      ) : (
        <>
          <div className="flex justify-between items-center mb-5">
            <div className="flex items-center gap-3">
              <span className="text-sm text-gray-500">{clusters.length} clusters</span>
              <button
                onClick={runExtraction}
                disabled={running}
                className="text-xs text-gray-400 hover:text-blue-600 underline disabled:opacity-50"
              >
                Re-run
              </button>
            </div>
            <Link
              to="/plo-synthesis"
              className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 text-sm font-medium transition-colors"
            >
              ดำเนินการต่อ → PLO Synthesis
            </Link>
          </div>
          <div className="space-y-6">
            {groupByBloom(clusters).map(([level, group]) => (
              <div key={level}>
                <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
                  {LEVEL_TH[level] ?? 'ยังไม่จัดระดับ'}
                  <span className="ml-2 text-gray-400 font-normal normal-case">({group.length})</span>
                </h2>
                <div className="space-y-4">
                  {group.map(c => (
                    <ClusterCard key={c.cluster_id} cluster={c} programId={programId} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function ClusterCard({ cluster: c, programId }: { cluster: SkillCluster; programId: string }) {
  const [quotesOpen, setQuotesOpen] = useState(false)
  const [traceOpen, setTraceOpen] = useState(false)

  return (
    <>
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
      <div className="flex items-start gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <h3 className="font-semibold text-gray-900">{c.canonical_name_th}</h3>
            {c.canonical_name_en && (
              <span className="text-gray-400 text-sm">({c.canonical_name_en})</span>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${SKILL_TYPE_COLOR[c.skill_type] ?? 'bg-gray-100 text-gray-700'}`}>
              {SKILL_TYPE_LABEL[c.skill_type] ?? c.skill_type}
            </span>
            {c.is_common_need && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-800 font-medium">
                common need
              </span>
            )}
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${c.is_subject_specific ? 'bg-indigo-100 text-indigo-800' : 'bg-emerald-100 text-emerald-800'}`}>
              {c.is_subject_specific ? 'เฉพาะสาขา' : 'ทักษะทั่วไป'}
            </span>
            {c.is_optional && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 font-medium">
                เสริม (want)
              </span>
            )}
          </div>
          <p className="text-gray-600 text-sm">{c.description_th}</p>
        </div>
        <div className="text-right shrink-0">
          <div className="text-xs text-gray-400 mb-0.5">demand</div>
          <div className="text-xl font-bold text-gray-900">{Math.round(c.demand_score * 100)}%</div>
        </div>
      </div>

      <div className="mt-3 h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-500 rounded-full transition-all"
          style={{ width: `${c.demand_score * 100}%` }}
        />
      </div>

      <div className="mt-3 flex items-center gap-4 text-xs text-gray-400 flex-wrap">
        <span>{c.member_skill_ids.length} skills</span>
        <span>{c.source_evidence_ids.length} evidence</span>
        <span>{Object.keys(c.stakeholder_coverage).length} stakeholder types</span>
        <div className="ml-auto flex items-center gap-3">
          {c.sample_quotes_th.length > 0 && (
            <button
              onClick={() => setQuotesOpen(o => !o)}
              className="text-blue-500 hover:text-blue-700 font-medium"
            >
              {quotesOpen ? 'ซ่อน quotes' : `quotes (${c.sample_quotes_th.length})`}
            </button>
          )}
          <button
            onClick={() => setTraceOpen(o => !o)}
            className="text-blue-500 hover:text-blue-700 font-medium flex items-center gap-1"
          >
            {traceOpen ? '▲ ซ่อน Trace' : '▼ ดู Trace'}
          </button>
        </div>
      </div>

      {quotesOpen && (
        <ul className="mt-3 space-y-2">
          {c.sample_quotes_th.map((q, i) => (
            <li key={i} className="text-sm text-gray-600 bg-gray-50 rounded-lg px-3 py-2 border-l-2 border-blue-300">
              <span className="italic">"{q}"</span>
              <span className="block mt-1 text-xs text-gray-400">
                อ้างอิงจาก evidence ของ cluster นี้ — กด "ดู Trace" เพื่อดูแหล่งที่มา
              </span>
            </li>
          ))}
        </ul>
      )}

    </div>
    {traceOpen && (
      <div className="border border-gray-200 rounded-xl bg-gray-50 px-5 py-4 -mt-2 shadow-sm">
        <ClusterTracePanel programId={programId} clusterId={c.cluster_id} />
      </div>
    )}
    </>
  )
}
