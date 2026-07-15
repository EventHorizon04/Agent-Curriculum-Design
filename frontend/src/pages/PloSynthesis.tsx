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
  domain: string
  bloom_level: string | null
  psychomotor_level: string | null
  krathwohl_level: string | null
  is_subject_specific: boolean
  action_verb_th: string
  smart_check: SMARTCheck
  source_cluster_ids: string[]
  source_evidence_ids: string[]
  rationale_th: string
  distinctive_feature_th: string | null
  version: number
  classification: 'generic' | 'specific' | null
  classification_method: 'skill_type' | 'llm' | 'manual' | null
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
  description_th: string
  skill_type: string
  demand_score: number
  is_common_need: boolean
  source_evidence_ids: string[]
}

interface StakeholderEvidence {
  evidence_id: string
  source_name: string
  stakeholder_type: string
  classification: string
  raw_text_th: string
  classification_rationale_th: string | null
}

interface PLOTrace {
  plo: PLO
  clusters: SkillCluster[]
  evidence: StakeholderEvidence[]
}

const DOMAIN_LABEL: Record<string, string> = {
  cognitive: 'Cognitive',
  psychomotor: 'Psychomotor',
  affective: 'Affective',
}

const DOMAIN_COLOR: Record<string, string> = {
  cognitive: 'bg-blue-100 text-blue-800',
  psychomotor: 'bg-green-100 text-green-800',
  affective: 'bg-purple-100 text-purple-800',
}

const BLOOM_LABEL: Record<string, string> = {
  remember: 'Remember',
  understand: 'Understand',
  apply: 'Apply',
  analyze: 'Analyze',
  evaluate: 'Evaluate',
  create: 'Create',
  imitate: 'Imitate',
  manipulate: 'Manipulate',
  precise: 'Precise',
  articulate: 'Articulate',
  naturalize: 'Naturalize',
}

const SMART_KEYS: (keyof SMARTCheck)[] = ['specific', 'measurable', 'achievable', 'relevant', 'timely']

const SOFT_FLAG_TH: Record<string, string> = {
  S_object: 'กรรมของกริยากว้างเกินไป',
  A_level: 'ระดับ Bloom อาจสูง/ต่ำเกินไป',
  R_alignment: 'อาจไม่สอดคล้องวิสัยทัศน์',
}

export default function PloSynthesis() {
  const { programId } = useProgram()
  const [plos, setPlos] = useState<PLO[]>([])
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  const fetchPlos = useCallback(async () => {
    if (!programId) return
    setLoading(true)
    setError('')
    try {
      const res = await api.get<PLO[]>(`/programs/${programId}/plos/`)
      setPlos(res.data)
    } catch {
      setError('โหลด PLO ไม่สำเร็จ')
    } finally {
      setLoading(false)
    }
  }, [programId])

  const runSynthesis = useCallback(async () => {
    if (!programId) return
    setRunning(true)
    setError('')
    try {
      const res = await api.post<PLO[]>(`/programs/${programId}/plos/run`)
      setPlos(res.data)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'รัน PLO Synthesis ไม่สำเร็จ')
    } finally {
      setRunning(false)
    }
  }, [programId])

  useEffect(() => { fetchPlos() }, [fetchPlos])

  const handleUpdate = (updated: PLO) =>
    setPlos(prev => prev.map(p => (p.plo_id === updated.plo_id ? updated : p)))

  if (!programId) {
    return (
      <div className="max-w-2xl mx-auto py-16 text-center">
        <p className="text-gray-500 mb-4">ยังไม่ได้เลือกโปรแกรม</p>
        <Link to="/" className="text-blue-600 hover:underline">ไปหน้า Intake</Link>
      </div>
    )
  }

  const smartPassCount = plos.filter(p =>
    SMART_KEYS.every(k => p.smart_check[k] === true)
  ).length

  return (
    <div className="max-w-4xl mx-auto py-8 px-4">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">Stage 4: PLO Synthesis</h1>
        <p className="text-gray-500 text-sm">ตรวจสอบและแก้ไข Program Learning Outcomes ที่ AI สังเคราะห์</p>
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
          <p className="text-gray-600 font-medium mb-1">กำลังสังเคราะห์ PLO...</p>
          <p className="text-gray-400 text-sm">LLM กำลัง generate และ SMART-validate PLO อาจใช้เวลา 2-5 นาที</p>
        </div>
      ) : plos.length === 0 ? (
        <div className="text-center py-20">
          <div className="text-5xl mb-4">🎯</div>
          <p className="text-gray-500 text-lg font-medium mb-1">ยังไม่มี PLO</p>
          <p className="text-gray-400 text-sm mb-6">กดปุ่มด้านล่างเพื่อให้ AI สังเคราะห์ PLO จาก skill clusters</p>
          <button
            onClick={runSynthesis}
            className="bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 font-medium transition-colors"
          >
            Run PLO Synthesis
          </button>
        </div>
      ) : (
        <>
          <div className="flex justify-between items-center mb-5">
            <div className="flex items-center gap-4 text-sm text-gray-500">
              <span>{plos.length} PLOs</span>
              <span className={`font-medium ${smartPassCount === plos.length ? 'text-green-600' : 'text-amber-600'}`}>
                SMART ผ่าน {smartPassCount}/{plos.length}
              </span>
              <button
                onClick={runSynthesis}
                disabled={running}
                className="text-xs text-gray-400 hover:text-blue-600 underline disabled:opacity-50"
              >
                Re-run
              </button>
            </div>
            <Link
              to="/plo-report"
              className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 text-sm font-medium transition-colors"
            >
              ดำเนินการต่อ → PLO Report
            </Link>
          </div>
          <div className="space-y-4">
            {plos.map(p => (
              <PLOCard key={p.plo_id} plo={p} programId={programId} onUpdate={handleUpdate} />
            ))}
          </div>
        </>
      )}
    </div>
  )
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
}

