import { Fragment, useMemo, useState } from 'react'
import {
  STAKEHOLDER_GROUPS,
  isRequirementStakeholder,
  stakeholderLabel,
} from '../../constants/stakeholder'

/**
 * `ksec_category`, `bloom_level`, and `classification` stay on the row because
 * the API sends them and the pipeline runs on them — they drive KSEC bucketing,
 * the one-verb rule, and need/want weighting. They are deliberately not
 * rendered: they are the machinery, not something a curriculum designer reviews
 * skill by skill. Drill-down still shows the quote and its source, which is what
 * a designer actually checks.
 */
export interface SkillRow {
  skill_id: string
  skill_name_th: string
  skill_name_en: string | null
  ksec_category: string
  bloom_level: string
  evidence_span_th: string
  source_evidence_id: string
  source_stakeholder_type: string
  classification: string
}

export interface EvidenceMeta {
  source_name: string
  stakeholder_type: string
  classification: string
}

interface StakeholderBucket {
  type: string
  skills: SkillRow[]
}

interface GroupSection {
  label: string
  buckets: StakeholderBucket[]
  total: number
}

/**
 * Group the extracted skills by the stakeholder that produced them.
 *
 * Two levels: external before internal (STAKEHOLDER_GROUPS' order), and inside
 * each group the requirement sources first — สภาวิชาชีพ and the institution's own
 * direction statements are mandates rather than demand signal, so a designer
 * reads them before anything else. The remaining order follows
 * STAKEHOLDER_GROUPS, which already mirrors the evidence weighting the backend
 * scores with.
 *
 * A stakeholder type with no extracted skills yields no box — an empty card
 * tells the designer nothing and pushes the populated ones off the screen.
 */
function buildSections(skills: SkillRow[]): GroupSection[] {
  const byType = new Map<string, SkillRow[]>()
  for (const skill of skills) {
    const existing = byType.get(skill.source_stakeholder_type)
    if (existing) existing.push(skill)
    else byType.set(skill.source_stakeholder_type, [skill])
  }

  return STAKEHOLDER_GROUPS.map(group => {
    const present = group.types.filter(t => byType.has(t))
    const ordered = [
      ...present.filter(isRequirementStakeholder),
      ...present.filter(t => !isRequirementStakeholder(t)),
    ]
    const buckets = ordered.map(type => ({ type, skills: byType.get(type) ?? [] }))
    return {
      label: group.label,
      buckets,
      total: buckets.reduce((sum, b) => sum + b.skills.length, 0),
    }
  }).filter(section => section.buckets.length > 0)
}

export default function SkillsByStakeholder({
  skills,
  evidenceById,
  droppedCount,
}: {
  skills: SkillRow[]
  evidenceById: Record<string, EvidenceMeta>
  droppedCount: number
}) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const sections = useMemo(() => buildSections(skills), [skills])

  const toggle = (skillId: string) => setExpanded(prev => (prev === skillId ? null : skillId))

  if (skills.length === 0) {
    return <p className="py-8 text-center text-sm text-gray-400">ยังไม่มีทักษะที่สกัดได้</p>
  }

  return (
    <div className="space-y-6">
      {droppedCount > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          ทิ้งไป {droppedCount} ทักษะ (ข้อความที่ยกอ้างไม่ตรงกับ evidence)
        </div>
      )}

      {sections.map(section => (
        <section key={section.label}>
          <div className="mb-2 flex items-center gap-3">
            <h2 className="text-sm font-semibold text-gray-700">{section.label}</h2>
            <div className="h-px flex-1 bg-gray-200" />
            <span className="text-xs text-gray-500">{section.total} ทักษะ</span>
          </div>

          <div className="space-y-3">
            {section.buckets.map(bucket => {
              return (
                <div
                  key={bucket.type}
                  className="overflow-hidden rounded-lg border border-gray-200 bg-white"
                >
                  <div className="flex items-center gap-2 border-b border-gray-100 bg-gray-50 px-3 py-2">
                    <span className="text-sm font-medium text-gray-800">
                      {stakeholderLabel(bucket.type)}
                    </span>
                    <span className="ml-auto text-xs text-gray-500">
                      {bucket.skills.length} ทักษะ
                    </span>
                  </div>

                  <ul className="divide-y divide-gray-100">
                    {bucket.skills.map(skill => {
                      const open = expanded === skill.skill_id
                      const evidence = evidenceById[skill.source_evidence_id]
                      return (
                        <Fragment key={skill.skill_id}>
                          <li>
                            <button
                              type="button"
                              onClick={() => toggle(skill.skill_id)}
                              aria-expanded={open}
                              className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-gray-50 focus:outline-none focus-visible:bg-blue-50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500"
                            >
                              <span className="flex-1 text-sm text-gray-800">
                                {skill.skill_name_th}
                                {skill.skill_name_en && (
                                  <span className="ml-2 text-xs italic text-gray-400">
                                    {skill.skill_name_en}
                                  </span>
                                )}
                              </span>
                            </button>
                          </li>
                          {open && (
                            <li className="bg-gray-50 px-3 py-2">
                              <p className="text-xs text-gray-500">ข้อความที่ยกอ้างจาก evidence:</p>
                              <blockquote className="mt-1 border-l-2 border-gray-300 pl-2 text-xs text-gray-700">
                                {skill.evidence_span_th}
                              </blockquote>
                              <p className="mt-1 text-xs text-gray-400">
                                จาก: {evidence?.source_name ?? skill.source_evidence_id}
                              </p>
                            </li>
                          )}
                        </Fragment>
                      )
                    })}
                  </ul>
                </div>
              )
            })}
          </div>
        </section>
      ))}
    </div>
  )
}
