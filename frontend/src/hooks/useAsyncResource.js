import { useEffect, useState } from 'react'

export function useAsyncResource(loader) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let mounted = true

    const load = async () => {
      try {
        const payload = await loader()
        if (mounted) {
          setData(payload)
          setError('')
        }
      } catch (err) {
        if (mounted) {
          setError(err.message)
        }
      }
    }

    load()

    return () => {
      mounted = false
    }
  }, [loader])

  return { data, error, setData, setError }
}
