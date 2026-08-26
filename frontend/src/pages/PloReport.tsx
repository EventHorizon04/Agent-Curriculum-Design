import { useState, useEffect, useCallback, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useProgram } from '../hooks/useProgram'
import api from '../api/client'
import { ksecLabel, stakeholderLabel, classStyle, isRequirementStakeholder } from '../constants/stakeholder'

interface PLO {
  plo_id: string
  statement_th: string
  statement_en: string | null
  bloom_level: string
  source_need_ids: string[]
  rationale_th: string
  smart_retry_count: number
  smart_escalated: boolean
  soft_flags: string[]
  is_optional: boolean
}

/** `/needs/` returns whole Needs; the report only reads these fields, and the
 *  unused-Need list needs the statement to be worth showing at all. */
interface NeedSummary {
  need_id: string
  statement_th?: string
  ksec_category: string
  demand_score?: number
}

interface ReportCounts {
  total: number
  core: number
  optional: number
  escalated: number
}

interface PLOReportResponse {
  plos: PLO[]
  counts: ReportCounts
  needs_by_id: Record<string, NeedSummary>
}

interface TraceNeed {
  need_id: string
  statement_th: string
  statement_en: string | null
  ksec_category: string
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

interface PLOTrace {
  plo: PLO
  clusters: TraceNeed[]
  evidence: TraceEvidence[]
}

const BLOOM_LABEL: Record<string, string> = {
  remember: 'Remember',
  understand: 'Understand',
  apply: 'Apply',
  analyze: 'Analyze',
  evaluate: 'Evaluate',
  create: 'Create',
}

const SOFT_FLAG_TH: Record<string, string> = {
  S_object: 'กรรมของกริยากว้างเกินไป',
  A_level: 'ระดับ Bloom อาจสูง/ต่ำเกินไป',
  R_alignment: 'อาจไม่สอดคล้องวิสัยทัศน์',
}

/** Mirrors MIN_NEEDS and MAX_CORE_PLOS in the pipeline. The band is the policy
 *  a curriculum is judged against, so the page states it rather than implying it. */
const MIN_CORE = 6
const MAX_CORE = 10
/** Two past the ceiling, so a set that overshoots still lands on the scale. */
const BAND_SCALE = 12

function countsFrom(plos: PLO[]): ReportCounts {
  const core = plos.filter((p) => !p.is_optional).length
  return {
    total: plos.length,
    core,
    optional: plos.length - core,
    escalated: plos.filter((p) => p.smart_escalated).length,
  }
}

/** A hairline tag. The letter is the code — K, S, EC carry their own meaning and
 *  a colour per category would only add five hues that mean nothing to a reader
 *  who has not memorised the key. Colour on this page means "mandate" alone. */
function Tag({ children, mono = false }: { children: React.ReactNode; mono?: boolean }) {
  return (
    <span
      className={`rounded-sm border border-rule px-1.5 py-px text-xs text-mute ${mono ? 'data' : ''}`}
    >
      {children}
    </span>
  )
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
    <section className="border-b border-rule pb-6" aria-labelledby="band-heading">
      <h2 id="band-heading" className="eyebrow">
        PLO หลัก
      </h2>

      <p className="mt-1 flex items-baseline gap-2">
        <span className="data text-3xl leading-none text-body">{core}</span>
        <span className="text-sm text-mute">
          {outside ? (
            <span className="text-seal">
              {short
                ? `ต่ำกว่าเกณฑ์ ${MIN_CORE} ข้อ — เพิ่มอีก ${MIN_CORE - core} ข้อ`
                : `เกินเพดาน ${MAX_CORE} ข้อ`}
            </span>
          ) : (
            `อยู่ในเกณฑ์ ${MIN_CORE}–${MAX_CORE} ข้อ`
          )}
        </span>
      </p>

      <div className="relative mt-4 h-8 max-w-md" aria-hidden="true">
        {/* Full scale, then the legal band drawn on top of it. */}
        <span className="absolute top-3 h-px w-full bg-rule" />
        <span
          className="absolute top-3 h-px bg-body"
          style={{ left: pct(MIN_CORE), width: pct(MAX_CORE - MIN_CORE) }}
        />
        {[MIN_CORE, MAX_CORE].map((n) => (
          <span key={n} className="absolute top-0" style={{ left: pct(n) }}>
            <span className="block h-6 w-px -translate-x-1/2 bg-rule" />
            <span className="data absolute left-0 top-6 -translate-x-1/2 text-[0.6875rem] text-faint">
              {n}
            </span>
          </span>
        ))}
        <span
          className={`absolute top-3 block h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rotate-45 ${
            outside ? 'bg-seal' : 'bg-body'
          }`}
          style={{ left: pct(core) }}
        />
      </div>

      {optional > 0 && (
        <p className="mt-2 text-xs text-mute">
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
  const [counts, setCounts] = useState<ReportCounts>({ total: 0, core: 0, optional: 0, escalated: 0 })
  // Derived, not read off the response: `fetchData` and `runReport` populate the
  // page by different routes, and a count that only one of them set would read as
  // "nothing was cut" on the other. Same rule the report stage applies server-side.
  const unusedNeeds = useMemo(() => {
    const cited = new Set(plos.flatMap((p) => p.source_need_ids))
    return Object.values(needsById).filter((n) => !cited.has(n.need_id))
  }, [plos, needsById])
  const [exporting, setExporting] = useState(false)
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    if (!programId) return
    setLoading(true)
    setError('')
    try {
      const [ploRes, needRes] = await Promise.all([
        api.get<PLO[]>(`/programs/${programId}/plos/`),
        api.get<NeedSummary[]>(`/programs/${programId}/needs/`),
      ])
      setPlos(ploRes.data)
      setNeedsById(Object.fromEntries(needRes.data.map((n) => [n.need_id, n])))
      setCounts(countsFrom(ploRes.data))
    } catch {
      setError('โหลดข้อมูลไม่สำเร็จ ตรวจว่า API ทำงานอยู่ แล้วลองใหม่')
    } finally {
      setLoading(false)
    }
  }, [programId])

  const runReport = useCallback(async () => {
    if (!programId) return
    setRunning(true)
    setError('')
    try {
      const res = await api.post<PLOReportResponse>(`/programs/${programId}/plos/report/run`)
      setPlos(res.data.plos)
      setCounts(res.data.counts)
      setNeedsById(res.data.needs_by_id)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'สร้างรายงานไม่สำเร็จ')
    } finally {
      setRunning(false)
    }
  }, [programId])

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
        <p className="mb-3 text-mute">ยังไม่ได้เลือกหลักสูตร</p>
        <Link to="/" className="text-seal underline underline-offset-2">
          เลือกจากรายการหลักสูตร
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-record text-2xl leading-tight text-body">รายงาน PLO</h1>
        <p className="mt-1 text-sm text-mute">
          ผลลัพธ์การเรียนรู้ทั้งชุด พร้อมที่มาของแต่ละข้อ — ตรวจให้ครบก่อนส่งออก
        </p>
      </header>

