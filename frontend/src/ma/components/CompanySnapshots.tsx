import { fmtCurrency, fmtPct, fmtShares } from '../api'
import type { CompanySnapshot } from '../types'
import type { PriceOverrides } from '../hooks/useDealState'

interface Props {
  acquirer: CompanySnapshot
  target: CompanySnapshot
  priceOverrides: PriceOverrides
  onPriceOverride: (role: 'acquirer' | 'target', value: string) => void
}

function Row({ label, a, b }: { label: string; a: string; b: string }) {
  return (
    <tr>
      <td className="row-label">{label}</td>
      <td className="mono">{a}</td>
      <td className="mono">{b}</td>
    </tr>
  )
}

function PriceCell({
  snap,
  role,
  override,
  onChange,
}: {
  snap: CompanySnapshot
  role: 'acquirer' | 'target'
  override: string
  onChange: (role: 'acquirer' | 'target', value: string) => void
}) {
  if (snap.currentPrice !== null) {
    return <span className="mono">${snap.currentPrice.toFixed(2)}</span>
  }
  // Gap-fill: price missing from data sources — inline user-provided input,
  // visually distinct (green) from normal inputs and system defaults.
  return (
    <span className="gapfill-wrap">
      <input
        className="gapfill-input"
        type="number"
        min="0"
        step="0.01"
        placeholder="enter price"
        value={override}
        onChange={(e) => onChange(role, e.target.value)}
        title="Missing from data sources — manually supplied by you (tagged user_provided)"
      />
      <span className="gapfill-tag">user-provided</span>
    </span>
  )
}

function GrowthCell({ snap }: { snap: CompanySnapshot }) {
  return (
    <span className={snap.growthIsFallback ? 'growth-fallback' : 'mono'} title={snap.growthNote}>
      {fmtPct(snap.growthDefault)}
      {snap.growthIsFallback && <span className="fallback-flag"> ⚠ fallback</span>}
    </span>
  )
}

export function CompanySnapshots({ acquirer, target, priceOverrides, onPriceOverride }: Props) {
  return (
    <section className="tile snapshot-tile">
      <div className="tile-head">
        <h2>Company data</h2>
        <span className="muted-note">Most recent fiscal year, fetched from SEC EDGAR</span>
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th />
            <th>
              {acquirer.companyName} <span className="th-ticker">({acquirer.ticker})</span>
            </th>
            <th>
              {target.companyName} <span className="th-ticker">({target.ticker})</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <Row
            label="Sector (SIC)"
            a={`${acquirer.sicCode} — ${acquirer.sicDescription}`}
            b={`${target.sicCode} — ${target.sicDescription}`}
          />
          <Row
            label="Fiscal year"
            a={acquirer.fiscalYear ? `FY${acquirer.fiscalYear}` : '—'}
            b={target.fiscalYear ? `FY${target.fiscalYear}` : '—'}
          />
          <tr>
            <td className="row-label">Share price</td>
            <td>
              <PriceCell
                snap={acquirer}
                role="acquirer"
                override={priceOverrides.acquirer}
                onChange={onPriceOverride}
              />
            </td>
            <td>
              <PriceCell
                snap={target}
                role="target"
                override={priceOverrides.target}
                onChange={onPriceOverride}
              />
            </td>
          </tr>
          <Row
            label="Diluted shares"
            a={fmtShares(acquirer.dilutedShares)}
            b={fmtShares(target.dilutedShares)}
          />
          <Row
            label="Diluted EPS"
            a={acquirer.dilutedEps !== null ? `$${acquirer.dilutedEps.toFixed(2)}` : '—'}
            b={target.dilutedEps !== null ? `$${target.dilutedEps.toFixed(2)}` : '—'}
          />
          <Row label="Revenue" a={fmtCurrency(acquirer.revenue)} b={fmtCurrency(target.revenue)} />
          <Row
            label="Operating income"
            a={fmtCurrency(acquirer.operatingIncome)}
            b={fmtCurrency(target.operatingIncome)}
          />
          <Row label="EBITDA" a={fmtCurrency(acquirer.ebitda)} b={fmtCurrency(target.ebitda)} />
          <Row
            label="Net income"
            a={fmtCurrency(acquirer.netIncome)}
            b={fmtCurrency(target.netIncome)}
          />
          <Row
            label="Total debt"
            a={fmtCurrency(acquirer.totalDebt)}
            b={fmtCurrency(target.totalDebt)}
          />
          <Row label="Cash" a={fmtCurrency(acquirer.cash)} b={fmtCurrency(target.cash)} />
          <Row
            label="Total assets"
            a={fmtCurrency(acquirer.totalAssets)}
            b={fmtCurrency(target.totalAssets)}
          />
          <Row
            label="Total liabilities"
            a={fmtCurrency(acquirer.totalLiabilities)}
            b={fmtCurrency(target.totalLiabilities)}
          />
          <tr>
            <td className="row-label">Revenue growth default</td>
            <td>
              <GrowthCell snap={acquirer} />
            </td>
            <td>
              <GrowthCell snap={target} />
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  )
}
