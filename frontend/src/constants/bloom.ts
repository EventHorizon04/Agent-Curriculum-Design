/** Bloom levels in the order a designer reads them, lowest first. */
export const BLOOM_ORDER = ['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create'] as const

/** One label per level, shared by every page that names a Bloom level — the
 *  synthesis page, the report, and the set review, which would otherwise each
 *  keep a copy to drift. */
export const BLOOM_LABEL: Record<string, string> = {
  remember: 'Remember',
  understand: 'Understand',
  apply: 'Apply',
  analyze: 'Analyze',
  evaluate: 'Evaluate',
  create: 'Create',
}

export const bloomLabel = (level: string): string => BLOOM_LABEL[level] ?? level