      {error && (
        <p className="border-l-2 border-seal bg-seal-soft px-3 py-2 text-sm text-seal">{error}</p>
      )}

      {loading ? (
        <p className="py-16 text-center text-sm text-faint">กำลังโหลด…</p>
      ) : running ? (
        <p className="py-16 text-center text-sm text-mute">
          กำลังสร้างรายงาน — รวบรวม PLO และย้อนรอยหลักฐาน
        </p>
      ) : plos.length === 0 ? (
        <div className="border border-rule bg-card px-6 py-12 text-center">
          <p className="font-record text-lg text-body">ยังไม่มี PLO ให้รายงาน</p>
          <p className="mx-auto mt-2 max-w-md text-sm text-mute">
            รายงานประกอบขึ้นจาก PLO ที่สังเคราะห์ไว้แล้ว ถ้ายังไม่ได้สังเคราะห์
            ให้กลับไปที่ขั้นที่ 4 ก่อน
          </p>
          <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
            <button
              onClick={runReport}
              className="bg-ink px-4 py-2 text-sm text-field transition-colors hover:bg-ink-raised"
            >
              สร้างรายงาน
            </button>
            <Link to="/plo-synthesis" className="text-sm text-mute underline underline-offset-2">
              ไปสังเคราะห์ PLO
            </Link>
          </div>
        </div>
      ) : (
        <>
          <PolicyBand core={counts.core} optional={counts.optional} />

          {/* Only what needs acting on. The set's size is the band's job, and
              repeating it here as a total would be the third place it appears. */}
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
            {counts.escalated > 0 && (
              <span className="text-seal">
                <span className="data">{counts.escalated}</span> ข้อไม่ผ่าน SMART
              </span>
            )}
            {unusedNeeds.length > 0 && (
              <a href="#unused-needs" className="text-mute underline underline-offset-2">
                <span className="data">{unusedNeeds.length}</span> Need ไม่ได้ใช้
              </a>
            )}

            <div className="ml-auto flex items-center gap-2">
              <button
                onClick={runReport}
                className="border border-rule px-3 py-1.5 text-sm text-mute transition-colors hover:border-body hover:text-body"
              >
                สร้างใหม่
              </button>
              <button
                onClick={exportMatrix}
                disabled={exporting}
                className="bg-ink px-3 py-1.5 text-sm text-field transition-colors hover:bg-ink-raised disabled:opacity-40"
              >
                {exporting ? 'กำลังส่งออก…' : 'ส่งออก Excel'}
              </button>
            </div>
          </div>

          <ol className="border-t border-rule">
            {plos.map((p) => (
              <PloRow key={p.plo_id} plo={p} programId={programId} needsById={needsById} />
            ))}
          </ol>

          {/* The CHECO and มคอ.2 exporters are stubs whose routes answer 501.
              Named as not-yet-available rather than rendered as dead buttons, so
              the designer plans around them instead of clicking to find out. */}
          <p className="text-xs text-faint">
            ส่งออก CHECO และ มคอ.2 ยังไม่เปิดใช้
          </p>

          {unusedNeeds.length > 0 && <UnusedNeeds needs={unusedNeeds} />}

          <p className="border-t border-rule pt-4 text-sm text-mute">
            ตรวจเสร็จแล้ว อนุมัติและปิด session ได้ที่{' '}
            <Link to="/pipeline" className="text-body underline underline-offset-2">
              รันทั้งชุด
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
function UnusedNeeds({ needs }: { needs: NeedSummary[] }) {
  const ordered = [...needs].sort((a, b) => (b.demand_score ?? 0) - (a.demand_score ?? 0))
  return (
    <section id="unused-needs" className="border-t border-rule pt-5">
      <h2 className="eyebrow">Need ที่ไม่ได้เป็น PLO</h2>
      <p className="mt-1 text-sm text-mute">
        เพดาน PLO หลักคือ {MAX_CORE} ข้อ เรียงตาม demand score — Need เหล่านี้ยังเก็บไว้
        พร้อมหลักฐานเดิม แต่ไม่ได้ถูกแปลงเป็นผลลัพธ์การเรียนรู้
      </p>
      <ul className="mt-3 space-y-2">
        {ordered.map((n) => (
          <li key={n.need_id} className="flex items-baseline gap-3 text-sm">
            <span className="data shrink-0 text-xs text-faint">{n.need_id}</span>
            <span className="min-w-0 flex-1 text-body">{n.statement_th ?? '—'}</span>
            {n.demand_score !== undefined && (
              <span className="data shrink-0 text-xs text-mute">
                {(n.demand_score * 100).toFixed(0)}%
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
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
      p.source_need_ids
        .map((id) => needsById[id]?.ksec_category)
        .filter((c): c is string => Boolean(c))
    ),
  ]

  return (
    <li className="border-b border-rule py-5">
      <div className="flex items-baseline gap-3">
        <span className="data w-16 shrink-0 text-sm text-faint">{p.plo_id}</span>
        <div className="min-w-0 flex-1">
          {/* The statement is the record — the sentence that ends up in มคอ.2 —
              so it is the one thing on this page set in the document's voice. */}
          <p className="font-record text-[1.0625rem] leading-relaxed text-body">{p.statement_th}</p>
          {p.statement_en && <p className="mt-1 text-sm text-faint">{p.statement_en}</p>}

          {p.smart_escalated && (
            <p className="mt-2 border-l-2 border-seal bg-seal-soft px-3 py-1.5 text-sm text-seal">
              ไม่ผ่าน SMART หลังแก้อัตโนมัติ {p.smart_retry_count} ครั้ง — ต้องแก้ข้อความเอง
            </p>
          )}

          {p.soft_flags.length > 0 && (
            <ul className="mt-2 space-y-0.5">
              {p.soft_flags.map((f) => (
                <li key={f} className="text-sm text-mute">
                  ข้อสังเกต — {SOFT_FLAG_TH[f] ?? f}
                </li>
              ))}
            </ul>
          )}

          {p.rationale_th && <p className="mt-2 text-sm text-mute">{p.rationale_th}</p>}

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Tag mono>{BLOOM_LABEL[p.bloom_level] ?? p.bloom_level}</Tag>
            {ksecTags.map((cat) => (
              <Tag key={cat}>{ksecLabel(cat)}</Tag>
            ))}
            {p.is_optional && <Tag>เสริม</Tag>}
            <button
              onClick={() => setTraceOpen((v) => !v)}
              aria-expanded={traceOpen}
              className="ml-auto text-sm text-mute underline underline-offset-2 transition-colors hover:text-body"
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

  if (loading) return <p className="mt-3 text-sm text-faint">กำลังโหลดที่มา…</p>
  if (error) return <p className="mt-3 text-sm text-seal">{error}</p>
  if (!trace) return null

  return (
    <div className="mt-4 border-l border-rule pl-4">
      <h3 className="eyebrow">ความต้องการของตลาด</h3>
      <ul className="mt-2 space-y-3">
        {trace.clusters.map((c) => (
          <li key={c.need_id}>
            <div className="flex items-baseline gap-3">
              <p className="min-w-0 flex-1 text-sm leading-relaxed text-body">{c.statement_th}</p>
              <span className="data shrink-0 text-xs text-mute">
                {(c.demand_score * 100).toFixed(0)}%
              </span>
            </div>
            <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-faint">
              <span className="data">{c.need_id}</span>
              <span>{ksecLabel(c.ksec_category)}</span>
              <span>{c.bloom_level}</span>
              <span>หลักฐาน {c.source_evidence_ids.length} ชิ้น</span>
            </p>
          </li>
        ))}
      </ul>

      <h3 className="eyebrow mt-5">หลักฐาน</h3>
      <ul className="mt-2 space-y-3">
        {trace.evidence.map((e) => (
          <li key={e.evidence_id}>
            <p className="flex flex-wrap items-baseline gap-2 text-xs">
              <span className="text-body">{e.source_name}</span>
              {/* สภาวิชาชีพ and the institution's own direction are the voices
                  that bind the program, and binding is what colour means here. */}
              <span className={isRequirementStakeholder(e.stakeholder_type) ? 'text-seal' : 'text-mute'}>
                {stakeholderLabel(e.stakeholder_type)}
              </span>
              <span className="text-faint">{classStyle(e.classification).label}</span>
            </p>
            <p className="mt-1 line-clamp-3 text-sm leading-relaxed text-mute">{e.raw_text_th}</p>
          </li>
        ))}
      </ul>
    </div>
  )
}
