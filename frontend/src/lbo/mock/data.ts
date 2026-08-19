import type {
  AnalyzeFailure,
  AnalyzeResult,
  AnalyzeSuccess,
  AssumptionMeta,
  Assumptions,
  CompanySnapshot,
  ModelResults,
  ValidationResult,
} from '../types'

const SCORE_MAX = {
  irr: 30,
  moic: 20,
  debtService: 25,
  leverageReduction: 15,
  dataQuality: 10,
} as const

function meta(
  items: Array<Omit<AssumptionMeta, 'flag'> & { flag?: AssumptionMeta['flag'] }>,
): AssumptionMeta[] {
  return items.map((i) => ({ ...i, flag: i.flag ?? null }))
}

function baseAssumptions(overrides: Partial<Assumptions> = {}): Assumptions {
  return {
    entryMultiple: 8.0,
    offerPremium: 0.25,
    leverageMultiple: 5.5,
    transactionFeePct: 0.02,
    revenueGrowth: 0.05,
    ebitdaMargin: 0.3,
    capexPct: 0.03,
    daPct: 0.03,
    nwcPct: 0.0,
    interestRate: 0.08,
    mandatoryAmortPct: 0.01,
    exitYear: 5,
    exitMultiple: 8.0,
    taxRate: 0.25,
    ...overrides,
  }
}

const AAPL: AnalyzeSuccess = {
  ok: true,
  snapshot: {
    ticker: 'AAPL',
    companyName: 'Apple Inc.',
    sicCode: 3571,
    sicDescription: 'Electronic Computers',
    currentPrice: 198.5,
    sharesOutstanding: 15_200_000_000,
    marketCap: 198.5 * 15_200_000_000,
    revenueHistory: [
      { year: 2020, revenue: 274_515_000_000 },
      { year: 2021, revenue: 365_817_000_000 },
      { year: 2022, revenue: 394_328_000_000 },
      { year: 2023, revenue: 383_285_000_000 },
      { year: 2024, revenue: 391_035_000_000 },
    ],
    validation: {
      status: 'pass',
      missingHard: [],
      missingSoft: [],
      disqualifyingReasons: [],
      sectorExcluded: false,
      sectorExcludedReason: null,
      defaultsApplied: [],
      substituteWarnings: [],
    },
  },
  assumptions: baseAssumptions({
    revenueGrowth: 0.048,
    ebitdaMargin: 0.34,
    capexPct: 0.028,
    daPct: 0.029,
    exitMultiple: 8.0,
  }),
  assumptionMeta: meta([
    {
      key: 'entryMultiple',
      label: 'Entry Multiple',
      group: 'deal',
      format: 'multiple',
      source: 'system default 8.0x',
    },
    {
      key: 'offerPremium',
      label: 'Offer Premium',
      group: 'deal',
      format: 'percent',
      source: 'system default 25%',
    },
    {
      key: 'leverageMultiple',
      label: 'Leverage Multiple',
      group: 'deal',
      format: 'multiple',
      source: 'system default 5.5x',
    },
    {
      key: 'transactionFeePct',
      label: 'Transaction Fee %',
      group: 'deal',
      format: 'percent',
      source: 'system default 2%',
    },
    {
      key: 'revenueGrowth',
      label: 'Revenue Growth',
      group: 'operating',
      format: 'percent',
      source: 'from historical median',
    },
    {
      key: 'ebitdaMargin',
      label: 'EBITDA Margin',
      group: 'operating',
      format: 'percent',
      source: 'from most recent FY',
    },
    {
      key: 'capexPct',
      label: 'CapEx %',
      group: 'operating',
      format: 'percent',
      source: 'from most recent FY CapEx / Revenue',
    },
    {
      key: 'daPct',
      label: 'D&A %',
      group: 'operating',
      format: 'percent',
      source: 'from most recent FY D&A / Revenue',
    },
    {
      key: 'nwcPct',
      label: 'NWC %',
      group: 'operating',
      format: 'percent',
      source: 'system default 0%',
    },
    {
      key: 'interestRate',
      label: 'Interest Rate',
      group: 'debt',
      format: 'percent',
      source: 'system default 8%',
    },
    {
      key: 'mandatoryAmortPct',
      label: 'Mandatory Amortization %',
      group: 'debt',
      format: 'percent',
      source: 'system default 1%',
    },
    {
      key: 'exitYear',
      label: 'Exit Year',
      group: 'exit',
      format: 'years',
      source: 'system default 5',
    },
    {
      key: 'exitMultiple',
      label: 'Exit Multiple',
      group: 'exit',
      format: 'multiple',
      source: 'defaults to Entry Multiple',
    },
    {
      key: 'taxRate',
      label: 'Tax Rate',
      group: 'exit',
      format: 'percent',
      source: 'system default 25%',
    },
  ]),
}

