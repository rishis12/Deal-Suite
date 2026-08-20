import { useEffect, useState } from 'react'
import { AssumptionsEditor } from './components/AssumptionsEditor'
import { CompanySnapshot } from './components/CompanySnapshot'
import { ComparisonPanel } from './components/ComparisonPanel'
import { HowItWorks } from './components/HowItWorks'
import { ResultsSummary } from './components/ResultsSummary'
import { SensitivityHeatmap } from './components/SensitivityHeatmap'
import { SkeletonTile } from './components/SkeletonTile'
import { TickerInput } from './components/TickerInput'
import { useAppState } from './hooks/useAppState'
import { useBackendWake } from './hooks/useBackendWake'
import type { SessionKeys } from './types'

type Tab = 'report' | 'comparison'

interface Props {
  keys: SessionKeys
  hasLlmKey: boolean
  openSettings: () => void
}

const API_HOST = (import.meta.env.VITE_API_URL || 'http://localhost:8002').replace(
  /^https?:\/\//,
  '',
)

function scrollToId(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/** Amber cold-start banner with an indicative elapsed counter (frame 1e). */
function ColdStartBanner({ waking }: { waking: boolean }) {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const t = window.setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => window.clearInterval(t)
  }, [])
  const mm = String(Math.floor(elapsed / 60)).padStart(2, '0')
  const ss = String(elapsed % 60).padStart(2, '0')
  const pct = Math.min(92, 8 + elapsed * 4)
  return (
    <>
      <div className="banner warn" role="status">
        <div className="banner-main">
          <div className="banner-title">
            {waking
              ? 'Backend is waking from idle — first request can take ~20 seconds.'
              : 'Pulling filings from SEC EDGAR and building the model.'}
          </div>
          <div className="banner-sub">Fetching XBRL facts · validating · deriving defaults</div>
        </div>
        <div className="banner-side">
          <span className="banner-timer">
            {mm}:{ss}
          </span>
        </div>
      </div>
      <div className="progress-track" aria-hidden>
        <div className="progress-bar" style={{ width: `${pct}%` }} />
      </div>
    </>
  )
}

