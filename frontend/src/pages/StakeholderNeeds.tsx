import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import { useProgram } from '../hooks/useProgram'

const STAKEHOLDER_LABELS: Record<string, string> = {
  employer:            'นายจ้าง',
  alumni:              'ศิษย์เก่า',
  professional_council:'สภาวิชาชีพ',
  accreditation_body:  'หน่วยงานประเมิน',
  university:          'มหาวิทยาลัย',
  community:           'ชุมชน',
  subject_benchmark:   'มาตรฐานสาขา',
  peer_program:        'หลักสูตรเทียบเคียง',
}

const CLASS_STYLE: Record<string, { label: string; cls: string }> = {
  need:         { label: 'ความต้องการ',  cls: 'bg-green-100 text-green-700' },
  requirement:  { label: 'ข้อกำหนด',     cls: 'bg-blue-100 text-blue-700' },
  want:         { label: 'ความปรารถนา', cls: 'bg-yellow-100 text-yellow-700' },
  unclassified: { label: 'ยังไม่จำแนก', cls: 'bg-gray-100 text-gray-500' },
}

interface EvidenceItem {
  evidence_id: string
  stakeholder_type: string
  source_name: string
  raw_text_th: string
  classification: string
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
  const [loadingList, setLoadingList] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const fetchEvidence = useCallback(async (pid: string) => {
    setLoadingList(true)
    setError('')
    try {
      const res = await api.get<EvidenceItem[]>(`/programs/${pid}/evidence/`)
      setItems(res.data)
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
      const axiosErr = err as { response?: { status: number } }
      if (axiosErr.response) {
        setError(`API error ${axiosErr.response.status}`)
      } else {
        setError('เชื่อมต่อ API ไม่ได้')
      }
    } finally {
      setSubmitting(false)
    }
  }

  async function handleFormSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!programId) { setError('กรุณาระบุรหัสหลักสูตรก่อน'); return }
    if (!sourceName.trim() || !rawText.trim()) { setError('กรุณากรอกแหล่งที่มาและข้อความหลักฐาน'); return }
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

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !programId) return
    const text = await file.text()
    if (!text.trim()) { setError('ไฟล์ว่างเปล่า'); return }
    await postEvidence({
      evidence_id: crypto.randomUUID(),
      program_id: programId,
      stakeholder_type: stakeholderType,
      source_name: file.name,
      raw_text_th: text,
    })
    if (fileRef.current) fileRef.current.value = ''
  }

  function handleSetProgram() {
    const pid = pidInput.trim()
    if (!pid) return
    setProgramId(pid)
    fetchEvidence(pid)
  }

  return (
    <div className="max-w-3xl mx-auto text-left space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-800">ขั้นตอนที่ 2 — หลักฐานผู้มีส่วนได้ส่วนเสีย</h1>
        <p className="text-gray-500 text-sm mt-1">
          เพิ่มหลักฐานจากแหล่งต่างๆ เพื่อใช้ในการสังเคราะห์ PLO
        </p>
      </div>

      {!programId ? (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
          <p className="text-sm text-amber-800 mb-3">
            ยังไม่ได้เลือกหลักสูตร —{' '}
            <button onClick={() => navigate('/')} className="underline font-medium">
              ไปที่ขั้นตอนที่ 1
            </button>{' '}
            หรือระบุรหัสหลักสูตรที่นี่
          </p>
          <div className="flex gap-2">
            <input
              value={pidInput} onChange={e => setPidInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSetProgram()}
              placeholder="รหัสหลักสูตร เช่น cs-2025"
              className="flex-1 border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              onClick={handleSetProgram}
              className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-1.5 rounded-lg transition-colors"
            >
              ยืนยัน
            </button>
          </div>
        </div>
      ) : (
        <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-2.5 flex items-center justify-between">
          <span className="text-sm text-blue-700">
            หลักสูตร: <strong>{programId}</strong>
            <span className="text-blue-400 ml-2">— พบ {items.length} หลักฐาน</span>
          </span>
          <button
            onClick={() => { setProgramId(''); setItems([]) }}
            className="text-xs text-blue-400 hover:text-blue-700 transition-colors"
          >
            เปลี่ยน
          </button>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm flex justify-between">
          <span>{error}</span>
          <button onClick={() => setError('')} className="ml-4 opacity-60 hover:opacity-100">✕</button>
        </div>
      )}
      {success && (
        <div className="bg-green-50 border border-green-200 text-green-700 rounded-lg px-4 py-3 text-sm flex justify-between">
          <span>✓ {success}</span>
          <button onClick={() => setSuccess('')} className="ml-4 opacity-60 hover:opacity-100">✕</button>
        </div>
      )}

      {programId && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h2 className="text-base font-semibold text-gray-700 mb-4">เพิ่มหลักฐานใหม่</h2>
          <form onSubmit={handleFormSubmit} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  ประเภทผู้มีส่วนได้ส่วนเสีย
                </label>
                <select
                  value={stakeholderType} onChange={e => setStakeholderType(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {Object.entries(STAKEHOLDER_LABELS).map(([v, l]) => (
                    <option key={v} value={v}>{l}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">แหล่งที่มา *</label>
                <input
                  value={sourceName} onChange={e => setSourceName(e.target.value)}
                  placeholder="บริษัท ABC / ผู้ประกอบการ XYZ"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                ข้อความหลักฐาน (ภาษาไทย) *
              </label>
              <textarea
                value={rawText} onChange={e => setRawText(e.target.value)}
                rows={4}
                placeholder="วางข้อความที่ได้จากการสัมภาษณ์ แบบสอบถาม หรือเอกสาร..."
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              />
            </div>

            <div className="flex items-center gap-4">
              <button
                type="submit" disabled={submitting}
                className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white text-sm font-medium px-5 py-2 rounded-lg transition-colors cursor-pointer disabled:cursor-not-allowed"
              >
                {submitting ? 'กำลังบันทึก...' : 'เพิ่มหลักฐาน'}
              </button>

              <div className="h-4 w-px bg-gray-200" />

              <label className="flex items-center gap-2 text-sm text-gray-500 hover:text-blue-600 cursor-pointer transition-colors group">
                <svg
                  className="w-4 h-4 group-hover:text-blue-600"
                  fill="none" stroke="currentColor" viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                </svg>
                อัปโหลดเอกสาร
                <span className="text-xs text-gray-400">(.txt, .md, .csv)</span>
                <input
                  ref={fileRef} type="file" accept=".txt,.md,.csv"
                  onChange={handleFileUpload} className="hidden"
                />
              </label>
            </div>
          </form>
        </div>
      )}

      {programId && (
        <div>
          <h2 className="text-base font-semibold text-gray-700 mb-3">หลักฐานทั้งหมด</h2>
          {loadingList ? (
            <div className="text-center text-gray-400 py-8 text-sm">กำลังโหลด...</div>
          ) : items.length === 0 ? (
            <div className="text-center text-gray-400 py-10 text-sm bg-white rounded-xl border border-gray-100">
              ยังไม่มีหลักฐาน — เพิ่มหลักฐานด้านบน
            </div>
          ) : (
            <div className="space-y-2">
              {items.map(item => {
                const cs = CLASS_STYLE[item.classification] ?? CLASS_STYLE.unclassified
                const typeLabel = STAKEHOLDER_LABELS[item.stakeholder_type] ?? item.stakeholder_type
                return (
                  <details
                    key={item.evidence_id}
                    className="bg-white rounded-lg border border-gray-100 shadow-sm group open:shadow-md transition-shadow"
                  >
                    <summary className="flex items-center justify-between px-4 py-3 cursor-pointer list-none select-none">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="font-medium text-gray-700 text-sm shrink-0">{typeLabel}</span>
                        <span className="text-gray-300">—</span>
                        <span className="text-gray-600 text-sm truncate">{item.source_name}</span>
                      </div>
                      <span className={`text-xs font-medium px-2.5 py-0.5 rounded-full shrink-0 ml-3 ${cs.cls}`}>
                        {cs.label}
                      </span>
                    </summary>
                    <div className="px-4 pb-4 pt-2 border-t border-gray-50">
                      <p className="text-sm text-gray-600 whitespace-pre-wrap leading-relaxed">{item.raw_text_th}</p>
                      <p className="text-xs text-gray-300 mt-3 font-mono">{item.evidence_id}</p>
                    </div>
                  </details>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
