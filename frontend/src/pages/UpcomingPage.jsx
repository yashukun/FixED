import { useCallback } from 'react'
import { api } from '../services/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { ErrorBanner, SpinnerState } from '../components/feedback'
import { useAsyncResource } from '../hooks/useAsyncResource'

export default function UpcomingPage() {
  const loadUpcoming = useCallback(() => api.getUpcomingEvents(), [])
  const { data, error } = useAsyncResource(loadUpcoming)

  if (error) {
    return <ErrorBanner message={error} />
  }
  if (!data) return <SpinnerState label="Loading upcoming schedule" />

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
