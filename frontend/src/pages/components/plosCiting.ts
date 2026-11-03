import type { PLO } from '../../types/plo'

/** Every PLO that cites at least one of `needIds` — the server's `plos_citing`
 *  rule, and so the set a merge over those Needs will replace. */
export function plosCiting(plos: PLO[], needIds: Iterable<string>): PLO[] {
  const wanted = new Set(needIds)
  if (wanted.size === 0) return []
  return plos.filter((p) => p.source_need_ids.some((id) => wanted.has(id)))
}