function TracePanel({ programId, ploId }: { programId: string; ploId: string }) {
  const [trace, setTrace] = useState<PLOTrace | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get<PLOTrace>(`/programs/${programId}/plos/${ploId}/trace`)
      .then(r => setTrace(r.data))
      .catch(() => setError('โหลด trace ไม่สำเร็จ'))
      .finally(() => setLoading(false))
  }, [programId, ploId])

  if (loading) return <div className="py-4 text-center text-sm text-gray-400">กำลังโหลด trace...</div>
  if (error) return <div className="py-3 text-sm text-red-600">{error}</div>
  if (!trace) return null

  return (
    <div className="mt-4 pt-4 border-t border-gray-100 space-y-4">
      {/* Clusters */}
      <div>
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Skill Clusters ({trace.clusters.length})
        </h4>
        <div className="space-y-2">
          {trace.clusters.map(c => (
            <div key={c.cluster_id} className="bg-gray-50 rounded-lg px-3 py-2.5 border border-gray-100">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-800 leading-snug">{c.canonical_name_th}</p>
                  {c.canonical_name_en && (
                    <p className="text-xs text-gray-400 italic">{c.canonical_name_en}</p>
                  )}
                  <p className="text-xs text-gray-500 mt-1 leading-relaxed">{c.description_th}</p>
                </div>
                <div className="shrink-0 flex flex-col items-end gap-1">
                  <span className="text-xs font-mono bg-white border border-gray-200 rounded px-1.5 py-0.5 text-gray-600">
                    {(c.demand_score * 100).toFixed(0)}%
                  </span>
                  {c.is_common_need && (
                    <span className="text-xs bg-green-50 text-green-700 border border-green-200 rounded px-1.5 py-0.5">
                      common need
                    </span>
                  )}
                </div>
              </div>
              <p className="text-xs text-gray-400 mt-1.5">
                {c.source_evidence_ids.length} evidence · {c.skill_type}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Evidence */}
      <div>
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Evidence ({trace.evidence.length})
        </h4>
        <div className="space-y-2">
          {trace.evidence.map(e => (
            <div key={e.evidence_id} className="bg-white rounded-lg px-3 py-2.5 border border-gray-100">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-medium text-gray-700">{e.source_name}</span>
                <span className="text-xs text-gray-400">{STAKEHOLDER_LABEL[e.stakeholder_type] ?? e.stakeholder_type}</span>
                <span className={`ml-auto text-xs px-2 py-0.5 rounded-full font-medium ${CLASSIFICATION_COLOR[e.classification] ?? 'bg-gray-100 text-gray-500'}`}>
                  {e.classification}
                </span>
              </div>
              <p className="text-xs text-gray-600 leading-relaxed line-clamp-3">{e.raw_text_th}</p>
              {e.classification_rationale_th && (
                <p className="text-xs text-gray-400 mt-1 italic">{e.classification_rationale_th}</p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function PLOCard({
  plo: p,
  programId,
  onUpdate,
}: {
  plo: PLO
  programId: string
  onUpdate: (plo: PLO) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<PLO>(p)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [traceOpen, setTraceOpen] = useState(false)

  const smartPassed = SMART_KEYS.every(k => p.smart_check[k] === true)

  const handleSave = async () => {
    setSaving(true)
    setSaveError('')
    try {
      const res = await api.put<PLO>(`/programs/${programId}/plos/${p.plo_id}`, draft)
      onUpdate(res.data)
      setEditing(false)
    } catch {
      setSaveError('บันทึกไม่สำเร็จ — กรุณาตรวจสอบ statement (ห้ามใช้คำต้องห้าม: รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก)')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
      {/* Header */}
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <span className="text-xs font-mono text-gray-400 bg-gray-50 px-2 py-0.5 rounded">
              {p.plo_id}
            </span>
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${DOMAIN_COLOR[p.domain] ?? 'bg-gray-100 text-gray-700'}`}>
              {DOMAIN_LABEL[p.domain] ?? p.domain}
            </span>
            {(p.bloom_level || p.psychomotor_level || p.krathwohl_level) && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 font-medium">
                {(() => {
                  const level = p.bloom_level ?? p.psychomotor_level
                  return level ? BLOOM_LABEL[level] ?? level : p.krathwohl_level
                })()}
              </span>
            )}
            {p.is_subject_specific && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 font-medium">
                subject-specific
              </span>
            )}
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
              smartPassed ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
            }`}>
              SMART {smartPassed ? '✓' : '✗'}
            </span>
            {p.is_optional && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 font-medium">
                เสริม
              </span>
            )}
            {p.smart_escalated && (
              <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                ไม่ผ่าน SMART หลัง retry {p.smart_retry_count} ครั้ง — ต้องแก้ด้วยมือ
              </span>
            )}
          </div>
          {p.soft_flags?.length > 0 && (
            <div className="mt-1 mb-2 flex flex-wrap gap-1">
              {p.soft_flags.map(f => (
                <span key={f} className="rounded-full bg-yellow-100 px-2 py-0.5 text-xs text-yellow-800">
                  {SOFT_FLAG_TH[f] ?? f}
                </span>
              ))}
            </div>
          )}

          {editing ? (
            <EditForm
              draft={draft}
              setDraft={setDraft}
              saving={saving}
              saveError={saveError}
              onSave={handleSave}
              onCancel={() => { setEditing(false); setDraft(p); setSaveError('') }}
            />
          ) : (
            <div>
              <p className="text-gray-900 font-medium leading-relaxed">{p.statement_th}</p>
              {p.statement_en && (
                <p className="text-gray-400 text-sm mt-1 italic">{p.statement_en}</p>
              )}
              <div className="mt-2 text-sm text-gray-600">
                <span className="font-medium text-gray-700">กริยา:</span>{' '}
                <span className="bg-gray-50 px-1.5 py-0.5 rounded text-gray-800">{p.action_verb_th}</span>
              </div>
              <p className="text-gray-500 text-sm mt-2 leading-relaxed">{p.rationale_th}</p>
              {p.distinctive_feature_th && (
                <p className="text-indigo-600 text-sm mt-1">
                  <span className="font-medium">จุดเด่น:</span> {p.distinctive_feature_th}
                </p>
              )}
            </div>
          )}
        </div>

        {!editing && (
          <button
            onClick={() => setEditing(true)}
            className="shrink-0 text-sm border border-gray-200 px-3 py-1.5 rounded-lg hover:bg-gray-50 text-gray-600 transition-colors"
          >
            แก้ไข
          </button>
        )}
      </div>

      {/* SMART check */}
      {!editing && (
        <div className="mt-4">
          <div className="flex gap-2 flex-wrap">
            {SMART_KEYS.map(k => (
              <span
                key={k}
                className={`text-xs px-2.5 py-1 rounded-md font-medium ${
                  p.smart_check[k] === true
                    ? 'bg-green-50 text-green-700 border border-green-200'
                    : 'bg-red-50 text-red-700 border border-red-200'
                }`}
              >
                {p.smart_check[k] ? '✓' : '✗'} {k.charAt(0).toUpperCase() + k.slice(1)}
              </span>
            ))}
          </div>
          {p.smart_check.notes_th && (
            <p className="mt-2 text-xs text-amber-700 bg-amber-50 rounded-lg px-3 py-2 border border-amber-100">
              {p.smart_check.notes_th}
            </p>
          )}
        </div>
      )}

      {/* Footer meta + trace toggle */}
      {!editing && (
        <>
          <div className="mt-3 pt-3 border-t border-gray-100 flex items-center gap-4 text-xs text-gray-400">
            <span>{p.source_cluster_ids.length} clusters</span>
            <span>{p.source_evidence_ids.length} evidence</span>
            <button
              onClick={() => setTraceOpen(v => !v)}
              className="ml-auto text-xs text-blue-500 hover:text-blue-700 font-medium transition-colors flex items-center gap-1"
            >
              {traceOpen ? '▲ ซ่อน Trace' : '▼ ดู Trace'}
            </button>
            <span className="text-gray-300">v{p.version}</span>
          </div>
          {traceOpen && <TracePanel programId={programId} ploId={p.plo_id} />}
        </>
      )}
    </div>
  )
}

function EditForm({
  draft,
  setDraft,
  saving,
  saveError,
  onSave,
  onCancel,
}: {
  draft: PLO
  setDraft: React.Dispatch<React.SetStateAction<PLO>>
  saving: boolean
  saveError: string
  onSave: () => void
  onCancel: () => void
}) {
  return (
    <div className="space-y-3 mt-1">
      <div>
        <label className="block text-xs font-semibold text-gray-600 mb-1">
          Statement (Thai) <span className="text-red-500">*</span>
        </label>
        <textarea
          className="w-full border border-gray-300 rounded-lg p-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 resize-none"
          rows={3}
          value={draft.statement_th}
          onChange={e => setDraft(d => ({ ...d, statement_th: e.target.value }))}
        />
        <p className="text-xs text-gray-400 mt-0.5">ห้ามใช้คำ: รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก</p>
      </div>
      <div>
        <label className="block text-xs font-semibold text-gray-600 mb-1">Action Verb (Thai)</label>
        <input
          className="w-full border border-gray-300 rounded-lg p-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          value={draft.action_verb_th}
          onChange={e => setDraft(d => ({ ...d, action_verb_th: e.target.value }))}
        />
      </div>
      <div>
        <label className="block text-xs font-semibold text-gray-600 mb-1">Rationale (Thai)</label>
        <textarea
          className="w-full border border-gray-300 rounded-lg p-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 resize-none"
          rows={2}
          value={draft.rationale_th}
          onChange={e => setDraft(d => ({ ...d, rationale_th: e.target.value }))}
        />
      </div>
      {saveError && (
        <p className="text-red-600 text-xs bg-red-50 rounded-lg px-3 py-2 border border-red-200">
          {saveError}
        </p>
      )}
      <div className="flex gap-2 pt-1">
        <button
          onClick={onSave}
          disabled={saving}
          className="bg-blue-600 text-white px-4 py-1.5 rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50 font-medium transition-colors"
        >
          {saving ? 'กำลังบันทึก...' : 'บันทึก'}
        </button>
        <button
          onClick={onCancel}
          className="border border-gray-300 px-4 py-1.5 rounded-lg text-sm hover:bg-gray-50 text-gray-600 transition-colors"
        >
          ยกเลิก
        </button>
      </div>
    </div>
  )
}
