import type {
  AnalyzeResponse,
  ComparisonResponse,
  GenerateResponse,
  MarketShareRow,
} from './types'

// One merged backend serves both products; the M&A app lives under /ma
export const API_BASE = `${import.meta.env.VITE_API_URL || 'http://localhost:8002'}/ma`

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `Request failed (${status})`)
    this.status = status
    this.detail = detail
  }
}

async function handle<T>(res: Response): Promise<T> {
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) {
    const detail =
      body && typeof body === 'object' && 'detail' in (body as object)
        ? (body as { detail: unknown }).detail
        : body
    throw new ApiError(res.status, detail)
  }
  return body as T
}

export function analyze(acquirerTicker: string, targetTicker: string): Promise<AnalyzeResponse> {
  return fetch(`${API_BASE}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ acquirerTicker, targetTicker }),
  }).then((res) => handle<AnalyzeResponse>(res))
}

export interface GenerateParams {
  acquirerTicker: string
  targetTicker: string
  assumptions: Record<string, number>
  marketShareTable?: MarketShareRow[]
  userOverrides?: {
    acquirer?: { currentPrice?: number }
    target?: { currentPrice?: number }
  }
  llmProvider?: string
  llmApiKey?: string
}

export function generate(params: GenerateParams): Promise<GenerateResponse> {
  return fetch(`${API_BASE}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  }).then((res) => handle<GenerateResponse>(res))
}

export function compare(
  fileA: Blob,
  fileB: Blob,
  llmProvider?: string,
  llmApiKey?: string,
): Promise<ComparisonResponse> {
  const form = new FormData()
  form.append('fileA', fileA, 'fileA.xlsx')
  form.append('fileB', fileB, 'fileB.xlsx')
  if (llmProvider && llmApiKey) {
    form.append('llmProvider', llmProvider)
    form.append('llmApiKey', llmApiKey)
  }
  return fetch(`${API_BASE}/compare`, { method: 'POST', body: form }).then((res) =>
    handle<ComparisonResponse>(res),
  )
}

export function base64ToBlob(b64: string): Blob {
  const bytes = atob(b64)
  const arr = new Uint8Array(bytes.length)
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i)
  return new Blob([arr], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
}

// ---- formatting helpers shared across components ----

export function fmtCurrency(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  const abs = Math.abs(v)
  if (abs >= 1e9) return `$${(v / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `$${(v / 1e6).toFixed(2)}M`
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

export function fmtShares(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  return v.toLocaleString(undefined, { maximumFractionDigits: 0 })
}
