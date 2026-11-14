/** The pipeline as the designer meets it.
 *
 * Seven stages, seven pages. Skill extraction (Agent 1) and Need analysis
 * (Agent 2) each have their own page; the Need gate sits after Need analysis and
 * the PLO gate on the review page (the designer approves there, then the report
 * is stored), so `gateNote` is on those two and the skill stage has none.
 */
export interface StageDef {
  /** Stage key as the API reports it in ProgramSummary.current_stage. */
  key: string
  route: string
  /** Position in the sequence a designer counts through. */
  ordinal: number
  label: string
  /** What this stage does, in the designer's words. */
  summary: string
  gateNote?: string
}

export const STAGES: StageDef[] = [
  {
    key: 'intake',
    route: '/intake',
    ordinal: 1,
    label: 'ข้อมูลหลักสูตร',
    summary: 'มหาวิทยาลัย คณะ สาขา ระดับปริญญา',
  },
  {
    key: 'stakeholder_needs',
    route: '/stakeholder-needs',
    ordinal: 2,
    label: 'ความต้องการผู้มีส่วนได้ส่วนเสีย',
    summary: 'เก็บหลักฐานจากสภาวิชาชีพ ผู้ประกอบการ ศิษย์เก่า',
  },
  {
    key: 'skill_extraction',
    route: '/skill-extraction',
    ordinal: 3,
    label: 'สกัดทักษะ',
    summary: 'อ่านหลักฐานเป็นทักษะ แล้วจัดกลุ่มตาม KSEC',
  },
  {
    key: 'need_analysis',
    route: '/need-analysis',
    ordinal: 4,
    label: 'วิเคราะห์ Need',
    summary: 'รวมกลุ่มทักษะเป็น Need และรวม Need ที่ซ้ำกัน',
    gateNote: 'ตรวจและอนุมัติที่ขั้นนี้',
  },
  {
    key: 'plo_synthesis',
    route: '/plo-synthesis',
    ordinal: 5,
    label: 'สังเคราะห์ PLO',
    summary: 'หนึ่ง Need เป็นหนึ่ง PLO สูงสุด 10 ข้อหลัก',
  },
  {
    key: 'plo_review',
    route: '/plo-review',
    ordinal: 6,
    label: 'ตรวจคุณภาพชุด PLO',
    summary: 'ตรวจทั้งชุด ส่งกลับไปแก้ แล้วผู้ออกแบบอนุมัติ',
    gateNote: 'ตรวจและอนุมัติที่ขั้นนี้',
  },
  {
    key: 'plo_report',
    route: '/plo-report',
    ordinal: 7,
    label: 'รายงาน PLO',
    summary: 'ชุด PLO สุดท้ายหลังอนุมัติ ย้อนรอยหลักฐาน และส่งออก',
  },
]

/** How a program is run: the four-agent pipeline, or one agent doing every stage. */
export type AgentMode = 'multi' | 'single'

export const AGENT_MODE_LABEL_TH: Record<AgentMode, string> = {
  multi: 'หลายตัวแทน',
  single: 'ตัวแทนเดียว',
}

/** The rail for one mode. A single-agent program has no skill stage and no
 *  separate review stage: its PLO step is the checkpoint, and carries the gate
 *  note the review stage carries in the multi-agent rail. Ordinals are renumbered
 *  so the rail still counts 1..n. */
export function stagesFor(mode: AgentMode): StageDef[] {
  if (mode === 'multi') return STAGES
  const review = STAGES.find((s) => s.key === 'plo_review')
  return STAGES.filter((s) => s.key !== 'skill_extraction' && s.key !== 'plo_review').map(
    (s, i) => ({
      ...s,
      ordinal: i + 1,
      ...(s.key === 'plo_synthesis'
        ? {
            label: 'ตรวจ PLO',
            summary: 'ตัวแทนเขียน PLO จาก Need ที่อนุมัติ แล้วผู้ออกแบบตรวจและอนุมัติ',
            gateNote: review?.gateNote,
          }
        : {}),
    }),
  )
}

/** The ordinal a stage carries on the rail of `mode`. */
export function ordinalOf(key: string, mode: AgentMode): number {
  return stagesFor(mode).find((s) => s.key === key)?.ordinal ?? 0
}

export const STAGE_LABELS: Record<string, string> = Object.fromEntries(
  STAGES.map((s) => [s.key, `ขั้นที่ ${s.ordinal}: ${s.label}`])
)

export const STAGE_ROUTES: Record<string, string> = Object.fromEntries(
  STAGES.map((s) => [s.key, s.route])
)

/** How far a program has reached. -1 means it has not started a stage yet. */
export function stageIndex(stageKey: string | null, stages: StageDef[] = STAGES): number {
  if (!stageKey) return -1
  return stages.findIndex((s) => s.key === stageKey)
}

export const SESSION_STATUS_LABELS: Record<string, string> = {
  running: 'กำลังทำงาน',
  suspended: 'รอตรวจสอบ',
  completed: 'เสร็จสิ้น',
  rejected: 'ถูกปฏิเสธ',
  failed: 'ล้มเหลว',
}

/** Why a single-agent run ended, for every reason except finishing. The agent
 *  stopped on its own limit rather than on its own judgement, so what it wrote
 *  may be partial. */
export const SINGLE_STOP_REASON_TH: Record<string, string> = {
  turn_cap: 'ตัวแทนใช้รอบครบกำหนดก่อนจบงาน',
  timeout: 'หมดเวลา',
  context_full: 'ข้อมูลเกินความจุของโมเดล',
  malformed: 'โมเดลตอบผิดรูปแบบซ้ำ',
}
