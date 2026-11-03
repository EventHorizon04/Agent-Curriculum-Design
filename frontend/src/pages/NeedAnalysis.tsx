import { useState, useEffect, useCallback, useMemo } from 'react'
import { Link } from 'react-router-dom'
import NextStageLink from '../components/NextStageLink'
import RunProgress, { LoadingLine, RunFailure } from '../components/RunProgress'
import { SKILL_RUN_PLANS } from '../constants/runPlans'
import { useProgram } from '../hooks/useProgram'
import { useJobs } from '../hooks/useProgramJobs'
import { useReloadOnJobs } from '../hooks/useReloadOnJobs'
import api from '../api/client'
import { startJob, type JobKind } from '../api/jobs'
import NeedCard, { type NeedRow } from './components/NeedCard'
import { scopeVerdict } from '../constants/scope'
import { MAX_CORE_PLOS, MIN_CORE_PLOS, fallbackKind } from '../constants/needPolicy'
import DesignerNote from './components/DesignerNote'

/** Agent 2 only. Extraction jobs are not this page's: a need_combination job is
 *  the one run that changes what it lists. */
const PAGE_KINDS: JobKind[] = ['need_combination']

interface SkillName {
  skill_id: string
  skill_name_th: string
}

export default function NeedAnalysis() {
  const { programId } = useProgram()
  // Every stored Need, merged-away originals included: the merged card shows
  // its originals, and only rows with no `merged_into` are listed as Needs.
  const [allNeeds, setAllNeeds] = useState<NeedRow[]>([])
  const [skills, setSkills] = useState<SkillName[]>([])
  const [loading, setLoading] = useState(false)
  const [starting, setStarting] = useState(false)
  // One in-flight card action (split, exclude or restore); each blocks the rest.
  const [acting, setActing] = useState(false)
  const [merging, setMerging] = useState(false)
  const [error, setError] = useState('')
  // A refused split, exclude or restore is shown on the card whose button was
  // pressed, not in the page notice at the top. One at a time: the next action
  // clears it.
  const [actionError, setActionError] = useState<{ needId: string; message: string } | null>(null)
  // The designer's pick for a merge, and the bar's own notice and reason.
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [mergeReason, setMergeReason] = useState('')
  const [mergeError, setMergeError] = useState('')
  const [note, setNote] = useState('')

  const { running, latestOf, started, refresh } = useJobs()
  const mine = running && PAGE_KINDS.includes(running.kind) ? running : null
  const last = latestOf(PAGE_KINDS)
  // Any job of the program blocks every start button, not just this page's kind:
  // the backend allows one writer per program.
  const busy = running !== null || starting || acting || merging

  const fetchAll = useCallback(async () => {
    if (!programId) return
    setLoading(true)
    setError('')
    try {
      const [needRes, skillRes] = await Promise.all([
        api.get<NeedRow[]>(`/programs/${programId}/needs/?active_only=false`),
        api.get<SkillName[]>(`/programs/${programId}/needs/skills`),
      ])
      setAllNeeds(needRes.data)
      // A Need that left the active list (restored ones come back unticked) is
      // dropped from the pick, so a stale tick never survives a reload.
      const active = new Set(
        needRes.data.filter(n => n.merged_into === null && n.excluded_at === null).map(n => n.need_id),
      )
      setSelected(prev => new Set([...prev].filter(id => active.has(id))))
      setSkills(skillRes.data)
    } catch {
      setError('โหลดข้อมูล Need ไม่สำเร็จ')
    } finally {
      setLoading(false)
    }
  }, [programId])

  // Reload once when an Agent 2 job ends, whichever way it ends.
  const watch = useReloadOnJobs(PAGE_KINDS, () => void fetchAll())

  const rerun = useCallback(async () => {
    if (!programId) return
    setStarting(true)
    setError('')
    setActionError(null)
    setMergeError('')
    try {
      const job = await startJob(`/programs/${programId}/needs/combine/run`, {
        note_th: note.trim() || null,
      })
      watch(job)
      started(job)
    } catch (err: unknown) {
      const res = (err as { response?: { status?: number; data?: { detail?: string } } })?.response
      setError(res?.data?.detail ?? 'รวม Need ไม่สำเร็จ')
      if (res?.status === 409) void refresh()
    } finally {
      setStarting(false)
    }
  }, [programId, note, watch, started, refresh])

  /** One card action. 404 / 422 / 409 all carry a Thai `detail` that says what
   *  to do next; a 409 means another writer is running, so the job list is stale. */
  const cardAction = useCallback(
    async (need: NeedRow, verb: 'split' | 'exclude' | 'restore', failure: string) => {
      if (!programId) return
      setActing(true)
      setError('')
      setMergeError('')
      setActionError(null)
      try {
        await api.post(`/programs/${programId}/needs/${need.need_id}/${verb}`)
        await fetchAll()
      } catch (err: unknown) {
        const res = (err as { response?: { status?: number; data?: { detail?: unknown } } })?.response
        const d = res?.data?.detail
        setActionError({ needId: need.need_id, message: typeof d === 'string' ? d : failure })
        if (res?.status === 409) void refresh()
      } finally {
        setActing(false)
      }
    },
    [programId, fetchAll, refresh],
  )
  const split = useCallback((n: NeedRow) => cardAction(n, 'split', 'แยก Need ไม่สำเร็จ'), [cardAction])
  const exclude = useCallback((n: NeedRow) => cardAction(n, 'exclude', 'ตัด Need ไม่สำเร็จ'), [cardAction])
  const restore = useCallback((n: NeedRow) => cardAction(n, 'restore', 'คืน Need ไม่สำเร็จ'), [cardAction])

  const toggleSelect = useCallback((need: NeedRow, on: boolean) => {
    setMergeError('')
    setSelected(prev => {
      const next = new Set(prev)
      if (on) next.add(need.need_id)
      else next.delete(need.need_id)
      return next
    })
  }, [])

  const merge = useCallback(
    async (needIds: string[]) => {
      if (!programId) return
      setMerging(true)
      setError('')
      setMergeError('')
      setActionError(null)
      try {
        await api.post(`/programs/${programId}/needs/merge`, {
          need_ids: needIds,
          reason_th: mergeReason.trim() || null,
        })
        setSelected(new Set())
        setMergeReason('')
        await fetchAll()
      } catch (err: unknown) {
        // 409 / 422 / 502 all carry a Thai `detail`; the bar shows it where the
        // designer pressed the button.
        const res = (err as { response?: { status?: number; data?: { detail?: unknown } } })?.response
        const d = res?.data?.detail
        setMergeError(typeof d === 'string' ? d : 'รวม Need ไม่สำเร็จ')
        if (res?.status === 409) void refresh()
        // The list may be what the refusal is about (a Need merged or excluded
        // elsewhere), so show the reason and then reload it.
        if (res?.status === 422) await fetchAll()
      } finally {
        setMerging(false)
      }
    },
    [programId, mergeReason, fetchAll, refresh],
  )

  useEffect(() => { fetchAll() }, [fetchAll])

  // Active: neither folded into a merge nor taken out by the designer. The
  // excluded ones are listed apart, since no stage reads them.
  const needs = useMemo(
    () => allNeeds.filter(n => n.merged_into === null && n.excluded_at === null),
    [allNeeds],
  )
  const excludedNeeds = useMemo(
    () => allNeeds.filter(n => n.merged_into === null && n.excluded_at !== null),
    [allNeeds],
  )
  // Derived from the active list so a Need that has since left it (merged,
  // excluded, re-run away) can never count toward the bar.
  const selectedIds = useMemo(
    () => needs.filter(n => selected.has(n.need_id)).map(n => n.need_id),
    [needs, selected],
  )

  const originalsOf = useMemo(() => {
    const byParent = new Map<string, NeedRow[]>()
    for (const n of allNeeds) {
      if (n.merged_into === null) continue
      byParent.set(n.merged_into, [...(byParent.get(n.merged_into) ?? []), n])
    }
    return byParent
  }, [allNeeds])
  const originalsFor = useCallback((needId: string) => originalsOf.get(needId) ?? [], [originalsOf])
  const skillNames = useMemo(
    () => Object.fromEntries(skills.map(s => [s.skill_id, s.skill_name_th])),
    [skills],
  )

  /**
   * Needs the scope guard will hold back at plo_synthesis.
   *
   * Derived here rather than read off a response: the guard runs at synthesis,
   * so nothing has judged these rows yet. This checkpoint is where saying it
   * pays off — the fix is to edit the scope statement and re-extract.
   */
  const guardedNeedCount = useMemo(
    () => needs.filter(n => scopeVerdict(n) !== 'in_scope').length,
    [needs],
  )

  /**
   * How many core PLOs this Need set will actually yield, against the 6-10 band.
   *
   * plo_synthesis drops out-of-scope Needs before it applies the ceiling, so the
   * number that lands in the curriculum is the in-scope core count capped at
   * MAX_CORE_PLOS, not the core count on its own.
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

  /**
   * Needs left behind by an older set of skills: re-extraction mints new skill
   * ids, so a Need naming an id no longer on record was built from a previous
   * extraction and its trace would come back empty.
   */
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

  const mergedCount = needs.filter(n => n.merged_from.length > 0).length

  return (
    <div className="max-w-4xl">
      <div className="mb-6">
        <p className="eyebrow">ขั้นที่ 4</p>
        <h1 className="page-title mb-1">วิเคราะห์ Need</h1>
        <p className="text-sm text-pencil">
          Need ที่กลั่นจากกลุ่มทักษะ และ Need ที่ซ้ำกันซึ่งรวมเป็นข้อเดียว — ตรวจและอนุมัติที่ขั้นนี้
        </p>
        <p className="data mt-1 text-xs text-lead">{programId}</p>
      </div>

      {error && <div className="notice notice-error mb-6">{error}</div>}
      {last?.status === 'failed' && (
        <div className="mb-6">
          <RunFailure job={last} />
        </div>
      )}

      {mine ? (
        <RunProgress key={mine.job_id} plan={SKILL_RUN_PLANS.needs} since={Date.parse(mine.created_at)} />
      ) : loading ? (
        <LoadingLine />
      ) : needs.length === 0 && excludedNeeds.length === 0 ? (
        <div className="panel border-dashed px-6 py-12 text-center">
          <p className="font-display mb-1 text-lg text-graphite">ยังไม่มี Need</p>
          {skills.length === 0 ? (
            <p className="mb-2 text-sm text-pencil">
              ต้องสกัดทักษะก่อนที่หน้า{' '}
              <Link to="/skill-extraction" className="link">สกัดทักษะ</Link>
            </p>
          ) : (
            <>
              <p className="mb-6 text-sm text-pencil">กดปุ่มด้านล่างเพื่อรวมกลุ่มทักษะเป็น Need</p>
              <div className="mx-auto mb-2 max-w-md">
                <DesignerNote value={note} onChange={setNote} />
              </div>
              <button onClick={rerun} disabled={busy} className="btn btn-primary">
                รวม Need
              </button>
            </>
          )}
        </div>
      ) : (
        <>
          <DesignerNote value={note} onChange={setNote} disabled={busy} />
          <div className="mb-5 flex flex-wrap items-center justify-between gap-2">
            <button
              onClick={rerun}
              disabled={busy}
              title="รวมกลุ่มทักษะที่มีอยู่เป็น Need ใหม่ (ไม่สกัดทักษะซ้ำ)"
              className="btn btn-sm btn-secondary"
            >
              รวม Need ใหม่
            </button>
            <p className="max-w-sm text-xs text-pencil">
              รัน Agent 2 ใหม่จะล้างการรวมและการตัดออกที่ทำด้วยมือ
            </p>
            <p className="w-full text-xs text-pencil">
              Need {needs.length} ข้อ
              {mergedCount > 0 && ` · รวมจากหลายข้อ ${mergedCount} ข้อ`}
            </p>
          </div>

          <div className="space-y-3">
            {staleNeedCount > 0 && (
              <div className="notice notice-warn">
                ทักษะเปลี่ยนไปแล้ว — Need {staleNeedCount} รายการมาจากทักษะชุดก่อน ดูที่หน้า{' '}
                <Link to="/skill-extraction" className="underline underline-offset-2">
                  สกัดทักษะ
                </Link>
              </div>
            )}
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
                  แล้วกด <span className="font-semibold">สกัดทักษะใหม่</span> ที่หน้า{' '}
                  <Link to="/skill-extraction" className="underline underline-offset-2">
                    สกัดทักษะ
                  </Link>{' '}
                  — ทั้งโปรแกรมถูกสกัดใหม่ (ระบบไม่รันให้เอง ทุกขั้นต้องผ่านการอนุมัติ)
                </p>
                <p className="mt-1.5">
                  <span className="font-semibold">ถ้าตัดสินถูกแต่ยังอยากได้:</span> เลือกมันที่หน้า
                  PLO Synthesis แล้วกด “รวมเป็น PLO เดียว” — ตรงนั้นไม่กัน
                </p>
              </div>
            )}
            {needs.map(n => (
              <NeedCard
                key={n.need_id}
                programId={programId}
                need={n}
                originals={originalsOf.get(n.need_id) ?? []}
                originalsOf={originalsFor}
                skillNames={skillNames}
                onSplit={split}
                onExclude={exclude}
                selected={selected.has(n.need_id)}
                onSelect={toggleSelect}
                actionError={actionError?.needId === n.need_id ? actionError.message : ''}
                disabled={busy}
              />
            ))}
          </div>

          {selectedIds.length > 0 && (
            <div className="panel sticky bottom-3 z-10 mt-4 space-y-2 p-3">
              <div className="flex flex-wrap items-end gap-3">
                <p className="text-sm text-graphite">
                  เลือกแล้ว <span className="data font-semibold">{selectedIds.length}</span> ข้อ
                  <span className="field-hint ml-2">รวมได้ 2-5 ข้อ</span>
                </p>
                <div className="min-w-48 flex-1">
                  <label htmlFor="merge-reason" className="field-label">เหตุผลที่รวม (ไม่บังคับ)</label>
                  <input
                    id="merge-reason"
                    type="text"
                    maxLength={400}
                    value={mergeReason}
                    onChange={e => setMergeReason(e.target.value)}
                    disabled={busy}
                    className="input"
                  />
                </div>
                <button
                  onClick={() => void merge(selectedIds)}
                  disabled={busy || selectedIds.length < 2 || selectedIds.length > 5}
                  className="btn btn-primary"
                >
                  {merging ? 'กำลังรวม...' : `รวม Need ที่เลือก (${selectedIds.length})`}
                </button>
              </div>
              {mergeError && (
                <p role="alert" className="notice notice-error text-xs">{mergeError}</p>
              )}
            </div>
          )}

          {excludedNeeds.length > 0 && (
            <details className="mt-6">
              <summary className="cursor-pointer text-sm text-pencil">
                Need ที่ตัดออก ({excludedNeeds.length})
              </summary>
              <div className="mt-3 space-y-3">
                {excludedNeeds.map(n => (
                  <NeedCard
                    key={n.need_id}
                    programId={programId}
                    need={n}
                    originals={originalsOf.get(n.need_id) ?? []}
                    originalsOf={originalsFor}
                    skillNames={skillNames}
                    onRestore={restore}
                    actionError={actionError?.needId === n.need_id ? actionError.message : ''}
                    disabled={busy}
                  />
                ))}
              </div>
            </details>
          )}
        </>
      )}

      {/* The review gate: approving here is moving on. plo_synthesis drafts one
          PLO per Need and never reads the skill rows. */}
      <NextStageLink
        from="need_analysis"
        ready={needs.length > 0 && mine === null}
        blockedReason={
          mine !== null
            ? 'รอให้รันเสร็จก่อน — ขั้นสังเคราะห์ PLO ต้องอ่านจาก Need ชุดนี้'
            : 'ยังไม่มี Need — รวมกลุ่มทักษะเป็น Need ให้เสร็จก่อน'
        }
      />
    </div>
  )
}
