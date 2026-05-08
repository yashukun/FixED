import { useContext } from 'react'
import { CostContext } from './CostContextValue'

export function useCost() {
  const context = useContext(CostContext)
  if (!context) {
    throw new Error('useCost must be used within a CostProvider')
  }
  return context
}

