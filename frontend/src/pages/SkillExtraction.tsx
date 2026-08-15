import { useState, useEffect, useCallback, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useProgram } from '../hooks/useProgram'
import api from '../api/client'
import SkillsByStakeholder, {
  type EvidenceMeta,
  type SkillRow,
} from './components/SkillsByStakeholder'
import NeedCard, { type NeedRow } from './components/NeedCard'
import DesignerNote from './components/DesignerNote'

/** Which stage a run covers. 'all' is the first run, where there is nothing to
 * combine yet; the other two are the split re-runs. */
type RunKind = 'all' | 'skills' | 'needs'

const RUN_PATH: Record<RunKind, string> = {
  all: 'run',
  skills: 'skills/run',
  needs: 'combine/run',
}

const RUN_LABEL: Record<RunKind, string> = {
  all: 'กำลังสกัดทักษะและรวม Need...',
  skills: 'กำลังสกัดทักษะจาก evidence...',
  needs: 'กำลังรวมทักษะเป็น Need...',
}

export default function SkillExtraction() {
  const { programId } = useProgram()
  const [tab, setTab] = useState<'skills' | 'needs'>('skills')
  const [skills, setSkills] = useState<SkillRow[]>([])
  const [needs, setNeeds] = useState<NeedRow[]>([])
  const [evidenceById, setEvidenceById] = useState<Record<string, EvidenceMeta>>({})
  const [droppedCount, setDroppedCount] = useState(0)
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState<RunKind | null>(null)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')

  const fetchAll = useCallback(async () => {
    if (!programId) return
    setLoading(true)
    setError('')
    try {
      const [skillRes, needRes, evidenceRes] = await Promise.all([
        api.get<SkillRow[]>(`/programs/${programId}/needs/skills`),
        api.get<NeedRow[]>(`/programs/${programId}/needs/`),
        api.get<(EvidenceMeta & { evidence_id: string })[]>(`/programs/${programId}/evidence/`),
      ])
      setSkills(skillRes.data)
      setNeeds(needRes.data)
      setEvidenceById(
        Object.fromEntries(
          evidenceRes.data.map(e => [
            e.evidence_id,
            {
              source_name: e.source_name,
              stakeholder_type: e.stakeholder_type,
              classification: e.classification,
            },
          ]),
        ),
      )
    } catch {
      setError('โหลดข้อมูล Stage 3 ไม่สำเร็จ')
    } finally {
      setLoading(false)
    }
  }, [programId])

  const runStage = useCallback(
    async (kind: RunKind) => {
      if (!programId) return
      setRunning(kind)
      setError('')
      try {
        const res = await api.post<{ dropped_ungrounded_count: number }>(
          `/programs/${programId}/needs/${RUN_PATH[kind]}`,
          { note_th: note.trim() || null },
        )
        // Only an extraction pass can drop a skill for being ungrounded, so a
        // combine-only run must not reset the count the last extraction reported.
        if (kind !== 'needs') setDroppedCount(res.data.dropped_ungrounded_count)
        await fetchAll()
      } catch (err: unknown) {
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        setError(msg ?? 'รัน Stage 3 ไม่สำเร็จ')
      } finally {
        setRunning(null)
      }
    },
    [programId, note, fetchAll],
  )

  useEffect(() => { fetchAll() }, [fetchAll])

  /**
   * Needs left behind by an older set of skills.
   *
   * skill_extraction deletes every skill row and mints new ids, so a Need that
   * still names an id no longer on record was built from a previous extraction.
   * Its trace would come back empty, which reads as a bug rather than as stale
   * data — hence the banner.
   */
  const staleNeedCount = useMemo(() => {
    if (skills.length === 0 || needs.length === 0) return 0
    const live = new Set(skills.map(s => s.skill_id))
    return needs.filter(n => n.member_skill_ids.some(id => !live.has(id))).length
  }, [skills, needs])

  if (!programId) {
    return (
      <div className="max-w-2xl mx-auto py-16 text-center">
        <p className="text-gray-500 mb-4">ยังไม่ได้เลือกโปรแกรม</p>
        <Link to="/" className="text-blue-600 hover:underline">ไปหน้า Intake</Link>
      </div>
    )
  }

  const hasData = skills.length > 0 || needs.length > 0

  return (
    <div className="max-w-4xl mx-auto py-8 px-4">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">Stage 3: Skill Extraction</h1>
        <p className="text-gray-500 text-sm">
          ทักษะดิบที่สกัดจาก evidence และ Need ที่กลั่นจากทักษะเหล่านั้น
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
          <p className="text-gray-600 font-medium mb-1">{RUN_LABEL[running]}</p>
          <p className="text-gray-400 text-sm">
            {running === 'needs'
              ? 'อาจใช้เวลาราวหนึ่งนาที'
              : 'อาจใช้เวลา 1-5 นาที ขึ้นกับจำนวน evidence'}
          </p>
        </div>
      ) : !hasData ? (
        <div className="text-center py-20">
          <div className="text-5xl mb-4">🔍</div>
          <p className="text-gray-500 text-lg font-medium mb-1">ยังไม่มีทักษะที่สกัดได้</p>
          <p className="text-gray-400 text-sm mb-6">กดปุ่มด้านล่างเพื่อสกัดทักษะจาก evidence ที่มีอยู่</p>
          <div className="mx-auto mb-2 max-w-md">
            <DesignerNote value={note} onChange={setNote} />
          </div>
          <button
            onClick={() => runStage('all')}
            className="bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 font-medium transition-colors"
          >
            Run Skill Extraction
          </button>
        </div>
      ) : (
        <>
          <DesignerNote value={note} onChange={setNote} disabled={running !== null} />
          <div className="flex justify-between items-center mb-5">
            <div className="flex items-center gap-3">
              {/* Two entry points, not one: re-extracting is the expensive
                  per-evidence LLM pass, while re-combining only re-clusters
                  what is already on record. */}
              <button
                onClick={() => runStage('skills')}
                disabled={running !== null}
                title="สกัดทักษะจาก evidence ใหม่ (ไม่แตะ Need ที่มีอยู่)"
                className="text-xs text-gray-400 hover:text-blue-600 underline disabled:opacity-50"
              >
                Re-run Skill
              </button>
              <span className="text-xs text-gray-300">·</span>
              <button
                onClick={() => runStage('needs')}
                disabled={running !== null}
                title="รวมทักษะที่มีอยู่เป็น Need ใหม่ (ไม่สกัดทักษะซ้ำ)"
                className="text-xs text-gray-400 hover:text-blue-600 underline disabled:opacity-50"
              >
                Re-run Need
              </button>
            </div>
            <Link
              to="/plo-synthesis"
              className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 text-sm font-medium transition-colors"
            >
              ดำเนินการต่อ → PLO Synthesis
            </Link>
          </div>

          <div className="mb-4 flex gap-1 border-b border-gray-200">
            {([
              ['skills', `Skill ดิบ (${skills.length})`],
              ['needs', `Need (${needs.length})`],
            ] as const).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`px-4 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded-t ${
                  tab === key
                    ? 'border-b-2 border-blue-600 text-blue-700'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {tab === 'skills' ? (
            <SkillsByStakeholder
              skills={skills}
              evidenceById={evidenceById}
              droppedCount={droppedCount}
            />
          ) : needs.length === 0 ? (
            <p className="py-8 text-center text-sm text-gray-400">ยังไม่มี Need — รัน Skill Extraction ก่อน</p>
          ) : (
            <div className="space-y-3">
              {staleNeedCount > 0 && (
                <div className="flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  <span className="flex-1">
                    Need {staleNeedCount} รายการมาจากทักษะชุดก่อน — กด Re-run Need
                    เพื่อรวมใหม่จากทักษะปัจจุบัน
                  </span>
                  <button
                    onClick={() => runStage('needs')}
                    disabled={running !== null}
                    className="shrink-0 rounded bg-amber-600 px-2 py-1 font-medium text-white hover:bg-amber-700 disabled:opacity-50"
                  >
                    Re-run Need
                  </button>
                </div>
              )}
              {needs.map(n => (
                <NeedCard key={n.need_id} programId={programId} need={n} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
