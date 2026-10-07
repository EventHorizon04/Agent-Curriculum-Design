import { useState, useEffect, useCallback, useMemo } from 'react'
import { Link } from 'react-router-dom'
import NextStageLink from '../components/NextStageLink'
import RunProgress, { LoadingLine } from '../components/RunProgress'
import { SKILL_RUN_PLANS } from '../constants/runPlans'
import { useProgram } from '../hooks/useProgram'
import api from '../api/client'
import SkillsByStakeholder, {
  type EvidenceMeta,
  type SkillRow,
} from './components/SkillsByStakeholder'
import NeedCard, { type NeedRow } from './components/NeedCard'
import { scopeVerdict } from '../constants/scope'
import { MAX_CORE_PLOS, MIN_CORE_PLOS, fallbackKind } from '../constants/needPolicy'
import DesignerNote from './components/DesignerNote'

/** Which stage a run covers. 'all' is the first run, where there is nothing to
 * combine yet; the other two are the split re-runs. */
type RunKind = 'all' | 'skills' | 'needs'

const RUN_PATH: Record<RunKind, string> = {
  all: 'run',
  skills: 'skills/run',
  needs: 'combine/run',
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
  /**
   * Needs the scope guard will hold back at plo_synthesis.
   *
   * Derived here rather than read off a response, the same way the report
   * derives it: the guard runs at synthesis, so nothing has judged these rows
   * yet and no endpoint returns a verdict. Saying it at this checkpoint is the
   * point of saying it at all — the fix is to edit the scope statement and
   * re-extract, and the button for that is on this page. Discovered at the
   * report instead, the same fix costs every synthesis call already paid for.
   */
  const guardedNeedCount = useMemo(
    () => needs.filter(n => scopeVerdict(n) !== 'in_scope').length,
    [needs],
  )

  /**
   * How many core PLOs this Need set will actually yield, against the 6-10 band.
   *
   * plo_synthesis drops out-of-scope Needs *before* it applies the ceiling, so
   * the number that lands in the curriculum is the in-scope core count capped at
   * MAX_CORE_PLOS — not the core count on its own, which is what the list above
   * shows and what a designer would otherwise count by eye.
   *
   * The pipeline already knows this and says so twice, both times only to the
   * server log: need_combination warns when the core count is short, and
   * plo_synthesis warns again after the guard has run, naming the guard as the
   * cause. Its own comment says "the designer must add more at the review
   * checkpoint" — this is that checkpoint, and until now it said nothing.
   */
  const coreOutlook = useMemo(() => {
    const core = needs.filter(n => !n.is_optional)
    const surviving = core.filter(n => scopeVerdict(n) === 'in_scope').length
    return {
      core: core.length,
      guarded: core.length - surviving,
      projected: Math.min(surviving, MAX_CORE_PLOS),
      unwritten: needs.filter(n => fallbackKind(n.statement_th)).length,
    }
  }, [needs])

  const staleNeedCount = useMemo(() => {
    if (skills.length === 0 || needs.length === 0) return 0
    const live = new Set(skills.map(s => s.skill_id))
    return needs.filter(n => n.member_skill_ids.some(id => !live.has(id))).length
  }, [skills, needs])

  if (!programId) {
    return (
      <div className="mx-auto max-w-2xl py-16 text-center">
        <p className="mb-4 text-pencil">ยังไม่ได้เลือกโปรแกรม</p>
        <Link to="/" className="link">ไปหน้า Intake</Link>
      </div>
    )
  }

  const hasData = skills.length > 0 || needs.length > 0

  return (
    <div className="max-w-4xl">
      <div className="mb-6">
        <p className="eyebrow">ขั้นที่ 3</p>
        <h1 className="page-title mb-1">สกัดทักษะและรวมเป็น Need</h1>
        <p className="text-sm text-pencil">
          ทักษะดิบที่สกัดจาก evidence และ Need ที่กลั่นจากทักษะเหล่านั้น
        </p>
        <p className="data mt-1 text-xs text-lead">{programId}</p>
      </div>

      {error && (
        <div className="notice notice-error mb-6">{error}</div>
      )}

      {loading ? (
        <LoadingLine />
      ) : running ? (
        <RunProgress plan={SKILL_RUN_PLANS[running]} />
      ) : !hasData ? (
        <div className="panel border-dashed px-6 py-12 text-center">
          <p className="font-display mb-1 text-lg text-graphite">ยังไม่มีทักษะที่สกัดได้</p>
          <p className="mb-6 text-sm text-pencil">กดปุ่มด้านล่างเพื่อสกัดทักษะจาก evidence ที่มีอยู่</p>
          <div className="mx-auto mb-2 max-w-md">
            <DesignerNote value={note} onChange={setNote} />
          </div>
          <button
            onClick={() => runStage('all')}
            className="btn btn-primary"
          >
            สกัดทักษะและรวม Need
          </button>
        </div>
      ) : (
        <>
          <DesignerNote value={note} onChange={setNote} disabled={running !== null} />
          <div className="mb-5 flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-1">
              {/* Two entry points, not one: re-extracting is the expensive
                  per-evidence LLM pass, while re-combining only re-clusters
                  what is already on record. */}
              <button
                onClick={() => runStage('skills')}
                disabled={running !== null}
                title="สกัดทักษะจาก evidence ใหม่ (ไม่แตะ Need ที่มีอยู่)"
                className="btn btn-sm btn-secondary"
              >
                สกัดทักษะใหม่
              </button>
              <span className="text-xs text-lead" aria-hidden="true">·</span>
              <button
                onClick={() => runStage('needs')}
                disabled={running !== null}
                title="รวมทักษะที่มีอยู่เป็น Need ใหม่ (ไม่สกัดทักษะซ้ำ)"
                className="btn btn-sm btn-secondary"
              >
                รวม Need ใหม่
              </button>
            </div>
          </div>

          <div className="mb-4 flex flex-wrap gap-1 border-b border-hair-strong">
            {([
              ['skills', `Skill ดิบ (${skills.length})`],
              ['needs', `Need (${needs.length})`],
            ] as const).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`-mb-px rounded-t-[3px] px-4 py-2 text-sm font-medium transition-colors ${
                  tab === key
                    ? 'border-b-2 border-stamp text-stamp'
                    : 'border-b-2 border-transparent text-pencil hover:text-graphite'
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
            <p className="py-8 text-center text-sm text-lead">ยังไม่มี Need — รัน Skill Extraction ก่อน</p>
          ) : (
            <div className="space-y-3">
              {staleNeedCount > 0 && (
                <div className="notice notice-warn flex flex-wrap items-center gap-3">
                  <span className="min-w-0 flex-1">
                    Need {staleNeedCount} รายการมาจากทักษะชุดก่อน — กด “รวม Need ใหม่”
                    เพื่อรวมใหม่จากทักษะปัจจุบัน
                  </span>
                  <button
                    onClick={() => runStage('needs')}
                    disabled={running !== null}
                    className="btn btn-sm btn-secondary"
                  >
                    รวม Need ใหม่
                  </button>
                </div>
              )}
              {/* Placed above the guard notice, which explains what to do about
                  the Needs this count is missing. */}
              <div
                className={`notice ${
                  coreOutlook.projected < MIN_CORE_PLOS
                    ? 'notice-warn'
                    : 'border-hair-strong bg-sunk text-graphite'
                }`}
              >
                <p>
                  จะได้ PLO หลัก <span className="data font-semibold">{coreOutlook.projected}</span> ข้อ
                  {' '}· เกณฑ์ {MIN_CORE_PLOS}-{MAX_CORE_PLOS} ข้อ
                  {coreOutlook.projected < MIN_CORE_PLOS && ' — ต่ำกว่าเกณฑ์'}
                </p>
                <p className="mt-1 text-xs opacity-85">
                  Need หลัก {coreOutlook.core} ข้อ
                  {coreOutlook.guarded > 0 && ` · ตัวกรองขอบเขตกันออก ${coreOutlook.guarded} ข้อ`}
                  {coreOutlook.core - coreOutlook.guarded > MAX_CORE_PLOS &&
                    ` · เกิน ${MAX_CORE_PLOS} ข้อ ระบบใช้เฉพาะ ${MAX_CORE_PLOS} ข้อที่ demand สูงสุด`}
                  {coreOutlook.unwritten > 0 &&
                    ` · เขียนไม่สำเร็จ ${coreOutlook.unwritten} ข้อ (นับรวมอยู่ด้วย)`}
                </p>
              </div>
              {guardedNeedCount > 0 && (
                <div className="notice notice-error">
                  <p>
                    <span className="data font-semibold">{guardedNeedCount}</span> จาก {needs.length}{' '}
                    ข้อจะไม่ถูกส่งต่อไป PLO synthesis เพราะอยู่นอกขอบเขตของหลักสูตร — ป้ายบนการ์ด
                    บอกเหตุผลรายใบ กด “ดูที่มา” เพื่อดูว่าทักษะตัวไหนทำให้ถูกกัน
                  </p>
                  <p className="mt-1.5">
                    <span className="font-semibold">ถ้าตัดสินผิด:</span> แก้ “ขอบเขตของหลักสูตร” ที่หน้า{' '}
                    <Link to="/intake" className="underline underline-offset-2">
                      Intake
                    </Link>{' '}
                    แล้วกด <span className="font-semibold">สกัดทักษะใหม่</span> ด้านบน — ทั้งโปรแกรมถูกสกัดใหม่
                    (ระบบไม่รันให้เอง ทุกขั้นต้องผ่านการอนุมัติ)
                  </p>
                  <p className="mt-1.5">
                    <span className="font-semibold">ถ้าตัดสินถูกแต่ยังอยากได้:</span> เลือกมันที่หน้า
                    PLO Synthesis แล้วกด “รวมเป็น PLO เดียว” — ตรงนั้นไม่กัน
                  </p>
                </div>
              )}
              {needs.map(n => (
                <NeedCard key={n.need_id} programId={programId} need={n} />
              ))}
            </div>
          )}
        </>
      )}

      {/* Needs, not skills: plo_synthesis drafts one PLO per Need and never
          reads the skill rows. A run that extracted skills and combined nothing
          has not produced what the next stage needs. */}
      <NextStageLink
        from="skill_extraction"
        ready={Boolean(programId) && needs.length > 0 && running === null}
        blockedReason={
          running !== null
            ? 'รอให้รันเสร็จก่อน — ขั้นสังเคราะห์ PLO ต้องอ่านจาก Need ชุดนี้'
            : 'ยังไม่มี Need — รันสกัดทักษะและรวม Need ให้เสร็จก่อน'
        }
      />
    </div>
  )
}
