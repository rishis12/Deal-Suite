import { useCallback, useState } from 'react'
import * as api from '../api'
import type {
  AnalyzeResponse,
  GenerateResponse,
  MarketShareRow,
  PairValidation,
  SavedModel,
} from '../types'

export type Phase = 'empty' | 'loading' | 'ready' | 'generated'

export interface PriceOverrides {
  acquirer: string // raw input strings; '' = not provided
  target: string
}

function describeApiError(err: unknown): {
  message: string
  validation: PairValidation | null
} {
  if (err instanceof api.ApiError) {
    const detail = err.detail
    if (detail && typeof detail === 'object' && 'validation' in (detail as object)) {
      return {
        message: 'Validation failed — see the breakdown below.',
        validation: (detail as { validation: PairValidation }).validation,
      }
    }
    return { message: typeof detail === 'string' ? detail : err.message, validation: null }
  }
  if (err instanceof TypeError) {
    return { message: 'Could not reach the backend — is it running?', validation: null }
  }
  return { message: String(err), validation: null }
}

export function useDealState(getLlm: () => { llmProvider: string; llmApiKey: string }) {
  const [acquirerTicker, setAcquirerTicker] = useState('')
  const [targetTicker, setTargetTicker] = useState('')
  const [phase, setPhase] = useState<Phase>('empty')
  const [error, setError] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null)
  const [failedValidation, setFailedValidation] = useState<PairValidation | null>(null)
  const [assumptions, setAssumptions] = useState<Record<string, number>>({})
  const [priceOverrides, setPriceOverrides] = useState<PriceOverrides>({
    acquirer: '',
    target: '',
  })
  const [marketShares, setMarketShares] = useState<MarketShareRow[]>([])
  const [generating, setGenerating] = useState(false)
  const [results, setResults] = useState<GenerateResponse | null>(null)
  const [savedModels, setSavedModels] = useState<SavedModel[]>([])
  const [toast, setToast] = useState<string | null>(null)

  const showToast = useCallback((msg: string) => {
    setToast(msg)
    window.setTimeout(() => setToast(null), 3500)
  }, [])

  const analyze = useCallback(async () => {
    const acq = acquirerTicker.trim().toUpperCase()
    const tgt = targetTicker.trim().toUpperCase()
    if (!acq || !tgt) {
      setError('Enter both an acquirer and a target ticker.')
      return
    }
    setPhase('loading')
    setError(null)
    setFailedValidation(null)
    setResults(null)
    try {
      const res = await api.analyze(acq, tgt)
      setAnalysis(res)
      setAssumptions({ ...res.defaultAssumptions })
      // Pre-populate the market share table with the two real companies
      setMarketShares([
        { companyName: res.acquirer.companyName, marketShare: NaN },
        { companyName: res.target.companyName, marketShare: NaN },
      ])
      setPriceOverrides({ acquirer: '', target: '' })
      setPhase('ready')
    } catch (err) {
      const { message, validation } = describeApiError(err)
      setError(message)
      setFailedValidation(validation)
      setAnalysis(null)
      setPhase('empty')
    }
  }, [acquirerTicker, targetTicker])

  const updateAssumption = useCallback((key: string, value: number) => {
    setAssumptions((prev) => ({ ...prev, [key]: value }))
  }, [])

  const generateModel = useCallback(async () => {
    if (!analysis) return
    setGenerating(true)
    setError(null)
    try {
      const overrides: api.GenerateParams['userOverrides'] = {}
      const acqPrice = parseFloat(priceOverrides.acquirer)
      const tgtPrice = parseFloat(priceOverrides.target)
      if (!Number.isNaN(acqPrice)) overrides.acquirer = { currentPrice: acqPrice }
      if (!Number.isNaN(tgtPrice)) overrides.target = { currentPrice: tgtPrice }

      const shares = marketShares.filter(
        (r) => r.companyName.trim() && !Number.isNaN(r.marketShare) && r.marketShare > 0,
      )

      const llm = getLlm()
      const res = await api.generate({
        acquirerTicker: analysis.acquirer.ticker,
        targetTicker: analysis.target.ticker,
        assumptions,
        marketShareTable: shares.length > 0 ? shares : undefined,
        userOverrides: Object.keys(overrides).length > 0 ? overrides : undefined,
        llmProvider: llm.llmApiKey ? llm.llmProvider : undefined,
        llmApiKey: llm.llmApiKey || undefined,
      })
      setResults(res)
      setPhase('generated')

      const blob = api.base64ToBlob(res.xlsxBase64)
      const model: SavedModel = {
        id: `${Date.now()}`,
        label: `${analysis.acquirer.ticker} → ${analysis.target.ticker} (${new Date().toLocaleTimeString()})`,
        filename: res.filename,
        blob,
        createdAt: Date.now(),
      }
      setSavedModels((prev) => [...prev, model])
      showToast('Model generated and saved for comparison')
    } catch (err) {
      const { message, validation } = describeApiError(err)
      setError(message)
      if (validation) setFailedValidation(validation)
    } finally {
      setGenerating(false)
    }
  }, [analysis, assumptions, marketShares, priceOverrides, getLlm, showToast])

  const downloadExcel = useCallback(() => {
    if (!results) return
    const blob = api.base64ToBlob(results.xlsxBase64)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = results.filename
    a.click()
    URL.revokeObjectURL(url)
  }, [results])

  return {
    acquirerTicker,
    setAcquirerTicker,
    targetTicker,
    setTargetTicker,
    phase,
    error,
    analysis,
    failedValidation,
    assumptions,
    updateAssumption,
    priceOverrides,
    setPriceOverrides,
    marketShares,
    setMarketShares,
    analyze,
    generateModel,
    generating,
    results,
    savedModels,
    downloadExcel,
    toast,
    showToast,
  }
}

export type DealState = ReturnType<typeof useDealState>
