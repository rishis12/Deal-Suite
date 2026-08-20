import { useEffect, useState } from 'react'
import type { LlmProvider, SessionKeys } from '../types'

interface Props {
  open: boolean
  keys: SessionKeys
  onClose: () => void
  onSave: (keys: SessionKeys) => void
  onClear: () => void
}

const PROVIDERS: { value: LlmProvider; label: string }[] = [
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'gemini', label: 'Google' },
]

/** BYOK modal (frame 1i): ink title bar, session-scope disclosure,
    provider segmented control, Clear key / Cancel / Save for session. */
export function SettingsModal({ open, keys, onClose, onSave, onClear }: Props) {
  const [provider, setProvider] = useState<LlmProvider>(keys.llmProvider)
  const [apiKey, setApiKey] = useState(keys.llmApiKey)

  useEffect(() => {
    if (open) {
      setProvider(keys.llmProvider)
      setApiKey(keys.llmApiKey)
    }
  }, [open, keys])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const hasStoredKey = Boolean(keys.llmApiKey.trim())

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-title-bar">
          <span>Add API key for AI analysis</span>
          <button type="button" className="esc" onClick={onClose}>
            ESC
          </button>
        </div>
        <div className="modal-body">
          <div className="modal-disclosure">
            Keys are held in this browser session only. They are sent with the requests they
            authorize and are never logged or persisted server-side. Closing the tab clears them.
          </div>

          <div className="form-stack">
            <div>
              <div className="eyebrow" style={{ marginBottom: 7 }}>
                Provider
              </div>
              <div className="seg" style={{ width: '100%' }}>
                {PROVIDERS.map((p) => (
                  <button
                    key={p.value}
                    type="button"
                    className={`seg-btn ${provider === p.value ? 'active' : ''}`}
                    onClick={() => setProvider(p.value)}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="eyebrow" style={{ marginBottom: 7 }}>
                API key
              </div>
              <div style={{ position: 'relative' }}>
                <input
                  className="input"
                  type="password"
                  value={apiKey}
                  placeholder="sk-…"
                  onChange={(e) => setApiKey(e.target.value)}
                  style={{ paddingRight: hasStoredKey ? 160 : undefined }}
                />
                {hasStoredKey && (
                  <span
                    className="positive"
                    style={{
                      position: 'absolute',
                      right: 12,
                      top: '50%',
                      transform: 'translateY(-50%)',
                      fontSize: 12,
                      fontWeight: 600,
                      pointerEvents: 'none',
                    }}
                  >
                    Added for this session
                  </span>
                )}
              </div>
              <p className="muted-note" style={{ marginTop: 6 }}>
                Used only for narrative reports and comparison commentary.
              </p>
            </div>
          </div>

          <div className="modal-actions">
            <button
              type="button"
              className="btn-danger-text"
              onClick={() => {
                setApiKey('')
                onClear()
              }}
            >
              Clear key
            </button>
            <span className="spacer" />
            <button type="button" className="secondary-btn" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              className="primary-btn"
              onClick={() => {
                onSave({ llmProvider: provider, llmApiKey: apiKey.trim() })
                onClose()
              }}
            >
              Save for session
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
