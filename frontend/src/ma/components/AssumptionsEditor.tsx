import { ASSUMPTION_FIELDS } from '../types'
import { fmtPct } from '../api'

interface Props {
  assumptions: Record<string, number>
  onChange: (key: string, value: number) => void
  onGenerate: () => void
  generating: boolean
  disabled: boolean
}

export function AssumptionsEditor({
  assumptions,
  onChange,
  onGenerate,
  generating,
  disabled,
}: Props) {
  const pctStock = 1 - (assumptions.pct_cash ?? 0) - (assumptions.pct_debt ?? 0)
  const mixInvalid = pctStock < -1e-9

  return (
    <section className="tile assumptions-tile">
      <div className="tile-head">
        <h2>Deal assumptions</h2>
        <span className="muted-note">Blue = your inputs. % Stock is always derived.</span>
      </div>
      <div className="assumptions-grid">
        {ASSUMPTION_FIELDS.map((f) => {
          const raw = assumptions[f.key]
          return (
            <label key={f.key} className="assumption-field">
              <span className="field-label">{f.label}</span>
              {f.kind === 'pct' ? (
                <span className="pct-input-wrap">
                  <input
                    type="number"
                    step="0.5"
                    value={raw !== undefined ? Math.round(raw * 1000) / 10 : ''}
                    onChange={(e) => onChange(f.key, parseFloat(e.target.value) / 100 || 0)}
                  />
                  <span className="pct-suffix">%</span>
                </span>
              ) : (
                <input
                  type="number"
                  step="1"
                  min="1"
                  value={raw !== undefined ? raw : ''}
                  onChange={(e) => onChange(f.key, parseInt(e.target.value, 10) || 1)}
                />
              )}
            </label>
          )
        })}

        {/* % Stock: read-only derived plug, never an editable input */}
        <div className="assumption-field derived-field">
          <span className="field-label">% Stock (derived)</span>
          <span className="derived-value mono" title="Always 100% − % Cash − % Debt — never a direct input">
            {fmtPct(pctStock)}
          </span>
        </div>
      </div>

      {mixInvalid && (
        <p className="negative-note">
          % Cash + % Debt exceeds 100% — the derived % Stock is negative. Fix the mix before
          generating.
        </p>
      )}

      <button
        type="button"
        className="primary-btn generate-btn"
        onClick={onGenerate}
        disabled={generating || disabled || mixInvalid}
      >
        {generating ? 'Generating (recalculating workbook)…' : 'Generate M&A Model'}
      </button>
    </section>
  )
}
