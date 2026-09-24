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

const OWN_LLM_PROMPT = `I exported this deal model from Deal Suite as an Excel workbook and want a narrative write-up without giving the tool my API key. Acting as a deal team associate, review the Assumptions tab and the Results tab I paste below and answer three questions: (1) is the deal financeable under these assumptions, (2) what is the single biggest driver of the return, (3) which one assumption would break the deal if it moved against me. Here are the Assumptions and Results tab values:

[paste the Assumptions tab here]

[paste the Results tab here]`

/** BYOK modal (frame 1i): ink title bar, session-scope disclosure,
    provider segmented control, Clear key / Cancel / Save for session. */
export function SettingsModal({ open, keys, onClose, onSave, onClear }: Props) {
  const [provider, setProvider] = useState<LlmProvider>(keys.llmProvider)
  const [apiKey, setApiKey] = useState(keys.llmApiKey)
  const [copied, setCopied] = useState(false)

  const copyPrompt = async () => {
    await navigator.clipboard.writeText(OWN_LLM_PROMPT)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 2000)
  }

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

          <div className="modal-disclosure" style={{ marginTop: 4 }}>
            <div className="eyebrow" style={{ marginBottom: 7 }}>
              No key? Write the narrative yourself
            </div>
            <p className="muted-note" style={{ marginTop: 0, marginBottom: 10 }}>
              Copy this prompt, paste the Assumptions and Results tabs from your exported
              workbook into it, and run it in any LLM chat you already have open.
            </p>
            <button type="button" className="secondary-btn" onClick={copyPrompt}>
              {copied ? 'Copied' : 'Copy prompt'}
            </button>
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
