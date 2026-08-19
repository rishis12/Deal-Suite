import { useState } from 'react'
import type { CompanySnapshot, MarketShareRow } from '../types'

interface Props {
  acquirer: CompanySnapshot
  target: CompanySnapshot
  rows: MarketShareRow[]
  onRowsChange: (rows: MarketShareRow[]) => void
}

/**
 * Build the research-assist prompt from the REAL analyzed companies —
 * mirrors the text the backend embeds in the workbook's Market
 * Concentration tab. The user runs it externally (any AI assistant with
 * search) and brings the numbers back; this tool never makes the research
 * call itself.
 */
function buildResearchPrompt(acq: CompanySnapshot, tgt: CompanySnapshot): string {
  return (
    `Research current market share estimates for a potential merger analysis. ` +
    `The two companies are: (1) ${acq.companyName} (ticker ${acq.ticker}) and ` +
    `(2) ${tgt.companyName} (ticker ${tgt.ticker}). Both operate in or around ` +
    `the industry: "${tgt.sicDescription}" (SEC SIC ${tgt.sicCode}; acquirer ` +
    `SIC ${acq.sicCode} - "${acq.sicDescription}"). Please: (a) define the most ` +
    `sensible relevant market these two actually compete in, (b) list the major ` +
    `competitors in that market, and (c) give best-available estimated market ` +
    `share percentages for each company including the two above, with sources ` +
    `and dates for every estimate. Flag any number that is an inference rather ` +
    `than a published figure.`
  )
}

export function MarketConcentration({ acquirer, target, rows, onRowsChange }: Props) {
  const [copied, setCopied] = useState(false)
  const sameIndustry = acquirer.sicCode === target.sicCode

  const updateRow = (i: number, patch: Partial<MarketShareRow>) => {
    const next = rows.slice()
    next[i] = { ...next[i], ...patch }
    onRowsChange(next)
  }

  const addRow = () => onRowsChange([...rows, { companyName: '', marketShare: NaN }])

  const removeRow = (i: number) => onRowsChange(rows.filter((_, idx) => idx !== i))

  const copyPrompt = async () => {
    await navigator.clipboard.writeText(buildResearchPrompt(acquirer, target))
    setCopied(true)
    window.setTimeout(() => setCopied(false), 2500)
  }

  return (
    <section className="tile concentration-tile">
      <div className="tile-head">
        <h2>Market Concentration (optional)</h2>
        <span className={sameIndustry ? 'status-pill degraded' : 'status-pill pass'}>
          {sameIndustry ? 'Same industry (same SIC)' : 'Different SIC codes'}
        </span>
      </div>

      <div className="research-assist">
        <button type="button" className="secondary-btn" onClick={copyPrompt}>
          {copied ? '✓ Copied' : 'Copy research prompt'}
        </button>
        <span className="muted-note">
          Paste this into any AI assistant with search access, then bring the numbers back here.
          Estimates you enter are tagged <em>user-provided</em> — AI research stays human-reviewed.
        </span>
      </div>

      <table className="data-table share-table">
        <thead>
          <tr>
            <th>Company</th>
            <th>Est. market share %</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const locked = i < 2 // acquirer + target rows keep their names
            return (
              <tr key={i}>
                <td>
                  <input
                    className="gapfill-input share-name"
                    type="text"
                    value={row.companyName}
                    placeholder="Competitor name"
                    disabled={locked}
                    onChange={(e) => updateRow(i, { companyName: e.target.value })}
                  />
                  {locked && (
                    <span className="th-ticker"> ({i === 0 ? 'acquirer' : 'target'})</span>
                  )}
                </td>
                <td>
                  <span className="pct-input-wrap">
                    <input
                      className="gapfill-input"
                      type="number"
                      min="0"
                      max="100"
                      step="0.5"
                      placeholder="—"
                      value={Number.isNaN(row.marketShare) ? '' : row.marketShare * 100}
                      onChange={(e) => {
                        const v = parseFloat(e.target.value)
                        updateRow(i, { marketShare: Number.isNaN(v) ? NaN : v / 100 })
                      }}
                    />
                    <span className="pct-suffix">%</span>
                  </span>
                </td>
                <td>
                  {!locked && (
                    <button
                      type="button"
                      className="remove-btn"
                      aria-label="Remove row"
                      onClick={() => removeRow(i)}
                    >
                      ✕
                    </button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <button type="button" className="secondary-btn add-row-btn" onClick={addRow}>
        + Add competitor
      </button>
      <p className="muted-note">
        Leave the table empty to skip — the model will report market concentration as not
        assessed rather than guessing.
      </p>
    </section>
  )
}
