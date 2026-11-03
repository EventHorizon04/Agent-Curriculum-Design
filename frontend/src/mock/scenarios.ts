/**
 * Seed data and the "pipeline" the mock runs.
 *
 * Everything here is invented: a fictional university, a fictional translation
 * programme, stakeholders described by role rather than by name. Nothing is
 * read from references/.
 *
 * The same builders serve two callers: the scenarios, which seed a database in
 * one go, and the run endpoints, which re-derive skills, Needs and PLOs from
 * whatever evidence the designer has on the page. So a re-run on a seeded
 * programme reproduces the seeded rows (with fresh ids, the way the real
 * stages mint new uuids), and a re-run on evidence typed into the mock still
 * produces something plausible.
 *
 * The derived fields follow the backend's own rules where they are pure code:
 * evidence class from stakeholder type, skill class from type/field/frequency,
 * `demand_score` from stages/demand.py, `is_optional` from is_optional_group,
 * plo_id numbering and order from plo_synthesis / PLORepository.
 */
import type { SMARTCheck, SmartFinding, ValidatedBy } from '../types/plo'
import type { PLOSetReview, UnusedNeedFinding } from '../types/ploReview'
import { MAX_CORE_PLOS, REVIEW_MARKER_TH } from '../constants/needPolicy'
import { scopeVerdict } from '../constants/scope'
import {
  emptyDb,
  newId,
  nowIso,
  replaceDb,
  setControls,
  type EvidenceRow,
  type MockDb,
  type NeedRow,
  type PloRow,
  type ProgramRow,
  type ScenarioName,
  type SessionRow,
  type SkillRow,
} from './db'

// ----------------------------------------------------------------------------
// Vocabulary mirrored from models.py
// ----------------------------------------------------------------------------

/** StakeholderType in declaration order — external first, as the Need's
 *  `source_stakeholder_types` is ordered. */
export const STAKEHOLDER_TYPES = [
  'professional_council',
  'employer',
  'industry',
  'alumni',
  'expert',
  'community',
  'partner_institution',
  'applicant',
  'parent',
  'institutional_direction',
  'administrator',
  'program_committee',
  'faculty',
  'student',
  'support_staff',
] as const

const REQUIREMENT_TYPES = new Set(['professional_council', 'institutional_direction'])
const PRACTITIONER_TYPES = new Set(['professional_council', 'employer', 'industry', 'alumni', 'expert'])

export const BLOOM_LEVELS = ['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create']

/** classify_evidence_type. */
export function classifyEvidence(stakeholderType: string): 'requirement' | 'general' {
  return REQUIREMENT_TYPES.has(stakeholderType) ? 'requirement' : 'general'
}

/** The graph's interrupt values, verbatim — what a suspended session shows. */
export const INTERRUPT_MESSAGE: Record<string, string> = {
  stakeholder_needs: 'Stage 1 complete — review classified evidence before clustering',
  need_analysis: 'Stage 2 complete — review raw skills and distilled Needs',
  plo_synthesis: 'Stage 3 complete — review/edit PLOs before PLO report',
}

/** The review gates a session suspends at, in order (REVIEW_NODE_STAGE). The
 *  last one is the PLO checkpoint: resuming it runs plo_report and plo_review
 *  straight through to END, with no gate after them. */
export const CHECKPOINTS = ['stakeholder_needs', 'need_analysis', 'plo_synthesis']

// ----------------------------------------------------------------------------
// Deterministic ids
// ----------------------------------------------------------------------------

/** A uuid-shaped id from a seed string, so seeded rows look like the real
 *  ones (uuid4) but stay stable across resets. */
export function fakeUuid(seed: string): string {
  let h1 = 0x811c9dc5
  let h2 = 0x01000193
  const hex: string[] = []
  for (let round = 0; round < 4; round++) {
    for (let i = 0; i < seed.length; i++) {
      const c = seed.charCodeAt(i) + round * 131
      h1 = Math.imul(h1 ^ c, 0x01000193) >>> 0
      h2 = Math.imul(h2 ^ (c + h1), 0x5bd1e995) >>> 0
    }
    hex.push(((h1 ^ h2) >>> 0).toString(16).padStart(8, '0'))
  }
  const s = hex.join('')
  return `${s.slice(0, 8)}-${s.slice(8, 12)}-4${s.slice(13, 16)}-8${s.slice(17, 20)}-${s.slice(20, 32)}`
}

// ----------------------------------------------------------------------------
// The fictional programme
// ----------------------------------------------------------------------------

const UNIVERSITY = 'มหาวิทยาลัยตัวอย่าง'
const FACULTY = 'คณะมนุษยศาสตร์'

function program(partial: Partial<ProgramRow> & Pick<ProgramRow, 'program_id' | 'field'>): ProgramRow {
  return {
    name_th: '',
    name_en: '',
    isced_code: null,
    degree_level: 'bachelor',
    duration_years: 4,
    faculty: FACULTY,
    university: UNIVERSITY,
    scope_th: '',
    professional_council: null,
    accreditation_body: null,
    subject_benchmark_ref: null,
    program_objectives_th: [],
    program_goals_th: [],
    created_at: '2026-09-15T03:12:00',
    ...partial,
  }
}

interface EvidenceSeed {
  key: string
  type: string
  source: string
  /** Joined with a space into raw_text_th; skills quote whole sentences, so
   *  every evidence_span_th is a verbatim substring, as is_grounded requires. */
  sentences: string[]
}

const TRANSLATION_EVIDENCE: EvidenceSeed[] = [
  {
    key: 'E1',
    type: 'professional_council',
    source: 'ร่างมาตรฐานสมรรถนะนักแปลวิชาชีพ — สมาคมวิชาชีพนักแปลและล่าม (สมมติ)',
    sentences: [
      'นักแปลวิชาชีพต้องแปลเอกสารทางกฎหมาย ธุรกิจ และการแพทย์ได้ถูกต้องตามความหมายและรูปแบบของต้นฉบับ',
      'ต้องรักษาความลับของผู้ว่าจ้างและไม่รับงานที่มีผลประโยชน์ทับซ้อน',
      'ต้องตรวจทานงานแปลของตนเองและของผู้อื่นตามเกณฑ์คุณภาพที่กำหนดไว้ก่อนส่งมอบ',
    ],
  },
  {
    key: 'E2',
    type: 'institutional_direction',
    source: 'วิสัยทัศน์และอัตลักษณ์บัณฑิต มหาวิทยาลัยตัวอย่าง',
    sentences: [
      'มหาวิทยาลัยมุ่งผลิตบัณฑิตที่สื่อสารข้ามวัฒนธรรมได้อย่างมีความรับผิดชอบต่อสังคม',
      'คณะมุ่งสร้างเครือข่ายความร่วมมือทางวิชาการกับสถาบันในภูมิภาคอาเซียน',
      'บัณฑิตมีจิตสาธารณะและยึดมั่นในจรรยาบรรณวิชาชีพ',
    ],
  },
  {
    key: 'E3',
    type: 'employer',
    source: 'สัมภาษณ์ผู้จัดการฝ่ายเอกสาร สำนักงานกฎหมายแห่งหนึ่ง',
    sentences: [
      'เราต้องการคนที่แปลสัญญาและเอกสารคดีความได้โดยใช้ศัพท์กฎหมายถูกต้อง',
      'นักแปลต้องใช้โปรแกรมช่วยแปลและคลังศัพท์ร่วมกับทีมได้',
      'ต้องส่งงานตรงเวลาและประสานกับทนายความเมื่อต้นฉบับกำกวม',
      'งานบางชิ้นต้องเรียบเรียงถ้อยคำใหม่ให้อ่านเป็นธรรมชาติในภาษาไทย',
    ],
  },
  {
    key: 'E4',
    type: 'industry',
    source: 'ผู้ประกอบการธุรกิจแปลและปรับเนื้อหาสู่ท้องถิ่น (localization)',
    sentences: [
      'งานส่วนใหญ่ตอนนี้คือการตรวจแก้งานแปลจากเครื่องแปลภาษาและ AI ให้ได้มาตรฐาน',
      'ต้องปรับเนื้อหาแอปพลิเคชันและเกมให้เหมาะกับผู้ใช้ชาวไทย',
      'ทักษะการบริหารโครงการแปลขนาดใหญ่ที่มีหลายภาษาเป็นสิ่งที่ขาดแคลน',
      'ความรู้การตลาดดิจิทัลและการวัดผลโฆษณาออนไลน์ช่วยให้ทำงานกับลูกค้าได้ง่ายขึ้น',
    ],
  },
  {
    key: 'E5',
    type: 'alumni',
    source: 'แบบสอบถามศิษย์เก่า รุ่นปีการศึกษา 2566',
    sentences: [
      'ในงานจริงต้องเป็นล่ามในการประชุมและการเจรจาธุรกิจบ่อยกว่าที่คาด',
      'อยากให้หลักสูตรฝึกใช้โปรแกรมช่วยแปลและคลังศัพท์มากขึ้น',
      'การวิเคราะห์ความต่างของโครงสร้างภาษาไทยและภาษาอังกฤษช่วยให้แก้ปัญหางานแปลได้',
      'ความรู้ด้านการตลาดดิจิทัลเป็นประโยชน์มากเมื่อทำงานฟรีแลนซ์',
    ],
  },
  {
    key: 'E6',
    type: 'expert',
    source: 'บันทึกการวิพากษ์หลักสูตร — ผู้ทรงคุณวุฒิด้านการแปลและการล่าม',
    sentences: [
      'ผู้เรียนควรวิเคราะห์ปัญหาการแปลที่เกิดจากความต่างทางไวยากรณ์และวัฒนธรรมได้อย่างเป็นระบบ',
      'ควรฝึกการล่ามพูดตามและการล่ามแปลสลับในสถานการณ์จำลอง',
      'บัณฑิตต้องประเมินคุณภาพงานแปลด้วยเกณฑ์ที่ใช้ในอุตสาหกรรม',
      'ผู้เรียนควรฝึกเขียนสรุปความและเรียบเรียงเนื้อหาจากต้นฉบับยาว',
    ],
  },
  {
    key: 'E7',
    type: 'employer',
    source: 'ประกาศรับสมัครงาน: นักแปลบทบรรยายใต้ภาพ บริษัทผลิตสื่อแห่งหนึ่ง',
    sentences: [
      'แปลและตั้งเวลาบทบรรยายใต้ภาพสำหรับภาพยนตร์และซีรีส์',
      'ใช้โปรแกรมทำซับไตเติลได้คล่อง',
      'ทำงานร่วมกับทีมตรวจทานภายใต้กำหนดส่งที่กระชั้น',
    ],
  },
  {
    key: 'E8',
    type: 'applicant',
    source: 'สนทนากลุ่มนักเรียนชั้น ม.6 ที่สนใจสมัครเรียน',
    sentences: [
      'อยากเรียนการแปลที่ได้ใช้ AI เป็นเครื่องมือ',
      'สนใจงานล่ามและการทำงานกับชาวต่างชาติ',
      'อยากให้มีกิจกรรมแลกเปลี่ยนกับมหาวิทยาลัยต่างประเทศ',
    ],
  },
]

