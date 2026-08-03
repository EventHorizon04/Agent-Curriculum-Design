// The single source for stakeholder and classification presentation. Five pages
// each carried their own copy of this before, and none of them agreed: one
// omitted `parent` (making it unreachable in the only dropdown that creates
// evidence), one named types that never existed in the API, and the need and
// requirement badge colours were swapped between two of them.

export const STAKEHOLDER_LABELS: Record<string, string> = {
  professional_council: 'สภาวิชาชีพ',
  employer: 'ผู้ใช้บัณฑิต',
  industry: 'ภาคอุตสาหกรรม',
  alumni: 'ศิษย์เก่า',
  expert: 'ผู้ทรงคุณวุฒิ',
  community: 'ชุมชนและสังคม',
  partner_institution: 'สถาบันคู่ความร่วมมือ',
  applicant: 'ผู้สมัครเรียน',
  parent: 'ผู้ปกครอง',
  institutional_direction: 'วิสัยทัศน์/พันธกิจ/อัตลักษณ์',
  administrator: 'ผู้บริหาร',
  program_committee: 'คณะกรรมการหลักสูตร',
  faculty: 'อาจารย์',
  student: 'ผู้เรียน',
  support_staff: 'บุคลากรสายสนับสนุน',
}

export const STAKEHOLDER_GROUPS: { label: string; types: string[] }[] = [
  {
    label: 'ภายนอก',
    types: [
      'professional_council', 'employer', 'industry', 'alumni', 'expert',
      'community', 'partner_institution', 'applicant', 'parent',
    ],
  },
  {
    label: 'ภายใน',
    types: [
      'institutional_direction', 'administrator', 'program_committee',
      'faculty', 'student', 'support_staff',
    ],
  },
]

export const stakeholderLabel = (value: string): string =>
  STAKEHOLDER_LABELS[value] ?? value

// Mirrors REQUIREMENT_TYPES in src/curriculum_agent/models.py: สภาวิชาชีพ sets
// legally binding practice requirements and the institution's own direction
// binds the program it governs, so evidence from either is classified
// `requirement` in code. Everything else carries demand signal, not mandate.
// Kept in the same order as STAKEHOLDER_GROUPS so requirement sources sort first
// within their group without a second ordering rule.
export const REQUIREMENT_STAKEHOLDER_TYPES = new Set([
  'professional_council',
  'institutional_direction',
])

export const isRequirementStakeholder = (value: string): boolean =>
  REQUIREMENT_STAKEHOLDER_TYPES.has(value)

export const KSEC_LABEL: Record<string, string> = {
  K: 'K · ความรู้',
  S: 'S · ทักษะ',
  EC: 'E|C · คุณธรรมและคุณลักษณะ',
  E: 'E · คุณธรรมจริยธรรม',
  C: 'C · คุณลักษณะบุคคล',
}

export const KSEC_COLOR: Record<string, string> = {
  K: 'bg-sky-100 text-sky-800',
  S: 'bg-emerald-100 text-emerald-800',
  EC: 'bg-violet-100 text-violet-800',
  E: 'bg-rose-100 text-rose-800',
  C: 'bg-amber-100 text-amber-800',
}

export const ksecLabel = (value: string): string => KSEC_LABEL[value] ?? value
export const ksecColor = (value: string): string =>
  KSEC_COLOR[value] ?? 'bg-gray-100 text-gray-600'

// Evidence carries requirement/general; a skill carries all four.
export const CLASS_STYLE: Record<string, { label: string; cls: string }> = {
  requirement: { label: 'ข้อกำหนด', cls: 'bg-blue-100 text-blue-700' },
  need: { label: 'ความต้องการ', cls: 'bg-green-100 text-green-700' },
  want: { label: 'ความปรารถนา', cls: 'bg-yellow-100 text-yellow-700' },
  general: { label: 'ทั่วไป', cls: 'bg-slate-100 text-slate-600' },
  unclassified: { label: 'ยังไม่จำแนก', cls: 'bg-gray-100 text-gray-500' },
}

export const classStyle = (value: string): { label: string; cls: string } =>
  CLASS_STYLE[value] ?? CLASS_STYLE.unclassified