const CCL: AnalyzeSuccess = {
  ok: true,
  snapshot: {
    ticker: 'CCL',
    companyName: 'Carnival Corporation',
    sicCode: 4400,
    sicDescription: 'Water Transportation',
    currentPrice: 18.4,
    sharesOutstanding: 1_260_000_000,
    marketCap: 18.4 * 1_260_000_000,
    revenueHistory: [
      { year: 2020, revenue: 5_595_000_000 },
      { year: 2021, revenue: 1_908_000_000 },
      { year: 2022, revenue: 12_168_000_000 },
      { year: 2023, revenue: 21_593_000_000 },
      { year: 2024, revenue: 25_021_000_000 },
    ],
    validation: {
      status: 'degraded',
      missingHard: [],
      missingSoft: ['Debt tranche detail unavailable — using aggregate total debt.'],
      disqualifyingReasons: [],
      sectorExcluded: false,
      sectorExcludedReason: null,
      defaultsApplied: [],
      substituteWarnings: [
        'Revenue growth rate outside sanity band — substituted with 3% fallback (COVID-distorted history).',
      ],
    },
  },
  assumptions: baseAssumptions({
    revenueGrowth: 0.03,
    ebitdaMargin: 0.22,
    capexPct: 0.08,
    daPct: 0.07,
    leverageMultiple: 5.5,
    exitMultiple: 8.0,
  }),
  assumptionMeta: meta([
    {
      key: 'entryMultiple',
      label: 'Entry Multiple',
      group: 'deal',
      format: 'multiple',
      source: 'system default 8.0x',
    },
    {
      key: 'offerPremium',
      label: 'Offer Premium',
      group: 'deal',
      format: 'percent',
      source: 'system default 25%',
    },
    {
      key: 'leverageMultiple',
      label: 'Leverage Multiple',
      group: 'deal',
      format: 'multiple',
      source: 'system default 5.5x',
    },
    {
      key: 'transactionFeePct',
      label: 'Transaction Fee %',
      group: 'deal',
      format: 'percent',
      source: 'system default 2%',
    },
    {
      key: 'revenueGrowth',
      label: 'Revenue Growth',
      group: 'operating',
      format: 'percent',
      source: 'fallback 3% (historical median rejected)',
      flag: 'substituted',
    },
    {
      key: 'ebitdaMargin',
      label: 'EBITDA Margin',
      group: 'operating',
      format: 'percent',
      source: 'from most recent FY',
    },
    {
      key: 'capexPct',
      label: 'CapEx %',
      group: 'operating',
      format: 'percent',
      source: 'from most recent FY CapEx / Revenue',
    },
    {
      key: 'daPct',
      label: 'D&A %',
      group: 'operating',
      format: 'percent',
      source: 'from most recent FY D&A / Revenue',
    },
    {
      key: 'nwcPct',
      label: 'NWC %',
      group: 'operating',
      format: 'percent',
      source: 'system default 0%',
    },
    {
      key: 'interestRate',
      label: 'Interest Rate',
      group: 'debt',
      format: 'percent',
      source: 'system default 8%',
    },
    {
      key: 'mandatoryAmortPct',
      label: 'Mandatory Amortization %',
      group: 'debt',
      format: 'percent',
      source: 'system default 1%',
    },
    {
      key: 'exitYear',
      label: 'Exit Year',
      group: 'exit',
      format: 'years',
      source: 'system default 5',
    },
    {
      key: 'exitMultiple',
      label: 'Exit Multiple',
      group: 'exit',
      format: 'multiple',
      source: 'defaults to Entry Multiple',
    },
    {
      key: 'taxRate',
      label: 'Tax Rate',
      group: 'exit',
      format: 'percent',
      source: 'system default 25%',
    },
  ]),
}

