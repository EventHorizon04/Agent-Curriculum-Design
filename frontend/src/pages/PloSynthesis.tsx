import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import NextStageLink from '../components/NextStageLink'
import { useProgram } from '../hooks/useProgram'
import api from '../api/client'
import DesignerNote from './components/DesignerNote'
import { classStyle, ksecLabel, stakeholderLabel } from '../constants/stakeholder'
import { SMART_KEYS, SMART_LABEL_TH, VALIDATED_BY_TH, findingLabel, needsAttention } from '../constants/smart'
import { DEMAND_SCORE_TITLE_TH, demandPercent } from '../constants/demand'
import type { PLO } from '../types/plo'

interface NeedSummary {
  need_id: string
  statement_th: string
  statement_en: string | null
  ksec_category: string
  bloom_level: string
  demand_score: number
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
  clusters: NeedSummary[]
  evidence: StakeholderEvidence[]
  missing_need_ids: string[]
  missing_evidence_ids: string[]
}

const BLOOM_LABEL: Record<string, string> = {
  remember: 'Remember',
  understand: 'Understand',
  apply: 'Apply',
  analyze: 'Analyze',
  evaluate: 'Evaluate',
  create: 'Create',
}

interface NeedListItem {
  need_id: string
  statement_th: string
}

export default function PloSynthesis() {
  const { programId } = useProgram()
  const [plos, setPlos] = useState<PLO[]>([])
  const [needs, setNeeds] = useState<NeedListItem[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')

  const fetchPlos = useCallback(async () => {
    if (!programId) return
    setLoading(true)
    setError('')
    try {
      const [ploRes, needRes] = await Promise.all([
        api.get<PLO[]>(`/programs/${programId}/plos/`),
        api.get<NeedListItem[]>(`/programs/${programId}/needs/`),
      ])
      setPlos(ploRes.data)
      setNeeds(needRes.data)
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
      const res = await api.post<PLO[]>(`/programs/${programId}/plos/run`, {
        note_th: note.trim() || null,
      })
      setPlos(res.data)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'รัน PLO Synthesis ไม่สำเร็จ')
    } finally {
      setRunning(false)
    }
  }, [programId, note])

  useEffect(() => { fetchPlos() }, [fetchPlos])

  const handleUpdate = (updated: PLO) =>
    setPlos(prev => prev.map(p => (p.plo_id === updated.plo_id ? updated : p)))

  const toggleNeed = (needId: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(needId)) next.delete(needId)
      else next.add(needId)
      return next
    })
  }

  const mergeSelected = async () => {
    if (selected.size < 2 || !programId) return
    setRunning(true)
    setError('')
    try {
      await api.post(`/programs/${programId}/plos/from-needs`, {
        need_ids: [...selected],
        note_th: note.trim() || null,
      })
      setSelected(new Set())
      await fetchPlos()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'รวม Need เป็น PLO เดียวไม่สำเร็จ')
    } finally {
      setRunning(false)
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

  const smartPassCount = plos.filter(p =>
    SMART_KEYS.every(k => p.smart_check[k] === true)
  ).length
  // "SMART ผ่าน 8/10" is misleading when two of the ten were never judged as
  // written, so say how many still need looking at.
  const unjudgedCount = plos.filter(p => needsAttention(p.smart_validated_by)).length

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
          <p className="text-gray-400 text-sm">ร่าง PLO ทุกข้อ แล้วให้ผู้ตรวจ SMART ตรวจทั้งชุด อาจใช้เวลา 3-10 นาที</p>
        </div>
      ) : plos.length === 0 ? (
        <div className="text-center py-20">
          <div className="text-5xl mb-4">🎯</div>
          <p className="text-gray-500 text-lg font-medium mb-1">ยังไม่มี PLO</p>
          <p className="text-gray-400 text-sm mb-6">กดปุ่มด้านล่างเพื่อให้ AI สังเคราะห์ PLO จาก skill clusters</p>
          <div className="mx-auto mb-2 max-w-md">
            <DesignerNote value={note} onChange={setNote} />
          </div>
          <button
            onClick={runSynthesis}
            className="bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 font-medium transition-colors"
          >
            Run PLO Synthesis
          </button>
        </div>
      ) : (
        <>
          <DesignerNote value={note} onChange={setNote} disabled={running} />
          <div className="flex justify-between items-center mb-5">
            <div className="flex items-center gap-4 text-sm text-gray-500">
              <span>{plos.length} PLOs</span>
              <span className={`font-medium ${smartPassCount === plos.length ? 'text-green-600' : 'text-amber-600'}`}>
                SMART ผ่าน {smartPassCount}/{plos.length}
              </span>
              {unjudgedCount > 0 && (
                <span className="font-medium text-orange-600">
                  รอตรวจซ้ำ {unjudgedCount}
                </span>
              )}
              <button
                onClick={runSynthesis}
                disabled={running}
                className="text-xs text-gray-400 hover:text-blue-600 underline disabled:opacity-50"
              >
                Re-run
              </button>
            </div>
          </div>
          <div className="space-y-4">
            {plos.map(p => (
              <PLOCard key={p.plo_id} plo={p} programId={programId} onUpdate={handleUpdate} />
            ))}
          </div>

          {needs.length >= 2 && (
            <div className="mt-8 rounded-xl border border-gray-200 bg-gray-50/60 p-5">
              <h2 className="text-sm font-semibold text-gray-700 mb-1">
                รวม Need หลายรายการเป็น PLO เดียว
              </h2>
              <p className="text-xs text-gray-500 mb-3">
                เลือก Need ตั้งแต่ 2 รายการที่ต้องการให้ AI สังเคราะห์รวมเป็น PLO เดียว
              </p>
              {note.trim() && (
                <p className="mb-3 rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs text-gray-500">
                  ใช้หมายเหตุด้านบน: <span className="text-gray-700">{note.trim()}</span>
                </p>
              )}
              <div className="space-y-2 mb-4">
                {needs.map(n => (
                  <label
                    key={n.need_id}
                    className="flex items-start gap-2 rounded-lg border border-gray-200 bg-white p-3"
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(n.need_id)}
                      onChange={() => toggleNeed(n.need_id)}
                      className="mt-1"
                    />
                    <span className="text-sm text-gray-800">{n.statement_th}</span>
                  </label>
                ))}
              </div>
              <button
                onClick={mergeSelected}
                disabled={selected.size < 2 || running}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:bg-gray-300"
              >
                รวมเป็น PLO เดียว ({selected.size})
              </button>
            </div>
          )}
        </>
      )}

      {/* The report reads the stored PLOs, so anything drafted is enough to go
          on — including a set carrying escalations, which is exactly what the
          report page is there to show. */}
      <NextStageLink
        from="plo_synthesis"
        ready={Boolean(programId) && plos.length > 0}
        blockedReason="ยังไม่มี PLO — รันสังเคราะห์ PLO ก่อน"
      />
    </div>
  )
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

  const stale = trace.missing_need_ids.length + trace.missing_evidence_ids.length > 0

  return (
    <div className="mt-4 pt-4 border-t border-gray-100 space-y-4">
      {stale && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded-lg px-3 py-2.5 text-sm">
          <p className="font-medium">PLO นี้อ้างข้อมูลที่ไม่มีอยู่แล้ว</p>
          <p className="text-xs mt-1 leading-relaxed">
            หาย {trace.missing_need_ids.length} Need
            {trace.missing_evidence_ids.length > 0 &&
              ` และ ${trace.missing_evidence_ids.length} หลักฐาน`}
            {' '}— เกิดจาก PLO ชุดนี้ถูกสร้างก่อนที่ Needs จะถูกสร้างใหม่
            สังเคราะห์ PLO อีกครั้งเพื่อให้ตรงกับ Needs ปัจจุบัน
          </p>
        </div>
      )}

      {/* Needs */}
      <div>
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Needs ({trace.clusters.length})
        </h4>
        <div className="space-y-2">
          {trace.clusters.map(c => (
            <div key={c.need_id} className="bg-gray-50 rounded-lg px-3 py-2.5 border border-gray-100">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-800 leading-snug">{c.statement_th}</p>
                  {c.statement_en && (
                    <p className="text-xs text-gray-400 italic">{c.statement_en}</p>
                  )}
                </div>
                <span
                  title={DEMAND_SCORE_TITLE_TH}
                  className="shrink-0 text-xs font-mono bg-white border border-gray-200 rounded px-1.5 py-0.5 text-gray-600"
                >
                  {demandPercent(c.demand_score)}
                </span>
              </div>
              <p className="text-xs text-gray-400 mt-1.5">
                {c.source_evidence_ids.length} evidence · {ksecLabel(c.ksec_category)} · {c.bloom_level}
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
                <span className="text-xs text-gray-400">{stakeholderLabel(e.stakeholder_type)}</span>
                <span className={`ml-auto text-xs px-2 py-0.5 rounded-full font-medium ${classStyle(e.classification).cls}`}>
                  {classStyle(e.classification).label}
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
  const [revalidating, setRevalidating] = useState(false)
  const [traceOpen, setTraceOpen] = useState(false)

  const smartPassed = SMART_KEYS.every(k => p.smart_check[k] === true)

  const handleSave = async () => {
    setSaving(true)
    setSaveError('')
    try {
      const res = await api.put<PLO>(`/programs/${programId}/plos/${p.plo_id}`, draft)
      onUpdate(res.data)
      setEditing(false)
    } catch (err) {
      // The server says why. Guessing "forbidden word" was wrong more often
      // than not, and the M check no longer fires on รักษา or จำแนก at all.
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setSaveError(detail ?? 'บันทึกไม่สำเร็จ กรุณาตรวจสอบข้อความ')
    } finally {
      setSaving(false)
    }
  }

  const findings = p.smart_check.findings ?? []
  const hardFindings = findings.filter(f => f.severity === 'hard')
  const softFindings = findings.filter(f => f.severity === 'soft')

  async function handleRevalidate() {
    setRevalidating(true)
    setSaveError('')
    try {
      const res = await api.post<PLO>(`/programs/${programId}/plos/${p.plo_id}/revalidate`)
      onUpdate(res.data)
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
      setSaveError(detail ?? 'ตรวจ SMART ซ้ำไม่สำเร็จ')
    } finally {
      setRevalidating(false)
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
            <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 font-medium">
              {BLOOM_LABEL[p.bloom_level] ?? p.bloom_level}
            </span>
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
              smartPassed ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
            }`}>
              SMART {smartPassed ? '✓' : '✗'}
            </span>
            {/* Every outcome says which kind it is, not only the supplementary
                ones. A core PLO used to carry no badge at all, so "หลัก" read as
                a missing label rather than as the answer — and the two kinds are
                counted against different rules (only core PLOs sit inside the
                6-10 band), which is the first thing a designer checks. */}
            <span
              className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                p.is_optional
                  ? 'bg-amber-100 text-amber-700'
                  : 'bg-indigo-100 text-indigo-700'
              }`}
            >
              {p.is_optional ? 'เสริม' : 'หลัก'}
            </span>
            {p.smart_escalated && (
              <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                ไม่ผ่าน SMART หลังแก้ {p.smart_retry_count} รอบ — ต้องแก้ด้วยมือ
              </span>
            )}
            {/* Provenance, not decoration: "the validator judged this and it
                failed" and "no validator has judged this as written" are
                different facts, and without this the page would attribute a
                diagnosis to something that never ran. */}
            {needsAttention(p.smart_validated_by) && (
              <span className="rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-800">
                {VALIDATED_BY_TH[p.smart_validated_by]}
              </span>
            )}
          </div>
          {/* The soft findings carry a reason each; the flat flag list is the
              fallback for rows written before findings existed. */}
          {softFindings.length > 0 ? (
            <div className="mt-1 mb-2 space-y-1">
              {softFindings.map(f => (
                <p key={f.criterion} className="rounded-lg bg-yellow-50 px-3 py-1.5 text-xs text-yellow-900 border border-yellow-100">
                  <span className="font-medium">{findingLabel(f.criterion)}</span>
                  {f.note_th && <span className="text-yellow-700"> — {f.note_th}</span>}
                </p>
              ))}
            </div>
          ) : p.soft_flags?.length > 0 ? (
            <div className="mt-1 mb-2 flex flex-wrap gap-1">
              {p.soft_flags.map(f => (
                <span key={f} className="rounded-full bg-yellow-100 px-2 py-0.5 text-xs text-yellow-800">
                  {findingLabel(f)}
                </span>
              ))}
            </div>
          ) : null}

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
          <div className="shrink-0 flex flex-col gap-1.5">
            <button
              onClick={() => setEditing(true)}
              className="text-sm border border-gray-200 px-3 py-1.5 rounded-lg hover:bg-gray-50 text-gray-600 transition-colors"
            >
              แก้ไข
            </button>
            {/* Without this the `stale` state is a dead end: PUT deliberately
                does not re-run the gate, so this is how an edited statement
                gets a verdict. */}
            <button
              onClick={handleRevalidate}
              disabled={revalidating}
              className="text-xs border border-blue-200 px-3 py-1.5 rounded-lg hover:bg-blue-50 text-blue-600 transition-colors disabled:opacity-50"
            >
              {revalidating ? 'กำลังตรวจ...' : 'ตรวจ SMART ซ้ำ'}
            </button>
          </div>
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
                {p.smart_check[k] ? '✓' : '✗'} {SMART_LABEL_TH[k] ?? k}
              </span>
            ))}
          </div>
          {/* The criterion that actually escalated this outcome. The old gate
              logged its surviving failures and dropped them, so a designer
              could see that a PLO failed and never which check did it. */}
          {hardFindings.length > 0 && (
            <div className="mt-2 space-y-1">
              {hardFindings.map(f => (
                <p key={f.criterion} className="rounded-lg bg-red-50 px-3 py-1.5 text-xs text-red-900 border border-red-100">
                  <span className="font-medium">{findingLabel(f.criterion)}</span>
                  {f.note_th && <span className="text-red-700"> — {f.note_th}</span>}
                </p>
              ))}
            </div>
          )}
          {/* The instruction a designer acts on, so it gets its own block. */}
          {p.smart_diagnosis_th && (
            <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
              <p className="text-xs font-medium text-amber-900 mb-0.5">ข้อวินิจฉัยจากผู้ตรวจ SMART</p>
              <p className="text-xs text-amber-800 leading-relaxed">{p.smart_diagnosis_th}</p>
            </div>
          )}
          {!p.smart_diagnosis_th && p.smart_check.notes_th && (
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
            <span>{p.source_need_ids.length} needs</span>
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
