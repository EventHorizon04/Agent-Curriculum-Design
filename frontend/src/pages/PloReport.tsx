import { useState, useEffect, useCallback, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useProgram } from '../hooks/useProgram'
import { useReloadOnJobs } from '../hooks/useReloadOnJobs'
import { LoadingLine } from '../components/RunProgress'
import api from '../api/client'
import type { JobKind } from '../api/jobs'
import { ksecLabel, stakeholderLabel, classStyle, isRequirementStakeholder } from '../constants/stakeholder'
import { VALIDATED_BY_TH, findingLabel, needsAttention } from '../constants/smart'
import { DEMAND_SCORE_TITLE_TH, demandPercent } from '../constants/demand'
import type { ScopeVerdict } from '../constants/scope'
import { SCOPE_REASON_TH, scopeCountsTh, scopeVerdict } from '../constants/scope'
import { MAX_CORE_PLOS, MIN_CORE_PLOS } from '../constants/needPolicy'
import { BLOOM_LABEL } from '../constants/bloom'
import type { PLO } from '../types/plo'

/** `/needs/` returns whole Needs; the report only reads these fields, and the
 *  unused-Need list needs the statement to be worth showing at all. */
interface NeedSummary {
  need_id: string
  statement_th?: string
  ksec_categories: string[]
  demand_score?: number
  /** Members that passed each scope axis. Absent on the report's own
   *  needs_by_id payload for older rows; treated as "passed" when missing, the
   *  same default the model and the migration use. */
  in_field_skill_count?: number
  graduate_capability_skill_count?: number
  member_skill_ids?: string[]
  source_stakeholder_types?: string[]
}

/** Why a Need produced no PLO.
 *
 *  The scope part is `scopeVerdict`, shared with the need_combination checkpoint
 *  so the two pages cannot disagree about which Needs survive. The demand part
 *  is this page's alone: only the report knows a Need went uncited, so only here
 *  does "in scope and still unused" mean it lost on the ceiling. */
type ExclusionReason = Exclude<ScopeVerdict, 'in_scope'> | 'lost_on_demand'

function exclusionReason(n: NeedSummary): ExclusionReason {
  const verdict = scopeVerdict(n)
  return verdict === 'in_scope' ? 'lost_on_demand' : verdict
}

/** A Need the designer excluded at the Need stage (`report.needs_excluded`). */
interface ExcludedNeed {
  need_id: string
  statement_th: string
  ksec_categories: string[]
  demand_score?: number
  /** ISO string. */
  excluded_at: string | null
}

interface ReportCounts {
  total: number
  core: number
  optional: number
  escalated: number
  /** Hand-edited since it was last judged. */
  stale: number
  /** The pure checks decided alone because the validator could not run. */
  code_only: number
}

/** The jobs that change what this page draws, whichever page started them: the
 *  stored report is written by the approval run, and a synthesis, a review's
 *  send-back, a re-check or a new set of Needs leave it older than the set. */
const RELOAD_KINDS: JobKind[] = [
  'plo_report',
  'plo_synthesis',
  'plo_review',
  'plo_revalidate',
  'needs_pipeline',
  'skill_extraction',
  'need_combination',
]

interface TraceNeed {
  need_id: string
  statement_th: string
  statement_en: string | null
  /** The model's account of why these skills are one demand. Shown under the
   *  statement and labelled as such — the evidence count beside it is the trail;
   *  this is not. Optional: rows predating the field carry "". */
  rationale_th?: string
  ksec_categories: string[]
  bloom_level: string
  demand_score: number
  source_evidence_ids: string[]
}

interface TraceEvidence {
  evidence_id: string
  source_name: string
  stakeholder_type: string
  classification: string
  raw_text_th: string
}

interface TraceSkill {
  skill_id: string
  skill_name_th: string
  evidence_span_th: string
  is_field_relevant: boolean
  is_graduate_capability: boolean
}