/** One extracted skill: which Need it ends up in, and where it is quoted from. */
interface SkillSeed {
  need: string
  evidence: string
  sentence: number
  name: string
  nameEn: string | null
  ksec: SkillRow['ksec_category']
  bloom: string
  inField?: false
  graduate?: false
}

const TRANSLATION_SKILLS: SkillSeed[] = [
  { need: 'legal', evidence: 'E1', sentence: 0, name: 'แปลเอกสารเฉพาะทางด้านกฎหมาย ธุรกิจ และการแพทย์', nameEn: 'Specialised legal, business and medical translation', ksec: 'S', bloom: 'apply' },
  { need: 'legal', evidence: 'E3', sentence: 0, name: 'แปลสัญญาและเอกสารคดีความด้วยศัพท์กฎหมายที่ถูกต้อง', nameEn: 'Contract and litigation translation', ksec: 'S', bloom: 'apply' },
  { need: 'qa', evidence: 'E1', sentence: 2, name: 'ประเมินคุณภาพงานแปลตามเกณฑ์ที่กำหนด', nameEn: 'Translation quality assessment', ksec: 'S', bloom: 'evaluate' },
  { need: 'qa', evidence: 'E4', sentence: 0, name: 'ตรวจแก้งานแปลจากเครื่องแปลภาษาและ AI', nameEn: 'Machine translation post-editing', ksec: 'S', bloom: 'evaluate' },
  { need: 'qa', evidence: 'E6', sentence: 2, name: 'ประเมินคุณภาพงานแปลตามเกณฑ์ที่กำหนด', nameEn: 'Translation quality assessment', ksec: 'S', bloom: 'evaluate' },
  { need: 'cat', evidence: 'E3', sentence: 1, name: 'ใช้โปรแกรมช่วยแปลและคลังศัพท์', nameEn: 'CAT tools and termbases', ksec: 'S', bloom: 'apply' },
  { need: 'cat', evidence: 'E5', sentence: 1, name: 'ใช้โปรแกรมช่วยแปลและคลังศัพท์', nameEn: 'CAT tools and termbases', ksec: 'S', bloom: 'apply' },
  { need: 'cat', evidence: 'E8', sentence: 0, name: 'ใช้ AI เป็นเครื่องมือในการแปล', nameEn: 'AI-assisted translation', ksec: 'S', bloom: 'apply' },
  { need: 'interp', evidence: 'E5', sentence: 0, name: 'ล่ามในการประชุมและการเจรจาธุรกิจ', nameEn: 'Conference and business interpreting', ksec: 'S', bloom: 'apply' },
  { need: 'interp', evidence: 'E6', sentence: 1, name: 'ล่ามพูดตามและล่ามแปลสลับ', nameEn: 'Simultaneous and consecutive interpreting', ksec: 'S', bloom: 'apply' },
  { need: 'interp', evidence: 'E8', sentence: 1, name: 'ทำงานล่ามร่วมกับชาวต่างชาติ', nameEn: null, ksec: 'S', bloom: 'apply' },
  { need: 'ethics', evidence: 'E1', sentence: 1, name: 'รักษาความลับของผู้ว่าจ้างและหลีกเลี่ยงผลประโยชน์ทับซ้อน', nameEn: 'Client confidentiality', ksec: 'E', bloom: 'apply' },
  { need: 'ethics', evidence: 'E2', sentence: 2, name: 'ยึดมั่นในจรรยาบรรณวิชาชีพ', nameEn: 'Professional ethics', ksec: 'E', bloom: 'apply' },
  { need: 'ling', evidence: 'E5', sentence: 2, name: 'วิเคราะห์ความต่างของโครงสร้างภาษาไทยและภาษาอังกฤษ', nameEn: 'Thai-English contrastive analysis', ksec: 'K', bloom: 'analyze' },
  { need: 'ling', evidence: 'E6', sentence: 0, name: 'วิเคราะห์ปัญหาการแปลจากความต่างทางไวยากรณ์และวัฒนธรรม', nameEn: 'Translation problem analysis', ksec: 'K', bloom: 'analyze' },
  { need: 'l10n', evidence: 'E4', sentence: 1, name: 'ปรับเนื้อหาแอปพลิเคชันและเกมสู่ผู้ใช้ชาวไทย', nameEn: 'Software and game localisation', ksec: 'S', bloom: 'create' },
  { need: 'l10n', evidence: 'E2', sentence: 0, name: 'สื่อสารข้ามวัฒนธรรมอย่างมีความรับผิดชอบต่อสังคม', nameEn: 'Responsible intercultural communication', ksec: 'S', bloom: 'apply' },
  { need: 'team', evidence: 'E3', sentence: 2, name: 'ส่งงานตรงเวลาและประสานกับผู้ว่าจ้างเมื่อต้นฉบับกำกวม', nameEn: null, ksec: 'C', bloom: 'apply' },
  { need: 'team', evidence: 'E4', sentence: 2, name: 'บริหารโครงการแปลหลายภาษา', nameEn: 'Multilingual translation project management', ksec: 'C', bloom: 'apply' },
  { need: 'team', evidence: 'E7', sentence: 2, name: 'ทำงานร่วมกับทีมตรวจทานภายใต้กำหนดส่งที่กระชั้น', nameEn: null, ksec: 'C', bloom: 'apply' },
  { need: 'subtitle', evidence: 'E7', sentence: 0, name: 'แปลและตั้งเวลาบทบรรยายใต้ภาพ', nameEn: 'Subtitle translation and timing', ksec: 'S', bloom: 'apply' },
  { need: 'subtitle', evidence: 'E7', sentence: 1, name: 'ใช้โปรแกรมทำซับไตเติล', nameEn: 'Subtitling software', ksec: 'S', bloom: 'apply' },
  { need: 'rewrite', evidence: 'E3', sentence: 3, name: 'เรียบเรียงถ้อยคำภาษาไทยให้เป็นธรรมชาติ', nameEn: null, ksec: 'S', bloom: 'apply' },
  { need: 'rewrite', evidence: 'E6', sentence: 3, name: 'เขียนสรุปความจากต้นฉบับยาว', nameEn: null, ksec: 'S', bloom: 'apply' },
  { need: 'marketing', evidence: 'E4', sentence: 3, name: 'การตลาดดิจิทัลและการวัดผลโฆษณาออนไลน์', nameEn: 'Digital marketing analytics', ksec: 'S', bloom: 'apply', inField: false },
  { need: 'marketing', evidence: 'E5', sentence: 3, name: 'การตลาดดิจิทัลสำหรับงานฟรีแลนซ์', nameEn: null, ksec: 'S', bloom: 'apply', inField: false },
  { need: 'network', evidence: 'E2', sentence: 1, name: 'สร้างเครือข่ายความร่วมมือทางวิชาการกับสถาบันในอาเซียน', nameEn: null, ksec: 'C', bloom: 'create', graduate: false },
  { need: 'network', evidence: 'E8', sentence: 2, name: 'จัดกิจกรรมแลกเปลี่ยนกับมหาวิทยาลัยต่างประเทศ', nameEn: null, ksec: 'C', bloom: 'apply', graduate: false },
]

interface PloSeed {
  action_verb_th: string
  bloom_level: string
  statement_th: string
  statement_en: string | null
  rationale_th: string
  distinctive_feature_th: string | null
}

interface NeedSeed {
  key: string
  ksec: NeedRow['ksec_categories'][number]
  bloom: string
  statement_th: string
  statement_en: string | null
  rationale_th: string
  /** Short noun phrase for a merged outcome's wording. */
  topic_th: string
  /** need_combination could not write this group: the statement becomes the
   *  marker plus the member names, as `_NeedStatement.model_construct` does. */
  fallback?: boolean
  plo: PloSeed
}

