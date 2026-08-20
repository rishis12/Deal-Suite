import { useEffect, useState } from 'react'
import { Analytics } from '@vercel/analytics/react'
import LboApp from './lbo/App'
import MaApp from './ma/App'
import { SettingsModal } from './ma/components/SettingsModal'
import { useBackendWake } from './ma/hooks/useBackendWake'
import { useSessionKeys } from './useSessionKeys'

type Product = 'lbo' | 'ma'

// Products map to URL paths so links survive refresh and are shareable
// (/lbo and /ma; anything else falls back to the LBO Analyzer).
function productFromPath(pathname: string): Product {
  return pathname.startsWith('/ma') ? 'ma' : 'lbo'
}

export default function App() {
  const [product, setProduct] = useState<Product>(() =>
    productFromPath(window.location.pathname),
  )
  const [settingsOpen, setSettingsOpen] = useState(false)
  const { keys, save, clear, hasLlmKey } = useSessionKeys()
  const wake = useBackendWake()

  const switchProduct = (next: Product) => {
    if (next !== product) {
      window.history.pushState(null, '', `/${next}`)
      setProduct(next)
    }
  }

  useEffect(() => {
    const onPop = () => setProduct(productFromPath(window.location.pathname))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const waking = wake.status === 'waking'

  return (
    <div className="app">
      <header className="masthead">
        <div className="m-brand">
          <span className="m-diamond" aria-hidden />
          <span className="m-wordmark">Deal Suite</span>
          <span className="m-tag">LBO &amp; M&amp;A modeling from SEC filings</span>
        </div>

        <div className="m-center">
          {waking ? (
            <span className="m-wake">Waking service — cold start</span>
          ) : (
            <nav className="m-switch" aria-label="Product">
              <button
                type="button"
                className={`m-switch-btn ${product === 'lbo' ? 'active' : ''}`}
                onClick={() => switchProduct('lbo')}
              >
                LBO Analyzer
              </button>
              <button
                type="button"
                className={`m-switch-btn ${product === 'ma' ? 'active' : ''}`}
                onClick={() => switchProduct('ma')}
              >
                M&amp;A Modeler
              </button>
            </nav>
          )}
        </div>

        <div className="m-right">
          <button
            type="button"
            className={`m-keybtn ${hasLlmKey ? 'has-key' : ''}`}
            onClick={() => setSettingsOpen(true)}
          >
            {hasLlmKey ? 'API key added' : 'Add API key for AI analysis'}
          </button>
          <button type="button" className="m-link" onClick={() => setSettingsOpen(true)}>
            Settings
          </button>
        </div>
      </header>

      {/* Both products stay mounted so in-progress models survive switching;
          the inactive one is hidden, not unmounted. */}
      <div id="lbo-pane" style={{ display: product === 'lbo' ? 'contents' : 'none' }}>
        <LboApp
          keys={keys}
          hasLlmKey={hasLlmKey}
          openSettings={() => setSettingsOpen(true)}
        />
      </div>
      <div id="ma-pane" style={{ display: product === 'ma' ? 'contents' : 'none' }}>
        <MaApp keys={keys} />
      </div>

      <SettingsModal
        open={settingsOpen}
        keys={keys}
        onClose={() => setSettingsOpen(false)}
        onSave={save}
        onClear={clear}
      />
      <Analytics />
    </div>
  )
}
