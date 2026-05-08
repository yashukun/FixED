import { useCallback, useMemo, useState } from 'react'
import { CostContext } from './CostContextValue'

export function CostProvider({ children }) {
  const [sessionTotalUsd, setSessionTotalUsd] = useState(0)
  const [liveCostUsd, setLiveCostUsd] = useState(null)
  const [liveLabel, setLiveLabel] = useState(null)

  const startLive = useCallback((label) => {
    setLiveLabel(label || 'Request')
    setLiveCostUsd(0)
  }, [])

  const setLive = useCallback((usd) => {
    const safe = Number(usd)
    if (Number.isFinite(safe) && safe >= 0) {
      setLiveCostUsd(safe)
    }
  }, [])

  const commitLive = useCallback((explicitUsd = null) => {
    setSessionTotalUsd((prev) => {
      const source = explicitUsd != null ? Number(explicitUsd) : Number(liveCostUsd ?? 0)
      const safe = Number.isFinite(source) && source > 0 ? source : 0
      return prev + safe
    })
    setLiveLabel(null)
    setLiveCostUsd(null)
  }, [liveCostUsd])

  const clearLive = useCallback(() => {
    setLiveLabel(null)
    setLiveCostUsd(null)
  }, [])

  const addCost = useCallback((usd) => {
    const safe = Number(usd)
    if (!Number.isFinite(safe) || safe <= 0) return
    setSessionTotalUsd((prev) => prev + safe)
  }, [])

  const value = useMemo(
    () => ({
      sessionTotalUsd,
      liveCostUsd,
      liveLabel,
      startLive,
      setLive,
      commitLive,
      clearLive,
      addCost,
    }),
    [sessionTotalUsd, liveCostUsd, liveLabel, startLive, setLive, commitLive, clearLive, addCost],
  )

  return <CostContext.Provider value={value}>{children}</CostContext.Provider>
}