const TRANSLATION_NEEDS: NeedSeed[] = [
  {
    key: 'legal',
    ksec: 'S',
    bloom: 'apply',
    statement_th:
      'ต้องการบัณฑิตที่แปลเอกสารเฉพาะทาง เช่น กฎหมาย ธุรกิจ และการแพทย์ ระหว่างภาษาไทยกับภาษาอังกฤษได้ถูกต้องทั้งความหมาย ศัพท์เฉพาะ และรูปแบบของต้นฉบับ',
    statement_en: 'Graduates who translate specialised legal, business and medical documents accurately.',
    rationale_th:
      'ทักษะทั้งสองคือการแปลเอกสารที่มีศัพท์และรูปแบบเฉพาะของวงการ ต่างกันแค่ประเภทเอกสาร จึงเป็นความต้องการเดียวกัน',
    topic_th: 'การแปลเอกสารเฉพาะทาง',
    plo: {
      action_verb_th: 'แปล',
      bloom_level: 'apply',
      statement_th:
        'แปลเอกสารเฉพาะทางด้านกฎหมาย ธุรกิจ และการแพทย์ระหว่างภาษาไทยและภาษาอังกฤษ โดยคงความหมาย ศัพท์เฉพาะ และรูปแบบของต้นฉบับได้ถูกต้อง',
      statement_en:
        'Translate specialised legal, business and medical documents between Thai and English, preserving meaning, terminology and format.',
      rationale_th:
        'สภาวิชาชีพกำหนดให้เป็นสมรรถนะหลักของนักแปล และผู้ใช้บัณฑิตด้านกฎหมายระบุตรงกัน จึงเป็นผลลัพธ์ที่บัณฑิตทุกคนต้องทำได้',
      distinctive_feature_th: 'เน้นเอกสารสามประเภทที่ตลาดแปลไทย-อังกฤษจ้างงานมากที่สุด',
    },
  },
  {
    key: 'qa',
    ksec: 'S',
    bloom: 'evaluate',
    statement_th:
      'ต้องการผู้ที่ตรวจแก้และประเมินคุณภาพงานแปล รวมถึงงานที่ผ่านเครื่องแปลภาษาและ AI ตามเกณฑ์คุณภาพที่อุตสาหกรรมใช้ก่อนส่งมอบงาน',
    statement_en: null,
    rationale_th:
      'ทั้งการตรวจทานตามเกณฑ์และการตรวจแก้งานจากเครื่องแปลคือการตัดสินคุณภาพงานแปลเทียบกับมาตรฐานเดียวกัน',
    topic_th: 'การประเมินคุณภาพงานแปล',
    plo: {
      action_verb_th: 'ประเมิน',
      bloom_level: 'evaluate',
      statement_th:
        'ประเมินคุณภาพงานแปลทั้งที่แปลโดยมนุษย์และโดยเครื่องแปลภาษาด้วยเกณฑ์ที่อุตสาหกรรมใช้ และระบุจุดที่ต้องแก้ไขพร้อมเหตุผลได้',
      statement_en: null,
      rationale_th:
        'สภาวิชาชีพ ผู้ประกอบการ และผู้ทรงคุณวุฒิต่างระบุว่าการตรวจคุณภาพคือสิ่งที่งานแปลปัจจุบันต้องการมากขึ้นจากการใช้เครื่องแปล',
      distinctive_feature_th: null,
    },
  },
  {
    key: 'cat',
    ksec: 'S',
    bloom: 'apply',
    statement_th:
      'ต้องการบัณฑิตที่ใช้โปรแกรมช่วยแปล คลังศัพท์ และเครื่องมือ AI ในกระบวนการแปลร่วมกับทีมได้อย่างมีประสิทธิภาพ',
    statement_en: null,
    rationale_th:
      'สมาชิกทุกตัวพูดถึงเครื่องมือที่ใช้ระหว่างแปล ทั้งโปรแกรมช่วยแปลและ AI จึงรวมเป็นความต้องการด้านเครื่องมือเดียว',
    topic_th: 'การแปลด้วยเครื่องมือช่วยแปลและ AI',
    plo: {
      action_verb_th: 'จัดทำ',
      bloom_level: 'apply',
      statement_th:
        'จัดทำงานแปลร่วมกับทีมโดยใช้โปรแกรมช่วยแปล คลังศัพท์ และเครื่องมือ AI ให้ศัพท์และสำนวนสอดคล้องกันทั้งโครงการได้',
      statement_en: null,
      rationale_th: 'ศิษย์เก่าและผู้ใช้บัณฑิตระบุตรงกันว่าการทำงานด้วยเครื่องมือช่วยแปลเป็นเงื่อนไขการรับเข้าทำงาน',
      distinctive_feature_th: null,
    },
  },
  {
    key: 'interp',
    ksec: 'S',
    bloom: 'apply',
    statement_th:
      'ต้องการบัณฑิตที่ทำหน้าที่ล่ามแบบพูดตามและแบบแปลสลับในการประชุมและการเจรจาธุรกิจได้',
    statement_en: 'Graduates who interpret simultaneously and consecutively in meetings and negotiations.',
    rationale_th: 'ทุกทักษะในกลุ่มคือการถ่ายทอดสารด้วยวาจาแบบทันที ต่างกันแค่สถานการณ์ที่ใช้',
    topic_th: 'การล่าม',
    plo: {
      action_verb_th: 'ถ่ายทอด',
      bloom_level: 'apply',
      statement_th:
        'ถ่ายทอดสารระหว่างภาษาไทยและภาษาอังกฤษแบบล่ามพูดตามและแบบแปลสลับในการประชุมและการเจรจาธุรกิจได้ครบถ้วนและทันเวลา',
      statement_en: 'Interpret between Thai and English, simultaneously and consecutively, in meetings and negotiations.',
      rationale_th: 'ศิษย์เก่ารายงานว่าต้องทำงานล่ามบ่อยกว่าที่หลักสูตรเตรียมไว้ และผู้ทรงคุณวุฒิเสนอให้ฝึกทั้งสองรูปแบบ',
      distinctive_feature_th: null,
    },
  },
  {
    key: 'ethics',
    ksec: 'E',
    bloom: 'apply',
    statement_th:
      'ต้องการบัณฑิตที่ปฏิบัติตามจรรยาบรรณวิชาชีพนักแปลและล่าม ทั้งการรักษาความลับของผู้ว่าจ้างและการหลีกเลี่ยงผลประโยชน์ทับซ้อน',
    statement_en: null,
    rationale_th: 'สมาชิกทั้งสองเป็นข้อกำหนดด้านจรรยาบรรณ หนึ่งจากสภาวิชาชีพ หนึ่งจากอัตลักษณ์ของมหาวิทยาลัย',
    topic_th: 'จรรยาบรรณวิชาชีพนักแปล',
    plo: {
      action_verb_th: 'ปฏิบัติงาน',
      bloom_level: 'apply',
      statement_th:
        'บัณฑิตสามารถปฏิบัติงานแปลและล่ามตามจรรยาบรรณวิชาชีพ โดยรักษาความลับของผู้ว่าจ้างและจัดการสถานการณ์ผลประโยชน์ทับซ้อนได้อย่างเหมาะสม',
      statement_en: null,
      rationale_th: 'เป็นข้อกำหนดของสภาวิชาชีพและสอดคล้องกับอัตลักษณ์บัณฑิตของมหาวิทยาลัย',
      distinctive_feature_th: null,
    },
  },
  {
    key: 'ling',
    ksec: 'K',
    bloom: 'analyze',
    statement_th:
      'ต้องการบัณฑิตที่วิเคราะห์ปัญหาการแปลที่เกิดจากความต่างของโครงสร้างภาษาและวัฒนธรรมระหว่างภาษาไทยกับภาษาอังกฤษได้อย่างเป็นระบบ',
    statement_en: null,
    rationale_th: 'ทั้งสองทักษะใช้ความรู้ภาษาศาสตร์เปรียบเทียบเป็นฐานในการหาสาเหตุของปัญหาการแปล',
    topic_th: 'การวิเคราะห์ปัญหาการแปลเชิงภาษาศาสตร์',
    plo: {
      action_verb_th: 'วิเคราะห์',
      bloom_level: 'analyze',
      statement_th:
        'วิเคราะห์ปัญหาการแปลที่เกิดจากความต่างทางโครงสร้างภาษาและวัฒนธรรมระหว่างภาษาไทยกับภาษาอังกฤษ และเสนอแนวทางแก้ไขอย่างเป็นระบบได้',
      statement_en: null,
      rationale_th: 'ผู้ทรงคุณวุฒิและศิษย์เก่าเห็นตรงกันว่าความรู้นี้คือสิ่งที่แยกนักแปลวิชาชีพออกจากผู้ใช้เครื่องแปล',
      distinctive_feature_th: null,
    },
  },
  {
    key: 'l10n',
    ksec: 'S',
    bloom: 'create',
    statement_th:
      'ต้องการบัณฑิตที่ปรับเนื้อหาแอปพลิเคชัน เกม และสื่อให้เหมาะกับผู้ใช้ชาวไทยโดยคำนึงถึงบริบททางวัฒนธรรม',
    statement_en: null,
    rationale_th: 'การปรับเนื้อหาสู่ท้องถิ่นและการสื่อสารข้ามวัฒนธรรมตอบโจทย์เดียวกัน คือทำให้สารเหมาะกับผู้รับต่างวัฒนธรรม',
    topic_th: 'การปรับเนื้อหาสู่ท้องถิ่น',
    plo: {
      action_verb_th: 'ออกแบบ',
      bloom_level: 'create',
      statement_th:
        'ออกแบบการปรับเนื้อหาแอปพลิเคชัน เกม และสื่อดิจิทัลจากภาษาอังกฤษสู่ผู้ใช้ชาวไทยให้เหมาะสมกับบริบททางวัฒนธรรมได้',
      statement_en: 'Design the localisation of apps, games and digital media for Thai users.',
      rationale_th: 'ภาคอุตสาหกรรมระบุว่าขาดแคลน และสอดคล้องกับวิสัยทัศน์ด้านการสื่อสารข้ามวัฒนธรรมของมหาวิทยาลัย',
      distinctive_feature_th: 'จุดเด่นของหลักสูตรที่ต่างจากหลักสูตรการแปลทั่วไป',
    },
  },
  {
    key: 'team',
    ksec: 'C',
    bloom: 'apply',
    statement_th:
      'ต้องการบัณฑิตที่บริหารงานแปลเป็นทีมได้ตรงกำหนดส่ง ประสานกับผู้ว่าจ้างเมื่อต้นฉบับกำกวม และรับผิดชอบต่อคุณภาพของงาน',
    statement_en: null,
    rationale_th: 'ทุกทักษะเป็นคุณลักษณะการทำงานร่วมกับผู้อื่นภายใต้กำหนดเวลา ไม่ใช่ทักษะการแปลโดยตรง',
    topic_th: 'การบริหารงานแปลเป็นทีม',
    plo: {
      action_verb_th: 'บริหาร',
      bloom_level: 'apply',
      statement_th:
        'บริหารงานแปลเป็นทีมให้ส่งมอบได้ตามกำหนด และประสานกับผู้ว่าจ้างเพื่อแก้ความกำกวมของต้นฉบับได้อย่างรับผิดชอบ',
      statement_en: null,
      rationale_th: 'ผู้ใช้บัณฑิตสองรายและภาคอุตสาหกรรมระบุตรงกันว่าการส่งงานตรงเวลาในทีมคือจุดอ่อนของนักแปลจบใหม่',
      distinctive_feature_th: null,
    },
  },
  {
    key: 'subtitle',
    ksec: 'S',
    bloom: 'apply',
    statement_th:
      'ต้องการผู้ที่แปลและตั้งเวลาบทบรรยายใต้ภาพสำหรับภาพยนตร์และซีรีส์ด้วยโปรแกรมทำซับไตเติล',
    statement_en: null,
    rationale_th: 'ทั้งสองทักษะมาจากงานเดียวกัน คือการทำบทบรรยายใต้ภาพตั้งแต่แปลจนตั้งเวลา',
    topic_th: 'การแปลบทบรรยายใต้ภาพ',
    plo: {
      action_verb_th: 'แปล',
      bloom_level: 'apply',
      statement_th:
        'แปลบทบรรยายใต้ภาพสำหรับภาพยนตร์และซีรีส์ให้กระชับ ตรงจังหวะภาพ และผู้ชมอ่านทันได้',
      statement_en: null,
      rationale_th: 'มีผู้ใช้บัณฑิตเพียงรายเดียวที่ระบุ จึงเป็นผลลัพธ์เสริมสำหรับผู้เรียนที่เลือกเส้นทางสื่อบันเทิง',
      distinctive_feature_th: null,
    },
  },
  {
    key: 'rewrite',
    ksec: 'S',
    bloom: 'apply',
    fallback: true,
    statement_th: '',
    statement_en: null,
    rationale_th: '',
    topic_th: 'การเรียบเรียงถ้อยคำภาษาไทย',
    plo: {
      action_verb_th: 'เรียบเรียง',
      bloom_level: 'apply',
      statement_th: 'เรียบเรียงงานแปลภาษาไทยให้อ่านเป็นธรรมชาติและกระชับตามลักษณะของสื่อได้',
      statement_en: null,
      rationale_th: 'ผู้ใช้บัณฑิตและผู้ทรงคุณวุฒิระบุว่างานแปลที่ถูกต้องแต่อ่านไม่เป็นธรรมชาติยังใช้ไม่ได้',
      distinctive_feature_th: null,
    },
  },
  {
    key: 'marketing',
    ksec: 'S',
    bloom: 'apply',
    statement_th:
      'ต้องการบัณฑิตที่วางแผนการตลาดดิจิทัลและวัดผลโฆษณาออนไลน์เพื่อหาลูกค้างานแปลด้วยตนเอง',
    statement_en: null,
    rationale_th: 'ทั้งสองทักษะเป็นการตลาดออนไลน์ที่ผู้ตอบเชื่อมกับการรับงานแปลอิสระ',
    topic_th: 'การตลาดดิจิทัลสำหรับนักแปลอิสระ',
    plo: {
      action_verb_th: 'วางแผน',
      bloom_level: 'create',
      statement_th: 'วางแผนการตลาดดิจิทัลสำหรับบริการแปลอิสระและวัดผลโฆษณาออนไลน์ได้',
      statement_en: null,
      rationale_th: 'ผู้ประกอบการและศิษย์เก่าที่ทำงานอิสระระบุ',
      distinctive_feature_th: null,
    },
  },
  {
    key: 'network',
    ksec: 'C',
    bloom: 'apply',
    statement_th:
      'ต้องการหลักสูตรที่สร้างเครือข่ายความร่วมมือและจัดกิจกรรมแลกเปลี่ยนกับมหาวิทยาลัยในภูมิภาคอาเซียน',
    statement_en: null,
    rationale_th: 'ทั้งสองทักษะพูดถึงความร่วมมือระหว่างสถาบัน ซึ่งเป็นงานของคณะมากกว่าของบัณฑิต',
    topic_th: 'ความร่วมมือระหว่างประเทศ',
    plo: {
      action_verb_th: 'ประสานงาน',
      bloom_level: 'apply',
      statement_th: 'ประสานงานโครงการแลกเปลี่ยนทางวิชาการกับสถาบันต่างประเทศได้',
      statement_en: null,
      rationale_th: 'มาจากวิสัยทัศน์ของคณะและผู้สมัครเรียน',
      distinctive_feature_th: null,
    },
  },
]

