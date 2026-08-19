import { useCallback, useMemo, useRef, useState } from 'react'
import type { ComparisonDelta, ComparisonResult, ComparisonSlot, LlmProvider } from '../types'
import styles from './ComparisonPanel.module.css'

const API_BASE = `${import.meta.env.VITE_API_URL || 'http://localhost:8002'}/lbo`

interface Props {
  savedModels: ComparisonSlot[]
  hasLlmKey: boolean
  llmProvider?: LlmProvider
  llmApiKey?: string
  onNeedKey: () => void
}

type SlotMode = 'session' | 'upload'

interface SlotState {
  mode: SlotMode
  sessionId: string
  uploadedFile: File | null
  uploadedBase64: string | null
}

export function ComparisonPanel({ savedModels, hasLlmKey, llmProvider, llmApiKey, onNeedKey }: Props) {
  const [collapsed, setCollapsed] = useState(false)
  const [slotA, setSlotA] = useState<SlotState>({ mode: 'session', sessionId: '', uploadedFile: null, uploadedBase64: null })
  const [slotB, setSlotB] = useState<SlotState>({ mode: 'session', sessionId: '', uploadedFile: null, uploadedBase64: null })
  const [comparison, setComparison] = useState<ComparisonResult | null>(null)
  const [comparing, setComparing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fileInputA = useRef<HTMLInputElement>(null)
  const fileInputB = useRef<HTMLInputElement>(null)

  const modelA = savedModels.find((s) => s.id === slotA.sessionId) ?? null
  const modelB = savedModels.find((s) => s.id === slotB.sessionId) ?? null

  // Check if we have valid files for both slots
  const canCompare = useMemo(() => {
    const hasA = (slotA.mode === 'session' && modelA?.xlsxBase64) ||
                 (slotA.mode === 'upload' && slotA.uploadedFile)
    const hasB = (slotB.mode === 'session' && modelB?.xlsxBase64) ||
                 (slotB.mode === 'upload' && slotB.uploadedFile)
    return hasA && hasB
  }, [slotA, slotB, modelA, modelB])

  const handleFileUpload = useCallback((slot: 'A' | 'B', file: File | null) => {
    if (slot === 'A') {
      setSlotA(prev => ({ ...prev, uploadedFile: file, uploadedBase64: null }))
    } else {
      setSlotB(prev => ({ ...prev, uploadedFile: file, uploadedBase64: null }))
    }
    setComparison(null)
    setError(null)
  }, [])

  const runComparison = useCallback(async () => {
    setComparing(true)
    setError(null)
    setComparison(null)

    try {
      // Prepare form data with the two files
      const formData = new FormData()

      // File A
      if (slotA.mode === 'session' && modelA?.xlsxBase64) {
        const binaryString = atob(modelA.xlsxBase64)
        const bytes = new Uint8Array(binaryString.length)
        for (let i = 0; i < binaryString.length; i++) {
          bytes[i] = binaryString.charCodeAt(i)
        }
        const blob = new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
        formData.append('file_a', blob, `${modelA.ticker}_a.xlsx`)
      } else if (slotA.mode === 'upload' && slotA.uploadedFile) {
        formData.append('file_a', slotA.uploadedFile)
      }

      // File B
      if (slotB.mode === 'session' && modelB?.xlsxBase64) {
        const binaryString = atob(modelB.xlsxBase64)
        const bytes = new Uint8Array(binaryString.length)
        for (let i = 0; i < binaryString.length; i++) {
          bytes[i] = binaryString.charCodeAt(i)
        }
        const blob = new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
        formData.append('file_b', blob, `${modelB.ticker}_b.xlsx`)
      } else if (slotB.mode === 'upload' && slotB.uploadedFile) {
        formData.append('file_b', slotB.uploadedFile)
      }

      // Add LLM credentials if available
      if (hasLlmKey && llmProvider && llmApiKey) {
        formData.append('llmProvider', llmProvider)
        formData.append('llmApiKey', llmApiKey)
      }

      const response = await fetch(`${API_BASE}/compare`, {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Comparison failed' }))
        throw new Error(errorData.detail || `HTTP ${response.status}`)
      }

      const result: ComparisonResult = await response.json()
      setComparison(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Comparison failed')
    } finally {
      setComparing(false)
    }
  }, [slotA, slotB, modelA, modelB, hasLlmKey, llmProvider, llmApiKey])

  const generateCommentary = useCallback(async () => {
    if (!hasLlmKey) {
      onNeedKey()
      return
    }
    // Re-run comparison with LLM credentials
    await runComparison()
  }, [hasLlmKey, onNeedKey, runComparison])

  return (
    <section className={`tile tile-comparison collapsible ${collapsed ? 'collapsed' : ''}`}>
      <button
        type="button"
        className="collapsible-header"
        onClick={() => setCollapsed((c) => !c)}
      >
        Comparison Panel
        <span>{collapsed ? '+' : '−'}</span>
      </button>
      <h2 className="tile-title">Comparison Panel</h2>
      <div className="collapsible-body">
        <div className={styles.slots}>
          {/* Slot A */}
          <div className={styles.slot}>
            <div className={styles.slotHeader}>
              <span className="field-label">File A</span>
              <div className={styles.modeToggle}>
                <button
                  type="button"
                  className={`${styles.modeBtn} ${slotA.mode === 'session' ? styles.active : ''}`}
                  onClick={() => {
                    setSlotA(prev => ({ ...prev, mode: 'session' }))
                    setComparison(null)
                  }}
                >
                  Session
                </button>
                <button
                  type="button"
                  className={`${styles.modeBtn} ${slotA.mode === 'upload' ? styles.active : ''}`}
                  onClick={() => {
                    setSlotA(prev => ({ ...prev, mode: 'upload' }))
                    setComparison(null)
                  }}
                >
                  Upload
                </button>
              </div>
            </div>
            {slotA.mode === 'session' ? (
              <select
                className="select"
                value={slotA.sessionId}
                onChange={(e) => {
                  setSlotA(prev => ({ ...prev, sessionId: e.target.value }))
                  setComparison(null)
                }}
              >
                <option value="">Select generated model…</option>
                {savedModels.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            ) : (
              <div className={styles.uploadArea}>
                <input
                  ref={fileInputA}
                  type="file"
                  accept=".xlsx"
                  style={{ display: 'none' }}
                  onChange={(e) => handleFileUpload('A', e.target.files?.[0] ?? null)}
                />
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => fileInputA.current?.click()}
                >
                  {slotA.uploadedFile ? slotA.uploadedFile.name : 'Choose .xlsx file'}
                </button>
              </div>
            )}
          </div>

          {/* Slot B */}
          <div className={styles.slot}>
            <div className={styles.slotHeader}>
              <span className="field-label">File B</span>
              <div className={styles.modeToggle}>
                <button
                  type="button"
                  className={`${styles.modeBtn} ${slotB.mode === 'session' ? styles.active : ''}`}
                  onClick={() => {
                    setSlotB(prev => ({ ...prev, mode: 'session' }))
                    setComparison(null)
                  }}
                >
                  Session
                </button>
                <button
                  type="button"
                  className={`${styles.modeBtn} ${slotB.mode === 'upload' ? styles.active : ''}`}
                  onClick={() => {
                    setSlotB(prev => ({ ...prev, mode: 'upload' }))
                    setComparison(null)
                  }}
                >
                  Upload
                </button>
              </div>
            </div>
            {slotB.mode === 'session' ? (
              <select
                className="select"
                value={slotB.sessionId}
                onChange={(e) => {
                  setSlotB(prev => ({ ...prev, sessionId: e.target.value }))
                  setComparison(null)
                }}
              >
                <option value="">Select generated model…</option>
                {savedModels.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            ) : (
              <div className={styles.uploadArea}>
                <input
                  ref={fileInputB}
                  type="file"
                  accept=".xlsx"
                  style={{ display: 'none' }}
                  onChange={(e) => handleFileUpload('B', e.target.files?.[0] ?? null)}
                />
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => fileInputB.current?.click()}
                >
                  {slotB.uploadedFile ? slotB.uploadedFile.name : 'Choose .xlsx file'}
                </button>
              </div>
            )}
          </div>
        </div>

        {savedModels.length === 0 && slotA.mode === 'session' && slotB.mode === 'session' && (
          <p className={styles.empty}>Generate at least one model to populate comparison slots, or upload files directly.</p>
        )}

        {canCompare && !comparison && (
          <button
            type="button"
            className="btn btn-primary"
            style={{ marginTop: '1rem' }}
            onClick={runComparison}
            disabled={comparing}
          >
            {comparing ? 'Comparing...' : 'Compare'}
          </button>
        )}

        {error && (
          <p className={styles.error}>{error}</p>
        )}

        {comparison && (
          <>
            <div className={styles.mode}>
              Mode:{' '}
              <strong>
                {comparison.mode === 'scenario' ? 'Scenario Comparison' : 'Company Comparison'}
              </strong>
            </div>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Value A</th>
                    <th>Value B</th>
                    <th>Change</th>
                  </tr>
                </thead>
                <tbody>
                  {comparison.deltas.map((d: ComparisonDelta) => (
                    <tr key={d.metric}>
                      <td>{d.metric}</td>
                      <td className="mono">{d.valueA}</td>
                      <td className="mono">{d.valueB}</td>
                      <td className="mono">{d.change}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {!comparison.commentary && (
              <button
                type="button"
                className="btn btn-secondary"
                style={{ marginTop: '0.85rem' }}
                onClick={generateCommentary}
                disabled={comparing}
              >
                {comparing ? 'Generating...' : 'Generate Commentary'}
              </button>
            )}

            {!hasLlmKey && !comparison.commentary && (
              <p className={styles.keyHint}>Requires an LLM API key in Settings (session only).</p>
            )}

            {comparison.commentary && (
              <div className={styles.commentary}>
                <h4>Commentary</h4>
                <p>{comparison.commentary}</p>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}
