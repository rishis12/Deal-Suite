/** Shared types mirroring the Python pipeline — ready for a future FastAPI. */

export type ValidationStatus = 'pass' | 'degraded' | 'fail'

export type LlmProvider = 'anthropic' | 'openai' | 'gemini'

export type AppPhase = 'empty' | 'loading' | 'error' | 'ready' | 'generated'

export interface SessionKeys {
  llmProvider: LlmProvider
  llmApiKey: string
}

export interface SourceHealth {
  secEdgar: boolean
  twelveData: boolean
}

export interface RevenuePoint {
  year: number
  revenue: number
}

export interface Assumptions {
  /** Deal Structure */
  entryMultiple: number
  offerPremium: number
  leverageMultiple: number
  transactionFeePct: number
  /** Operating */
  revenueGrowth: number
  ebitdaMargin: number
  capexPct: number
  daPct: number
  nwcPct: number
  /** Debt Terms */
  interestRate: number
  mandatoryAmortPct: number
  /** Exit */
  exitYear: number
  exitMultiple: number
  taxRate: number
}

export type AssumptionKey = keyof Assumptions

export type FieldFlag = 'defaulted' | 'substituted' | 'user_provided' | null

/** Fields that can be user-overridden when missing from data sources */
export interface UserOverrides {
  currentPrice?: number
  totalDebt?: number
  cash?: number
  capex?: number
}

export type OverrideKey = keyof UserOverrides

export interface AssumptionMeta {
  key: AssumptionKey
  label: string
  group: 'deal' | 'operating' | 'debt' | 'exit'
  format: 'multiple' | 'percent' | 'years'
  source: string
  flag: FieldFlag
}

export interface ScoreBreakdown {
  total: number
  irr: number
  moic: number
  debtService: number
  leverageReduction: number
  dataQuality: number
  /** max points per component */
  max: {
    irr: number
    moic: number
    debtService: number
    leverageReduction: number
    dataQuality: number
  }
}

export interface ModelResults {
  irr: number
  moic: number
  feasibility: ScoreBreakdown
  exitEquityValue: number
  reportMarkdown: string
}

export interface SensitivityCell {
  entryMultiple: number
  exitMultiple: number
  moic: number
  irr: number
  isBase: boolean
}

export interface ValidationResult {
  status: ValidationStatus
  missingHard: string[]
  missingSoft: string[]
  disqualifyingReasons: string[]
  sectorExcluded: boolean
  sectorExcludedReason: string | null
  defaultsApplied: string[]
  substituteWarnings: string[]
}

export interface CompanySnapshot {
  ticker: string
  companyName: string
  sicCode: number
  sicDescription: string
  currentPrice: number
  sharesOutstanding: number
  marketCap: number
  revenueHistory: RevenuePoint[]
  validation: ValidationResult
}

export interface AnalyzeSuccess {
  ok: true
  snapshot: CompanySnapshot
  assumptions: Assumptions
  assumptionMeta: AssumptionMeta[]
}

export interface AnalyzeFailure {
  ok: false
  ticker: string
  validation: ValidationResult
  nextSteps: string[]
}

export type AnalyzeResult = AnalyzeSuccess | AnalyzeFailure

export type ComparisonMode = 'scenario' | 'company'

export interface ComparisonSlot {
  id: string
  label: string
  ticker: string
  results: ModelResults
  assumptions: Assumptions
  xlsxBase64: string
}

export interface ComparisonDelta {
  metric: string
  valueA: string
  valueB: string
  change: string
}

export interface ComparisonResult {
  mode: ComparisonMode
  deltas: ComparisonDelta[]
  commentary: string | null
}
