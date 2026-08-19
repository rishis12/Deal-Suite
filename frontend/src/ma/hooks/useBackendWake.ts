import { useEffect, useState } from 'react'
import { API_BASE } from '../api'

/** How long the health ping can stay unresolved before we tell the user the server is waking. */
const WAKING_THRESHOLD_MS = 3500
/** How long the "Server is ready" confirmation stays visible after a slow wake. */
const READY_FLASH_MS = 2500

export type BackendWakeStatus = 'unknown' | 'waking' | 'awake' | 'unreachable'

// One ping per page load, shared across StrictMode remounts. Free-tier hosts
// spin the backend down when idle; this fire-and-forget request starts the
// cold boot as soon as the page loads, before the user hits Analyze.
let healthPing: Promise<boolean> | null = null
function pingHealth(): Promise<boolean> {
  if (!healthPing) {
    healthPing = fetch(`${API_BASE}/health`).then(
      (res) => res.ok,
      () => false,
    )
  }
  return healthPing
}

export function useBackendWake() {
  const [status, setStatus] = useState<BackendWakeStatus>('unknown')
  const [showReadyFlash, setShowReadyFlash] = useState(false)

  useEffect(() => {
    let cancelled = false
    let readyTimer: number | undefined
    let wakingShown = false

    const wakingTimer = window.setTimeout(() => {
      wakingShown = true
      setStatus('waking')
    }, WAKING_THRESHOLD_MS)

    pingHealth().then((ok) => {
      if (cancelled) return
      window.clearTimeout(wakingTimer)
      setStatus(ok ? 'awake' : 'unreachable')
      if (ok && wakingShown) {
        setShowReadyFlash(true)
        readyTimer = window.setTimeout(() => setShowReadyFlash(false), READY_FLASH_MS)
      }
    })

    return () => {
      cancelled = true
      window.clearTimeout(wakingTimer)
      window.clearTimeout(readyTimer)
    }
  }, [])

  return { status, awake: status === 'awake', showReadyFlash }
}
