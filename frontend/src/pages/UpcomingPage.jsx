import { useEffect, useState } from 'react'
import { api } from '../services/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'

export default function UpcomingPage() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let mounted = true
    const load = async () => {
      try {
        const payload = await api.getUpcomingEvents()
        if (mounted) setData(payload)
      } catch (err) {
        if (mounted) setError(err.message)
      }
    }
    load()
    return () => {
      mounted = false
    }
  }, [])

  if (error) {
    return <p className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</p>
  }
  if (!data) return <div className="spinner" aria-label="Loading upcoming schedule" />

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-white">Upcoming</h2>
        <p className="text-sm text-slate-400">Scheduled tests and upcoming viva/mock interview modules.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Scheduled Tests</CardTitle>
          <CardDescription>Timeline from teacher scheduling feed</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {data.events.map((event) => (
            <div key={event.id} className="flex items-center justify-between rounded-lg border border-slate-800 p-3">
              <div>
                <p className="font-medium text-white">{event.title}</p>
                <p className="text-xs text-slate-400">{event.when} • {event.subject}</p>
              </div>
              <Badge variant={event.kind === 'viva' ? 'warning' : 'info'}>{event.kind}</Badge>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Coming Soon</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-slate-300">
          <p>• Guided AI mock interview with teacher rubric.</p>
          <p>• Viva simulation with follow-up scoring.</p>
          <p>• Auto-generated practice sets from assigned books.</p>
        </CardContent>
      </Card>
      <p className="text-xs text-slate-500">Data source: {data.source}</p>
    </div>
  )
}
