import type { BackendWakeStatus } from '../hooks/useBackendWake'

interface Props {
  acquirer: string
  target: string
  onAcquirerChange: (v: string) => void
  onTargetChange: (v: string) => void
  onAnalyze: () => void
  loading: boolean
  error: string | null
  serverStatus: BackendWakeStatus
  serverReadyFlash: boolean
}

export function TickerPairInput({
  acquirer,
  target,
  onAcquirerChange,
  onTargetChange,
  onAnalyze,
  loading,
  error,
  serverStatus,
  serverReadyFlash,
}: Props) {
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !loading) onAnalyze()
  }

  return (
    <section className="tile ticker-tile">
      <div className="ticker-pair-row">
        <label className="ticker-field">
          <span className="field-label">Acquirer ticker</span>
          <input
            type="text"
            value={acquirer}
            placeholder="e.g. MSFT"
            onChange={(e) => onAcquirerChange(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={loading}
          />
        </label>
        <span className="ticker-arrow" aria-hidden>
          acquires
        </span>
        <label className="ticker-field">
          <span className="field-label">Target ticker</span>
          <input
            type="text"
            value={target}
            placeholder="e.g. POOL"
            onChange={(e) => onTargetChange(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={loading}
          />
        </label>
        <button type="button" className="primary-btn" onClick={onAnalyze} disabled={loading}>
          {loading ? 'Analyzing…' : 'Analyze'}
        </button>
      </div>

      {serverStatus === 'waking' && (
        <p className="server-note warning-note">
          Server is asleep — waking it up now, this can take up to a minute.
        </p>
      )}
      {serverReadyFlash && <p className="server-note positive-note">Server is ready.</p>}
      {serverStatus === 'unreachable' && (
        <p className="server-note negative-note">Backend unreachable — check that it's running.</p>
      )}
      {error && <p className="server-note negative-note">{error}</p>}
    </section>
  )
}
