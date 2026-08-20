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

/** Ink returns card (frame 1a vocabulary): feasibility breakdown on dark,
    exit equity value in gold, output actions. */
export function ResultsSummary({
  results,
  onDownload,
  onReport,
  showReport,
  hasLlmKey,
  onNeedKey,
}: Props) {
  const f = results.feasibility
  const bars = [
    { label: 'IRR', value: f.irr, max: f.max.irr },
    { label: 'MOIC', value: f.moic, max: f.max.moic },
    { label: 'Debt service', value: f.debtService, max: f.max.debtService },
    { label: 'Leverage reduction', value: f.leverageReduction, max: f.max.leverageReduction },
    { label: 'Data quality', value: f.dataQuality, max: f.max.dataQuality },
  ]

  const fmtExit = (v: number) =>
    v >= 1e9 ? `$${(v / 1e9).toFixed(2)}B` : `$${(v / 1e6).toFixed(0)}M`

  return (
    <section className="card card-ink card-flush">
      <div className="card-head">
        <span className="card-title">Returns &amp; feasibility</span>
        <span className="card-note">{f.total} / 100</span>
      </div>
      <div className="card-body">
        <div className={styles.headRow}>
          <div>
            <div className={styles.hLabel}>Sponsor IRR</div>
            <div className={styles.hFig}>{(results.irr * 100).toFixed(1)}%</div>
          </div>
          <div>
            <div className={styles.hLabel}>MOIC</div>
            <div className={styles.hFig}>{results.moic.toFixed(2)}×</div>
          </div>
        </div>

        <div className={styles.bars}>
          {bars.map((b) => {
            const ratio = b.max > 0 ? b.value / b.max : 0
            return (
              <div key={b.label} className={styles.barRow}>
                <div className={styles.barMeta}>
                  <span>{b.label}</span>
                  <span>
                    {b.value.toFixed(0)}/{b.max}
                  </span>
                </div>
                <div className={styles.barTrack}>
                  <div
                    className={styles.barFill}
                    style={{ width: `${Math.min(100, ratio * 100)}%` }}
                  />
                </div>
              </div>
            )
          })}
        </div>

        <div className={styles.exitRow}>
          <span className={styles.exitLabel}>Exit equity value</span>
          <span className={styles.exitFig}>{fmtExit(results.exitEquityValue)}</span>
        </div>

        <div className={styles.actions}>
          <button type="button" className={styles.actionGhost} onClick={onDownload}>
            Download .xlsx
          </button>
          <button
            type="button"
            className={styles.actionGhost}
            onClick={hasLlmKey ? onReport : onNeedKey}
          >
            {showReport ? 'Hide narrative report' : 'Narrative report'}
          </button>
        </div>

        {!hasLlmKey && (
          <p className={styles.keyHint}>Add an LLM API key in Settings to generate reports.</p>
        )}

        {showReport && hasLlmKey && <pre className={styles.report}>{results.reportMarkdown}</pre>}
      </div>
    </section>
  )
}
