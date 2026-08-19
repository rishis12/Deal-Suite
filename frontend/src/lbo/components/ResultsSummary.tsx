import { useState } from 'react'
import type { ModelResults } from '../types'
import styles from './ResultsSummary.module.css'

interface Props {
  results: ModelResults
  onDownload: () => void
  onReport: () => void
  showReport: boolean
  hasLlmKey: boolean
  onNeedKey: () => void
}

function irrColor(irr: number): string {
  if (irr > 0.2) return 'var(--success)'
  if (irr >= 0.15) return 'var(--warning)'
  return 'var(--danger)'
}

export function ResultsSummary({ results, onDownload, onReport, showReport, hasLlmKey, onNeedKey }: Props) {
  const [collapsed, setCollapsed] = useState(false)
  const f = results.feasibility
  const pct = (f.total / 100) * 100
  const circumference = 2 * Math.PI * 42
  const offset = circumference - (pct / 100) * circumference

  const bars = [
    { label: 'IRR', value: f.irr, max: f.max.irr },
    { label: 'MOIC', value: f.moic, max: f.max.moic },
    { label: 'Debt Service', value: f.debtService, max: f.max.debtService },
    { label: 'Leverage Reduction', value: f.leverageReduction, max: f.max.leverageReduction },
    { label: 'Data Quality', value: f.dataQuality, max: f.max.dataQuality },
  ]

  return (
    <section className={`tile tile-results collapsible ${collapsed ? 'collapsed' : ''}`}>
      <button
        type="button"
        className="collapsible-header"
        onClick={() => setCollapsed((c) => !c)}
      >
        Results Summary
        <span>{collapsed ? '+' : '−'}</span>
      </button>
      <h2 className="tile-title">Results Summary</h2>
      <div className="collapsible-body">
        <div className={styles.headlines}>
          <div>
            <div className={styles.hlLabel}>IRR</div>
            <div className={`mono ${styles.hlValue}`} style={{ color: irrColor(results.irr) }}>
              {(results.irr * 100).toFixed(1)}%
            </div>
          </div>
          <div>
            <div className={styles.hlLabel}>MOIC</div>
            <div className={`mono ${styles.hlValue}`}>{results.moic.toFixed(2)}x</div>
          </div>
        </div>

        <div className={styles.ringRow}>
          <svg className={styles.ring} viewBox="0 0 100 100" aria-label={`Feasibility ${f.total} of 100`}>
            <circle cx="50" cy="50" r="42" fill="none" stroke="var(--border)" strokeWidth="8" />
            <circle
              cx="50"
              cy="50"
              r="42"
              fill="none"
              stroke="var(--accent)"
              strokeWidth="8"
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={offset}
              transform="rotate(-90 50 50)"
            />
            <text x="50" y="48" textAnchor="middle" className={styles.ringScore}>
              {f.total}
            </text>
            <text x="50" y="62" textAnchor="middle" className={styles.ringSub}>
              /100
            </text>
          </svg>
          <div className={styles.ringCaption}>Feasibility Score</div>
        </div>

        <div className={styles.bars}>
          {bars.map((b) => (
            <div key={b.label} className={styles.barRow}>
              <div className={styles.barMeta}>
                <span>{b.label}</span>
                <span className="mono">
                  {b.value.toFixed(0)}/{b.max}
                </span>
              </div>
              <div className={styles.barTrack}>
                <div
                  className={styles.barFill}
                  style={{ width: `${Math.min(100, (b.value / b.max) * 100)}%` }}
                />
              </div>
            </div>
          ))}
        </div>

        <div className={styles.actions}>
          <button type="button" className="btn btn-primary btn-block" onClick={onDownload}>
            Download Excel
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-block"
            onClick={hasLlmKey ? onReport : onNeedKey}
          >
            {showReport ? 'Hide Report' : 'Generate AI Analysis Report'}
          </button>
        </div>

        {!hasLlmKey && (
          <p className={styles.keyHint}>
            Add an LLM API key in Settings to generate AI analysis reports.
          </p>
        )}

        {showReport && hasLlmKey && (
          <pre className={styles.report}>{results.reportMarkdown}</pre>
        )}
      </div>
    </section>
  )
}