const NEED_BY_KEY = new Map(TRANSLATION_NEEDS.map((n) => [n.key, n]))

/** Skill name → the Need it belongs to; how combine() regroups re-extracted
 *  skills without remembering anything from the previous run. */
const NEED_KEY_BY_SKILL_NAME = new Map(TRANSLATION_SKILLS.map((s) => [s.name, s.need]))

/** For evidence the designer typed into the mock: which skill names a generic
 *  extraction can come up with, one per in-scope Need. */
const GENERIC_SKILLS: SkillSeed[] = TRANSLATION_NEEDS.filter(
  (n) => !n.fallback && n.key !== 'marketing' && n.key !== 'network',
).map((n) => {
  const first = TRANSLATION_SKILLS.find((s) => s.need === n.key)
  if (!first) throw new Error(`mock: no skill seed for ${n.key}`)
  return first
})

// ----------------------------------------------------------------------------
// Evidence
// ----------------------------------------------------------------------------

function evidenceFromSeeds(
  programId: string,
  seeds: EvidenceSeed[],
  collectedAt: string,
): EvidenceRow[] {
  return seeds.map((s) => ({
    evidence_id: fakeUuid(`${programId}:evidence:${s.key}`),
    program_id: programId,
    stakeholder_type: s.type,
    source_name: s.source,
    source_url: null,
    raw_text_th: s.sentences.join(' '),
    raw_text_en: null,
    collected_at: collectedAt,
    classification: classifyEvidence(s.type),
    classification_rationale_th: null,
    // Where the mock remembers which seed an item came from, so extraction can
    // quote the authored spans. A real field on StakeholderEvidence.
    metadata: { mock_seed: s.key },
  }))
}

// ----------------------------------------------------------------------------
// Stage 2a: skill extraction
// ----------------------------------------------------------------------------

export interface ExtractionResult {
  skills: SkillRow[]
  dropped: number
}

/**
 * Skills for a programme's evidence.
 *
 * A seeded item yields its authored skills; anything else yields one generic
 * skill quoting the item's own opening words. `idFor` decides the ids: stable
 * for a seed, fresh uuids for a run — skill_extraction mints new ones every
 * time, which is what makes the "Need มาจากทักษะชุดก่อน" banner reachable.
 */
export function extractSkills(
  programId: string,
  evidence: EvidenceRow[],
  idFor: (key: string) => string = () => newId(),
): ExtractionResult {
  const raw: { seed: SkillSeed; ev: EvidenceRow; span: string; key: string }[] = []
  for (const ev of evidence) {
    const seedKey = typeof ev.metadata?.mock_seed === 'string' ? ev.metadata.mock_seed : null
    const seed = seedKey ? TRANSLATION_EVIDENCE.find((e) => e.key === seedKey) : undefined
    if (seed) {
      TRANSLATION_SKILLS.forEach((s, i) => {
        if (s.evidence !== seed.key) return
        const span = seed.sentences[s.sentence]
        // Grounding: a span that is no longer in the (edited) text is dropped,
        // as is_grounded would drop it.
        if (!ev.raw_text_th.includes(span)) return
        raw.push({ seed: s, ev, span, key: `${seed.key}:${i}` })
      })
    } else {
      const text = ev.raw_text_th.trim()
      if (!text) continue
      const pick = GENERIC_SKILLS[hashIndex(ev.evidence_id, GENERIC_SKILLS.length)]
      raw.push({ seed: pick, ev, span: openingWords(text), key: `generic:${ev.evidence_id}` })
    }
  }

  // Classification is a cross-evidence property, decided once every item is in
  // (skill_extraction.classify_skills): requirement wins, then off-field means
  // unclassified, then a name in more than one item is a need.
  const itemsPerName = new Map<string, Set<string>>()
  for (const r of raw) {
    const set = itemsPerName.get(r.seed.name) ?? new Set<string>()
    set.add(r.ev.evidence_id)
    itemsPerName.set(r.seed.name, set)
  }
  const corpus = scoringCorpus(raw.map((r) => [r.ev.evidence_id, r.ev.stakeholder_type]))

  const skills = raw.map(({ seed, ev, span, key }, i): SkillRow => {
    const inField = seed.inField !== false
    const classification: SkillRow['classification'] = REQUIREMENT_TYPES.has(ev.stakeholder_type)
      ? 'requirement'
      : !inField
        ? 'unclassified'
        : (itemsPerName.get(seed.name)?.size ?? 0) > 1
          ? 'need'
          : 'want'
    return {
      skill_id: idFor(`${programId}:skill:${key}`),
      program_id: programId,
      skill_name_th: seed.name,
      skill_name_en: seed.nameEn,
      ksec_category: seed.ksec,
      bloom_level: seed.bloom,
      evidence_span_th: span,
      source_evidence_id: ev.evidence_id,
      source_stakeholder_type: ev.stakeholder_type,
      classification,
      is_field_relevant: inField,
      is_graduate_capability: seed.graduate !== false,
      extraction_method: 'llm',
      confidence: 0.72 + ((i * 7) % 23) / 100,
      importance_score: demandScore([...(itemsPerName.get(seed.name) ?? [])], corpus),
    }
  })

  // One or two invented quotes the grounding check threw away — enough for the
  // warning on the skills tab to have something to say on a big corpus.
  const dropped = evidence.length >= 6 ? 2 : evidence.length >= 3 ? 1 : 0
  return { skills, dropped }
}

