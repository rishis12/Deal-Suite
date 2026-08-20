import { useCallback, useState } from 'react'
import { AssumptionsEditor } from './components/AssumptionsEditor'
import { CompanySnapshots } from './components/CompanySnapshots'
import { ComparisonPanel } from './components/ComparisonPanel'
import { MarketConcentration } from './components/MarketConcentration'
import { ResultsPanel } from './components/ResultsPanel'
import { TickerPairInput } from './components/TickerPairInput'
import { ValidationPanel } from './components/ValidationPanel'
import { useBackendWake } from './hooks/useBackendWake'
import { useDealState } from './hooks/useDealState'
import type { SessionKeys } from './types'

type Tab = 'deal' | 'comparison'

interface Props {
  keys: SessionKeys
}

const API_HOST = (import.meta.env.VITE_API_URL || 'http://localhost:8002').replace(
  /^https?:\/\//,
  '',
)

function scrollToId(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const fmtPctSigned = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`

/** M&A Modeler product pane — rail + main column in the terminal shell. */
export default function MaApp({ keys }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('deal')
  const backendWake = useBackendWake()

  const getLlm = useCallback(
    () => ({ llmProvider: keys.llmProvider, llmApiKey: keys.llmApiKey }),
    [keys],
  )
  const state = useDealState(getLlm)

  const analyzed = state.phase === 'ready' || state.phase === 'generated'
  const generated = state.phase === 'generated' && state.results

  const validation = state.analysis?.validation ?? state.failedValidation
  const issueCount = validation
    ? [validation.acquirer, validation.target].reduce(
        (n, v) =>
          n +
          v.disqualifyingReasons.length +
          v.missingHard.length +
          v.missingSoft.length +
          v.warnings.length +
          v.substituteWarnings.length,
        0,
      )
    : 0

  const ad = state.results?.accretionDilutionByYear ?? []
  const y1 = ad[0] ?? null
  const hhi = state.results?.hhi

  const apiStatus =
    backendWake.status === 'awake'
      ? 'OK'
      : backendWake.status === 'waking' || backendWake.status === 'unknown'
        ? 'waking…'
        : 'unreachable'

  const pctCash = state.assumptions.pct_cash ?? 0
  const pctDebt = state.assumptions.pct_debt ?? 0
  const pctStock = Math.max(0, 1 - pctCash - pctDebt)

  return (
    <div className="body-row">
      <aside className="rail">
        <div className="rail-group">
          <div className="rail-eyebrow">Workspace</div>
          <button
            type="button"
            className={`rail-item ${activeTab === 'deal' ? 'active' : ''}`}
            onClick={() => setActiveTab('deal')}
          >
            Deal builder
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
          <div className="rail-eyebrow">Deal</div>
          <button
            type="button"
            className={`rail-item ${!validation ? 'disabled' : ''}`}
            onClick={() => validation && (setActiveTab('deal'), scrollToId('ma-validation'))}
          >
            Data validation
            {validation && issueCount > 0 && (
              <span className={`rail-badge ${validation.status === 'fail' ? 'alert' : ''}`}>
                {issueCount}
              </span>
            )}
          </button>
          <button
            type="button"
            className={`rail-item ${!analyzed ? 'disabled' : ''}`}
            onClick={() => analyzed && (setActiveTab('deal'), scrollToId('ma-company-data'))}
          >
            Company data
          </button>
          <button
            type="button"
            className={`rail-item ${!analyzed ? 'disabled' : ''}`}
            onClick={() => analyzed && (setActiveTab('deal'), scrollToId('ma-assumptions'))}
          >
            Deal assumptions
          </button>
          <button
            type="button"
            className={`rail-item ${!analyzed ? 'disabled' : ''}`}
            onClick={() => analyzed && (setActiveTab('deal'), scrollToId('ma-concentration'))}
          >
            Market concentration
          </button>
          <button
            type="button"
            className={`rail-item ${!generated ? 'disabled' : ''}`}
            onClick={() => generated && (setActiveTab('deal'), scrollToId('ma-results'))}
          >
            Results
          </button>
        </div>

        <div className="rail-group">
          <div className="rail-eyebrow">Output</div>
          <button
            type="button"
            className={`rail-item ${!generated ? 'disabled' : ''}`}
            onClick={() => generated && state.downloadExcel()}
          >
            Excel workbook
          </button>
          <button
            type="button"
            className={`rail-item ${!generated || !state.results?.report ? 'disabled' : ''}`}
            onClick={() =>
              generated && state.results?.report && (setActiveTab('deal'), scrollToId('ma-report'))
            }
          >
            Narrative report
          </button>
        </div>

        <div className="rail-footer">
          <div className="rail-foot-line">API {API_HOST} · {apiStatus}</div>
          <div className="rail-foot-line">
            {state.analysis
              ? `${state.analysis.acquirer.ticker} acquires ${state.analysis.target.ticker}`
              : 'No deal loaded'}
          </div>
        </div>
      </aside>

      <div className="main-col">
        {activeTab === 'deal' && (
          <>
            <TickerPairInput
              acquirer={state.acquirerTicker}
              target={state.targetTicker}
              onAcquirerChange={state.setAcquirerTicker}
              onTargetChange={state.setTargetTicker}
              onAnalyze={state.analyze}
              loading={state.phase === 'loading'}
              error={state.error}
              serverStatus={backendWake.status}
              serverReadyFlash={backendWake.showReadyFlash}
              acquirerInfo={state.analysis?.acquirer ?? null}
              targetInfo={state.analysis?.target ?? null}
            />

            {state.failedValidation && (
              <div id="ma-validation">
                <ValidationPanel validation={state.failedValidation} />
              </div>
            )}

            {generated && state.results && (
              <div className="kpi-strip">
                <div className="kpi">
                  <div className="kpi-label">Yr 1 EPS impact</div>
                  <div className={`kpi-fig ${(y1 ?? 0) >= 0 ? 'positive' : 'negative'}`}>
                    {fmtPctSigned(y1)}
                  </div>
                  <div className={`kpi-sub ${(y1 ?? 0) >= 0 ? 'pos' : 'neg'}`}>
                    {(y1 ?? 0) >= 0 ? '▲ Accretive' : '▼ Dilutive'}
                  </div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Year {ad.length} EPS impact</div>
                  <div
                    className={`kpi-fig ${(ad[ad.length - 1] ?? 0) >= 0 ? 'positive' : 'negative'}`}
                  >
                    {fmtPctSigned(ad[ad.length - 1])}
                  </div>
                  <div className="kpi-sub muted">End of analysis window</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Offer premium</div>
                  <div className="kpi-fig">
                    {((state.assumptions.offer_premium ?? 0) * 100).toFixed(1)}%
                  </div>
                  <div className="kpi-sub muted">To current price</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Consideration</div>
                  <div className="kpi-fig">
                    {Math.round(pctCash * 100)}/{Math.round(pctDebt * 100)}/
                    {Math.round(pctStock * 100)}
                  </div>
                  <div className="kpi-sub muted">Cash / debt / stock</div>
                </div>
                <div className="kpi">
                  <div className="kpi-label">Post-deal HHI</div>
                  <div className="kpi-fig">
                    {hhi?.assessed && hhi.postMergerHHI !== null
                      ? Math.round(hhi.postMergerHHI).toLocaleString()
                      : '—'}
                  </div>
                  <div className={`kpi-sub ${hhi?.assessed ? 'warn' : 'muted'}`}>
                    {hhi?.assessed && hhi.deltaHHI !== null
                      ? `+${Math.round(hhi.deltaHHI)} · ${hhi.postMergerClass ?? ''}`
                      : 'Not assessed'}
                  </div>
                </div>
              </div>
            )}

            {analyzed && state.analysis && (
              <>
                <div id="ma-validation-live">
                  <ValidationPanel validation={state.analysis.validation} />
                </div>
                <div id="ma-company-data">
                  <CompanySnapshots
                    acquirer={state.analysis.acquirer}
                    target={state.analysis.target}
                    priceOverrides={state.priceOverrides}
                    onPriceOverride={(role, value) =>
                      state.setPriceOverrides((prev) => ({ ...prev, [role]: value }))
                    }
                  />
                </div>
                <div id="ma-assumptions">
                  <AssumptionsEditor
                    assumptions={state.assumptions}
                    onChange={state.updateAssumption}
                    onGenerate={state.generateModel}
                    generating={state.generating}
                    disabled={state.analysis.validation.status === 'fail'}
                  />
                </div>
                <div id="ma-concentration">
                  <MarketConcentration
                    acquirer={state.analysis.acquirer}
                    target={state.analysis.target}
                    rows={state.marketShares}
                    onRowsChange={state.setMarketShares}
                  />
                </div>
              </>
            )}

            {generated && state.results && (
              <div id="ma-results">
                <ResultsPanel results={state.results} onDownload={state.downloadExcel} />
              </div>
            )}
          </>
        )}

        {activeTab === 'comparison' && (
          <ComparisonPanel
            savedModels={state.savedModels}
            llmProvider={keys.llmProvider}
            llmApiKey={keys.llmApiKey}
          />
        )}

        {state.toast && <div className="toast">{state.toast}</div>}
      </div>
    </div>
  )
}
