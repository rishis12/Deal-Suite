import { useState } from 'react'
import type { CompanySnapshot, OverrideKey, UserOverrides } from '../types'
import styles from './CompanySnapshot.module.css'

interface Props {
  snapshot: CompanySnapshot
  userOverrides: UserOverrides
  onUpdateOverride: (key: OverrideKey, value: number | undefined) => void
}

function formatCap(n: number): string {
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`
  return `$${n.toLocaleString()}`
}

function formatShares(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  return n.toLocaleString()
}

// Map flag text patterns to override keys
function getOverrideKeyFromFlagText(text: string): OverrideKey | null {
  const lower = text.toLowerCase()
  if (lower.includes('price') || lower.includes('share price')) return 'currentPrice'
  if (lower.includes('debt')) return 'totalDebt'
  if (lower.includes('cash')) return 'cash'
  if (lower.includes('capex')) return 'capex'
  return null
}

export function CompanySnapshot({ snapshot, userOverrides, onUpdateOverride }: Props) {
  const [collapsed, setCollapsed] = useState(false)
  const [showTooltip, setShowTooltip] = useState(false)
  const [editingPrice, setEditingPrice] = useState(false)
  const [priceInput, setPriceInput] = useState('')
  const v = snapshot.validation
  const maxRev = Math.max(...snapshot.revenueHistory.map((p) => p.revenue), 1)

  // Check if price is user-provided
  const isPriceUserProvided = userOverrides.currentPrice !== undefined
  const displayPrice = isPriceUserProvided ? userOverrides.currentPrice! : snapshot.currentPrice

  // Collect all issues for display, excluding user-provided ones
  const issues = [
    ...v.missingHard.map((t) => ({ type: 'missing' as const, text: t })),
    ...v.missingSoft.map((t) => ({ type: 'warning' as const, text: t })),
    ...v.defaultsApplied.map((t) => ({ type: 'defaulted' as const, text: t })),
    ...v.substituteWarnings.map((t) => ({ type: 'substituted' as const, text: t })),
  ].map((issue) => {
    // Check if this issue has been resolved by a user override
    const overrideKey = getOverrideKeyFromFlagText(issue.text)
    if (overrideKey && userOverrides[overrideKey] !== undefined) {
      return { ...issue, type: 'user_provided' as const }
    }
    return issue
  })

  const unresolvedIssues = issues.filter((i) => i.type !== 'user_provided')
  const hasDegradedIssues = v.status === 'degraded' && unresolvedIssues.length > 0

  const handlePriceSubmit = () => {
    const value = parseFloat(priceInput)
    if (!isNaN(value) && value > 0) {
      onUpdateOverride('currentPrice', value)
      setEditingPrice(false)
    }
  }

  const handlePriceKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handlePriceSubmit()
    } else if (e.key === 'Escape') {
      setEditingPrice(false)
    }
  }

  return (
    <section className={`tile tile-snapshot collapsible ${collapsed ? 'collapsed' : ''}`}>
      <button
        type="button"
        className="collapsible-header"
        onClick={() => setCollapsed((c) => !c)}
      >
        Company Snapshot
        <span>{collapsed ? '+' : '−'}</span>
      </button>
      <h2 className="tile-title">Company Snapshot</h2>
      <div className="collapsible-body">
        <div className={styles.head}>
          <div>
            <div className={styles.name}>{snapshot.companyName}</div>
            <div className={styles.tickerRow}>
              <span className={`mono ${styles.ticker}`}>{snapshot.ticker}</span>
              <span className="badge badge-sector">
                SIC {snapshot.sicCode} · {snapshot.sicDescription}
              </span>
            </div>
          </div>
          <div
            className={styles.quality}
            onMouseEnter={() => hasDegradedIssues && setShowTooltip(true)}
            onMouseLeave={() => setShowTooltip(false)}
          >
            <span className={`status-dot ${hasDegradedIssues ? 'degraded' : 'pass'}`} />
            <span className={styles.qualityLabel}>
              {hasDegradedIssues ? 'Degraded' : isPriceUserProvided ? 'User-Filled' : 'Pass'}
            </span>
            {hasDegradedIssues && (
              <span className={styles.infoIcon} title="Click to see details">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <path d="M12 16v-4M12 8h.01" />
                </svg>
              </span>
            )}
            {showTooltip && hasDegradedIssues && (
              <div className={styles.tooltip}>
                <div className={styles.tooltipTitle}>Data Quality Issues</div>
                <p className={styles.tooltipDesc}>
                  Some data wasn't reported by the company and was estimated using fallbacks.
                  You can manually provide missing values below.
                </p>
                <ul className={styles.tooltipList}>
                  {unresolvedIssues.map((issue, i) => (
                    <li key={i} className={styles[issue.type]}>
                      {issue.text}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>

        <div className={styles.metrics}>
          <div className={styles.metricBlock}>
            <div className={styles.metricLabel}>
              Price
              {isPriceUserProvided && (
                <span className={styles.userProvidedTag}>User</span>
              )}
            </div>
            {editingPrice ? (
              <div className={styles.inlineEdit}>
                <span className={styles.currencyPrefix}>$</span>
                <input
                  type="number"
                  step="0.01"
                  autoFocus
                  className={styles.inlineInput}
                  value={priceInput}
                  onChange={(e) => setPriceInput(e.target.value)}
                  onKeyDown={handlePriceKeyDown}
                  onBlur={handlePriceSubmit}
                  placeholder="0.00"
                />
              </div>
            ) : displayPrice > 0 ? (
              <div
                className={`mono ${styles.metricVal} ${isPriceUserProvided ? styles.userProvided : ''}`}
                onClick={() => {
                  if (!isPriceUserProvided || displayPrice === 0) {
                    setPriceInput(displayPrice > 0 ? displayPrice.toFixed(2) : '')
                    setEditingPrice(true)
                  }
                }}
              >
                ${displayPrice.toFixed(2)}
              </div>
            ) : (
              <button
                type="button"
                className={styles.addValueBtn}
                onClick={() => {
                  setPriceInput('')
                  setEditingPrice(true)
                }}
              >
                <span className={styles.addIcon}>+</span> Add price
              </button>
            )}
          </div>
          <div>
            <div className={styles.metricLabel}>Shares</div>
            <div className={`mono ${styles.metricVal}`}>{formatShares(snapshot.sharesOutstanding)}</div>
          </div>
          <div>
            <div className={styles.metricLabel}>
              Market Cap
              {isPriceUserProvided && snapshot.marketCap > 0 && (
                <span className={styles.derivedTag}>Derived</span>
              )}
            </div>
            <div className={`mono ${styles.metricVal}`}>
              {snapshot.marketCap > 0 ? formatCap(snapshot.marketCap) : '—'}
            </div>
          </div>
        </div>

        <div className={styles.chartLabel}>5-year revenue</div>
        <div className={styles.bars} role="img" aria-label="Five year revenue trend">
          {snapshot.revenueHistory.map((p) => (
            <div key={p.year} className={styles.barCol}>
              <div
                className={styles.bar}
                style={{ height: `${Math.max(8, (p.revenue / maxRev) * 100)}%` }}
                title={`${p.year}: ${formatCap(p.revenue)}`}
              />
              <span className={styles.barYear}>{String(p.year).slice(2)}</span>
            </div>
          ))}
        </div>

        {issues.length > 0 && (
          <div className={styles.flags}>
            <div className={styles.flagsTitle}>Data Quality Flags</div>
            {issues.map((f, i) => {
              const overrideKey = getOverrideKeyFromFlagText(f.text)
              const isResolved = f.type === 'user_provided'

              return (
                <div key={i} className={styles.flagRow}>
                  <span
                    className={`badge ${
                      isResolved ? 'badge-user-provided' :
                      f.type === 'defaulted' ? 'badge-defaulted' :
                      f.type === 'substituted' ? 'badge-substituted' :
                      f.type === 'missing' ? 'badge-missing' :
                      'badge-warning'
                    }`}
                  >
                    {isResolved ? '✓ User-Provided' :
                     f.type === 'defaulted' ? '⚠ Defaulted' :
                     f.type === 'substituted' ? '⚠ Substituted' :
                     f.type === 'missing' ? '✗ Missing' :
                     '⚠ Warning'}: {f.text}
                  </span>
                  {!isResolved && overrideKey && (
                    <button
                      type="button"
                      className={styles.fillBtn}
                      onClick={() => {
                        if (overrideKey === 'currentPrice') {
                          setPriceInput('')
                          setEditingPrice(true)
                        }
                      }}
                    >
                      Fill manually
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </section>
  )
}