function openingWords(text: string): string {
  if (text.length <= 80) return text
  const cut = text.indexOf(' ', 40)
  return (cut > 0 && cut <= 100 ? text.slice(0, cut) : text.slice(0, 80)).trim()
}

function hashIndex(seed: string, size: number): number {
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (Math.imul(h, 31) + seed.charCodeAt(i)) >>> 0
  return h % size
}

// ----------------------------------------------------------------------------
// demand.py
// ----------------------------------------------------------------------------

function scoringCorpus(pairs: [string, string][]): Map<string, string> {
  return new Map(pairs)
}

/** compute_demand_score: 0.20 mandate + 0.55 practitioner share + 0.25 other
 *  share, each frequency block a share of its own audience. */
function demandScore(sourceEvidenceIds: string[], corpus: Map<string, string>): number {
  const named = new Set(sourceEvidenceIds.filter((id) => corpus.has(id)))
  const mandated = [...named].some((id) => corpus.get(id) === 'professional_council')
  const practitionerTotal = [...corpus.values()].filter((t) => PRACTITIONER_TYPES.has(t)).length
  const otherTotal = corpus.size - practitionerTotal
  const practitionerNamed = [...named].filter((id) => PRACTITIONER_TYPES.has(corpus.get(id) ?? '')).length
  const otherNamed = named.size - practitionerNamed
  let score = 0.2 * (mandated ? 1 : 0)
  if (practitionerTotal) score += (0.55 * practitionerNamed) / practitionerTotal
  if (otherTotal) score += (0.25 * otherNamed) / otherTotal
  return Math.round(score * 10000) / 10000
}

// ----------------------------------------------------------------------------
// Stage 2b: need combination
// ----------------------------------------------------------------------------

/**
 * Needs from the stored skills. Grouping is by the Need each skill name was
 * authored under — standing in for llm_clustering — and stays inside one KSEC
 * bucket by construction. Every derived field is computed from the members.
 */
export function combineNeeds(
  programId: string,
  skills: SkillRow[],
  idFor: (key: string) => string = () => newId(),
): NeedRow[] {
  const groups = new Map<string, SkillRow[]>()
  for (const s of skills) {
    const key = NEED_KEY_BY_SKILL_NAME.get(s.skill_name_th)
    if (!key) continue
    const list = groups.get(key) ?? []
    list.push(s)
    groups.set(key, list)
  }
  const corpus = scoringCorpus(skills.map((s) => [s.source_evidence_id, s.source_stakeholder_type]))

  const needs: NeedRow[] = []
  for (const seed of TRANSLATION_NEEDS) {
    const members = groups.get(seed.key)
    if (!members?.length) continue
    const evidenceIds = [...new Set(members.map((m) => m.source_evidence_id))]
    const coverage: Record<string, number> = {}
    const classCoverage: Record<string, number> = {}
    for (const m of members) {
      coverage[m.source_stakeholder_type] = (coverage[m.source_stakeholder_type] ?? 0) + 1
      classCoverage[m.classification] = (classCoverage[m.classification] ?? 0) + 1
    }
    const names = [...new Set(members.map((m) => m.skill_name_th))]
    const fallbackStatement = `${REVIEW_MARKER_TH} ${names.join(', ')}`
    needs.push({
      need_id: idFor(`${programId}:need:${seed.key}`),
      program_id: programId,
      statement_th: seed.fallback ? fallbackStatement : seed.statement_th,
      statement_en: seed.statement_en,
      rationale_th: seed.fallback
        ? `${REVIEW_MARKER_TH} ไม่มีเหตุผลประกอบ เพราะขั้นเขียนประโยคไม่สำเร็จ ผู้ออกแบบหลักสูตรต้องเขียนทั้งประโยคและเหตุผลเอง`
        : seed.rationale_th,
      ksec_categories: [seed.ksec],
      bloom_level: seed.bloom,
      member_skill_ids: members.map((m) => m.skill_id),
      top_skill_ids: members.slice(0, 3).map((m) => m.skill_id),
      merged_from: [],
      merged_into: null,
      merged_by: null,
      excluded_at: null,
      merge_reason_th: '',
      source_evidence_ids: evidenceIds,
      stakeholder_coverage: coverage,
      source_stakeholder_types: STAKEHOLDER_TYPES.filter((t) => t in coverage),
      freq: members.length,
      demand_score: demandScore(evidenceIds, corpus),
      is_optional: isOptionalGroup(classCoverage, evidenceIds.length),
      classification_coverage: classCoverage,
      in_field_skill_count: members.filter((m) => m.is_field_relevant).length,
      graduate_capability_skill_count: members.filter((m) => m.is_graduate_capability).length,
    })
  }
  return sortNeeds(mergeMockDuplicates(needs, idFor(`${programId}:need:merged`)))
}

/** is_optional_group: a mandate makes a group core, a group of nothing but
 *  unclassified members is optional, otherwise one evidence item is optional. */
function isOptionalGroup(classCoverage: Record<string, number>, evidenceCount: number): boolean {
  if ((classCoverage.requirement ?? 0) > 0) return false
  const total = Object.values(classCoverage).reduce((a, b) => a + b, 0)
  if (total > 0 && (classCoverage.unclassified ?? 0) === total) return true
  return evidenceCount <= 1
}

/** Needs the downstream stages read: merged ones and never-merged ones, not the
 *  originals a merge folded away and not the ones the designer excluded
 *  (`NeedRepository.list_active_by_program`). */
export function activeNeeds(needs: NeedRow[]): NeedRow[] {
  return needs.filter((n) => n.merged_into === null && n.excluded_at === null)
}

/** The scenario's one merged Need: Agent 2 judged "ปรับเนื้อหาสู่ผู้ใช้ไทย"
 *  (S) and "จรรยาบรรณ" (E) to ask for one capability, so the two originals stay
 *  stored, marked `merged_into`, and a third row carries both tags. Applies only
 *  when both originals exist. */
const MERGE_PAIR = ['l10n', 'ethics'] as const

function mergeMockDuplicates(needs: NeedRow[], mergedId: string): NeedRow[] {
  const [a, b] = MERGE_PAIR.map((key) => {
    const seed = NEED_BY_KEY.get(key)
    return needs.find((n) => seed !== undefined && n.statement_th === seed.statement_th)
  })
  if (!a || !b) return needs
  const merged: NeedRow = {
    ...a,
    need_id: mergedId,
    ksec_categories: [...new Set([...a.ksec_categories, ...b.ksec_categories])],
    member_skill_ids: [...a.member_skill_ids, ...b.member_skill_ids],
    top_skill_ids: [...a.top_skill_ids.slice(0, 2), ...b.top_skill_ids.slice(0, 2)],
    source_evidence_ids: [...new Set([...a.source_evidence_ids, ...b.source_evidence_ids])],
    source_stakeholder_types: STAKEHOLDER_TYPES.filter(
      (t) => a.source_stakeholder_types.includes(t) || b.source_stakeholder_types.includes(t),
    ),
    freq: a.freq + b.freq,
    demand_score: Math.max(a.demand_score, b.demand_score),
    is_optional: a.is_optional && b.is_optional,
    in_field_skill_count: a.in_field_skill_count + b.in_field_skill_count,
    graduate_capability_skill_count: a.graduate_capability_skill_count + b.graduate_capability_skill_count,
    merged_from: [a.need_id, b.need_id],
    merged_into: null,
    merged_by: 'agent',
    excluded_at: null,
    merge_reason_th:
      'ทั้งสองข้อพูดถึงการทำงานกับผู้ว่าจ้างและผู้ใช้ชาวไทยอย่างรับผิดชอบ ผู้มีส่วนได้ส่วนเสียเอ่ยถึงสิ่งเดียวกันคนละมุม จึงรวมเป็นความสามารถเดียว',
  }
  return needs
    .map((n) => (n === a || n === b ? { ...n, merged_into: merged.need_id } : n))
    .concat(merged)
}

/** Agent 1's stored output: the skills grouped inside one KSEC bucket (E and C
 *  share `EC`), the way the Need seeds group them. */
export function skillGroupsOf(programId: string, skills: SkillRow[]) {
  const byKey = new Map<string, SkillRow[]>()
  for (const s of skills) {
    const key = NEED_KEY_BY_SKILL_NAME.get(s.skill_name_th)
    if (!key) continue
    byKey.set(key, [...(byKey.get(key) ?? []), s])
  }
  const corpus = scoringCorpus(skills.map((s) => [s.source_evidence_id, s.source_stakeholder_type]))
  return TRANSLATION_NEEDS.flatMap((seed) => {
    const members = byKey.get(seed.key)
    if (!members?.length) return []
    const freq = new Map<string, number>()
    for (const m of members) freq.set(m.skill_name_th, (freq.get(m.skill_name_th) ?? 0) + 1)
    const names = [...freq.entries()].sort((x, y) => y[1] - x[1])
    const evidenceIds = [...new Set(members.map((m) => m.source_evidence_id))]
    const coverage: Record<string, number> = {}
    const classCoverage: Record<string, number> = {}
    for (const m of members) {
      coverage[m.source_stakeholder_type] = (coverage[m.source_stakeholder_type] ?? 0) + 1
      classCoverage[m.classification] = (classCoverage[m.classification] ?? 0) + 1
    }
    return [
      {
        group_id: newId(),
        program_id: programId,
        is_graduate: members.every((m) => m.is_graduate_capability),
        ksec: seed.ksec === 'E' || seed.ksec === 'C' ? 'EC' : seed.ksec,
        skill_ids: members.map((m) => m.skill_id),
        evidence_ids: evidenceIds,
        skill_names: names.map(([n]) => n),
        skill_frequencies: names.map(([, c]) => c),
        bloom_level: seed.bloom,
        demand_score: demandScore(evidenceIds, corpus),
        is_optional: isOptionalGroup(classCoverage, evidenceIds.length),
        classification_coverage: classCoverage,
        stakeholder_coverage: coverage,
        stakeholder_types: STAKEHOLDER_TYPES.filter((t) => t in coverage),
        in_field_skill_count: members.filter((m) => m.is_field_relevant).length,
        graduate_capability_skill_count: members.filter((m) => m.is_graduate_capability).length,
      },
    ]
  })
}

