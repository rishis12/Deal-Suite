// Types mirroring the backend API contract (backend/api.py Pydantic models).
// The backend contract is the source of truth — do not diverge.

export type LlmProvider = 'anthropic' | 'openai' | 'gemini'

export interface SessionKeys {
  llmProvider: LlmProvider
  llmApiKey: string
}

export interface CompanyVerdict {
  ticker: string
  status: 'pass' | 'degraded' | 'fail'
  missingHard: string[]
  missingSoft: string[]
  disqualifyingReasons: string[]
  sectorExcluded: boolean
  sectorExcludedReason: string | null
  defaultsApplied: string[]
  substituteWarnings: string[]
  warnings: string[]
  goodwillPrecisionDegraded: boolean
}

export interface PairValidation {
  status: 'pass' | 'degraded' | 'fail'
  disqualifyingReasons: string[]
  acquirer: CompanyVerdict
  target: CompanyVerdict
}

export interface CompanySnapshot {
  ticker: string
  companyName: string
  sicCode: string
  sicDescription: string
  fiscalYear: number | null
  currentPrice: number | null
  dilutedShares: number | null
  dilutedEps: number | null
  revenue: number | null
  operatingIncome: number | null
  da: number | null
  ebitda: number | null
  netIncome: number | null
  totalDebt: number | null
  cash: number | null
  totalAssets: number | null
  totalLiabilities: number | null
  growthDefault: number
  growthIsFallback: boolean
  growthNote: string
}

export interface AnalyzeResponse {
  validation: PairValidation
  acquirer: CompanySnapshot
  target: CompanySnapshot
  defaultAssumptions: Record<string, number>
}

export interface MarketShareRow {
  companyName: string
  marketShare: number // fraction: 0.25 = 25%
}

export interface HHIResult {
  assessed: boolean
  preMergerHHI: number | null
  postMergerHHI: number | null
  deltaHHI: number | null
  preMergerClass: string | null
  postMergerClass: string | null
  presumptiveConcern: string | null
}

export interface GenerateResponse {
  validation: PairValidation
  sourcesUses: {
    purchaseEquityValue: number | null
    transactionFees: number | null
    totalUses: number | null
    cashUsed: number | null
    newDebt: number | null
    newStockIssued: number | null
    newSharesIssued: number | null
    balanceCheck: number | null
  }
  ppa: {
    targetBookEquity: number | null
    premiumOverBook: number | null
    assetStepUp: number | null
    goodwill: number | null
    incrementalDA: number | null
  }
  standaloneEps: number | null
  proFormaEpsByYear: (number | null)[]
  accretionDilutionByYear: (number | null)[]
  crossover: string | null
  hhi: HHIResult
  report: string | null
  reportError: string | null
  xlsxBase64: string
  filename: string
}

export interface InputDiff {
  field: string
  displayName: string
  valueA: number | null
  valueB: number | null
  formatType: string
}

export interface AssumptionComparisonRow {
  field: string
  displayName: string
  valueA: number | null
  valueB: number | null
}

export interface ComparisonResponse {
  mode: 'scenario' | 'deal'
  dealLabelA: string
  dealLabelB: string
  inputDiffs: InputDiff[]
  assumptionsComparison: AssumptionComparisonRow[]
  adByYearA: (number | null)[]
  adByYearB: (number | null)[]
  epsByYearA: (number | null)[]
  epsByYearB: (number | null)[]
  goodwillA: number | null
  goodwillB: number | null
  hhiA: Record<string, unknown> | null
  hhiB: Record<string, unknown> | null
  commentary: string | null
  commentaryError: string | null
}

// A model generated during this browser session, kept for the Comparison tab
export interface SavedModel {
  id: string
  label: string
  filename: string
  blob: Blob
  createdAt: number
}

// The 13 deal assumptions (keys match backend DEFAULT_DEAL_ASSUMPTIONS)
export interface AssumptionField {
  key: string
  label: string
  kind: 'pct' | 'int'
}

export const ASSUMPTION_FIELDS: AssumptionField[] = [
  { key: 'offer_premium', label: 'Offer Premium %', kind: 'pct' },
  { key: 'pct_cash', label: '% Cash', kind: 'pct' },
  { key: 'pct_debt', label: '% Debt', kind: 'pct' },
  { key: 'new_debt_rate', label: 'New Debt Interest Rate', kind: 'pct' },
  { key: 'foregone_cash_rate', label: 'Foregone Interest on Cash', kind: 'pct' },
  { key: 'revenue_synergies_pct', label: 'Revenue Synergies %', kind: 'pct' },
  { key: 'cost_synergies_pct', label: 'Cost Synergies %', kind: 'pct' },
  { key: 'synergy_ramp_years', label: 'Synergy Ramp (years)', kind: 'int' },
  { key: 'transaction_fee_pct', label: 'Transaction Fee %', kind: 'pct' },
  { key: 'asset_step_up_pct', label: 'Asset Step-Up %', kind: 'pct' },
  { key: 'intangible_amort_years', label: 'Intangible Amort. (years)', kind: 'int' },
  { key: 'tax_rate', label: 'Tax Rate', kind: 'pct' },
  { key: 'analysis_years', label: 'Analysis Years', kind: 'int' },
]
