import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import NextStageLink from '../components/NextStageLink'
import RunProgress, { LoadingLine, RunFailure } from '../components/RunProgress'
import { PLO_SYNTHESIS_PLAN, PLO_SYNTHESIS_CODE_ONLY_PLAN } from '../constants/runPlans'
import { useProgram } from '../hooks/useProgram'
import { useJobs } from '../hooks/useProgramJobs'
import { useReloadOnJobs } from '../hooks/useReloadOnJobs'
import api from '../api/client'
import { startJob, type JobKind } from '../api/jobs'
import DesignerNote from './components/DesignerNote'
import SupersededPlos from './components/SupersededPlos'
import { plosCiting } from './components/plosCiting'
import MergeNeedPicker from './components/MergeNeedPicker'
import { attachBlockedReason, unusedNeedsOf, type PickerNeed } from './components/pickerNeed'
import { AttachButton, AttachPanel } from './components/AttachNeed'
import ValidationToggle, { type ValidationStatus } from './components/ValidationToggle'
import { classStyle, ksecLabel, stakeholderLabel } from '../constants/stakeholder'
import { SMART_KEYS, SMART_LABEL_TH, VALIDATED_BY_TH, findingLabel, needsAttention } from '../constants/smart'
import { DEMAND_SCORE_TITLE_TH, demandPercent } from '../constants/demand'
import { BLOOM_LABEL } from '../constants/bloom'
import type { PLO, SupersededPLO } from '../types/plo'