export function sortNeeds(needs: NeedRow[]): NeedRow[] {
  return [...needs].sort((a, b) => b.demand_score - a.demand_score)
}

// ----------------------------------------------------------------------------
// Stage 3: PLO synthesis
// ----------------------------------------------------------------------------

/** The authored outcome for a Need, found by statement (or, for a rewritten or
 *  fallback Need, by its member skills). */
function seedForNeed(need: NeedRow, skills: SkillRow[]): NeedSeed | undefined {
  const byStatement = TRANSLATION_NEEDS.find((n) => !n.fallback && n.statement_th === need.statement_th)
  if (byStatement) return byStatement
  const memberNames = skills
    .filter((s) => need.member_skill_ids.includes(s.skill_id))
    .map((s) => s.skill_name_th)
  const key = memberNames.map((n) => NEED_KEY_BY_SKILL_NAME.get(n)).find(Boolean)
  return key ? NEED_BY_KEY.get(key) : undefined
}

/** A verdict the validation agent passed: all five true, no findings. */
export function passingCheck(): SMARTCheck {
  return {
    specific: true,
    measurable: true,
    achievable: true,
    relevant: true,
    timely: true,
    notes_th: null,
    findings: [],
  }
}

export function formatPloId(index: number, optional: boolean): string {
  return `${optional ? 'OPT' : 'PLO'}${index}`
}

/** PLORepository.list_by_program's order: core first, then by id length, then id. */
export function sortPlos(plos: PloRow[]): PloRow[] {
  return [...plos].sort(
    (a, b) =>
      Number(a.is_optional) - Number(b.is_optional) ||
      a.plo_id.length - b.plo_id.length ||
      a.plo_id.localeCompare(b.plo_id),
  )
}

export function stripOutcomePrefix(statement: string): string {
  return statement
    .replace(/^\s*(?:(?:บัณฑิต|ผู้เรียน|ผู้สำเร็จการศึกษา)\s*(?:จะ)?\s*(?:มีความ)?)?สามารถ\s*(?:ใน(?:การ)?)?\s*/, '')
    .trimStart()
}

export function makePlo(
  programId: string,
  ploId: string,
  need: NeedRow[],
  seed: PloSeed,
  isOptional: boolean,
): PloRow {
  return {
    plo_id: ploId,
    program_id: programId,
    // plo_synthesis._adopt strips the subject prefix from every shippable draft.
    statement_th: stripOutcomePrefix(seed.statement_th),
    statement_en: seed.statement_en,
    bloom_level: seed.bloom_level,
    action_verb_th: seed.action_verb_th,
    smart_check: passingCheck(),
    source_need_ids: need.map((n) => n.need_id),
    source_evidence_ids: [...new Set(need.flatMap((n) => n.source_evidence_ids))],
    rationale_th: seed.rationale_th,
    distinctive_feature_th: seed.distinctive_feature_th,
    version: 1,
    smart_retry_count: 0,
    smart_escalated: false,
    soft_flags: [],
    smart_validated_by: 'agent',
    smart_diagnosis_th: null,
    is_optional: isOptional,
  }
}

/**
 * One PLO per Need, the way plo_synthesis selects them: the scope guard drops
 * out-of-scope Needs first, the core series is capped at MAX_CORE_PLOS by
 * demand, optional Needs become OPTn outside the cap.
 *
 * Simplification: a `[ต้องทบทวน]` fallback Need is skipped. The real stage
 * would hand that sentence to the model; the mock has no outcome to invent
 * for a list of words.
 */
export function synthesizePlos(programId: string, needs: NeedRow[], skills: SkillRow[]): PloRow[] {
  const usable = sortNeeds(activeNeeds(needs)).filter(
    (n) => scopeVerdict(n) === 'in_scope' && !n.statement_th.startsWith(REVIEW_MARKER_TH),
  )
  const core = usable.filter((n) => !n.is_optional).slice(0, MAX_CORE_PLOS)
  const optional = usable.filter((n) => n.is_optional)
  const plos: PloRow[] = []
  const draft = (list: NeedRow[], isOptional: boolean) => {
    list.forEach((need, i) => {
      const seed = seedForNeed(need, skills)?.plo ?? genericPlo(need)
      plos.push(makePlo(programId, formatPloId(i + 1, isOptional), [need], seed, isOptional))
    })
  }
  draft(core, false)
  draft(optional, true)

  // A fresh run is not all green: the validator usually has something to say
  // about one outcome, and the page should show that the common case looks so.
  const flagged = plos.find((p) => p.action_verb_th === 'จัดทำ') ?? plos[2]
  if (flagged) applySoftFindings(flagged)
  return sortPlos(plos)
}

/**
 * A set review shaped like the stored one, built from whatever PLOs and Needs the
 * mock holds now so every id in it resolves on the other pages.
 *
 * It is a fixture, not a reviewer: the code facts (current KSEC, counts,
 * histogram, unused Needs) are derived the way the backend derives them, and the
 * judgements are fixed sentences chosen so every part of the page has something
 * to draw — one KSEC disagreement, one Bloom suggestion, one redundancy group,
 * one `consider` and one `ok_to_leave`. The counts, missing domains and flags
 * are all derived from the same rows the table shows, so the page never
 * disagrees with itself; a set with no E or C outcome draws the missing chips.
 */
export function buildMockReview(
  programId: string,
  plos: PloRow[],
  needs: NeedRow[],
  degreeLevel: string,
): PLOSetReview {
  const sorted = sortPlos(plos)
  const needById = new Map(needs.map((n) => [n.need_id, n]))
  needs = activeNeeds(needs)
  const currentOf = (p: PloRow): string[] => {
    const found = new Set<string>()
    for (const id of p.source_need_ids) {
      for (const k of needById.get(id)?.ksec_categories ?? []) {
        if (k === 'EC') {
          found.add('E')
          found.add('C')
        } else found.add(k)
      }
    }
    return ['K', 'S', 'E', 'C'].filter((d) => found.has(d))
  }

  const ksec = sorted.map((p, i) => {
    const current = currentOf(p)
    // The first outcome is the one the reviewer disagrees on: it proposes a
    // second domain the outcome's Need does not carry.
    const extra = i === 0 ? ['E', 'C', 'S', 'K'].find((d) => !current.includes(d)) : undefined
    const suggested = extra ? [...current, extra].sort((a, b) => 'KSEC'.indexOf(a) - 'KSEC'.indexOf(b)) : current
    return {
      plo_id: p.plo_id,
      current,
      suggested,
      agrees: suggested.join('') === current.join(''),
      reason_th: extra
        ? `ข้อความ PLO ยังมีส่วนของหมวด ${extra} ปนอยู่ด้วย นอกเหนือจากหมวดของ Need ต้นทาง`
        : 'หมวดตรงกับสิ่งที่ข้อความ PLO ให้บัณฑิตทำ',
      agreed_runs: extra ? 2 : 3,
    }
  })

  const KSEC_DOMAINS = ['K', 'S', 'E', 'C'] as const
  const ksecCounts: Record<string, number> = { K: 0, S: 0, E: 0, C: 0 }
  for (const row of ksec) for (const d of row.current) ksecCounts[d] += 1
  // Missing and flags follow from the counts, by the rules the backend applies,
  // so every figure on the page agrees with the table beside it.
  const missing = KSEC_DOMAINS.filter((d) => ksecCounts[d] === 0)
  const ksecFlags: string[] = []
  if (sorted.length > 0 && ksecCounts.S + ksecCounts.E + ksecCounts.C === 0) ksecFlags.push('all_k')
  if (sorted.length > 0 && ksecCounts.E === 0 && ksecCounts.C === 0) ksecFlags.push('no_e_or_c')

  const bloomCounts: Record<string, number> = Object.fromEntries(BLOOM_LEVELS.map((l) => [l, 0]))
  for (const p of sorted) bloomCounts[p.bloom_level] = (bloomCounts[p.bloom_level] ?? 0) + 1
  const belowApply = (bloomCounts.remember ?? 0) + (bloomCounts.understand ?? 0)

  const toRevise = sorted.find((p) => p.bloom_level === 'apply') ?? sorted[0]
  const bloom = toRevise
    ? [
        {
          plo_id: toRevise.plo_id,
          declared: toRevise.bloom_level,
          suggested_level: toRevise.bloom_level === 'analyze' ? 'evaluate' : 'analyze',
          reason_th: 'งานที่ข้อความ PLO ระบุต้องเลือกระหว่างวิธีทำ ซึ่งสูงกว่าระดับที่ประกาศไว้',
          agreed_runs: 3,
        },
      ]
    : []

  const cited = new Set(sorted.flatMap((p) => p.source_need_ids))
  const unusedNeeds: UnusedNeedFinding[] = needs
    .filter((n) => !cited.has(n.need_id))
    .sort((a, b) => b.demand_score - a.demand_score)
    .slice(0, 2)
    .map((n, i) => {
      const verdict = scopeVerdict(n)
      return {
        need_id: n.need_id,
        statement_th: n.statement_th,
        demand_score: n.demand_score,
        ksec_categories: n.ksec_categories,
        stakeholder_types: n.source_stakeholder_types,
        exclusion: n.statement_th.startsWith(REVIEW_MARKER_TH)
          ? 'unwritten'
          : verdict === 'in_scope'
            ? 'lost_on_demand'
            : 'out_of_scope',
        verdict: i === 0 ? 'consider' : 'ok_to_leave',
        reason_th:
          i === 0
            ? 'หลายฝ่ายเอ่ยถึงความต้องการนี้ และยังไม่มี PLO ข้อใดครอบคลุม'
            : 'เป็นงานของอีกวิชาชีพ ไม่ใช่สิ่งที่บัณฑิตสาขานี้ต้องทำเอง',
        agreed_runs: 3,
      }
    })

  return {
    program_id: programId,
    plo_fingerprint: 'mock',
    model: 'mock/qa-agent',
    created_at: nowIso(),
    redundancies:
      sorted.length >= 2
        ? [
            {
              plo_ids: [sorted[0].plo_id, sorted[1].plo_id],
              reason_th: 'ทั้งสองข้อให้บัณฑิตทำงานเดียวกันกับเอกสารประเภทเดียวกัน ต่างกันที่ถ้อยคำ',
              suggestion_th: 'รวมสอง Need ที่หน้าสังเคราะห์ PLO ให้เหลือ PLO ข้อเดียว',
              agreed_runs: 3,
            },
            // Seen in one run of three: below the threshold, so it draws in the
            // "พบไม่ถึงเกณฑ์" fold rather than the main list.
            ...(sorted.length >= 4
              ? [
                  {
                    plo_ids: [sorted[2].plo_id, sorted[3].plo_id],
                    reason_th: 'บางรอบเห็นว่าสองข้อนี้ใช้กริยาและวัตถุใกล้กัน',
                    suggestion_th: '',
                    agreed_runs: 1,
                  },
                ]
              : []),
          ]
        : [],
    ksec,
    bloom,
    bloom_distribution_th: 'PLO ส่วนใหญ่อยู่ที่ระดับประยุกต์ใช้ ซึ่งพอดีกับหลักสูตรระดับปริญญาตรี',
    summary_th:
      'ชุด PLO ครอบคลุมงานแปลหลักของสาขา มีสองข้อที่ซ้ำกันและหนึ่งข้อที่หมวดสมรรถนะควรทบทวน',
    ksec_coverage: { counts: ksecCounts, missing, flags: ksecFlags },
    bloom_histogram: {
      counts: bloomCounts,
      degree_level: degreeLevel,
      flags: belowApply * 2 > sorted.length ? ['below_apply_majority'] : [],
    },
    coverage_th: 'งานแปล ล่าม และการใช้เครื่องมือช่วยแปลมี PLO รองรับ',
    unused_needs: unusedNeeds,
    reviewed_by: 'agent',
    code_only_reason: null,
    runs_requested: 3,
    runs_succeeded: 3,
    agreement_threshold: 2,
    dropped_findings: { redundancy: 1 },
    tool_calls: [
      { tool: 'read_need', arg: unusedNeeds[0]?.need_id ?? sorted[0]?.plo_id ?? '' },
      { tool: 'read_plo', arg: sorted[0]?.plo_id ?? '' },
    ],
  }
}

