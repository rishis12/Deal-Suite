import { useCallback, useState } from 'react'
import type {
  AnalyzeFailure,
  AnalyzeResult,
  AppPhase,
  AssumptionMeta,
  Assumptions,
  CompanySnapshot,
  ComparisonSlot,
  LlmProvider,
  ModelResults,
  OverrideKey,
  SensitivityCell,
  UserOverrides,
} from '../types'

const API_BASE = `${import.meta.env.VITE_API_URL || 'http://localhost:8002'}/lbo`

interface UseAppStateOptions {
  llmProvider: LlmProvider
  llmApiKey: string
}

export function useAppState(options?: UseAppStateOptions) {
  const [phase, setPhase] = useState<AppPhase>('empty')
  const [tickerInput, setTickerInput] = useState('')
  const [error, setError] = useState<AnalyzeFailure | null>(null)
  const [snapshot, setSnapshot] = useState<CompanySnapshot | null>(null)
  const [assumptions, setAssumptions] = useState<Assumptions | null>(null)
  const [assumptionMeta, setAssumptionMeta] = useState<AssumptionMeta[]>([])
  const [results, setResults] = useState<ModelResults | null>(null)
  const [sensitivity, setSensitivity] = useState<SensitivityCell[]>([])
  const [generating, setGenerating] = useState(false)
  const [savedModels, setSavedModels] = useState<ComparisonSlot[]>([])
  const [showReport, setShowReport] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [currentXlsxBase64, setCurrentXlsxBase64] = useState<string | null>(null)
  const [userOverrides, setUserOverrides] = useState<UserOverrides>({})

  const showToast = useCallback((msg: string) => {
    setToast(msg)
    window.setTimeout(() => setToast(null), 2800)
  }, [])

  const analyze = useCallback(async (raw: string) => {
    setPhase('loading')
    setError(null)
    setResults(null)
    setSensitivity([])
    setShowReport(false)
    setSnapshot(null)
    setAssumptions(null)
    setCurrentXlsxBase64(null)
    setUserOverrides({}) // Reset overrides on new analysis

    try {
      const response = await fetch(`${API_BASE}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker: raw.trim().toUpperCase() }),
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Request failed' }))
        throw new Error(errorData.detail || `HTTP ${response.status}`)
      }

      const result: AnalyzeResult = await response.json()

      if (!result.ok) {
        setError(result as AnalyzeFailure)
        setPhase('error')
        return
      }

      setSnapshot(result.snapshot)
      setAssumptions(result.assumptions)
      setAssumptionMeta(result.assumptionMeta)
      setTickerInput(result.snapshot.ticker)
      setPhase('ready')
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      setError({
        ok: false,
        ticker: raw.trim().toUpperCase(),
        validation: {
          status: 'fail',
          missingHard: [],
          missingSoft: [],
          disqualifyingReasons: [message],
          sectorExcluded: false,
          sectorExcludedReason: null,
          defaultsApplied: [],
          substituteWarnings: [],
        },
        nextSteps: ['Check your network connection', 'Try again in a moment'],
      })
      setPhase('error')
    }
  }, [])

  const updateAssumption = useCallback(<K extends keyof Assumptions>(key: K, value: Assumptions[K]) => {
    setAssumptions((prev) => (prev ? { ...prev, [key]: value } : prev))
  }, [])

  /**
   * Update a user-provided override for a missing field.
   * Also updates the snapshot immediately for derived fields (e.g., market cap).
   */
  const updateOverride = useCallback((key: OverrideKey, value: number | undefined) => {
    setUserOverrides((prev) => {
      if (value === undefined) {
        const next = { ...prev }
        delete next[key]
        return next
      }
      return { ...prev, [key]: value }
    })

    // Update snapshot with derived calculations
    if (key === 'currentPrice' && value !== undefined) {
      setSnapshot((prev) => {
        if (!prev) return prev
        const newMarketCap = value * prev.sharesOutstanding
        return {
          ...prev,
          currentPrice: value,
          marketCap: newMarketCap,
        }
      })
    }
  }, [])

  const generate = useCallback(async () => {
    if (!snapshot || !assumptions) return
    setGenerating(true)

    try {
      const response = await fetch(`${API_BASE}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ticker: snapshot.ticker,
          assumptions,
          userOverrides: Object.keys(userOverrides).length > 0 ? userOverrides : undefined,
          llmProvider: options?.llmApiKey ? options.llmProvider : undefined,
          llmApiKey: options?.llmApiKey || undefined,
        }),
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Request failed' }))
        throw new Error(errorData.detail || `HTTP ${response.status}`)
      }

      const data = await response.json()

      const r: ModelResults = {
        irr: data.irr,
        moic: data.moic,
        feasibility: data.feasibility,
        exitEquityValue: data.exitEquityValue,
        reportMarkdown: data.reportMarkdown || '',
      }

      const grid: SensitivityCell[] = data.sensitivity || []

      setResults(r)
      setSensitivity(grid)
      setCurrentXlsxBase64(data.xlsxBase64)
      setPhase('generated')

      // Save to comparison slots
      const slot: ComparisonSlot = {
        id: `${snapshot.ticker}-${Date.now()}`,
        label: `${snapshot.ticker} · ${assumptions.leverageMultiple.toFixed(1)}x lev`,
        ticker: snapshot.ticker,
        results: r,
        assumptions: { ...assumptions },
        xlsxBase64: data.xlsxBase64,
      }
      setSavedModels((prev) => [slot, ...prev].slice(0, 8))
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Generation failed'
      showToast(`Error: ${message}`)
    } finally {
      setGenerating(false)
    }
  }, [snapshot, assumptions, userOverrides, options?.llmProvider, options?.llmApiKey, showToast])

  const downloadExcel = useCallback(() => {
    if (!snapshot || !currentXlsxBase64) {
      showToast('No Excel file available')
      return
    }

    // Decode base64 to binary
    const binaryString = atob(currentXlsxBase64)
    const bytes = new Uint8Array(binaryString.length)
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i)
    }

    const blob = new Blob([bytes], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `LBO_${snapshot.ticker}_${new Date().toISOString().slice(0, 10)}.xlsx`
    a.click()
    URL.revokeObjectURL(url)
    showToast('Excel model downloaded')
  }, [snapshot, currentXlsxBase64, showToast])

  return {
    phase,
    tickerInput,
    setTickerInput,
    error,
    snapshot,
    assumptions,
    assumptionMeta,
    results,
    sensitivity,
    generating,
    savedModels,
    showReport,
    setShowReport,
    toast,
    showToast,
    userOverrides,
    analyze,
    updateAssumption,
    updateOverride,
    generate,
    downloadExcel,
  }
}