const FIZZ: AnalyzeSuccess = {
  ok: true,
  snapshot: {
    ticker: 'FIZZ',
    companyName: 'National Beverage Corp.',
    sicCode: 2086,
    sicDescription: 'Bottled & Canned Soft Drinks',
    currentPrice: 46.2,
    sharesOutstanding: 46_800_000,
    marketCap: 46.2 * 46_800_000,
    revenueHistory: [
      { year: 2020, revenue: 1_000_000_000 },
      { year: 2021, revenue: 1_072_000_000 },
      { year: 2022, revenue: 1_138_000_000 },
      { year: 2023, revenue: 1_173_000_000 },
      { year: 2024, revenue: 1_192_000_000 },
    ],
    validation: {
      status: 'degraded',
      missingHard: [],
      missingSoft: ['Total debt missing — soft default applied.'],
      disqualifyingReasons: [],
      sectorExcluded: false,
      sectorExcludedReason: null,
      defaultsApplied: [
        'Total debt will default to $0 — verify this is accurate before proceeding.',
      ],
      substituteWarnings: [],
    },
  },
  assumptions: baseAssumptions({
    revenueGrowth: 0.04,
    ebitdaMargin: 0.18,
    capexPct: 0.02,
    daPct: 0.025,
    leverageMultiple: 5.5,
    exitMultiple: 8.0,
  }),
  assumptionMeta: meta([
    {
      key: 'entryMultiple',
      label: 'Entry Multiple',
      group: 'deal',
      format: 'multiple',
      source: 'system default 8.0x',
    },
    {
      key: 'offerPremium',
      label: 'Offer Premium',
      group: 'deal',
      format: 'percent',
      source: 'system default 25%',
    },
    {
      key: 'leverageMultiple',
      label: 'Leverage Multiple',
      group: 'deal',
      format: 'multiple',
      source: 'system default 5.5x',
    },
    {
      key: 'transactionFeePct',
      label: 'Transaction Fee %',
      group: 'deal',
      format: 'percent',
      source: 'system default 2%',
    },
    {
      key: 'revenueGrowth',
      label: 'Revenue Growth',
      group: 'operating',
      format: 'percent',
      source: 'from historical median',
    },
    {
      key: 'ebitdaMargin',
      label: 'EBITDA Margin',
      group: 'operating',
      format: 'percent',
      source: 'from most recent FY',
    },
    {
      key: 'capexPct',
      label: 'CapEx %',
      group: 'operating',
      format: 'percent',
      source: 'system default 2% (CapEx not reported)',
      flag: 'defaulted',
    },
    {
      key: 'daPct',
      label: 'D&A %',
      group: 'operating',
      format: 'percent',
      source: 'from most recent FY D&A / Revenue',
    },
    {
      key: 'nwcPct',
      label: 'NWC %',
      group: 'operating',
      format: 'percent',
      source: 'system default 0%',
    },
    {
      key: 'interestRate',
      label: 'Interest Rate',
      group: 'debt',
      format: 'percent',
      source: 'system default 8%',
    },
    {
      key: 'mandatoryAmortPct',
      label: 'Mandatory Amortization %',
      group: 'debt',
      format: 'percent',
      source: 'system default 1%',
    },
    {
      key: 'exitYear',
      label: 'Exit Year',
      group: 'exit',
      format: 'years',
      source: 'system default 5',
    },
    {
      key: 'exitMultiple',
      label: 'Exit Multiple',
      group: 'exit',
      format: 'multiple',
      source: 'defaults to Entry Multiple',
    },
    {
      key: 'taxRate',
      label: 'Tax Rate',
      group: 'exit',
      format: 'percent',
      source: 'system default 25%',
    },
  ]),
}

