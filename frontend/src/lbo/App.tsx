import { useState } from 'react'
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

/** AIO LBO product pane — header/settings live in the Deal Suite shell. */
export default function LboApp({ keys, hasLlmKey, openSettings }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('report')
  const backendWake = useBackendWake()
  const state = useAppState({ llmProvider: keys.llmProvider, llmApiKey: keys.llmApiKey })

  const showReady = state.phase === 'ready' || state.phase === 'generated'
  const showGenerated = state.phase === 'generated'

  // Only show tabs once we have at least one generated model
  const showTabs = state.savedModels.length > 0

  const needKey = () => {
    state.showToast('Add an LLM API key in Settings')
    openSettings()
  }

  return (
    <>
      {showTabs && (
        <nav className="tab-bar">
          <button
            type="button"
            className={`tab-btn ${activeTab === 'report' ? 'active' : ''}`}
            onClick={() => setActiveTab('report')}
          >
            Report Generation
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
      )}

      {activeTab === 'report' && (
        <div className="dashboard-grid">
          <TickerInput
            value={state.tickerInput}
            onChange={state.setTickerInput}
            onAnalyze={() => state.analyze(state.tickerInput)}
            loading={state.phase === 'loading'}
            error={state.error}
            serverStatus={backendWake.status}
            serverReadyFlash={backendWake.showReadyFlash}
          />

          {state.phase === 'empty' && <HowItWorks />}

          {state.phase === 'loading' && (
            <>
              <SkeletonTile className="tile-snapshot" />
              <SkeletonTile className="skeleton-mid" />
            </>
          )}

          {showReady && state.snapshot && (
            <CompanySnapshot
              snapshot={state.snapshot}
              userOverrides={state.userOverrides}
              onUpdateOverride={state.updateOverride}
            />
          )}

          {showReady && state.assumptions && (
            <AssumptionsEditor
              assumptions={state.assumptions}
              meta={state.assumptionMeta}
              onChange={state.updateAssumption}
              onGenerate={state.generate}
              generating={state.generating}
            />
          )}

          {showGenerated && state.results && (
            <ResultsSummary
              results={state.results}
              onDownload={state.downloadExcel}
              onReport={() => state.setShowReport((v) => !v)}
              showReport={state.showReport}
              hasLlmKey={hasLlmKey}
              onNeedKey={needKey}
            />
          )}

          {showGenerated && state.sensitivity.length > 0 && (
            <SensitivityHeatmap cells={state.sensitivity} />
          )}
        </div>
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
    </>
  )
}
