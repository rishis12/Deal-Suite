import type { ReactNode } from 'react'
import type { ComparisonSlot } from '../types'
import styles from './HowItWorks.module.css'

interface Props {
  tickerForm: ReactNode
  savedModels: ComparisonSlot[]
}

/** Empty / first-run state (frame 1d): intro block, method strip, recent runs. */
export function HowItWorks({ tickerForm, savedModels }: Props) {
  return (
    <>
      <div className={styles.intro}>
        <div className="eyebrow-gold">Step 01 · subject company</div>
        <h1 className={styles.headline}>
          Enter a ticker. The model is built from the company's own filings, not from estimates.
        </h1>
        <p className={styles.copy}>
          Deal Suite pulls the latest 10-K and 10-Q from SEC EDGAR, derives the fundamentals it
          needs, and flags every figure it had to default or substitute.
        </p>
        {tickerForm}
      </div>

      <div className={styles.methods}>
        <div className={styles.method}>
          <div className="eyebrow-gold">01 Pull</div>
          <div className={styles.methodTitle}>Filings, not guesses</div>
          <p className={styles.methodCopy}>
            Revenue, EBITDA, debt, share count and capex read straight from EDGAR XBRL.
          </p>
        </div>
        <div className={styles.method}>
          <div className="eyebrow-gold">02 Model</div>
          <div className={styles.methodTitle}>Assumptions you own</div>
          <p className={styles.methodCopy}>
            Entry and exit multiples, leverage, coupon and hold period are yours to set. Each one
            shows whether it came from you, from the filing, or from a default we applied.
          </p>
        </div>
        <div className={styles.method}>
          <div className="eyebrow-gold">03 Export</div>
          <div className={styles.methodTitle}>A live workbook</div>
          <p className={styles.methodCopy}>
            Excel out with every cell still a formula. LibreOffice recalculates the whole
            workbook before any number is shown to you.
          </p>
        </div>
      </div>

      <section className="card card-flush">
        <div className="card-head">
          <span className="card-title">Recent runs</span>
          <span className="card-note">Session only</span>
        </div>
        <div className="card-body">
          {savedModels.length === 0 ? (
            <p className={styles.emptyRuns}>
              No saved models yet.
              <br />
              Generated models appear here and can be compared side by side.
            </p>
          ) : (
            <ul className={styles.runList}>
              {savedModels.map((m) => (
                <li key={m.id}>
                  <span className={styles.runTicker}>{m.ticker}</span> {m.label}
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      <p className={styles.sourceLine}>
        Source SEC EDGAR · contact email required by SEC fair access · prices via market data
        provider, degrades gracefully
      </p>
    </>
  )
}
