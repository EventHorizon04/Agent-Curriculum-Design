import { useState, useEffect, useRef, useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../api/client'
import NextStageLink from '../components/NextStageLink'
import { useProgram } from '../hooks/useProgram'
import { STAKEHOLDER_GROUPS, classStyle, stakeholderLabel } from '../constants/stakeholder'

interface EvidenceItem {
  evidence_id: string
  stakeholder_type: string
  source_name: string
  raw_text_th: string
  classification: string
}

interface EvidenceLock {
  locked: boolean
  reason_th: string | null
}

interface EvidencePayload {
  evidence_id: string
  program_id: string
  stakeholder_type: string
  source_name: string
  raw_text_th: string
}

export default function StakeholderNeeds() {
  const navigate = useNavigate()
  const { programId, setProgramId } = useProgram()
  const [pidInput, setPidInput] = useState('')
  const [stakeholderType, setStakeholderType] = useState('employer')
  const [sourceName, setSourceName] = useState('')
  const [rawText, setRawText] = useState('')
  const [items, setItems] = useState<EvidenceItem[]>([])
  // The server's answer to "may evidence change now": skills or Needs exist, or
  // a writer is running. Read with the list, so one failed read is one error.
  const [lock, setLock] = useState<EvidenceLock>({ locked: false, reason_th: null })
  // The item whose text the add form currently holds; null means the form adds.
  const [editingId, setEditingId] = useState<string | null>(null)
  const [loadingList, setLoadingList] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [classifying, setClassifying] = useState(false)
  const [classifyProgress, setClassifyProgress] = useState<{ index: number; total: number; source_name: string } | null>(null)
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState('')
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null)
  const confirmRevertTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const fetchEvidence = useCallback(async (pid: string) => {
    setLoadingList(true)
    setError('')
    try {
      const [res, lockRes] = await Promise.all([
        api.get<EvidenceItem[]>(`/programs/${pid}/evidence/`),
        api.get<EvidenceLock>(`/programs/${pid}/evidence/lock`),
      ])
      setItems(res.data)
      setLock(lockRes.data)
    } catch {
      setError('โหลดหลักฐานไม่ได้ — ตรวจสอบว่า backend รันอยู่')
    } finally {
      setLoadingList(false)
    }
  }, [])

  useEffect(() => {
    if (programId) fetchEvidence(programId)
  }, [programId, fetchEvidence])

  async function postEvidence(payload: EvidencePayload) {
    setSubmitting(true)
    setError('')
    setSuccess('')
    try {
      await api.post(`/programs/${payload.program_id}/evidence/`, payload)
      setSuccess('เพิ่มหลักฐานสำเร็จ')
      await fetchEvidence(payload.program_id)
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status: number; data?: { detail?: unknown } } }
      if (axiosErr.response) {
        const detail = axiosErr.response.data?.detail
        // The 409s carry Thai detail meant to be shown as-is (locked, busy).
        setError(typeof detail === 'string' ? detail : `API error ${axiosErr.response.status}`)
      } else {
        setError('เชื่อมต่อ API ไม่ได้')
      }
    } finally {
      setSubmitting(false)
    }
  }

  function handleEditClick(item: EvidenceItem) {
    setEditingId(item.evidence_id)
    setStakeholderType(item.stakeholder_type)
    setSourceName(item.source_name)
    setRawText(item.raw_text_th)
    setError('')
    setSuccess('')
    handleCancelFile()
  }

  function handleCancelEdit() {
    setEditingId(null)
    setSourceName('')
    setRawText('')
  }

  async function putEvidence(evidenceId: string, pid: string) {
    setSubmitting(true)
    setError('')
    setSuccess('')
    try {
      await api.put(`/programs/${pid}/evidence/${evidenceId}`, {
        stakeholder_type: stakeholderType,
        source_name: sourceName.trim(),
        raw_text_th: rawText.trim(),
      })
      setSuccess('แก้ไขหลักฐานสำเร็จ')
      handleCancelEdit()
      await fetchEvidence(pid)
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: unknown } } }
      const detail = axiosErr.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'แก้ไขหลักฐานไม่สำเร็จ')
      // A 409 may mean the lock closed under the form; the list says which.
      await fetchEvidence(pid)
    } finally {
      setSubmitting(false)
    }
  }

  async function handleFormSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!programId) { setError('กรุณาระบุรหัสหลักสูตรก่อน'); return }
    if (!sourceName.trim() || !rawText.trim()) { setError('กรุณากรอกแหล่งที่มาและข้อความหลักฐาน'); return }
    if (editingId) { await putEvidence(editingId, programId); return }
    await postEvidence({
      evidence_id: crypto.randomUUID(),
      program_id: programId,
      stakeholder_type: stakeholderType,
      source_name: sourceName.trim(),
      raw_text_th: rawText.trim(),
    })
    setSourceName('')
    setRawText('')
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    setPendingFile(file ?? null)
    setFileError('')
  }

  function handleCancelFile() {
    setPendingFile(null)
    setFileError('')
    if (fileRef.current) fileRef.current.value = ''
  }

  async function handleConfirmUpload() {
    if (!pendingFile || !programId) return
    const text = await pendingFile.text()
    if (!text.trim()) { setFileError('ไฟล์ว่างเปล่า'); return }
    await postEvidence({
      evidence_id: crypto.randomUUID(),
      program_id: programId,
      stakeholder_type: stakeholderType,
      source_name: pendingFile.name,
      raw_text_th: text,
    })
    setPendingFile(null)
    if (fileRef.current) fileRef.current.value = ''
  }

  function handleDeleteClick(evidenceId: string) {
    if (confirmingDeleteId === evidenceId) {
      if (confirmRevertTimer.current) clearTimeout(confirmRevertTimer.current)
      setConfirmingDeleteId(null)
      handleDelete(evidenceId)
      return
    }
    if (confirmRevertTimer.current) clearTimeout(confirmRevertTimer.current)
    setConfirmingDeleteId(evidenceId)
    confirmRevertTimer.current = setTimeout(() => setConfirmingDeleteId(null), 3000)
  }

  async function handleDelete(evidenceId: string) {
    if (!programId) return
    setError('')
    setSuccess('')
    try {
      await api.delete(`/programs/${programId}/evidence/${evidenceId}`)
      setItems(prev => prev.filter(item => item.evidence_id !== evidenceId))
      if (editingId === evidenceId) handleCancelEdit()
      setSuccess('ลบหลักฐานสำเร็จ')
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(axiosErr.response?.data?.detail ?? 'ลบหลักฐานไม่สำเร็จ')
    }
  }

  async function handleClassify() {
    if (!programId || classifying) return
    setClassifying(true)
    setClassifyProgress(null)
    setError('')
    try {
      const response = await fetch(
        `/programs/${programId}/evidence/classify-stream`,
        { headers: { 'Accept': 'text/event-stream' } }
      )
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: unknown } | null
        setError(typeof body?.detail === 'string' ? body.detail : `classify-stream error: ${response.status}`)
        return
      }
      const reader = response.body?.getReader()
      if (!reader) return
      const decoder = new TextDecoder()
      let buf = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const evt = JSON.parse(line.slice(6))
          if (evt.status === 'progress') {
            setClassifyProgress({ index: evt.index, total: evt.total, source_name: evt.source_name })
            setItems(prev => prev.map(item =>
              item.evidence_id === evt.evidence_id
                ? { ...item, classification: evt.classification }
                : item
            ))
          } else if (evt.status === 'done') {
            setClassifyProgress(null)
            await fetchEvidence(programId)
          }
        }
      }
    } catch {
      setError('จำแนกหลักฐานไม่สำเร็จ — ตรวจสอบว่า backend รันอยู่')
    } finally {
      setClassifying(false)
      setClassifyProgress(null)
    }
  }

  function handleSetProgram() {
    const pid = pidInput.trim()
    if (!pid) return
    setProgramId(pid)
    fetchEvidence(pid)
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 text-left">
      <div>
        <p className="eyebrow">ขั้นที่ 2</p>
        <h1 className="page-title">หลักฐานผู้มีส่วนได้ส่วนเสีย</h1>
        <p className="mt-1 text-sm text-pencil">
          เพิ่มหลักฐานจากแหล่งต่างๆ เพื่อใช้ในการสังเคราะห์ PLO
        </p>
      </div>

      {!programId ? (
        <div className="notice notice-warn">
          <p className="mb-3">
            ยังไม่ได้เลือกหลักสูตร —{' '}
            <button onClick={() => navigate('/')} className="font-medium underline underline-offset-2">
              ไปที่ขั้นตอนที่ 1
            </button>{' '}
            หรือระบุรหัสหลักสูตรที่นี่
          </p>
          <div className="flex flex-wrap gap-2">
            <input
              value={pidInput} onChange={e => setPidInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSetProgram()}
              placeholder="รหัสหลักสูตร เช่น cs-2025"
              className="input min-w-0 flex-1 py-1.5"
            />
            <button
              onClick={handleSetProgram}
              className="btn btn-primary py-1.5"
            >
              ยืนยัน
            </button>
          </div>
        </div>
      ) : (
        <div className="panel flex flex-wrap items-center justify-between gap-2 bg-sunk px-4 py-2.5">
          <span className="text-sm text-graphite">
            หลักสูตร: <strong className="data">{programId}</strong>
            <span className="ml-2 text-pencil">— พบ <span className="data">{items.length}</span> หลักฐาน</span>
          </span>
          <button
            onClick={() => { setProgramId(''); setItems([]); setLock({ locked: false, reason_th: null }); handleCancelEdit() }}
            className="btn btn-sm btn-quiet"
          >
            เปลี่ยน
          </button>
        </div>
      )}

      {error && (
        <div className="notice notice-error flex justify-between gap-4">
          <span>{error}</span>
          <button onClick={() => setError('')} className="ml-4 opacity-60 hover:opacity-100">✕</button>
        </div>
      )}
      {success && (
        <div className="notice notice-info flex justify-between gap-4">
          <span>✓ {success}</span>
          <button onClick={() => setSuccess('')} className="ml-4 opacity-60 hover:opacity-100">✕</button>
        </div>
      )}

      {programId && lock.locked && (
        <div className="notice notice-warn flex flex-wrap items-center justify-between gap-x-4 gap-y-1" role="status">
          <span>{lock.reason_th ?? 'หลักฐานของหลักสูตรนี้แก้ไม่ได้ในขณะนี้'}</span>
          <Link to="/" className="font-medium underline underline-offset-2">
            ไปที่รายการหลักสูตร →
          </Link>
        </div>
      )}

      {programId && !lock.locked && (
        <div className="panel p-4 sm:p-6">
          <h2 className="section-title mb-4">{editingId ? 'แก้ไขหลักฐาน' : 'เพิ่มหลักฐานใหม่'}</h2>
          <form onSubmit={handleFormSubmit} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className="field-label">
                  ประเภทผู้มีส่วนได้ส่วนเสีย
                </label>
                <select
                  value={stakeholderType} onChange={e => setStakeholderType(e.target.value)}
                  className="input"
                >
                  {STAKEHOLDER_GROUPS.map(g => (
                    <optgroup key={g.label} label={g.label}>
                      {g.types.map(t => (
                        <option key={t} value={t}>{stakeholderLabel(t)}</option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </div>
              <div>
                <label className="field-label">แหล่งที่มา *</label>
                <input
                  value={sourceName} onChange={e => setSourceName(e.target.value)}
                  placeholder="บริษัท ABC / ผู้ประกอบการ XYZ"
                  className="input"
                />
              </div>
            </div>

            <div>
              <label className="field-label">
                ข้อความหลักฐาน (ภาษาไทย) *
              </label>
              <textarea
                value={rawText} onChange={e => setRawText(e.target.value)}
                rows={4}
                placeholder="วางข้อความที่ได้จากการสัมภาษณ์ แบบสอบถาม หรือเอกสาร..."
                className="input resize-none"
              />
            </div>

            <div className="flex flex-wrap items-center gap-4">
              <button
                type="submit" disabled={submitting}
                className="btn btn-primary"
              >
                {submitting ? 'กำลังบันทึก...' : editingId ? 'บันทึกการแก้ไข' : 'เพิ่มหลักฐาน'}
              </button>

              {editingId && (
                <button
                  type="button" onClick={handleCancelEdit} disabled={submitting}
                  className="btn btn-secondary"
                >
                  ยกเลิกการแก้ไข
                </button>
              )}

              {!editingId && <div className="h-4 w-px bg-hair" />}

              {editingId ? null : !pendingFile ? (
                <label className="group flex cursor-pointer items-center gap-2 text-sm text-pencil transition-colors hover:text-stamp">
                  <svg
                    className="h-4 w-4 group-hover:text-stamp"
                    fill="none" stroke="currentColor" viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                  </svg>
                  อัปโหลดเอกสาร
                  <span className="data text-xs text-lead">(.txt, .md, .csv)</span>
                  <input
                    ref={fileRef} type="file" accept=".txt,.md,.csv"
                    onChange={handleFileSelect} className="hidden"
                  />
                </label>
              ) : (
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center gap-3">
                    <span className="max-w-[200px] truncate text-sm text-graphite">
                      📄 {pendingFile.name}
                    </span>
                    <button
                      type="button" onClick={handleCancelFile}
                      className="btn btn-sm btn-quiet"
                    >
                      ยกเลิก
                    </button>
                    <button
                      type="button" onClick={handleConfirmUpload} disabled={submitting}
                      className="btn btn-sm btn-primary"
                    >
                      {submitting ? 'กำลังอัปโหลด...' : 'อัปโหลด'}
                    </button>
                  </div>
                  {fileError && <p className="text-xs text-mandate">{fileError}</p>}
                </div>
              )}
            </div>
          </form>
        </div>
      )}

      {programId && (
        <div>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="section-title">หลักฐานทั้งหมด</h2>
            {!lock.locked && items.some(i => i.classification === 'unclassified') && (
              <button
                onClick={handleClassify}
                disabled={classifying}
                className="btn btn-secondary py-1.5"
              >
                {classifying ? (
                  <>
                    <svg className="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                    </svg>
                    กำลังจำแนก...
                  </>
                ) : 'จำแนกหลักฐาน'}
              </button>
            )}
          </div>
          {classifying && classifyProgress && (
            <div className="panel mb-3 bg-sunk px-4 py-3">
              <div className="mb-1.5 flex justify-between gap-3 text-xs text-pencil">
                <span>กำลังจำแนก: <strong>{classifyProgress.source_name}</strong></span>
                <span className="data">{classifyProgress.index}/{classifyProgress.total}</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-[2px] bg-hair">
                <div
                  className="h-full rounded-[2px] bg-stamp transition-all duration-300"
                  style={{ width: `${(classifyProgress.index / classifyProgress.total) * 100}%` }}
                />
              </div>
            </div>
          )}
          {loadingList ? (
            <div className="py-8 text-center text-sm text-pencil">กำลังโหลด...</div>
          ) : items.length === 0 ? (
            <div className="panel border-dashed py-10 text-center text-sm text-pencil">
              {lock.locked ? 'ยังไม่มีหลักฐาน' : 'ยังไม่มีหลักฐาน — เพิ่มหลักฐานด้านบน'}
            </div>
          ) : (
            <div className="space-y-2">
              {items.map(item => {
                const cs = classStyle(item.classification)
                const typeLabel = stakeholderLabel(item.stakeholder_type)
                return (
                  <details
                    key={item.evidence_id}
                    className="panel group transition-colors open:border-hair-strong"
                  >
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 select-none hover:bg-sunk">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="shrink-0 text-sm font-medium text-graphite">{typeLabel}</span>
                        <span className="text-lead">—</span>
                        <span className="truncate text-sm text-pencil">{item.source_name}</span>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        {!lock.locked && (
                          <>
                            <button
                              type="button"
                              onClick={e => { e.preventDefault(); e.stopPropagation(); handleEditClick(item) }}
                              className="btn btn-sm btn-quiet"
                            >
                              แก้ไข
                            </button>
                            <button
                              type="button"
                              onClick={e => { e.preventDefault(); e.stopPropagation(); handleDeleteClick(item.evidence_id) }}
                              className={`btn btn-sm ${
                                confirmingDeleteId === item.evidence_id
                                  ? 'btn-danger'
                                  : 'btn-danger-quiet'
                              }`}
                            >
                              {confirmingDeleteId === item.evidence_id ? 'ยืนยันลบ?' : 'ลบ'}
                            </button>
                          </>
                        )}
                        <span className={`chip ${cs.cls}`}>
                          {cs.label}
                        </span>
                      </div>
                    </summary>
                    <div className="border-t border-hair px-4 pt-3 pb-4">
                      <p className="record whitespace-pre-wrap">{item.raw_text_th}</p>
                      <p className="data mt-3 text-xs text-lead">{item.evidence_id}</p>
                    </div>
                  </details>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* Skill extraction reads the evidence table, so one item is the floor.
          Classification is not required here: stage 3 re-reads every item and
          the classify pass is pure code. */}
      <NextStageLink
        from="stakeholder_needs"
        ready={Boolean(programId) && items.length > 0}
        blockedReason="เพิ่มหลักฐานอย่างน้อย 1 รายการก่อน — ขั้นสกัดทักษะอ่านจากหลักฐานเหล่านี้"
      />
    </div>
  )
}
