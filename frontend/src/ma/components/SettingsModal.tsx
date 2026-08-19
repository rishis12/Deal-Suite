import { useState } from 'react'
import type { LlmProvider, SessionKeys } from '../types'

interface Props {
  open: boolean
  keys: SessionKeys
  onClose: () => void
  onSave: (keys: SessionKeys) => void
  onClear: () => void
}

const PROVIDERS: { value: LlmProvider; label: string }[] = [
  { value: 'anthropic', label: 'Anthropic (Claude)' },
  { value: 'openai', label: 'OpenAI (GPT)' },
  { value: 'gemini', label: 'Google (Gemini)' },
]

export function SettingsModal({ open, keys, onClose, onSave, onClear }: Props) {
  const [provider, setProvider] = useState<LlmProvider>(keys.llmProvider)
  const [apiKey, setApiKey] = useState(keys.llmApiKey)

  if (!open) return null

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>LLM API Key (BYOK)</h2>
        <p className="muted-note">
          Used only to generate narrative reports and comparison commentary. Your key is stored in
          this browser session only (sessionStorage) — never saved to disk or any server — and is
          sent only with the requests you trigger.
        </p>
        <label className="field-label slot-field">
          Provider
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value as LlmProvider)}
          >
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field-label slot-field">
          API key
          <input
            type="password"
            value={apiKey}
            placeholder="sk-…"
            onChange={(e) => setApiKey(e.target.value)}
          />
        </label>
        <div className="modal-actions">
          <button
            type="button"
            className="primary-btn"
            onClick={() => {
              onSave({ llmProvider: provider, llmApiKey: apiKey.trim() })
              onClose()
            }}
          >
            Save for this session
          </button>
          <button
            type="button"
            className="secondary-btn"
            onClick={() => {
              setApiKey('')
              onClear()
            }}
          >
            Clear
          </button>
          <button type="button" className="secondary-btn" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