/** `/needs/{id}/trace` — only the members are read here; the evidence rows it
 *  also returns are already quoted through each skill's span. */
interface NeedTraceResponse {
  skills: TraceSkill[]
}

/** `GET /plos/report`: the report stored when the designer approved the set. */
interface StoredReportResponse {
  report: {
    plos: PLO[]
    needs_by_id: Record<string, NeedSummary>
    /** Absent on a report stored before the excluded list existed. */
    needs_excluded?: ExcludedNeed[]
  } | null
  /** The PLOs or Needs changed after the report was stored. */
  stale: boolean
  created_at: string | null
}

interface PLOTrace {
  plo: PLO
  clusters: TraceNeed[]
  evidence: TraceEvidence[]
}

/** The band is the policy a curriculum is judged against, so the page states it
 *  rather than implying it. Shared with the need_combination checkpoint, which
 *  reports the same bounds one stage earlier — see constants/needPolicy.ts. */
const MIN_CORE = MIN_CORE_PLOS
const MAX_CORE = MAX_CORE_PLOS
/** Two past the ceiling, so a set that overshoots still lands on the scale. */
const BAND_SCALE = 12

function countsFrom(plos: PLO[]): ReportCounts {
  const core = plos.filter((p) => !p.is_optional).length
  return {
    total: plos.length,
    core,
    optional: plos.length - core,
    escalated: plos.filter((p) => p.smart_escalated).length,
    stale: plos.filter((p) => p.smart_validated_by === 'stale').length,
    code_only: plos.filter((p) => p.smart_validated_by === 'code_only').length,
  }
}

/** A hairline tag. The letter is the code — K, S, EC carry their own meaning and
 *  a colour per category would only add five hues that mean nothing to a reader
 *  who has not memorised the key. Colour on a tag means "mandate" alone. */
function Tag({
  children,
  mono = false,
  tone = 'plain',
}: {
  children: React.ReactNode
  mono?: boolean
  // `mandate` is the record's red — reserved for what the designer has to read,
  // not for anything merely notable.
  tone?: 'plain' | 'mandate'
}) {
  const toned = tone === 'mandate' ? 'chip-mandate' : 'chip-neutral'
  return <span className={`chip ${toned} ${mono ? 'data' : ''}`}>{children}</span>
}

/**
 * The set against its policy band — the one measure a curriculum designer is
 * held to, and the thing the whole pipeline spends its effort enforcing. Drawn
 * as a range with a floor and a ceiling rather than a number in a tile, because
 * the question is never "how many" but "are we inside the band".
 */
function PolicyBand({ core, optional }: { core: number; optional: number }) {
  const pct = (n: number) => `${Math.min((n / BAND_SCALE) * 100, 100)}%`
  const short = core < MIN_CORE
  const over = core > MAX_CORE
  const outside = short || over

  return (
    <section className="panel px-5 py-5" aria-labelledby="band-heading">
      <h2 id="band-heading" className="eyebrow">
        PLO หลัก
      </h2>

      <p className="mt-1 flex flex-wrap items-baseline gap-2">
        <span className={`data text-3xl leading-none ${outside ? 'text-mandate' : 'text-graphite'}`}>
          {core}
        </span>
        <span className="text-sm text-pencil">
          {outside ? (
            <span className="font-medium text-mandate">
              {short
                ? `ต่ำกว่าเกณฑ์ ${MIN_CORE} ข้อ — เพิ่มอีก ${MIN_CORE - core} ข้อ`
                : `เกินจำนวนสูงสุด ${MAX_CORE} ข้อ`}
            </span>
          ) : (
            `อยู่ในเกณฑ์ ${MIN_CORE}–${MAX_CORE} ข้อ`
          )}
        </span>
      </p>

      <div className="relative mt-4 h-8 max-w-md" aria-hidden="true">
        {/* Full scale, then the legal band drawn on top of it. */}
        <span className="absolute top-3 h-px w-full bg-hair-strong" />
        <span
          className="absolute top-[11px] h-[3px] bg-stamp"
          style={{ left: pct(MIN_CORE), width: pct(MAX_CORE - MIN_CORE) }}
        />
        {[MIN_CORE, MAX_CORE].map((n) => (
          <span key={n} className="absolute top-0" style={{ left: pct(n) }}>
            <span className="block h-6 w-px -translate-x-1/2 bg-hair-strong" />
            <span className="data absolute left-0 top-6 -translate-x-1/2 text-[0.6875rem] text-lead">
              {n}
            </span>
          </span>
        ))}
        <span
          className={`absolute top-3 block h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rotate-45 ${
            outside ? 'bg-mandate' : 'bg-stamp-deep'
          }`}
          style={{ left: pct(core) }}
        />
      </div>

      {optional > 0 && (
        <p className="mt-2 text-xs text-pencil">
          อีก {optional} ข้อเป็น PLO เสริม ซึ่งอยู่นอกเกณฑ์นี้
        </p>
      )}
    </section>
  )
}