const FIXTURES: Record<string, AnalyzeSuccess> = {
  AAPL,
  CCL,
  FIZZ,
}

const FAIL_CASES: Record<string, AnalyzeFailure> = {
  JPM: {
    ok: false,
    ticker: 'JPM',
    validation: {
      status: 'fail',
      missingHard: [],
      missingSoft: [],
      disqualifyingReasons: [
        'Sector excluded: Banks (SIC 6000–6199). Banking institutions use a different capital structure and are out of scope for v1 LBO modeling.',
      ],
      sectorExcluded: true,
      sectorExcludedReason: 'Banks (SIC 6000–6199)',
      defaultsApplied: [],
      substituteWarnings: [],
    },
    nextSteps: [
      'Try a non-financial ticker (e.g. AAPL, CCL, FIZZ).',
      'Banks, insurance, REITs, and utilities are excluded in v1.',
    ],
  },
  ARM: {
    ok: false,
    ticker: 'ARM',
    validation: {
      status: 'fail',
      missingHard: [],
      missingSoft: [],
      disqualifyingReasons: [
        'No 10-K filings found — this may be a foreign private issuer filing under Form 20-F (IFRS), which isn’t supported yet.',
      ],
      sectorExcluded: false,
      sectorExcludedReason: null,
      defaultsApplied: [],
      substituteWarnings: [],
    },
    nextSteps: [
      'Use a US-listed company that files Form 10-K.',
      '20-F / IFRS support is planned for a later release.',
    ],
  },
}

/** Baseline results shaped like verified README examples (AAPL ~20% IRR / ~2.5x MOIC). */
export const BASE_RESULTS: Record<string, ModelResults> = {
  AAPL: {
    irr: 0.203,
    moic: 2.52,
    feasibility: {
      total: 78,
      irr: 22,
      moic: 15,
      debtService: 22,
      leverageReduction: 12,
      dataQuality: 10,
      max: { ...SCORE_MAX },
    },
    exitEquityValue: 420_000_000_000,
    reportMarkdown: '',
  },
  CCL: {
    irr: 0.142,
    moic: 1.85,
    feasibility: {
      total: 52,
      irr: 12,
      moic: 8,
      debtService: 14,
      leverageReduction: 10,
      dataQuality: 8,
      max: { ...SCORE_MAX },
    },
    exitEquityValue: 8_500_000_000,
    reportMarkdown: '',
  },
  FIZZ: {
    irr: 0.178,
    moic: 2.15,
    feasibility: {
      total: 64,
      irr: 18,
      moic: 11,
      debtService: 18,
      leverageReduction: 9,
      dataQuality: 8,
      max: { ...SCORE_MAX },
    },
    exitEquityValue: 1_100_000_000,
    reportMarkdown: '',
  },
}

export const SOURCE_HEALTH = {
  secEdgar: true,
  twelveData: true,
}

export function normalizeTicker(raw: string): string {
  return raw.trim().toUpperCase().replace(/\./g, '-')
}

export function getFixture(ticker: string): AnalyzeResult {
  const t = normalizeTicker(ticker)
  if (FAIL_CASES[t]) return FAIL_CASES[t]
  if (FIXTURES[t]) return FIXTURES[t]

  // Unknown ticker → generic fail (keeps shell demo honest)
  const validation: ValidationResult = {
    status: 'fail',
    missingHard: [`No mock fixture for ticker “${t}”.`],
    missingSoft: [],
    disqualifyingReasons: [
      `Demo shell only includes AAPL, CCL, and FIZZ (plus fail demos JPM / ARM).`,
    ],
    sectorExcluded: false,
    sectorExcludedReason: null,
    defaultsApplied: [],
    substituteWarnings: [],
  }
  return {
    ok: false,
    ticker: t,
    validation,
    nextSteps: [
      'Try AAPL (pass), CCL (degraded / substituted growth), or FIZZ (defaulted debt).',
      'JPM and ARM demonstrate validation failure states.',
    ],
  }
}

export function cloneSnapshot(s: CompanySnapshot): CompanySnapshot {
  return structuredClone(s)
}

export function listDemoTickers(): string[] {
  return Object.keys(FIXTURES)
}