function genericPlo(need: NeedRow): PloSeed {
  return {
    action_verb_th: 'ประยุกต์',
    bloom_level: 'apply',
    statement_th: `ประยุกต์ทักษะตามความต้องการ "${need.statement_th.slice(0, 40)}" ในงานแปลจริงได้`,
    statement_en: null,
    rationale_th: 'ร่างจาก Need ที่ไม่มีแม่แบบใน mock',
    distinctive_feature_th: null,
  }
}

/** Two soft verdicts: they set their SMARTCheck fields and soft_flags, never
 *  escalate. */
export function applySoftFindings(plo: PloRow): void {
  const findings: SmartFinding[] = [
    {
      criterion: 'S_object',
      severity: 'soft',
      note_th: '"งานแปลร่วมกับทีม" ยังกว้าง ไม่บอกว่าเป็นงานแปลประเภทใดหรือขนาดเท่าใด',
    },
    {
      criterion: 'M_assessable',
      severity: 'soft',
      note_th: 'ยังไม่ชัดว่าจะวัด "ความสอดคล้องทั้งโครงการ" ด้วยชิ้นงานหรือเกณฑ์ใด',
    },
  ]
  plo.smart_check = { ...passingCheck(), specific: false, measurable: false, findings }
  plo.soft_flags = findings.map((f) => f.criterion)
  plo.smart_diagnosis_th =
    'ประโยคผ่านเกณฑ์บังคับทั้งหมด แต่กรรมของกริยายังกว้าง แนะนำให้ระบุประเภทงานแปลและชิ้นงานที่ใช้ประเมิน เช่น "แฟ้มงานแปลเอกสารธุรกิจไม่น้อยกว่า 5,000 คำ"'
}

/** Wording for a merged outcome (POST /plos/from-needs). */
export function mergedPloSeed(needs: NeedRow[], skills: SkillRow[]): PloSeed {
  const topics = [...new Set(needs.map((n) => seedForNeed(n, skills)?.topic_th ?? n.statement_th.slice(0, 30)))]
  const joined =
    topics.length <= 2 ? topics.join('และ') : `${topics.slice(0, -1).join(' ')} และ${topics[topics.length - 1]}`
  const top = Math.max(...needs.map((n) => BLOOM_LEVELS.indexOf(n.bloom_level)))
  return {
    action_verb_th: 'ปฏิบัติงาน',
    bloom_level: BLOOM_LEVELS[Math.max(top, 2)],
    statement_th: `ปฏิบัติงานแปลที่ผสาน${joined}ให้ได้ผลงานตามมาตรฐานวิชาชีพได้`,
    statement_en: null,
    rationale_th: `รวมจาก Need ${needs.length} รายการที่ผู้ออกแบบหลักสูตรเลือก เพื่อให้ผลลัพธ์ข้อเดียวตอบความต้องการทั้งหมด`,
    distinctive_feature_th: null,
  }
}

// ----------------------------------------------------------------------------
// Scenarios
// ----------------------------------------------------------------------------

const TRANSLATION_PROGRAM_ID = 'program'

function translationProgram(programId: string, createdAt: string): ProgramRow {
  return program({
    program_id: programId,
    field: 'การแปล',
    scope_th:
      'หลักสูตรนี้ครอบคลุม การแปลเอกสารเฉพาะทางไทย-อังกฤษ การล่าม การใช้เทคโนโลยีช่วยแปล และการปรับเนื้อหาข้ามวัฒนธรรม',
    created_at: createdAt,
  })
}

function session(
  programId: string,
  key: string,
  partial: Partial<SessionRow> & Pick<SessionRow, 'status' | 'created_at'>,
): SessionRow {
  const sessionId = fakeUuid(`${programId}:session:${key}`)
  return {
    session_id: sessionId,
    program_id: programId,
    thread_id: `${programId}:${sessionId}`,
    current_stage: null,
    suspended_message: null,
    updated_at: partial.created_at,
    due_at: null,
    target: CHECKPOINTS.length,
    will_fail: false,
    ...partial,
  }
}

/** The translation programme up to and including its Needs. */
function seedTranslation(db: MockDb, programId: string, createdAt: string): void {
  db.programs.push(translationProgram(programId, createdAt))
  const evidence = evidenceFromSeeds(programId, TRANSLATION_EVIDENCE, createdAt)
  db.evidence.push(...evidence)
  const { skills } = extractSkills(programId, evidence, fakeUuid)
  db.skills.push(...skills)
  db.needs.push(...combineNeeds(programId, skills, fakeUuid))
}

/**
 * The PLO set for `complete`: one outcome per verdict state the two PLO pages
 * render. Keyed by Need so the states do not move when demand reorders.
 */
