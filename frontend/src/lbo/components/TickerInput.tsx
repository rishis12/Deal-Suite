import styles from './TickerInput.module.css'
import { SOURCE_HEALTH } from '../mock/data'
import type { BackendWakeStatus } from '../hooks/useBackendWake'
import type { AnalyzeFailure } from '../types'

const WAKING_MESSAGE = 'Server is asleep — waking it up now, this can take up to a minute.'

interface Props {
  value: string
  onChange: (v: string) => void
  onAnalyze: () => void
  loading: boolean
  error: AnalyzeFailure | null
  serverStatus: BackendWakeStatus
  serverReadyFlash: boolean
  /** hero = large field inside the empty-state intro; bar = command row */
  variant?: 'hero' | 'bar'
  companyName?: string
  companyMeta?: string
}

export function TickerInput({
  value,
  onChange,
  onAnalyze,
  loading,
  error,
  serverStatus,
  serverReadyFlash,
  variant = 'bar',
  companyName,
  companyMeta,
}: Props) {
  // While a cold backend is still booting, an in-flight Analyze is stuck on
  // that same cold start — label the wait honestly instead of "Analyzing…".
  const wakingDuringAnalyze = loading && (serverStatus === 'unknown' || serverStatus === 'waking')

  const form = (
    <form
      className={variant === 'hero' ? styles.heroRow : styles.barForm}
      onSubmit={(e) => {
        e.preventDefault()
        if (value.trim()) onAnalyze()
      }}
    >
      <input
        className={variant === 'hero' ? styles.heroInput : styles.barInput}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value.toUpperCase())}
        placeholder={variant === 'hero' ? 'Ticker' : 'TICKER'}
        aria-label="Ticker symbol"
        autoComplete="off"
        spellCheck={false}
        disabled={loading}
      />
      <button className="btn btn-primary" type="submit" disabled={loading || !value.trim()}>
        {loading ? (wakingDuringAnalyze ? 'Waking server…' : 'Analyzing…') : 'Analyze'}
      </button>
    </form>
  )

  const statusNotes = (
    <>
      {(serverStatus === 'waking' || wakingDuringAnalyze) && (
        <p className={styles.waking} role="status">
          {WAKING_MESSAGE}
        </p>
      )}
      {serverReadyFlash && !loading && (
        <p className={styles.ready} role="status">
          Server is ready.
        </p>
      )}
      {error && (
        <div className="error-banner" role="alert">
          <strong>Validation failed — {error.ticker}</strong>
          <ul>
            {error.validation.disqualifyingReasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
            {error.validation.missingHard.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          <p style={{ margin: '0.65rem 0 0.25rem', fontWeight: 600 }}>Next steps</p>
          <ul>
            {error.nextSteps.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  )

  if (variant === 'hero') {
    return (
      <div className={styles.heroWrap}>
        {form}
        {statusNotes}
      </div>
    )
  }

  return (
    <section className={`tile ${styles.barTile}`}>
      <div className={styles.barRow}>
        <div className={styles.barField}>
          <span className={styles.barLabel}>Ticker</span>
          {form}
        </div>
        {companyName && (
          <div className={styles.identity}>
            <div className={styles.coName}>{companyName}</div>
            {companyMeta && <div className={styles.coMeta}>{companyMeta}</div>}
          </div>
        )}
        <div className={styles.chips}>
          <span className={`chip ${SOURCE_HEALTH.secEdgar ? 'ok' : 'bad'}`}>SEC EDGAR</span>
          <span className={`chip ${SOURCE_HEALTH.twelveData ? 'ok' : 'bad'}`}>Twelve Data</span>
        </div>
      </div>
      {statusNotes}
    </section>
  )
}
