import * as React from 'react'
import { checkHealth } from '@/lib/api-client'

const POLL_INTERVAL_MS = 15000

/** Polls /api/health so the header's mode indicator reflects reality even
 * if the backend is started or stopped mid-demo. */
export function useBackendMode(): boolean {
  const [live, setLive] = React.useState(false)

  React.useEffect(() => {
    let cancelled = false

    async function poll() {
      const status = await checkHealth()
      if (!cancelled) setLive(status.reachable && status.redisOk)
    }

    poll()
    const id = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  return live
}