function seedCompletePlos(db: MockDb, programId: string): void {
  const needs = db.needs.filter((n) => n.program_id === programId)
  const skills = db.skills.filter((s) => s.program_id === programId)
  const plos = synthesizePlos(programId, needs, skills).map((p) => {
    // Reset the fresh-run soft finding; states are assigned explicitly below.
    p.smart_check = passingCheck()
    p.soft_flags = []
    p.smart_diagnosis_th = null
    return p
  })
  const byKey = (key: string): PloRow | undefined => {
    const seed = NEED_BY_KEY.get(key)
    return plos.find((p) => seed && p.action_verb_th === seed.plo.action_verb_th && p.rationale_th === seed.plo.rationale_th)
  }

  // Escalated: a forbidden word used, three repairs spent. Allowed on the model
  // only because smart_escalated is true.
  const qa = byKey('qa')
  if (qa) {
    Object.assign(qa, {
      action_verb_th: 'ตรวจแก้',
      statement_th:
        'ตรวจแก้งานแปลจากเครื่องแปลภาษาและ AI ให้ได้มาตรฐาน โดยเข้าใจเกณฑ์คุณภาพที่อุตสาหกรรมใช้',
      smart_escalated: true,
      smart_retry_count: 3,
      smart_validated_by: 'agent' satisfies ValidatedBy,
      smart_diagnosis_th:
        'ซ่อมสามรอบแล้วคำว่า "เข้าใจ" ยังกลับมาทุกครั้ง เพราะ Need เน้นการรู้เกณฑ์มากกว่าการใช้เกณฑ์ ให้เขียนใหม่โดยเปลี่ยนเป็นสิ่งที่ทำได้ เช่น "ประเมินคุณภาพงานแปลตามเกณฑ์…และระบุจุดที่ต้องแก้ไข"',
      smart_check: {
        ...passingCheck(),
        measurable: false,
        findings: [
          {
            criterion: 'M_forbidden',
            severity: 'hard',
            note_th:
              'Measurable ไม่ผ่าน: ห้ามใช้คำ รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก ให้แทนด้วยกริยาที่สังเกตได้ เช่น อธิบาย วิเคราะห์ ออกแบบ (คำที่มีคำห้ามอยู่ข้างในแต่ใช้ได้ เช่น จำแนก จำลอง รักษา ความรู้ เรียนรู้)',
          },
        ],
      },
    })
  }

  const cat = byKey('cat')
  if (cat) applySoftFindings(cat)

  const interp = byKey('interp')
  if (interp) {
    Object.assign(interp, {
      statement_th:
        'ถ่ายทอดสารระหว่างภาษาไทยและภาษาอังกฤษแบบล่ามพูดตามและแบบแปลสลับในการประชุม การเจรจาธุรกิจ และงานแถลงข่าวได้ครบถ้วนและทันเวลา',
      version: 2,
      smart_validated_by: 'stale' satisfies ValidatedBy,
      smart_diagnosis_th:
        'แก้ข้อความแล้ว ตรวจด้วยกฎพื้นฐานเท่านั้น — กด "ตรวจ SMART ซ้ำ" เพื่อให้ผู้ตรวจอ่านประโยคใหม่',
    })
  }

  const ling = byKey('ling')
  if (ling) {
    Object.assign(ling, {
      smart_validated_by: 'code_only' satisfies ValidatedBy,
      // The backend's own wording for an endpoint that failed
      // (smart_agent.code_only_result): the page shows it verbatim.
      smart_diagnosis_th: 'ไม่ได้ตรวจ (เรียกผู้ตรวจไม่สำเร็จ)',
      smart_check: passingCheck(),
    })
  }

  // A row from before the validator agent: the subject prefix was not yet
  // stripped, and its soft verdict survives as a bare flag with no finding.
  const ethics = byKey('ethics')
  if (ethics) {
    Object.assign(ethics, {
      statement_th: NEED_BY_KEY.get('ethics')?.plo.statement_th ?? ethics.statement_th,
      smart_validated_by: 'legacy' satisfies ValidatedBy,
      soft_flags: ['A_level'],
      smart_check: { ...passingCheck(), achievable: false },
    })
  }

  db.plos.push(...plos)
  const degree = db.programs.find((p) => p.program_id === programId)?.degree_level ?? 'bachelor'
  db.reviews = [...(db.reviews ?? []), buildMockReview(programId, plos, needs, degree)]
}

function seedEmpty(): MockDb {
  return emptyDb()
}

function seedCheckpoint(): MockDb {
  const db = emptyDb()
  seedTranslation(db, TRANSLATION_PROGRAM_ID, '2026-09-15T03:12:00')
  db.sessions.push(
    session(TRANSLATION_PROGRAM_ID, 'current', {
      status: 'suspended',
      current_stage: 'need_analysis',
      suspended_message: INTERRUPT_MESSAGE.need_analysis,
      created_at: '2026-10-04T02:40:00',
      updated_at: '2026-10-04T02:46:31',
      target: CHECKPOINTS.indexOf('need_analysis') + 1,
    }),
  )
  return db
}

function seedComplete(): MockDb {
  const db = emptyDb()
  seedTranslation(db, TRANSLATION_PROGRAM_ID, '2026-09-15T03:12:00')
  seedCompletePlos(db, TRANSLATION_PROGRAM_ID)
  db.sessions.push(
    session(TRANSLATION_PROGRAM_ID, 'current', {
      status: 'completed',
      // A completed run keeps the stage it last suspended at.
      current_stage: 'plo_synthesis',
      suspended_message: INTERRUPT_MESSAGE.plo_synthesis,
      created_at: '2026-10-03T07:05:00',
      updated_at: '2026-10-03T08:21:47',
    }),
    session(TRANSLATION_PROGRAM_ID, 'earlier', {
      status: 'rejected',
      current_stage: 'stakeholder_needs',
      suspended_message: INTERRUPT_MESSAGE.stakeholder_needs,
      created_at: '2026-09-28T04:10:00',
      updated_at: '2026-09-28T04:13:02',
    }),
  )
  return db
}

const THAI_COMM_EVIDENCE: EvidenceSeed[] = [
  {
    key: 'T1',
    type: 'employer',
    source: 'สัมภาษณ์บรรณาธิการสำนักพิมพ์แห่งหนึ่ง',
    sentences: [
      'บัณฑิตต้องเขียนบทความและข่าวประชาสัมพันธ์ภาษาไทยได้ถูกต้องตามหลักภาษา',
      'ต้องพิสูจน์อักษรและตรวจแก้ต้นฉบับได้รวดเร็ว',
    ],
  },
  {
    key: 'T2',
    type: 'institutional_direction',
    source: 'พันธกิจคณะมนุษยศาสตร์ มหาวิทยาลัยตัวอย่าง',
    sentences: ['คณะมุ่งส่งเสริมการใช้ภาษาไทยอย่างถูกต้องและสร้างสรรค์เพื่อสังคม'],
  },
  {
    key: 'T3',
    type: 'alumni',
    source: 'แบบสอบถามศิษย์เก่า (ข้อมูลก่อนปรับระบบจำแนก)',
    sentences: ['งานจริงต้องผลิตเนื้อหาสำหรับสื่อสังคมออนไลน์ทุกวัน'],
  },
]

function seedMany(): MockDb {
  const db = emptyDb()

  // Furthest along: the full translation set, approved through the report.
  seedTranslation(db, 'program', '2026-08-12T02:30:00')
  seedCompletePlos(db, 'program')
  db.sessions.push(
    session('program', 'current', {
      status: 'completed',
      // A completed run keeps the stage it last suspended at.
      current_stage: 'plo_synthesis',
      suspended_message: INTERRUPT_MESSAGE.plo_synthesis,
      created_at: '2026-09-30T06:00:00',
      updated_at: '2026-09-30T07:12:09',
    }),
  )

  // Waiting at the first gate. One evidence item still carries the
  // pre-migration `unclassified`, which the current model would refuse on read
  // — seeded only so the page's classify button has a reason to appear.
  db.programs.push(
    program({
      program_id: 'program-2',
      field: 'ภาษาไทยเพื่อการสื่อสาร',
      created_at: '2026-09-02T04:00:00',
    }),
  )
  const thaiEvidence = evidenceFromSeeds('program-2', THAI_COMM_EVIDENCE, '2026-09-02T04:00:00')
  thaiEvidence[2].classification = 'unclassified'
  db.evidence.push(...thaiEvidence)
  db.sessions.push(
    session('program-2', 'current', {
      status: 'suspended',
      current_stage: 'stakeholder_needs',
      suspended_message: INTERRUPT_MESSAGE.stakeholder_needs,
      created_at: '2026-10-02T03:00:00',
      updated_at: '2026-10-02T03:00:41',
      target: 1,
    }),
  )

  // Created, nothing else yet.
  db.programs.push(
    program({
      program_id: 'program-3',
      field: 'ภาษาจีนธุรกิจ',
      faculty: 'คณะศิลปศาสตร์',
      degree_level: 'master',
      duration_years: 2,
      created_at: '2026-09-20T09:45:00',
    }),
  )

  // An older programme from when intake still asked for a name, whose last
  // run failed in extraction.
  db.programs.push(
    program({
      program_id: 'program-4',
      name_th: 'หลักสูตรศิลปศาสตรบัณฑิต สาขาวิชาภาษาญี่ปุ่น',
      name_en: 'Bachelor of Arts Program in Japanese',
      field: 'ภาษาญี่ปุ่น',
      created_at: '2026-07-01T01:20:00',
    }),
  )
  db.evidence.push(
    ...evidenceFromSeeds(
      'program-4',
      [
        {
          key: 'J1',
          type: 'industry',
          source: 'สมาคมผู้ประกอบการญี่ปุ่นในจังหวัดตัวอย่าง (สมมติ)',
          sentences: ['ต้องการล่ามภาษาญี่ปุ่นประจำโรงงานที่สื่อสารเรื่องความปลอดภัยและคุณภาพได้'],
        },
        {
          key: 'J2',
          type: 'alumni',
          source: 'สนทนากลุ่มศิษย์เก่า',
          sentences: ['ควรฝึกเขียนอีเมลธุรกิจภาษาญี่ปุ่นตามธรรมเนียมองค์กร'],
        },
      ],
      '2026-07-01T01:20:00',
    ),
  )
  db.sessions.push(
    session('program-4', 'current', {
      status: 'failed',
      current_stage: 'stakeholder_needs',
      suspended_message:
        'สกัดทักษะไม่สำเร็จ — การเรียกโมเดลล้มเหลวทุกครั้งสำหรับหลักฐาน 2 รายการ (โควตาของผู้ให้บริการหมด) ลองรันใหม่ภายหลัง',
      created_at: '2026-07-03T02:00:00',
      updated_at: '2026-07-03T02:07:15',
    }),
  )
  return db
}

export function buildScenario(name: ScenarioName): { db: MockDb; selected: string } {
  switch (name) {
    case 'empty':
      return { db: seedEmpty(), selected: '' }
    case 'checkpoint':
      return { db: seedCheckpoint(), selected: TRANSLATION_PROGRAM_ID }
    case 'complete':
      return { db: seedComplete(), selected: TRANSLATION_PROGRAM_ID }
    case 'many':
      return { db: seedMany(), selected: 'program' }
  }
}

/** The program every page reads — useProgram's localStorage key. */
const SELECTED_PROGRAM_KEY = 'ca_program_id'

/** Replace the database with a scenario and select its program. The caller
 *  reloads (or has not rendered yet), so every page reads the new state. */
export function seedScenario(name: ScenarioName): void {
  const { db, selected } = buildScenario(name)
  replaceDb(db)
  setControls({ scenario: name })
  try {
    if (selected) localStorage.setItem(SELECTED_PROGRAM_KEY, selected)
    else localStorage.removeItem(SELECTED_PROGRAM_KEY)
  } catch {
    // Storage blocked: the pages fall back to "no program selected".
  }
}
