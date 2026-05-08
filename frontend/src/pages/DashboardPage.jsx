import { useCallback } from 'react'
import { api } from '../services/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { ErrorBanner, SpinnerState } from '../components/feedback'
import { useAsyncResource } from '../hooks/useAsyncResource'

export default function DashboardPage() {
  const loadOverview = useCallback(() => api.getDashboardOverview(), [])
  const { data: overview, error } = useAsyncResource(loadOverview)

  if (error) {
    return <ErrorBanner message={error} />
  }

  if (!overview) {
    return <SpinnerState label="Loading dashboard data" />
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-white">Student Dashboard</h2>
        <p className="mt-1 text-sm text-slate-400">Track your learning progress, assigned subjects, and upcoming activities.</p>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        {overview.metrics.map((metric) => (
          <Card key={metric.label}>
            <CardHeader>
              <CardDescription>{metric.label}</CardDescription>
              <CardTitle className="text-3xl">{metric.value}</CardTitle>
            </CardHeader>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Today&apos;s Focus</CardTitle>
          <CardDescription>Plan generated from dashboard overview feed</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {overview.todayFocus.map((item) => (
            <div key={item.title} className="flex items-center justify-between rounded-lg border border-slate-800 p-3">
              <div>
                <p className="font-medium text-slate-100">{item.title}</p>
                <p className="text-xs text-slate-400">{item.time}</p>
              </div>
              <Badge variant={item.type === 'viva' ? 'warning' : 'info'}>{item.type}</Badge>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
