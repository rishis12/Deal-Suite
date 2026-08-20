import { fmtCurrency, fmtPct, fmtShares } from '../api'
import type { GenerateResponse } from '../types'

interface Props {
  results: GenerateResponse
  onDownload: () => void
}

/** Year-by-year accretion/dilution trajectory — the headline visual.
    Simple deterministic bar chart: green up-bars accretive, red down-bars
    dilutive, so the crossover story is visible at a glance. */
function AdTrajectory({ values }: { values: (number | null)[] }) {
  const nums = values.filter((v): v is number => v !== null)
  if (nums.length === 0) return null
  const maxAbs = Math.max(...nums.map(Math.abs), 0.001)
  const H = 72 // px half-height

  return (
    <div className="ad-chart" role="img" aria-label="Accretion dilution by year">
      {values.map((v, i) => {
        const h = v === null ? 0 : (Math.abs(v) / maxAbs) * H
        const positive = (v ?? 0) >= 0
        return (
          <div key={i} className="ad-col">
            <div className="ad-bar-area">
              <div className="ad-bar-up">
                {positive && v !== null && (
                  <div className="ad-bar pos" style={{ height: `${Math.max(h, 2)}px` }} />
                )}
              </div>
              <div className="ad-zero-line" />
              <div className="ad-bar-down">
                {!positive && v !== null && (
                  <div className="ad-bar neg" style={{ height: `${Math.max(h, 2)}px` }} />
                )}
              </div>
            </div>
            <span className={`ad-value mono ${positive ? 'positive' : 'negative'}`}>
              {v === null ? '—' : fmtPct(v)}
            </span>
            <span className="ad-year">Y{i + 1}</span>
          </div>
        )
      })}
    </div>
  )
}

