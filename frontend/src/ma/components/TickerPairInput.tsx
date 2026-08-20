import type { BackendWakeStatus } from '../hooks/useBackendWake'
import type { CompanySnapshot } from '../types'

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
  acquirerInfo?: CompanySnapshot | null
  targetInfo?: CompanySnapshot | null
}

function PartyCard({
  role,
  value,
  onChange,
  onKeyDown,
  loading,
  info,
  placeholder,
}: {
  role: string
  value: string
  onChange: (v: string) => void
  onKeyDown: (e: React.KeyboardEvent) => void
  loading: boolean
  info?: CompanySnapshot | null
  placeholder: string
}) {
  return (
    <div className="party-card">
      <div className="party-head">
        <span className="party-role">{role}</span>
        {info && (
          <span className="party-figs">
            {info.currentPrice !== null && (
              <span>
                <span className="party-fig-label">Price </span>
                {info.currentPrice.toFixed(2)}
              </span>
            )}
            {info.dilutedEps !== null && (
              <span>
                <span className="party-fig-label">EPS </span>
                {info.dilutedEps.toFixed(2)}
              </span>
            )}
          </span>
        )}
      </div>
      <div className="party-body">
        <input
          type="text"
          value={value}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={loading}
          aria-label={`${role} ticker`}
        />
        {info && <div className="party-name">{info.companyName}</div>}
      </div>
    </div>
  )
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
  acquirerInfo,
  targetInfo,
}: Props) {
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !loading) onAnalyze()
  }

  return (
    <section className="party-row-wrap">
      <div className="party-row">
        <PartyCard
          role="Acquirer"
          value={acquirer}
          onChange={onAcquirerChange}
          onKeyDown={onKeyDown}
          loading={loading}
          info={acquirerInfo}
          placeholder="e.g. MSFT"
        />
        <span className="party-plus" aria-hidden>
          +
        </span>
        <PartyCard
          role="Target"
          value={target}
          onChange={onTargetChange}
          onKeyDown={onKeyDown}
          loading={loading}
          info={targetInfo}
          placeholder="e.g. POOL"
        />
        <button type="button" className="primary-btn party-analyze" onClick={onAnalyze} disabled={loading}>
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