export default function PloReport() {
  const { programId } = useProgram()
  const [plos, setPlos] = useState<PLO[]>([])
  const [needsById, setNeedsById] = useState<Record<string, NeedSummary>>({})
  const [counts, setCounts] = useState<ReportCounts>({
    total: 0,
    core: 0,
    optional: 0,
    escalated: 0,
    stale: 0,
    code_only: 0,
  })
  // Derived, not read off a response: the counts come from the stored PLOs the
  // page loaded, so a count only one source set would read as "nothing was cut"
  // on the other. Same rule the report stage applies server-side.
  const unusedNeeds = useMemo(() => {
    const cited = new Set(plos.flatMap((p) => p.source_need_ids))
    return Object.values(needsById).filter((n) => !cited.has(n.need_id))
  }, [plos, needsById])
  const [excludedNeeds, setExcludedNeeds] = useState<ExcludedNeed[]>([])
  const [hasReport, setHasReport] = useState(false)
  const [stale, setStale] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    if (!programId) return
    setLoading(true)
    setError('')
    try {
      const res = await api.get<StoredReportResponse>(`/programs/${programId}/plos/report`)
      const { report, stale: isStale } = res.data
      setHasReport(report !== null)
      setStale(report !== null && isStale)
      setPlos(report?.plos ?? [])
      setNeedsById(report?.needs_by_id ?? {})
      setExcludedNeeds(report?.needs_excluded ?? [])
      setCounts(countsFrom(report?.plos ?? []))
    } catch {
      setError('โหลดข้อมูลไม่สำเร็จ ตรวจว่า API ทำงานอยู่ แล้วลองใหม่')
    } finally {
      setLoading(false)
    }
  }, [programId])

  // Reload once when a job that changes this page's data ends, whichever page
  // started it and whichever way it ended.
  useReloadOnJobs(RELOAD_KINDS, () => void fetchData())

  // Fetched as a blob through the api client rather than linked with a plain
  // anchor, so a 422 or 501 surfaces as an error message here instead of
  // navigating the designer to a raw JSON body.
  const exportMatrix = useCallback(async () => {
    if (!programId) return
    setExporting(true)
    setError('')
    try {
      const res = await api.get(`/programs/${programId}/plos/export/matrix.xlsx`, {
        responseType: 'blob',
      })
      const url = URL.createObjectURL(res.data as Blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `plo-matrix-${programId}.xlsx`
      link.click()
      URL.revokeObjectURL(url)
    } catch {
      setError('ส่งออก Excel ไม่สำเร็จ')
    } finally {
      setExporting(false)
    }
  }, [programId])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  if (!programId) {
    return (
      <div className="py-16 text-center">
        <p className="mb-3 text-pencil">ยังไม่ได้เลือกหลักสูตร</p>
        <Link to="/" className="link">
          เลือกจากรายการหลักสูตร
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <header>
        <p className="eyebrow">ขั้นที่ 7</p>
        <h1 className="page-title">รายงาน PLO</h1>
        <p className="mt-1 text-sm text-pencil">
          ชุด PLO ที่อนุมัติแล้ว พร้อมที่มาของแต่ละข้อ — ตรวจให้ครบก่อนส่งออก
        </p>
      </header>

      {error && <p className="notice notice-error">{error}</p>}
      {hasReport && stale && (
        <p className="notice notice-warn">
          รายงานนี้จัดทำจากชุด PLO ก่อนหน้า — PLO หรือ Need เปลี่ยนหลังอนุมัติ กลับไปตรวจและอนุมัติใหม่เพื่อให้ตรงกับชุดปัจจุบัน{' '}
          <Link to="/plo-review" className="link">
            ไปหน้าตรวจคุณภาพ
          </Link>
        </p>
      )}

      {loading && !hasReport ? (
        <LoadingLine />
      ) : !hasReport ? (
        <div className="panel px-6 py-12 text-center">
          <p className="record text-lg">ยังไม่ได้อนุมัติชุด PLO</p>
          <p className="mx-auto mt-2 max-w-md text-sm text-pencil">
            รายงานเก็บเมื่อผู้ออกแบบอนุมัติชุด PLO ที่ขั้นตรวจคุณภาพ
          </p>
          <div className="mt-5">
            <Link to="/plo-review" className="link text-sm">
              ไปตรวจคุณภาพชุด PLO
            </Link>
          </div>
        </div>
      ) : (
        <>
          <PolicyBand core={counts.core} optional={counts.optional} />

          {/* Only what needs acting on. The set's size is the band's job, and
              repeating it here as a total would be the third place it appears. */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
            {counts.escalated > 0 && (
              <span className="chip chip-mandate">
                <span className="data">{counts.escalated}</span> ข้อไม่ผ่าน SMART
              </span>
            )}
            {counts.stale + counts.code_only > 0 && (
              <span className="chip chip-marker">
                <span className="data">{counts.stale + counts.code_only}</span> ข้อยังไม่ได้ตรวจตามข้อความปัจจุบัน
              </span>
            )}
            {unusedNeeds.length > 0 && (
              <a href="#unused-needs" className="link text-sm">
                <span className="data">{unusedNeeds.length}</span> Need ไม่ได้ใช้
              </a>
            )}

            <div className="ml-auto flex flex-wrap items-center gap-2">
              <button
                onClick={exportMatrix}
                disabled={exporting}
                className="btn btn-primary btn-sm"
              >
                {exporting ? 'กำลังส่งออก…' : 'ส่งออก Excel'}
              </button>
            </div>
          </div>

          <ol className="panel divide-y divide-hair">
            {plos.map((p) => (
              <PloRow key={p.plo_id} plo={p} programId={programId} needsById={needsById} />
            ))}
          </ol>

          {/* The CHECO and มคอ.2 exporters are stubs whose routes answer 501.
              Named as not-yet-available rather than rendered as dead buttons, so
              the designer plans around them instead of clicking to find out. */}
          <p className="text-xs text-lead">
            ส่งออก CHECO และ มคอ.2 ยังไม่เปิดใช้
          </p>

          {unusedNeeds.length > 0 && <UnusedNeeds needs={unusedNeeds} programId={programId} />}
          {excludedNeeds.length > 0 && <ExcludedNeeds needs={excludedNeeds} />}

          <p className="border-t border-hair pt-4 text-sm text-pencil">
            <Link to="/plo-review" className="link">
              ← กลับไปหน้าตรวจคุณภาพชุด PLO
            </Link>
          </p>
        </>
      )}
    </div>
  )
}

/**
 * Needs that produced no PLO — the ones below the ceiling cut, plus any whose
 * synthesis failed. Listed rather than counted: a demand the market raised and
 * the program did not answer is a decision the designer should make knowingly.
 */
function UnusedNeeds({ needs, programId }: { needs: NeedSummary[]; programId: string }) {
  // One list, ordered by demand, with the reason carried per row rather than by
  // grouping. Separate sections per reason read worse than they sound: the two
  // scope axes agree on nearly every Need, so an "off-field" heading and a "not a
  // graduate capability" heading would list the same rows twice.
  const ordered = [...needs].sort((a, b) => (b.demand_score ?? 0) - (a.demand_score ?? 0))
  const guarded = ordered.filter((n) => exclusionReason(n) !== 'lost_on_demand')

  return (
    <section id="unused-needs" className="border-t border-hair pt-5">
      <h2 className="section-title">Need ที่ไม่ได้เป็น PLO</h2>
      <p className="mt-1 text-sm text-pencil">
        PLO หลักมีได้ไม่เกิน {MAX_CORE} ข้อ เลือกจาก demand score สูงสุด — Need เหล่านี้ยังเก็บไว้
        พร้อมหลักฐานเดิม แต่ไม่ได้ถูกแปลงเป็นผลลัพธ์การเรียนรู้
      </p>
      <ul className="mt-3 divide-y divide-hair rounded-[4px] border border-hair bg-sunk">
        {ordered.map((n) => (
          <UnusedNeedRow key={n.need_id} need={n} programId={programId} />
        ))}
      </ul>

      {guarded.length > 0 && <ScopeRerunNote count={guarded.length} />}
    </section>
  )
}

/** Needs the designer cut at the Need stage. Kept apart from the unused ones:
 *  those lost on demand or to the scope guard, these were removed by a person. */
function ExcludedNeeds({ needs }: { needs: ExcludedNeed[] }) {
  return (
    <section id="excluded-needs" className="border-t border-hair pt-5">
      <h2 className="section-title">Need ที่ผู้ออกแบบตัดออก</h2>
      <p className="mt-1 text-sm text-pencil">ตัดออกที่ขั้นวิเคราะห์ Need — กู้คืนได้ที่หน้า Need</p>
      <ul className="mt-3 divide-y divide-hair rounded-[4px] border border-hair bg-sunk">
        {needs.map((n) => (
          <li key={n.need_id} className="flex items-baseline gap-3 px-4 py-2.5 text-sm">
            <span className="data shrink-0 text-xs text-lead">{n.need_id}</span>
            <span className="min-w-0 flex-1 text-pencil">{n.statement_th}</span>
            <span className="shrink-0 text-xs text-lead">
              {n.ksec_categories.map(ksecLabel).join(' + ')}
            </span>
            {n.excluded_at && (
              <span className="data shrink-0 text-xs text-lead">
                {new Date(n.excluded_at).toLocaleDateString('th-TH')}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

function UnusedNeedRow({ need: n, programId }: { need: NeedSummary; programId: string }) {
  const [open, setOpen] = useState(false)
  const reason = exclusionReason(n)
  const guarded = reason !== 'lost_on_demand'
  const total = n.member_skill_ids?.length
  const passed =
    reason === 'not_graduate' ? n.graduate_capability_skill_count : n.in_field_skill_count
  // A mandate the guard filtered anyway. `classification` never reaches the
  // filter, so a professional council's requirement is dropped on the model's
  // word like anything else — worth seeing before the set is approved.
  const mandated = guarded && n.source_stakeholder_types?.includes('professional_council')

  return (
    <li className="px-4 py-2.5">
      <div className="flex items-baseline gap-3 text-sm">
        <span className="data shrink-0 text-xs text-lead">{n.need_id}</span>
        <span className="min-w-0 flex-1 text-pencil">{n.statement_th ?? '—'}</span>
        {n.demand_score !== undefined && (
          <span className="data shrink-0 text-xs text-pencil" title={DEMAND_SCORE_TITLE_TH}>
            {demandPercent(n.demand_score)}
          </span>
        )}
      </div>

      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        {guarded ? (
          <>
            <Tag tone="mandate">{SCOPE_REASON_TH[reason]}</Tag>
            {mandated && <Tag tone="mandate">สภาวิชาชีพระบุไว้</Tag>}
            {total !== undefined && passed !== undefined && (
              <span className="data text-xs text-pencil" title={scopeCountsTh(n)}>
                สมาชิกผ่าน {passed}/{total}
              </span>
            )}
            {/* Scanning the chips is enough to sort the list; deciding whether the
                model read it wrong needs the skill names that got it filtered,
                which is why they are a click away rather than always on. */}
            <button
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              className="link text-xs"
            >
              {open ? 'ซ่อนทักษะที่ทำให้ถูกกัน' : 'ดูทักษะที่ทำให้ถูกกัน'}
            </button>
          </>
        ) : (
          <span
            title={`ผ่านเกณฑ์ขอบเขตแล้ว แต่ demand score ต่ำกว่า Need ${MAX_CORE_PLOS} ข้อที่ถูกเลือกไปเขียนเป็น PLO หลัก — ยังเลือกไปรวมเป็น PLO ได้ที่หน้าสังเคราะห์ PLO`}
          >
            <Tag>ไม่ติด {MAX_CORE_PLOS} อันดับแรก</Tag>
          </span>
        )}
      </div>

      {open && <GuardedNeedDetail programId={programId} needId={n.need_id} />}
    </li>
  )
}

/** The members and the quoted evidence behind one filtered Need, fetched on
 *  demand — most rows in this list are never opened. */
function GuardedNeedDetail({ programId, needId }: { programId: string; needId: string }) {
  const [trace, setTrace] = useState<NeedTraceResponse | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .get<NeedTraceResponse>(`/programs/${programId}/needs/${needId}/trace`)
      .then((r) => setTrace(r.data))
      .catch(() => setError('โหลดทักษะไม่สำเร็จ ลองเปิดใหม่อีกครั้ง'))
  }, [programId, needId])

  if (error) return <p className="mt-2 text-xs text-mandate">{error}</p>
  if (!trace) return <p className="mt-2 text-xs text-lead">กำลังโหลด…</p>

  return (
    <ul className="mt-2 space-y-2 border-l-2 border-hair-strong pl-3">
      {trace.skills.map((s) => (
        <li key={s.skill_id} className="text-xs">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-graphite">{s.skill_name_th}</span>
            {!s.is_field_relevant && <span className="text-mandate">นอกสาขา</span>}
            {!s.is_graduate_capability && <span className="text-mandate">ไม่ใช่สมรรถนะบัณฑิต</span>}
          </div>
          <p className="record mt-0.5 text-sm">
            “<span className="marker">{s.evidence_span_th}</span>”
          </p>
        </li>
      ))}
    </ul>
  )
}

/** Shown once per page, not once per row: editing the scope statement re-runs
 *  the whole program, so repeating it beside every filtered Need would be the
 *  same instruction n times. */
function ScopeRerunNote({ count }: { count: number }) {
  return (
    <div className="notice notice-warn mt-4">
      <p>
        <span className="data">{count}</span> Need ถูกกันเพราะอยู่นอกขอบเขตของหลักสูตร
        ทุกใบยังเก็บไว้ครบและกู้กลับได้
      </p>
      <p className="mt-1.5">
        <span className="font-medium">ถ้าตัดสินผิด:</span> แก้ “ขอบเขตของหลักสูตร” ที่หน้า{' '}
        <Link to="/intake" className="link">
          Intake
        </Link>{' '}
        แล้วรัน <span className="font-medium">สกัดทักษะ</span> ใหม่ทั้งโปรแกรม — Need
        จะถูกสร้างใหม่ตามไปเอง (ระบบไม่รันให้เอง ทุกขั้นต้องผ่านการอนุมัติ)
      </p>
      <p className="mt-1.5">
        <span className="font-medium">ถ้าตัดสินถูกแต่ยังอยากได้:</span> เลือกมันที่หน้า{' '}
        <Link to="/plo-synthesis" className="link">
          PLO Synthesis
        </Link>{' '}
        แล้วกด “รวมเป็น PLO เดียว” — ตรงนั้นไม่กัน
      </p>
    </div>
  )
}

function PloRow({
  plo: p,
  programId,
  needsById,
}: {
  plo: PLO
  programId: string
  needsById: Record<string, NeedSummary>
}) {
  const [traceOpen, setTraceOpen] = useState(false)

  const ksecTags = [
    ...new Set(
      p.source_need_ids.flatMap((id) => needsById[id]?.ksec_categories ?? [])
    ),
  ]

  const findings = p.smart_check?.findings ?? []
  const hardFindings = findings.filter((f) => f.severity === 'hard')
  const softFindings = findings.filter((f) => f.severity === 'soft')

  return (
    <li
      className={`px-4 py-5 sm:px-5 ${p.smart_escalated ? 'border-l-[3px] border-l-mandate' : ''}`}
    >
      <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:gap-3">
        <span
          className={`data w-16 shrink-0 text-sm font-semibold ${
            p.smart_escalated ? 'text-mandate' : 'text-stamp'
          }`}
        >
          {p.plo_id}
        </span>
        <div className="min-w-0 flex-1">
          {/* The statement is the record — the sentence that ends up in มคอ.2 —
              so it is the one thing on this page set in the document's voice. */}
          <p className="record">{p.statement_th}</p>
          {p.statement_en && <p className="mt-1 text-sm text-lead">{p.statement_en}</p>}

          {p.smart_escalated && (
            <p className="notice notice-error mt-2 font-medium">
              ไม่ผ่าน SMART หลังแก้อัตโนมัติ {p.smart_retry_count} รอบ — ต้องแก้ข้อความเอง
              {hardFindings.length > 0 && (
                <span className="mt-0.5 block text-[0.8125rem] font-normal">
                  {hardFindings.map((f) => findingLabel(f.criterion)).join(' · ')}
                </span>
              )}
            </p>
          )}

          {needsAttention(p.smart_validated_by) && (
            <p className="notice notice-warn mt-2">{VALIDATED_BY_TH[p.smart_validated_by]}</p>
          )}

          {/* The reason per criterion, with the flat flag list as the fallback
              for rows written before findings existed. */}
          {softFindings.length > 0 ? (
            <ul className="mt-2 space-y-1">
              {softFindings.map((f) => (
                <li key={f.criterion} className="text-sm text-marker-ink">
                  <span className="chip chip-marker mr-1.5">ข้อสังเกต</span>
                  {findingLabel(f.criterion)}
                  {f.note_th && <span className="text-pencil"> · {f.note_th}</span>}
                </li>
              ))}
            </ul>
          ) : p.soft_flags.length > 0 ? (
            <ul className="mt-2 space-y-1">
              {p.soft_flags.map((f) => (
                <li key={f} className="text-sm text-marker-ink">
                  <span className="chip chip-marker mr-1.5">ข้อสังเกต</span>
                  {findingLabel(f)}
                </li>
              ))}
            </ul>
          ) : null}

          {p.smart_diagnosis_th && (
            <p className="mt-2 border-l-2 border-hair-strong bg-sunk px-3 py-1.5 text-sm text-pencil">
              <span className="font-medium text-graphite">ข้อวินิจฉัย</span> — {p.smart_diagnosis_th}
            </p>
          )}

          {p.rationale_th && <p className="mt-2 text-sm text-pencil">{p.rationale_th}</p>}

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Tag mono>{BLOOM_LABEL[p.bloom_level] ?? p.bloom_level}</Tag>
            {ksecTags.map((cat) => (
              <Tag key={cat}>{ksecLabel(cat)}</Tag>
            ))}
            {/* Shown for both kinds: the band above counts core PLOs only, so
                which kind an outcome is belongs on the outcome, not just in the
                count. */}
            <Tag>{p.is_optional ? 'เสริม' : 'หลัก'}</Tag>
            <button
              onClick={() => setTraceOpen((v) => !v)}
              aria-expanded={traceOpen}
              className="btn btn-quiet btn-sm ml-auto"
            >
              {traceOpen
                ? 'ซ่อนที่มา'
                : `ดูที่มา · ${p.source_need_ids.length} Need`}
            </button>
          </div>

          {traceOpen && <TracePanel programId={programId} ploId={p.plo_id} />}
        </div>
      </div>
    </li>
  )
}

/**
 * The evidence chain, drawn as one. Every PLO in this system is required to
 * trace to evidence, so the trace is not a detail panel — it is the proof of
 * the claim above it, and it is indented off a single rule to read that way.
 */
function TracePanel({ programId, ploId }: { programId: string; ploId: string }) {
  const [trace, setTrace] = useState<PLOTrace | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .get<PLOTrace>(`/programs/${programId}/plos/${ploId}/trace`)
      .then((r) => setTrace(r.data))
      .catch(() => setError('โหลดที่มาไม่สำเร็จ ลองเปิดใหม่อีกครั้ง'))
      .finally(() => setLoading(false))
  }, [programId, ploId])

  if (loading) return <p className="mt-3 text-sm text-lead">กำลังโหลดที่มา…</p>
  if (error) return <p className="notice notice-error mt-3">{error}</p>
  if (!trace) return null

  return (
    <div className="mt-4 border-l-2 border-stamp/40 pl-4">
      <h3 className="eyebrow">ความต้องการของตลาด</h3>
      <ul className="mt-2 space-y-3">
        {trace.clusters.map((c) => (
          <li key={c.need_id}>
            <div className="flex items-baseline gap-3">
              <p className="record min-w-0 flex-1 text-base">{c.statement_th}</p>
              <span className="data shrink-0 text-xs text-pencil" title={DEMAND_SCORE_TITLE_TH}>
                {demandPercent(c.demand_score)}
              </span>
            </div>
            {c.rationale_th && (
              <p className="mt-1 text-xs leading-relaxed text-pencil">
                <span className="text-lead">เหตุผลการจัดกลุ่ม (คำอธิบายของโมเดล): </span>
                {c.rationale_th}
              </p>
            )}
            <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-lead">
              <span className="data text-graphite">{c.need_id}</span>
              <span>{c.ksec_categories.map(ksecLabel).join(' + ')}</span>
              <span className="data">{c.bloom_level}</span>
              <span>หลักฐาน {c.source_evidence_ids.length} ชิ้น</span>
            </p>
          </li>
        ))}
      </ul>

      <h3 className="eyebrow mt-5">หลักฐาน</h3>
      <ul className="mt-2 space-y-3">
        {trace.evidence.map((e) => (
          <li key={e.evidence_id} className="rounded-[3px] border border-hair bg-sunk px-3 py-2">
            <p className="flex flex-wrap items-baseline gap-2 text-xs">
              <span className="font-medium text-graphite">{e.source_name}</span>
              {/* สภาวิชาชีพ and the institution's own direction are the voices
                  that bind the program, and binding is what colour means here. */}
              <span
                className={`chip ${isRequirementStakeholder(e.stakeholder_type) ? 'chip-mandate' : 'chip-neutral'}`}
              >
                {stakeholderLabel(e.stakeholder_type)}
              </span>
              <span className="text-lead">{classStyle(e.classification).label}</span>
            </p>
            <p className="record mt-1 line-clamp-3 text-sm text-pencil">{e.raw_text_th}</p>
          </li>
        ))}
      </ul>
    </div>
  )
}
