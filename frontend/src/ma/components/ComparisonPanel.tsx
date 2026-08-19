import { useState } from 'react'
import { compare, fmtCurrency, fmtPct } from '../api'
import type { ComparisonResponse, SavedModel } from '../types'

interface Props {
  savedModels: SavedModel[]
  llmProvider: string
  llmApiKey: string
}

type SlotSource = { kind: 'session'; modelId: string } | { kind: 'upload'; file: File } | null

function Slot({
  label,
  savedModels,
  value,
  onChange,
}: {
  label: string
  savedModels: SavedModel[]
  value: SlotSource
  onChange: (v: SlotSource) => void
}) {
  return (
    <div className="compare-slot">
      <h3 className="subhead">{label}</h3>
      {savedModels.length > 0 && (
        <label className="field-label slot-field">
          Session model
          <select
            value={value?.kind === 'session' ? value.modelId : ''}
            onChange={(e) =>
              onChange(e.target.value ? { kind: 'session', modelId: e.target.value } : null)
            }
          >
            <option value="">— choose —</option>
            {savedModels.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="field-label slot-field">
        {savedModels.length > 0 ? 'or upload a .xlsx' : 'Upload a .xlsx'}
        <input
          type="file"
          accept=".xlsx"
          onChange={(e) => {
            const file = e.target.files?.[0]
            onChange(file ? { kind: 'upload', file } : null)
          }}
        />
      </label>
      {value && (
        <p className="positive-note">
          ✓ {value.kind === 'session' ? 'Session model selected' : value.file.name}
        </p>
      )}
    </div>
  )
}

function AdTable({
  result,
}: {
  result: ComparisonResponse
}) {
  const years = Math.max(result.adByYearA.length, result.adByYearB.length)
  const scenario = result.mode === 'scenario'
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Year</th>
          <th>{scenario ? 'Scenario A' : 'Deal A'}</th>
          <th>{scenario ? 'Scenario B' : 'Deal B'}</th>
          {scenario && <th>Δ (pp)</th>}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: years }, (_, i) => {
          const a = result.adByYearA[i]
          const b = result.adByYearB[i]
          return (
            <tr key={i}>
              <td className="row-label">Y{i + 1}</td>
              <td className={`mono ${(a ?? 0) >= 0 ? 'positive' : 'negative'}`}>{fmtPct(a)}</td>
              <td className={`mono ${(b ?? 0) >= 0 ? 'positive' : 'negative'}`}>{fmtPct(b)}</td>
              {scenario && (
                <td className="mono">
                  {a !== null && b !== null ? ((b - a) * 100).toFixed(2) : '—'}
                </td>
              )}
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

export function ComparisonPanel({ savedModels, llmProvider, llmApiKey }: Props) {
  const [slotA, setSlotA] = useState<SlotSource>(null)
  const [slotB, setSlotB] = useState<SlotSource>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ComparisonResponse | null>(null)

  const resolveBlob = (slot: SlotSource): Blob | null => {
    if (!slot) return null
    if (slot.kind === 'upload') return slot.file
    return savedModels.find((m) => m.id === slot.modelId)?.blob ?? null
  }

  const runCompare = async () => {
    const blobA = resolveBlob(slotA)
    const blobB = resolveBlob(slotB)
    if (!blobA || !blobB) {
      setError('Pick a model (session-generated or uploaded file) for both slots.')
      return
    }
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await compare(blobA, blobB, llmProvider, llmApiKey || undefined)
      setResult(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="comparison-page">
      <section className="tile">
        <div className="tile-head">
          <h2>Compare two models</h2>
          <span className="muted-note">
            Same deal → scenario comparison. Different deals → Deal A vs Deal B.
          </span>
        </div>
        <div className="compare-slots">
          <Slot label="Slot A" savedModels={savedModels} value={slotA} onChange={setSlotA} />
          <Slot label="Slot B" savedModels={savedModels} value={slotB} onChange={setSlotB} />
        </div>
        <button
          type="button"
          className="primary-btn"
          onClick={runCompare}
          disabled={loading}
        >
          {loading ? 'Comparing…' : 'Compare'}
        </button>
        {error && <p className="negative-note">{error}</p>}
      </section>

      {result && (
        <section className="tile">
          <div className="tile-head">
            <h2>
              {result.mode === 'scenario' ? (
                <>Scenario comparison — {result.dealLabelA}</>
              ) : (
                <>
                  Deal A ({result.dealLabelA}) vs Deal B ({result.dealLabelB})
                </>
              )}
            </h2>
            <span className={`status-pill ${result.mode === 'scenario' ? 'degraded' : 'pass'}`}>
              {result.mode === 'scenario' ? 'Mode A: scenario' : 'Mode B: deal vs deal'}
            </span>
          </div>

          {result.mode === 'scenario' ? (
            <>
              <h3 className="subhead">Input changes</h3>
              {result.inputDiffs.length === 0 ? (
                <p className="muted-note">No assumption changes detected.</p>
              ) : (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Assumption</th>
                      <th>Scenario A</th>
                      <th>Scenario B</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.inputDiffs.map((d) => (
                      <tr key={d.field}>
                        <td className="row-label">{d.displayName}</td>
                        <td className="mono">
                          {d.formatType === 'pct' ? fmtPct(d.valueA) : String(d.valueA ?? '—')}
                        </td>
                        <td className="mono">
                          {d.formatType === 'pct' ? fmtPct(d.valueB) : String(d.valueB ?? '—')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          ) : (
            <>
              <h3 className="subhead">Deal assumptions — Deal A vs Deal B</h3>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Assumption</th>
                    <th>Deal A</th>
                    <th>Deal B</th>
                  </tr>
                </thead>
                <tbody>
                  {result.assumptionsComparison.map((r) => (
                    <tr key={r.field}>
                      <td className="row-label">{r.displayName}</td>
                      <td className="mono">{String(r.valueA ?? '—')}</td>
                      <td className="mono">{String(r.valueB ?? '—')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          <h3 className="subhead">Accretion / (Dilution) trajectories</h3>
          <AdTable result={result} />

          <dl className="kv-list">
            <div>
              <dt>{result.mode === 'scenario' ? 'Goodwill (A → B)' : 'Goodwill (Deal A vs Deal B)'}</dt>
              <dd className="mono">
                {fmtCurrency(result.goodwillA)}{' '}
                {result.mode === 'scenario' ? '→' : 'vs'} {fmtCurrency(result.goodwillB)}
              </dd>
            </div>
          </dl>

          {result.commentary && (
            <>
              <h3 className="subhead">Commentary</h3>
              <div className="report-body">{result.commentary}</div>
            </>
          )}
          {result.commentaryError && (
            <p className="warning-note">Commentary not generated: {result.commentaryError}</p>
          )}
        </section>
      )}
    </div>
  )
}