export function ResultsPanel({ results, onDownload }: Props) {
  const su = results.sourcesUses
  const ppa = results.ppa
  const ad = results.accretionDilutionByYear
  const y1 = ad[0]
  const yN = ad[ad.length - 1]

  return (
    <section className="tile results-tile">
      <div className="tile-head">
        <h2>Results</h2>
        <button type="button" className="primary-btn" onClick={onDownload}>
          Download .xlsx
        </button>
      </div>

      {/* Headline: accretion/dilution */}
      <div className="headline-row">
        <div className="headline-stat">
          <span className="headline-label">Year 1</span>
          <span className={`headline-value mono ${(y1 ?? 0) >= 0 ? 'positive' : 'negative'}`}>
            {fmtPct(y1)}
          </span>
        </div>
        <div className="headline-stat">
          <span className="headline-label">Year {ad.length}</span>
          <span className={`headline-value mono ${(yN ?? 0) >= 0 ? 'positive' : 'negative'}`}>
            {fmtPct(yN)}
          </span>
        </div>
        <div className="headline-crossover">
          {results.crossover && <p className="crossover-note">{results.crossover}</p>}
          {results.standaloneEps !== null && (
            <p className="muted-note">
              vs. acquirer standalone EPS ${results.standaloneEps.toFixed(2)}
            </p>
          )}
        </div>
      </div>

      <h3 className="subhead">Accretion / (dilution) by year</h3>
      <AdTrajectory values={ad} />

      <h3 className="subhead">Pro forma EPS bridge</h3>
      <div style={{ overflowX: 'auto' }}>
        <table className="deck-table">
          <thead>
            <tr>
              <th>Line item</th>
              {ad.map((_, i) => (
                <th key={i} className="num">
                  Y{i + 1}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Pro forma diluted EPS</td>
              {results.proFormaEpsByYear.map((v, i) => (
                <td key={i} className="num">
                  {v === null ? '—' : `$${v.toFixed(2)}`}
                </td>
              ))}
            </tr>
            <tr className="row-em">
              <td>EPS — accretion / (dilution)</td>
              {ad.map((v, i) => (
                <td key={i} className={`num ${(v ?? 0) >= 0 ? 'pos-num' : 'neg-num'}`}>
                  {v === null ? '—' : fmtPct(v)}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>

      <div className="results-columns">
        <div>
          <h3 className="subhead">Sources &amp; uses</h3>
          <dl className="kv-list">
            <div>
              <dt>Purchase equity value</dt>
              <dd className="mono">{fmtCurrency(su.purchaseEquityValue)}</dd>
            </div>
            <div>
              <dt>Transaction fees</dt>
              <dd className="mono">{fmtCurrency(su.transactionFees)}</dd>
            </div>
            <div>
              <dt>Total uses</dt>
              <dd className="mono">{fmtCurrency(su.totalUses)}</dd>
            </div>
            <div>
              <dt>Cash used</dt>
              <dd className="mono">{fmtCurrency(su.cashUsed)}</dd>
            </div>
            <div>
              <dt>New debt raised</dt>
              <dd className="mono">{fmtCurrency(su.newDebt)}</dd>
            </div>
            <div>
              <dt>New stock issued</dt>
              <dd className="mono">
                {fmtCurrency(su.newStockIssued)}
                {su.newSharesIssued !== null && su.newSharesIssued > 0 && (
                  <span className="muted-note"> ({fmtShares(su.newSharesIssued)} shares)</span>
                )}
              </dd>
            </div>
            <div>
              <dt>Balance check</dt>
              <dd className={`mono ${su.balanceCheck === 0 ? 'positive' : 'negative'}`}>
                {su.balanceCheck === 0 ? '0 ✓' : fmtCurrency(su.balanceCheck)}
              </dd>
            </div>
          </dl>
        </div>

        <div>
          <h3 className="subhead">Purchase price allocation</h3>
          <dl className="kv-list">
            <div>
              <dt>Target book equity</dt>
              <dd className="mono">{fmtCurrency(ppa.targetBookEquity)}</dd>
            </div>
            <div>
              <dt>Premium over book</dt>
              <dd className="mono">{fmtCurrency(ppa.premiumOverBook)}</dd>
            </div>
            <div>
              <dt>Asset step-up</dt>
              <dd className="mono">{fmtCurrency(ppa.assetStepUp)}</dd>
            </div>
            <div>
              <dt>Goodwill</dt>
              <dd className="mono">{fmtCurrency(ppa.goodwill)}</dd>
            </div>
            <div>
              <dt>Incremental annual D&amp;A</dt>
              <dd className="mono">{fmtCurrency(ppa.incrementalDA)}</dd>
            </div>
          </dl>
        </div>
      </div>

      {/* HHI */}
      <h3 className="subhead">Market concentration (HHI)</h3>
      {results.hhi.assessed ? (
        <dl className="kv-list hhi-list">
          <div>
            <dt>Pre-merger HHI</dt>
            <dd className="mono">
              {results.hhi.preMergerHHI?.toLocaleString(undefined, { maximumFractionDigits: 0 })}{' '}
              <span className="muted-note">({results.hhi.preMergerClass})</span>
            </dd>
          </div>
          <div>
            <dt>Post-merger HHI</dt>
            <dd className="mono">
              {results.hhi.postMergerHHI?.toLocaleString(undefined, { maximumFractionDigits: 0 })}{' '}
              <span className="muted-note">({results.hhi.postMergerClass})</span>
            </dd>
          </div>
          <div>
            <dt>Delta HHI</dt>
            <dd className="mono">
              {results.hhi.deltaHHI?.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </dd>
          </div>
          <div>
            <dt>Presumptive concern</dt>
            <dd
              className={
                results.hhi.presumptiveConcern?.startsWith('PRESUMED')
                  ? 'negative-note'
                  : 'positive-note'
              }
            >
              {results.hhi.presumptiveConcern}
            </dd>
          </div>
        </dl>
      ) : (
        <p className="muted-note">
          Not assessed — the market share table was left empty.
        </p>
      )}

      {/* Narrative report */}
      {results.report && (
        <>
          <h3 className="subhead">Narrative report</h3>
          <div className="report-body">{results.report}</div>
        </>
      )}
      {results.reportError && (
        <p className="warning-note">Report not generated: {results.reportError}</p>
      )}
    </section>
  )
}
