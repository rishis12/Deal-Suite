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

/** M&A Modeler product pane — header/settings live in the Deal Suite shell. */
export default function MaApp({ keys }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('deal')
  const backendWake = useBackendWake()

  const getLlm = useCallback(
    () => ({ llmProvider: keys.llmProvider, llmApiKey: keys.llmApiKey }),
    [keys],
  )
  const state = useDealState(getLlm)

  const analyzed = state.phase === 'ready' || state.phase === 'generated'

  return (
    <>
      {/* Real top-level tab navigation, always visible */}
      <nav className="tab-bar">
        <button
          type="button"
          className={`tab-btn ${activeTab === 'deal' ? 'active' : ''}`}
          onClick={() => setActiveTab('deal')}
        >
          Deal Builder
        </button>
        <button
          type="button"
          className={`tab-btn ${activeTab === 'comparison' ? 'active' : ''}`}
          onClick={() => setActiveTab('comparison')}
        >
          Comparison
          {state.savedModels.length > 0 && (
            <span className="tab-badge">{state.savedModels.length}</span>
          )}
        </button>
      </nav>

      {activeTab === 'deal' && (
        <div className="dashboard-grid">
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
          />

          {state.failedValidation && <ValidationPanel validation={state.failedValidation} />}

          {analyzed && state.analysis && (
            <>
              <ValidationPanel validation={state.analysis.validation} />
              <CompanySnapshots
                acquirer={state.analysis.acquirer}
                target={state.analysis.target}
                priceOverrides={state.priceOverrides}
                onPriceOverride={(role, value) =>
                  state.setPriceOverrides((prev) => ({ ...prev, [role]: value }))
                }
              />
              <AssumptionsEditor
                assumptions={state.assumptions}
                onChange={state.updateAssumption}
                onGenerate={state.generateModel}
                generating={state.generating}
                disabled={state.analysis.validation.status === 'fail'}
              />
              <MarketConcentration
                acquirer={state.analysis.acquirer}
                target={state.analysis.target}
                rows={state.marketShares}
                onRowsChange={state.setMarketShares}
              />
            </>
          )}

          {state.phase === 'generated' && state.results && (
            <ResultsPanel results={state.results} onDownload={state.downloadExcel} />
          )}
        </div>
      )}

      {activeTab === 'comparison' && (
        <ComparisonPanel
          savedModels={state.savedModels}
          llmProvider={keys.llmProvider}
          llmApiKey={keys.llmApiKey}
        />
      )}

      {state.toast && <div className="toast">{state.toast}</div>}
    </>
  )
}