interface NeedSummary {
  need_id: string
  statement_th: string
  statement_en: string | null
  ksec_categories: string[]
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

type NeedListItem = PickerNeed

/** The jobs this page owns: the synthesis run, and the SMART re-check of one
 *  outcome. They are what it shows as running and what its failure notice is
 *  about. */
const PAGE_KINDS: JobKind[] = ['plo_synthesis', 'plo_revalidate']
/** The jobs that change what this page lists, whichever page started them: the
 *  PLOs it shows are written by the first two, the Needs it offers for merging
 *  by the last two. */
const RELOAD_KINDS: JobKind[] = ['plo_synthesis', 'plo_revalidate', 'needs_pipeline', 'skill_extraction', 'need_combination']

/** Wall clock, read from an event handler: kept out of the component body so
 *  the purity lint does not mistake the handler for render. */
const clockMs = (): number => Date.now()

export default function PloSynthesis() {
  const { programId } = useProgram()
  const [plos, setPlos] = useState<PLO[]>([])
  const [superseded, setSuperseded] = useState<SupersededPLO[]>([])
  const [needs, setNeeds] = useState<NeedListItem[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(false)
  // Between a click and the job being known, and during the synchronous merge.
  const [starting, setStarting] = useState(false)
  const [merging, setMerging] = useState(false)
  // The cards a merge in flight will replace, and when it began.
  const [mergeFlight, setMergeFlight] = useState<{ ids: Set<string>; since: number } | null>(null)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [runValidation, setRunValidation] = useState(true)
  const [validation, setValidation] = useState<ValidationStatus | null>(null)
  // What the next run will actually do: the system switch wins over the box.
  const agentWillRun = validation?.enabled !== false && runValidation

  const { running, latestOf, started, refresh } = useJobs()
  // `running` is any job of this program; `mine` is one this page shows.
  const mine = running && PAGE_KINDS.includes(running.kind) ? running : null
  const synthesis = mine?.kind === 'plo_synthesis' ? mine : null
  const revalidatingId =
    mine?.kind === 'plo_revalidate' && typeof mine.params.plo_id === 'string' ? mine.params.plo_id : null
  const last = latestOf(PAGE_KINDS)
  // Any job of the program blocks every start button, not just this page's
  // kinds: the backend allows one writer per program, merging included.
  const busy = running !== null || starting || merging

  // Read once per program. A failed read leaves the status unknown rather than
  // "off": the box stays usable, and the backend still refuses to run an agent
  // its own settings disable.
  useEffect(() => {
    if (!programId) return
    let cancelled = false
    api
      .get<ValidationStatus>(`/programs/${programId}/plos/validation`)
      .then((res) => {
        if (!cancelled) setValidation(res.data)
      })
      .catch(() => {
        if (!cancelled) setValidation(null)
      })
    return () => {
      cancelled = true
    }
  }, [programId])

  /** `quiet` reloads behind the list that is showing instead of replacing it
   *  with the loading line: a re-check changes one outcome, and swapping the
   *  whole list out would close every open trace and drop an edit in progress. */
  const fetchPlos = useCallback(
    async (quiet = false) => {
      if (!programId) return
      if (!quiet) setLoading(true)
      setError('')
      try {
        const [ploRes, supersededRes, needRes] = await Promise.all([
          api.get<PLO[]>(`/programs/${programId}/plos/`),
          // The replaced list is secondary: its failure must not blank the PLOs.
          api
            .get<SupersededPLO[]>(`/programs/${programId}/plos/superseded`)
            .catch(() => ({ data: [] as SupersededPLO[] })),
          api.get<NeedListItem[]>(`/programs/${programId}/needs/?active_only=true`),
        ])
        setPlos(ploRes.data)
        setSuperseded(supersededRes.data)
        setNeeds(needRes.data)
      } catch {
        setError('โหลด PLO ไม่สำเร็จ')
      } finally {
        if (!quiet) setLoading(false)
      }
    },
    [programId],
  )

  // Reload once when a job that changes this page's data ends, whichever page
  // started it and whichever way it ended: a run that fails part-way has already
  // written rows. A re-check changes one outcome, so it reloads behind the list
  // on screen.
  const watch = useReloadOnJobs(RELOAD_KINDS, (job) => void fetchPlos(job.kind === 'plo_revalidate'))

  // Starting a run only records the job; the PLOs arrive in the table and are
  // read by the reload above when it ends.
  const runSynthesis = useCallback(async () => {
    if (!programId) return
    setStarting(true)
    setError('')
    try {
      const job = await startJob(`/programs/${programId}/plos/run`, {
        note_th: note.trim() || null,
        run_validation: agentWillRun,
      })
      watch(job)
      started(job)
    } catch (err: unknown) {
      const res = (err as { response?: { status?: number; data?: { detail?: string } } })?.response
      setError(res?.data?.detail ?? 'รัน PLO Synthesis ไม่สำเร็จ')
      // A 409 means a job this page has not heard of is running: read the list
      // now so the buttons say so too.
      if (res?.status === 409) void refresh()
    } finally {
      setStarting(false)
    }
  }, [programId, note, agentWillRun, watch, started, refresh])

  const revalidate = useCallback(
    async (ploId: string) => {
      if (!programId) return
      setStarting(true)
      setError('')
      try {
        const job = await startJob(`/programs/${programId}/plos/${ploId}/revalidate`)
        watch(job)
        started(job)
      } catch (err: unknown) {
        const res = (err as { response?: { status?: number; data?: { detail?: string } } })?.response
        setError(res?.data?.detail ?? 'ตรวจ SMART ซ้ำไม่สำเร็จ')
        if (res?.status === 409) void refresh()
      } finally {
        setStarting(false)
      }
    },
    [programId, watch, started, refresh],
  )

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

  // Still synchronous — it is not one of the background jobs — but it is a
  // writer like them, so a 409 here means the program already has one running.
  // The picker and the card's attach control both come through here, so the
  // cards a merge replaces and the page line behave the same for either.
  const submitMerge = async (needIds: string[], mergeNote: string | null) => {
    if (needIds.length < 2 || !programId || busy) return
    setMerging(true)
    // Same rule as the server's: every outcome citing a selected Need goes.
    setMergeFlight({ ids: new Set(plosCiting(plos, needIds).map(p => p.plo_id)), since: clockMs() })
    setError('')
    try {
      await api.post(`/programs/${programId}/plos/from-needs`, {
        need_ids: needIds,
        note_th: mergeNote,
      })
      await fetchPlos()
    } catch (err: unknown) {
      const res = (err as { response?: { status?: number; data?: { detail?: string } } })?.response
      setError(res?.data?.detail ?? 'รวม Need เป็น PLO เดียวไม่สำเร็จ')
      if (res?.status === 409) void refresh()
    } finally {
      setMerging(false)
      setMergeFlight(null)
    }
  }

  /** What a card is waiting on, if anything: its own SMART re-check, or the
   *  merge that will replace it. */
  const pendingOf = (ploId: string): Pending | undefined => {
    if (revalidatingId === ploId && mine) {
      return { label: REVALIDATING_LABEL, since: Date.parse(mine.created_at) }
    }
    if (mergeFlight?.ids.has(ploId)) {
      return { label: 'กำลังร่าง PLO ใหม่แทนข้อนี้', since: mergeFlight.since }
    }
    return undefined
  }

  if (!programId) {
    return (
      <div className="panel mx-auto max-w-2xl border-dashed px-6 py-12 text-center">
        <p className="mb-3 text-pencil">ยังไม่ได้เลือกโปรแกรม</p>
        <Link to="/" className="link">ไปหน้า Intake</Link>
      </div>
    )
  }

  const citedNeedIds = new Set(plos.flatMap(p => p.source_need_ids))
  const unusedNeeds = unusedNeedsOf(needs, citedNeedIds)

  const smartPassCount = plos.filter(p =>
    SMART_KEYS.every(k => p.smart_check[k] === true)
  ).length
  // "SMART ผ่าน 8/10" is misleading when two of the ten were never judged as
  // written, so say how many still need looking at.
  const unjudgedCount = plos.filter(p => needsAttention(p.smart_validated_by)).length

  return (
    <div>
      <div className="mb-6">
        <p className="eyebrow">ขั้นที่ 5</p>
        <h1 className="page-title">สังเคราะห์ PLO</h1>
        <p className="mt-1 text-sm text-pencil">ตรวจสอบและแก้ไข Program Learning Outcomes ที่ AI สังเคราะห์</p>
        <p className="data mt-1 text-xs text-lead">{programId}</p>
      </div>

      {error && (
        <div className="notice notice-error mb-6">{error}</div>
      )}
      {last?.status === 'failed' && (
        <div className="mb-6">
          <RunFailure
            job={last}
            subject={typeof last.params.plo_id === 'string' ? last.params.plo_id : undefined}
          />
        </div>
      )}

      {/* A run in progress comes before the loading line: what a load would
          show is about to be replaced, and a page opened mid-run should say so
          at once rather than after its own read finishes. */}
      {synthesis ? (
        // The plan is what the job was asked to do, not what the checkbox says
        // now: a page opened mid-run has a checkbox nobody touched.
        <RunProgress
          key={synthesis.job_id}
          plan={synthesis.params.run_validation !== false ? PLO_SYNTHESIS_PLAN : PLO_SYNTHESIS_CODE_ONLY_PLAN}
          since={Date.parse(synthesis.created_at)}
        />
      ) : loading ? (
        <LoadingLine />
      ) : plos.length === 0 ? (
        <div className="panel border-dashed px-6 py-12 text-center">
          <p className="font-display mb-1 text-lg text-graphite">ยังไม่มี PLO</p>
          <p className="mb-6 text-sm text-pencil">กดปุ่มด้านล่างเพื่อให้ AI สังเคราะห์ PLO จาก skill clusters</p>
          <div className="mx-auto mb-2 max-w-md">
            <DesignerNote value={note} onChange={setNote} />
            <ValidationToggle checked={runValidation} onChange={setRunValidation} status={validation} />
          </div>
          <button
            onClick={runSynthesis}
            disabled={busy}
            className="btn btn-primary mt-3"
          >
            สังเคราะห์ PLO
          </button>
        </div>
      ) : (
        <>
          <DesignerNote value={note} onChange={setNote} disabled={busy} />
          <div className="mb-4">
            <ValidationToggle
              checked={runValidation}
              onChange={setRunValidation}
              status={validation}
              disabled={busy}
            />
          </div>
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2 text-sm text-pencil">
              <span className="data">{plos.length} PLOs</span>
              <span className={`chip ${smartPassCount === plos.length ? 'chip-stamp' : 'chip-marker'}`}>
                SMART ผ่าน {smartPassCount}/{plos.length}
              </span>
              {unjudgedCount > 0 && (
                <span className="chip chip-marker">
                  ยังไม่ได้ตรวจด้วยผู้ตรวจ {unjudgedCount}
                </span>
              )}
              <button
                onClick={runSynthesis}
                disabled={busy}
                className="btn btn-sm btn-quiet"
              >
                สังเคราะห์ใหม่
              </button>
            </div>
          </div>
          {/* Whatever cards the merge replaces, the call itself takes a while:
              this is the one line that says so, and the one that is announced. */}
          {mergeFlight && (
            <PendingLine
              pending={{ label: 'กำลังร่าง PLO จาก Need ที่เลือก', since: mergeFlight.since }}
              announce
            />
          )}
          <div className="space-y-4">
            {plos.map(p => (
              <PLOCard
                key={p.plo_id}
                plo={p}
                programId={programId}
                onUpdate={handleUpdate}
                busy={busy}
                pending={pendingOf(p.plo_id)}
                onRevalidate={() => revalidate(p.plo_id)}
                unusedNeeds={unusedNeeds}
                onAttach={(needId) => void submitMerge([...p.source_need_ids, needId], null)}
              />
            ))}
          </div>

          <SupersededPlos items={superseded} needs={needs} />

          {needs.length >= 2 && (
            <MergeNeedPicker
              needs={needs}
              plos={plos}
              selected={selected}
              onToggle={toggleNeed}
              note={note}
              busy={busy}
              merging={merging}
              onSubmit={() => void submitMerge([...selected], note.trim() || null).then(() => setSelected(new Set()))}
              flight={mergeFlight && (
                <PendingLine
                  pending={{ label: 'กำลังร่าง PLO จาก Need ที่เลือก', since: mergeFlight.since }}
                  announce
                />
              )}
            />
          )}
        </>
      )}

      {/* The report reads the stored PLOs, so anything drafted is enough to go
          on — including a set carrying escalations, which is exactly what the
          report page is there to show. */}
      <NextStageLink
        from="plo_synthesis"
        ready={Boolean(programId) && plos.length > 0 && mine === null && !merging}
        blockedReason={
          mine !== null || merging
            ? 'รอให้งานที่กำลังทำเสร็จก่อน — รายงานต้องอ่านจาก PLO ชุดนี้'
            : 'ยังไม่มี PLO — รันสังเคราะห์ PLO ก่อน'
        }
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

  if (loading) return <div className="py-4 text-center text-sm text-pencil">กำลังโหลด trace...</div>
  if (error) return <div className="notice notice-error mt-3">{error}</div>
  if (!trace) return null

  const stale = trace.missing_need_ids.length + trace.missing_evidence_ids.length > 0

  return (
    <div className="mt-4 space-y-4 border-t border-hair pt-4">
      {stale && (
        <div className="notice notice-warn">
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
        <h4 className="eyebrow mb-2">
          Needs (<span className="data">{trace.clusters.length}</span>)
        </h4>
        <div className="space-y-2">
          {trace.clusters.map(c => (
            <div key={c.need_id} className="rounded-[3px] border border-hair bg-sunk px-3 py-2.5">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="record text-base">{c.statement_th}</p>
                  {c.statement_en && (
                    <p className="text-xs italic text-pencil">{c.statement_en}</p>
                  )}
                </div>
                <span
                  title={DEMAND_SCORE_TITLE_TH}
                  className="chip chip-neutral data shrink-0 bg-sheet"
                >
                  {demandPercent(c.demand_score)}
                </span>
              </div>
              <p className="mt-1.5 text-xs text-pencil">
                <span className="data">{c.source_evidence_ids.length}</span> evidence · {c.ksec_categories.map(ksecLabel).join(' + ')} · {c.bloom_level}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Evidence */}
      <div>
        <h4 className="eyebrow mb-2">
          Evidence (<span className="data">{trace.evidence.length}</span>)
        </h4>
        <div className="space-y-2">
          {trace.evidence.map(e => (
            <div key={e.evidence_id} className="rounded-[3px] border border-hair bg-sheet px-3 py-2.5">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <span className="text-xs font-medium text-graphite">{e.source_name}</span>
                <span className="text-xs text-pencil">{stakeholderLabel(e.stakeholder_type)}</span>
                <span className={`chip ml-auto ${classStyle(e.classification).cls}`}>
                  {classStyle(e.classification).label}
                </span>
              </div>
              <p className="line-clamp-3 text-xs leading-relaxed text-graphite">{e.raw_text_th}</p>
              {e.classification_rationale_th && (
                <p className="mt-1 text-xs italic text-pencil">{e.classification_rationale_th}</p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

const REVALIDATING_LABEL = 'กำลังตรวจ SMART ใหม่'

/** A card that is waiting on a job: dimmed, its actions off, a sweep line with
 *  the seconds it has waited. `since` is epoch ms. */
interface Pending {
  label: string
  since: number
}

function PendingLine({ pending, announce = false }: { pending: Pending; announce?: boolean }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])
  const since = Number.isFinite(pending.since) ? pending.since : now
  const seconds = Math.max(0, Math.floor((now - since) / 1000))
  return (
    <div className="mb-3" role={announce ? 'status' : undefined} aria-live={announce ? 'polite' : undefined}>
      <div className="relative h-1 overflow-hidden rounded-[2px] bg-sunk ring-1 ring-hair ring-inset">
        <span className="animate-run-sweep absolute inset-y-0 left-0 w-1/3 bg-gradient-to-r from-transparent via-stamp/25 to-transparent" />
      </div>
      <p className="mt-1 text-xs text-pencil">
        {pending.label} · <span className="data tabular-nums">{seconds}</span> วินาที
      </p>
    </div>
  )
}

function PLOCard({
  plo: p,
  programId,
  onUpdate,
  busy,
  pending,
  onRevalidate,
  unusedNeeds,
  onAttach,
}: {
  unusedNeeds: PickerNeed[]
  /** Redraft this outcome from its Needs plus the chosen one. */
  onAttach: (needId: string) => void
  plo: PLO
  programId: string
  onUpdate: (plo: PLO) => void
  /** The program has a writer running, whatever it is; nothing here may start another. */
  busy: boolean
  /** A job concerning *this* outcome is running: its SMART re-check, or the
   *  merge that will replace it. */
  pending?: Pending
  onRevalidate: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<PLO>(p)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [traceOpen, setTraceOpen] = useState(false)
  const [attachOpen, setAttachOpen] = useState(false)

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
  // Presentation only: which ink a failed criterion takes. A hard failure is
  // mandate red and a soft verdict is marker, so a set of soft flags does not
  // read like an escalation. Finding codes lead with their SMART letter.
  const hardFailed = p.smart_escalated || hardFindings.length > 0
  const hardLetters = new Set(hardFindings.map(f => f.criterion.charAt(0)))

  return (
    <div
      className={`panel p-4 sm:p-5 ${
        p.smart_escalated ? 'border-mandate border-l-4' : ''
      } ${pending ? 'opacity-60' : ''}`}
      aria-busy={pending ? true : undefined}
    >
      {pending && <PendingLine pending={pending} announce={pending.label === REVALIDATING_LABEL} />}
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <span className="data text-sm font-semibold text-graphite">
              {p.plo_id}
            </span>
            <span className="chip chip-neutral">
              {BLOOM_LABEL[p.bloom_level] ?? p.bloom_level}
            </span>
            <span className={`chip ${
              smartPassed ? 'chip-stamp' : hardFailed ? 'chip-mandate' : 'chip-marker'
            }`}>
              SMART {smartPassed ? '✓' : '✗'}
            </span>
            {/* Every outcome says which kind it is, not only the supplementary
                ones. A core PLO used to carry no badge at all, so "หลัก" read as
                a missing label rather than as the answer — and the two kinds are
                counted against different rules (only core PLOs sit inside the
                6-10 band), which is the first thing a designer checks. */}
            <span
              className={`chip ${
                p.is_optional
                  ? 'border border-dashed border-hair-strong bg-sheet text-pencil'
                  : 'chip-neutral font-semibold text-graphite'
              }`}
            >
              {p.is_optional ? 'เสริม' : 'หลัก'}
            </span>
            {p.smart_escalated && (
              <span className="chip bg-mandate font-semibold whitespace-normal text-sheet">
                ไม่ผ่าน SMART หลังแก้ {p.smart_retry_count} รอบ — ต้องแก้ด้วยมือ
              </span>
            )}
            {/* Provenance, not decoration: "the validator judged this and it
                failed" and "no validator has judged this as written" are
                different facts, and without this the page would attribute a
                diagnosis to something that never ran. */}
            {/* code_only covers three different causes — this run skipped the
                agent, .env disables it, the endpoint failed — and only the
                diagnosis says which, so the badge quotes it instead of guessing. */}
            {p.smart_validated_by === 'code_only' ? (
              <span
                className="chip chip-marker cursor-help"
                title={p.smart_diagnosis_th ?? VALIDATED_BY_TH.code_only}
              >
                ไม่ได้ตรวจ
              </span>
            ) : (
              needsAttention(p.smart_validated_by) && (
                <span className="chip chip-marker whitespace-normal">
                  {VALIDATED_BY_TH[p.smart_validated_by]}
                </span>
              )
            )}
          </div>
          {/* The soft findings carry a reason each; the flat flag list is the
              fallback for rows written before findings existed. */}
          {softFindings.length > 0 ? (
            <div className="mt-1 mb-2 space-y-1">
              {softFindings.map(f => (
                <p key={f.criterion} className="notice notice-warn py-1.5 text-xs">
                  <span className="font-medium">{findingLabel(f.criterion)}</span>
                  {f.note_th && <span> — {f.note_th}</span>}
                </p>
              ))}
            </div>
          ) : p.soft_flags?.length > 0 ? (
            <div className="mt-1 mb-2 flex flex-wrap gap-1">
              {p.soft_flags.map(f => (
                <span key={f} className="chip chip-marker">
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
              disabled={Boolean(pending)}
              saveError={saveError}
              onSave={handleSave}
              onCancel={() => { setEditing(false); setDraft(p); setSaveError('') }}
            />
          ) : (
            <div>
              <p className="record">{p.statement_th}</p>
              {p.statement_en && (
                <p className="mt-1 text-sm italic text-pencil">{p.statement_en}</p>
              )}
              <div className="mt-2 text-sm text-pencil">
                <span className="font-medium text-graphite">กริยา:</span>{' '}
                <span className="rounded-[2px] bg-sunk px-1.5 py-0.5 text-graphite ring-1 ring-hair ring-inset">{p.action_verb_th}</span>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-pencil">{p.rationale_th}</p>
              {p.distinctive_feature_th && (
                <p className="mt-1 text-sm text-graphite">
                  <span className="font-medium">จุดเด่น:</span> {p.distinctive_feature_th}
                </p>
              )}
            </div>
          )}
        </div>

        {!editing && (
          <div className="flex shrink-0 flex-row flex-wrap gap-1.5 sm:flex-col">
            <button
              onClick={() => setEditing(true)}
              disabled={Boolean(pending)}
              className="btn btn-sm btn-secondary"
            >
              แก้ไข
            </button>
            {/* Without this the `stale` state is a dead end: PUT deliberately
                does not re-run the gate, so this is how an edited statement
                gets a verdict. It is a background job: the page owns starting
                it, and says which outcome's re-check is the one running. */}
            <button
              onClick={onRevalidate}
              disabled={busy}
              className="btn btn-sm btn-secondary"
            >
              {pending?.label === REVALIDATING_LABEL ? 'กำลังตรวจ...' : 'ตรวจ SMART ซ้ำ'}
            </button>
            <AttachButton
              blocked={attachBlockedReason(p.source_need_ids.length, unusedNeeds)}
              busy={busy || Boolean(pending)}
              onOpen={() => setAttachOpen(true)}
            />
          </div>
        )}
      </div>

      {attachOpen && !editing && (
        <AttachPanel
          unused={unusedNeeds}
          busy={busy || Boolean(pending)}
          onAttach={onAttach}
          onClose={() => setAttachOpen(false)}
        />
      )}

      {/* SMART check */}
      {!editing && (
        <div className="mt-4">
          <div className="flex gap-2 flex-wrap">
            {SMART_KEYS.map(k => (
              <span
                key={k}
                className={`chip px-2 py-0.5 ${
                  p.smart_check[k] === true
                    ? 'chip-stamp'
                    : hardLetters.has(k.charAt(0).toUpperCase())
                      ? 'chip-mandate'
                      : 'chip-marker'
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
                <p key={f.criterion} className="notice notice-error py-1.5 text-xs">
                  <span className="font-semibold">{findingLabel(f.criterion)}</span>
                  {f.note_th && <span> — {f.note_th}</span>}
                </p>
              ))}
            </div>
          )}
          {/* The instruction a designer acts on, so it gets its own block. */}
          {p.smart_diagnosis_th && (
            <div className="notice notice-warn mt-2">
              {/* A code_only diagnosis is the reason nothing judged this, not
                  a judgement — titled as one, it reads as the agent's opinion. */}
              <p className="mb-0.5 text-xs font-semibold">
                {p.smart_validated_by === 'code_only'
                  ? 'ตรวจด้วยกฎพื้นฐานเท่านั้น'
                  : 'ข้อวินิจฉัยจากผู้ตรวจ SMART'}
              </p>
              <p className="text-xs leading-relaxed">{p.smart_diagnosis_th}</p>
            </div>
          )}
          {!p.smart_diagnosis_th && p.smart_check.notes_th && (
            <p className="notice notice-warn mt-2 text-xs">
              {p.smart_check.notes_th}
            </p>
          )}
        </div>
      )}

      {/* Footer meta + trace toggle */}
      {!editing && (
        <>
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-hair pt-3 text-xs text-pencil">
            <span className="data">{p.source_need_ids.length} needs</span>
            <span className="data">{p.source_evidence_ids.length} evidence</span>
            <button
              onClick={() => setTraceOpen(v => !v)}
              aria-expanded={traceOpen}
              className="btn btn-sm btn-quiet ml-auto text-stamp"
            >
              {traceOpen ? '▲ ซ่อน Trace' : '▼ ดู Trace'}
            </button>
            <span className="data text-lead">v{p.version}</span>
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
  disabled,
  saveError,
  onSave,
  onCancel,
}: {
  draft: PLO
  setDraft: React.Dispatch<React.SetStateAction<PLO>>
  saving: boolean
  /** A job is working on this outcome: nothing here may be saved meanwhile. */
  disabled: boolean
  saveError: string
  onSave: () => void
  onCancel: () => void
}) {
  return (
    <div className="space-y-3 mt-1">
      <div>
        <label className="field-label">
          Statement (Thai) <span className="text-mandate">*</span>
        </label>
        <textarea
          className="input record resize-none"
          disabled={disabled}
          rows={3}
          value={draft.statement_th}
          onChange={e => setDraft(d => ({ ...d, statement_th: e.target.value }))}
        />
        <p className="field-hint">ห้ามใช้คำ: รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก</p>
      </div>
      <div>
        <label className="field-label">Action Verb (Thai)</label>
        <input
          className="input"
          disabled={disabled}
          value={draft.action_verb_th}
          onChange={e => setDraft(d => ({ ...d, action_verb_th: e.target.value }))}
        />
      </div>
      <div>
        <label className="field-label">Rationale (Thai)</label>
        <textarea
          className="input resize-none"
          disabled={disabled}
          rows={2}
          value={draft.rationale_th}
          onChange={e => setDraft(d => ({ ...d, rationale_th: e.target.value }))}
        />
      </div>
      {saveError && (
        <p className="notice notice-error text-xs">
          {saveError}
        </p>
      )}
      <div className="flex flex-wrap gap-2 pt-1">
        <button
          onClick={onSave}
          disabled={saving || disabled}
          className="btn btn-sm btn-primary"
        >
          {saving ? 'กำลังบันทึก...' : 'บันทึก'}
        </button>
        <button
          onClick={onCancel}
          className="btn btn-sm btn-secondary"
        >
          ยกเลิก
        </button>
      </div>
    </div>
  )
}