/** LBO Analyzer product pane — rail + main column in the terminal shell. */
export default function LboApp({ keys, hasLlmKey, openSettings }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('report')
  const backendWake = useBackendWake()
  const state = useAppState({ llmProvider: keys.llmProvider, llmApiKey: keys.llmApiKey })

  const showReady = state.phase === 'ready' || state.phase === 'generated'
  const showGenerated = state.phase === 'generated'
  const loading = state.phase === 'loading'
  const waking =
    loading && (backendWake.status === 'unknown' || backendWake.status === 'waking')

  const needKey = () => {
    state.showToast('Add an LLM API key in Settings')
    openSettings()
  }

  const f = state.results?.feasibility
  const feasWord = f
    ? f.total >= 75
      ? 'Financeable'
      : f.total >= 60
        ? 'Financeable — tight'
        : 'Stressed'
    : ''

  // Implied split from current assumptions (entry EBITDA cancels out)
  const split = state.assumptions
    ? (() => {
        const { entryMultiple, leverageMultiple, transactionFeePct } = state.assumptions!
        const debt = entryMultiple > 0 ? leverageMultiple / (entryMultiple * (1 + transactionFeePct)) : 0
        return { debt, equity: 1 - debt }
      })()
    : null

  const apiStatus =
    backendWake.status === 'awake'
      ? 'OK'
      : backendWake.status === 'waking' || backendWake.status === 'unknown'
        ? 'waking…'
        : 'unreachable'

  return (
    <div className="body-row">
      <aside className="rail">
        <div className="rail-group">
          <div className="rail-eyebrow">Workspace</div>
          <button
            type="button"
            className={`rail-item ${activeTab === 'report' ? 'active' : ''}`}
            onClick={() => setActiveTab('report')}
          >
            Model builder
          </button>
          <button
            type="button"
            className={`rail-item ${activeTab === 'comparison' ? 'active' : ''}`}
            onClick={() => setActiveTab('comparison')}
          >
            Comparison
            {state.savedModels.length > 0 && (
              <span className="rail-badge">{state.savedModels.length}</span>
            )}
          </button>
        </div>

        <div className="rail-group">
          <div className="rail-eyebrow">Model</div>
          <button
            type="button"
            className={`rail-item ${!showReady ? 'disabled' : ''}`}
            onClick={() => showReady && (setActiveTab('report'), scrollToId('lbo-snapshot'))}
          >
            Company snapshot
          </button>
          <button
            type="button"
            className={`rail-item ${!showReady ? 'disabled' : ''}`}
            onClick={() => showReady && (setActiveTab('report'), scrollToId('lbo-assumptions'))}
          >
            Assumptions
          </button>
          <button
            type="button"
            className={`rail-item ${!showGenerated ? 'disabled' : ''}`}
            onClick={() =>
              showGenerated && (setActiveTab('report'), scrollToId('lbo-sensitivity'))
            }
          >
            Sensitivity
          </button>
        </div>

        <div className="rail-group">
          <div className="rail-eyebrow">Output</div>
          <button
            type="button"
            className={`rail-item ${!showGenerated ? 'disabled' : ''}`}
            onClick={() => showGenerated && state.downloadExcel()}
          >
            Excel workbook
          </button>
          <button
            type="button"
            className={`rail-item ${!showGenerated ? 'disabled' : ''}`}
            onClick={() => {
              if (!showGenerated) return
              if (!hasLlmKey) return needKey()
              state.setShowReport(true)
              setActiveTab('report')
              scrollToId('lbo-results')
            }}
          >
            Narrative report
          </button>
        </div>

        <div className="rail-footer">
          <div className="rail-foot-line">API {API_HOST} · {apiStatus}</div>
          <div className="rail-foot-line">
            {state.snapshot
              ? `${state.snapshot.ticker} · SIC ${state.snapshot.sicCode}`
              : 'No subject loaded'}
          </div>
        </div>
      </aside>

      <div className="main-col">
        {activeTab === 'report' && (
          <>
            {state.phase === 'empty' && (
              <HowItWorks
                tickerForm={
                  <TickerInput
                    variant="hero"
                    value={state.tickerInput}
                    onChange={state.setTickerInput}
                    onAnalyze={() => state.analyze(state.tickerInput)}
                    loading={loading}
                    error={state.error}
                    serverStatus={backendWake.status}
                    serverReadyFlash={backendWake.showReadyFlash}
                  />
                }
                savedModels={state.savedModels}
              />
            )}

            {state.phase !== 'empty' && (
              <TickerInput
                variant="bar"
                value={state.tickerInput}
                onChange={state.setTickerInput}
                onAnalyze={() => state.analyze(state.tickerInput)}
                loading={loading}
                error={state.error}
                serverStatus={backendWake.status}
                serverReadyFlash={backendWake.showReadyFlash}
                companyName={state.snapshot?.companyName}
                companyMeta={
                  state.snapshot
                    ? `SIC ${state.snapshot.sicCode} · ${state.snapshot.sicDescription}`
                    : undefined
                }
              />
            )}

            {loading && (
              <>
                <ColdStartBanner waking={waking} />
                <div className="deck-row cols-3">
                  <SkeletonTile />
                  <SkeletonTile />
                  <SkeletonTile />
                </div>
                <SkeletonTile className="skeleton-wide" />
                <p className="step-trail">
                  Step 1 · resolve CIK · step 2 fetch filings · step 3 normalize facts · step 4
                  validate · step 5 build model
                </p>
              </>
            )}

            {showGenerated && state.results && (
              <div className="kpi-strip">
                <div className="kpi">
                  <div className="kpi-label">Sponsor IRR</div>
                  <div
                    className={`kpi-fig ${state.results.irr >= 0.15 ? '' : 'negative'}`}
                  >
                    {(state.results.irr * 100).toFixed(1)}%
                  </div>
                  <div className={`kpi-sub ${state.results.irr >= 0.2 ? 'pos' : state.results.irr >= 0.15 ? 'warn' : 'neg'}`}>
                    {state.results.irr >= 0.2
                      ? 'Above 20% hurdle'
                      : state.results.irr >= 0.15
                        ? 'Near 15–20% band'
                        : 'Below 15% hurdle'}
                  </div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">MOIC</div>
                  <div className="kpi-fig">{state.results.moic.toFixed(2)}×</div>
                  <div className="kpi-sub muted">
                    {state.assumptions ? `${Math.round(state.assumptions.exitYear)}-year hold` : ''}
                  </div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Entry / exit</div>
                  <div className="kpi-fig">
                    {state.assumptions
                      ? `${state.assumptions.entryMultiple.toFixed(1)} / ${state.assumptions.exitMultiple.toFixed(1)}`
                      : '—'}
                  </div>
                  {state.assumptions && (
                    <div
                      className={`kpi-sub ${
                        state.assumptions.exitMultiple < state.assumptions.entryMultiple
                          ? 'neg'
                          : 'muted'
                      }`}
                    >
                      {state.assumptions.exitMultiple < state.assumptions.entryMultiple
                        ? `${(state.assumptions.entryMultiple - state.assumptions.exitMultiple).toFixed(1)}× multiple compression`
                        : 'No multiple compression'}
                    </div>
                  )}
                </div>
                <div className="kpi">
                  <div className="kpi-label">Debt / equity</div>
                  <div className="kpi-fig">
                    {split ? `${Math.round(split.debt * 100)}/${Math.round(split.equity * 100)}` : '—'}
                  </div>
                  <div className="kpi-sub muted">Implied by entry leverage</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Feasibility</div>
                  <div className="kpi-fig">
                    {f?.total}
                    <span style={{ fontSize: 14, color: 'var(--text-faint)' }}>/100</span>
                  </div>
                  <div className={`kpi-sub ${f && f.total >= 75 ? 'pos' : f && f.total >= 60 ? 'warn' : 'neg'}`}>
                    {feasWord}
                  </div>
                </div>
              </div>
            )}

            {showReady && (
              <div className={`deck-row ${showGenerated ? 'cols-3' : 'cols-2'}`}>
                {state.snapshot && (
                  <div id="lbo-snapshot">
                    <CompanySnapshot
                      snapshot={state.snapshot}
                      userOverrides={state.userOverrides}
                      onUpdateOverride={state.updateOverride}
                    />
                  </div>
                )}
                {state.assumptions && (
                  <div id="lbo-assumptions">
                    <AssumptionsEditor
                      assumptions={state.assumptions}
                      meta={state.assumptionMeta}
                      onChange={state.updateAssumption}
                      onGenerate={state.generate}
                      generating={state.generating}
                    />
                  </div>
                )}
                {showGenerated && state.results && (
                  <div id="lbo-results">
                    <ResultsSummary
                      results={state.results}
                      onDownload={state.downloadExcel}
                      onReport={() => state.setShowReport((v) => !v)}
                      showReport={state.showReport}
                      hasLlmKey={hasLlmKey}
                      onNeedKey={needKey}
                    />
                  </div>
                )}
              </div>
            )}

            {showGenerated && state.sensitivity.length > 0 && (
              <div id="lbo-sensitivity">
                <SensitivityHeatmap cells={state.sensitivity} />
              </div>
            )}
          </>
        )}

        {activeTab === 'comparison' && (
          <div className="comparison-page">
            <ComparisonPanel
              savedModels={state.savedModels}
              hasLlmKey={hasLlmKey}
              llmProvider={keys.llmProvider}
              llmApiKey={keys.llmApiKey}
              onNeedKey={needKey}
            />
          </div>
        )}

        {state.toast && <div className="toast">{state.toast}</div>}
      </div>
    </div>
  )
}
