import { useCallback } from 'react'
import { api } from '../services/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { ErrorBanner, SpinnerState } from '../components/feedback'
import { useAsyncResource } from '../hooks/useAsyncResource'

export default function DashboardPage() {
  const loadOverview = useCallback(() => api.getDashboardOverview(), [])
  const loadAnalyticsSummary = useCallback(() => api.getDashboardAnalyticsSummary(), [])
  const loadAnalyticsTimeseries = useCallback(() => api.getDashboardAnalyticsTimeseries(), [])
  const loadAnalyticsBreakdown = useCallback(() => api.getDashboardAnalyticsBreakdown(), [])

  const { data: overview, error: overviewError } = useAsyncResource(loadOverview)
  const { data: summary, error: summaryError } = useAsyncResource(loadAnalyticsSummary)
  const { data: timeseries, error: timeseriesError } = useAsyncResource(loadAnalyticsTimeseries)
  const { data: breakdown, error: breakdownError } = useAsyncResource(loadAnalyticsBreakdown)

  const error = overviewError || summaryError || timeseriesError || breakdownError

  if (error) {
    return <ErrorBanner message={error} />
  }

  if (!overview || !summary || !timeseries || !breakdown) {
    return <SpinnerState label="Loading dashboard data" />
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-white">Dashboard</h2>
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

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader>
            <CardDescription>Total Cost</CardDescription>
            <CardTitle className="text-2xl">${Number(summary.total_cost_usd || 0).toFixed(4)}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Total Tokens</CardDescription>
            <CardTitle className="text-2xl">{summary.total_tokens || 0}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Prompt Tokens</CardDescription>
            <CardTitle className="text-2xl">{summary.total_prompt_tokens || 0}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Completion Tokens</CardDescription>
            <CardTitle className="text-2xl">{summary.total_completion_tokens || 0}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Usage Volume</CardTitle>
          <CardDescription>Global activity across active backend features</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg border border-slate-800 p-3">
            <p className="text-xs uppercase tracking-wide text-slate-400">Searches</p>
            <p className="text-xl font-semibold text-white">{summary.usage_volume.searches || 0}</p>
          </div>
          <div className="rounded-lg border border-slate-800 p-3">
            <p className="text-xs uppercase tracking-wide text-slate-400">Generated Papers</p>
            <p className="text-xl font-semibold text-white">{summary.usage_volume.generated_papers || 0}</p>
          </div>
          <div className="rounded-lg border border-slate-800 p-3">
            <p className="text-xs uppercase tracking-wide text-slate-400">Uploads</p>
            <p className="text-xl font-semibold text-white">{summary.usage_volume.uploads || 0}</p>
          </div>
          <div className="rounded-lg border border-slate-800 p-3">
            <p className="text-xs uppercase tracking-wide text-slate-400">Viva Sessions</p>
            <p className="text-xl font-semibold text-white">{summary.usage_volume.viva_sessions || 0}</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent Trend (14d)</CardTitle>
          <CardDescription>Daily request, token, and cost snapshots</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {timeseries.points.length === 0 ? (
            <p className="text-sm text-slate-400">No analytics events recorded yet.</p>
          ) : (
            timeseries.points.map((point) => (
              <div key={point.bucket} className="rounded-lg border border-slate-800 p-3 text-sm">
                <p className="font-medium text-white">{point.bucket}</p>
                <p className="text-slate-300">
                  Requests: {point.requests} • Tokens: {point.total_tokens} • Cost: ${Number(point.cost_usd || 0).toFixed(4)}
                </p>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>By Service</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {breakdown.by_service.length === 0 ? (
              <p className="text-sm text-slate-400">No service data yet.</p>
            ) : (
              breakdown.by_service.map((item) => (
                <div key={item.key} className="rounded-lg border border-slate-800 p-3 text-sm text-slate-200">
                  {item.key}: ${Number(item.cost_usd || 0).toFixed(4)} • {item.requests} req
                </div>
              ))
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>By Model</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {breakdown.by_model.length === 0 ? (
              <p className="text-sm text-slate-400">No model data yet.</p>
            ) : (
              breakdown.by_model.map((item) => (
                <div key={item.key} className="rounded-lg border border-slate-800 p-3 text-sm text-slate-200">
                  {item.key}: ${Number(item.cost_usd || 0).toFixed(4)} • {item.total_tokens} tokens
                </div>
              ))
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>By Usage Kind</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {breakdown.by_kind.length === 0 ? (
              <p className="text-sm text-slate-400">No usage-kind data yet.</p>
            ) : (
              breakdown.by_kind.map((item) => (
                <div key={item.key} className="rounded-lg border border-slate-800 p-3 text-sm text-slate-200">
                  {item.key}: ${Number(item.cost_usd || 0).toFixed(4)} • {item.requests} req
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Today&apos;s Focus</CardTitle>
          <CardDescription>Recent activity feed from live services</CardDescription>
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
