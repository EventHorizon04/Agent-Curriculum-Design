/** The pipeline as the designer meets it.
 *
 * Seven stages run in the engine; six of them have a page, because
 * skill_extraction and need_combination run back to back behind one review gate
 * and are therefore reviewed together on one screen. `engineStages` records that
 * — the nav shows it rather than hiding it, since a designer looking for a
 * "Need" page needs to know why there isn't one.
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
  /** Set only where one page covers more than one engine stage. */
  engineStages?: string[]
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
    label: 'สกัดทักษะและรวมเป็น Need',
    summary: 'อ่านหลักฐานเป็นทักษะ แล้วรวมทักษะเป็นความต้องการของตลาด',
    engineStages: ['สกัดทักษะจากหลักฐาน', 'รวมทักษะเป็น Need'],
    gateNote: 'ตรวจครั้งเดียว หลังรวม Need เสร็จ',
  },
  {
    key: 'plo_synthesis',
    route: '/plo-synthesis',
    ordinal: 4,
    label: 'สังเคราะห์ PLO',
    summary: 'หนึ่ง Need เป็นหนึ่ง PLO สูงสุด 10 ข้อหลัก',
  },
  {
    key: 'plo_report',
    route: '/plo-report',
    ordinal: 5,
    label: 'รายงาน PLO',
    summary: 'ทบทวนผลตรวจ ย้อนรอยหลักฐาน และส่งออก',
  },
  {
    key: 'plo_review',
    route: '/plo-review',
    ordinal: 6,
    label: 'ตรวจคุณภาพชุด PLO',
    summary: 'QA agent อ่าน PLO ทั้งชุด แนะนำเรื่องซ้ำ KSEC Bloom และ Need ที่ตกหล่น',
  },
]

export const STAGE_LABELS: Record<string, string> = Object.fromEntries(
  STAGES.map((s) => [s.key, `ขั้นที่ ${s.ordinal}: ${s.label}`])
)

export const STAGE_ROUTES: Record<string, string> = Object.fromEntries(
  STAGES.map((s) => [s.key, s.route])
)

/** How far a program has reached. -1 means it has not started a stage yet. */
export function stageIndex(stageKey: string | null): number {
  if (!stageKey) return -1
  return STAGES.findIndex((s) => s.key === stageKey)
}

export const SESSION_STATUS_LABELS: Record<string, string> = {
  running: 'กำลังทำงาน',
  suspended: 'รอตรวจสอบ',
  completed: 'เสร็จสิ้น',
  rejected: 'ถูกปฏิเสธ',
  failed: 'ล้มเหลว',
}
