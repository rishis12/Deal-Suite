import { useCallback, useState } from 'react'
import type { LlmProvider, SessionKeys } from './ma/types'

// One BYOK store for the whole suite — both products read the same session
// keys. sessionStorage ONLY, never localStorage: the key lives for this
// browser session and is gone when the tab closes.
const STORAGE_KEY = 'deal-suite-session-keys'

const DEFAULTS: SessionKeys = {
  llmProvider: 'anthropic',
  llmApiKey: '',
}

function read(): SessionKeys {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULTS }
    return { ...DEFAULTS, ...JSON.parse(raw) }
  } catch {
    return { ...DEFAULTS }
  }
}

export function useSessionKeys() {
  const [keys, setKeys] = useState<SessionKeys>(() => read())

  const save = useCallback((next: SessionKeys) => {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    setKeys(next)
  }, [])

  const clear = useCallback(() => {
    sessionStorage.removeItem(STORAGE_KEY)
    setKeys({ ...DEFAULTS })
  }, [])

  const hasLlmKey = Boolean(keys.llmApiKey.trim())

  return { keys, save, clear, hasLlmKey }
}

export type { LlmProvider }
