/**
 * Whether a Need clears the scope guard, and how to say so in Thai.
 *
 * Mirrors `passes_scope_axes` in `stages/need_grouping.py`: half a Need's
 * members have to clear each axis, and the two axes are judged separately
 * because a designer does something different about each. Off-field means
 * deciding whether the model read the program's field correctly; not-a-graduate
 * -capability means deciding whether the sentence could be a learning outcome at
 * all.
 *
 * The verdict is derived from the two counters on the Need, never stored, and
 * no endpoint returns it — which is why both the report and the checkpoint can
 * ask for it without a round trip. It lived inside `PloReport.tsx` while that
 * page was the only caller (ticket 06 decided the report was the one place);
 * the need_combination checkpoint now needs the same judgement, and a second
 * copy of a 0.5 that mirrors a Python constant is how two pages come to disagree
 * about which Needs will survive.
 *
 * **A missing counter means "passed".** Absent is not zero: zero means the
 * extractor judged every member out of scope and disqualifies the Need, while
 * absent means nobody ever asked. A Need written before the guard existed has to
 * read exactly as it read then — the same default `models.Need` applies and the
 * same one the migration backfilled.
 */

/** Mirrors SCOPE_PASS_RATIO in need_grouping.py. */
export const SCOPE_PASS_RATIO = 0.5

export type ScopeVerdict = 'in_scope' | 'off_field' | 'not_graduate' | 'both'

/** The fields the verdict reads. Every caller's row type is a superset. */
export interface ScopeCounters {
  member_skill_ids?: string[]
  in_field_skill_count?: number
  graduate_capability_skill_count?: number
}

export function scopeVerdict(n: ScopeCounters): ScopeVerdict {
  const total = n.member_skill_ids?.length ?? 0
  const ratio = (count: number | undefined) =>
    count === undefined || total === 0 ? 1 : count / total
  const offField = ratio(n.in_field_skill_count) < SCOPE_PASS_RATIO
  const offGrad = ratio(n.graduate_capability_skill_count) < SCOPE_PASS_RATIO
  if (offField && offGrad) return 'both'
  if (offField) return 'off_field'
  if (offGrad) return 'not_graduate'
  return 'in_scope'
}

export const SCOPE_REASON_TH: Record<Exclude<ScopeVerdict, 'in_scope'>, string> = {
  off_field: 'นอกสาขา',
  not_graduate: 'ไม่ใช่สมรรถนะบัณฑิต',
  both: 'นอกขอบเขตหลักสูตร',
}

/**
 * The counts behind a verdict, as one line for a `title`.
 *
 * Both axes, always, whichever one failed: the margin on the axis that passed is
 * what says whether the verdict was close. A Need at 3/6 and one at 6/6 read the
 * same from the badge alone.
 */
export function scopeCountsTh(n: ScopeCounters): string {
  const total = n.member_skill_ids?.length ?? 0
  const show = (count: number | undefined) => (count === undefined ? total : count)
  return (
    `ในสาขา ${show(n.in_field_skill_count)}/${total}` +
    ` · เป็นสมรรถนะบัณฑิต ${show(n.graduate_capability_skill_count)}/${total}` +
    ` · เกณฑ์ผ่านคือครึ่งหนึ่งของสมาชิกในทั้งสองแกน`
  )
}
