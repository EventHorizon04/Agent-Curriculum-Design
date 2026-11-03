import { FALLBACK_LABEL_TH, fallbackKind } from '../../constants/needPolicy'

export interface PickerNeed {
  need_id: string
  statement_th: string
  demand_score?: number
}

/** Short Thai reason a Need cannot be drafted from, or null when it can. The
 *  server answers 422 for these; saying so up front saves the round trip. */
export function unwrittenReason(n: PickerNeed): string | null {
  const kind = fallbackKind(n.statement_th)
  return kind ? `ยังไม่มีประโยค Need (${FALLBACK_LABEL_TH[kind]})` : null
}
