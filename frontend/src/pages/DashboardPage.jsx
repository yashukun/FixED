import { useCallback, useEffect, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { api } from '../services/api'
import { ErrorBanner, SpinnerState } from '../components/feedback'
import { useAsyncResource } from '../hooks/useAsyncResource'
import Icon from '../components/Icon'
import { Sparkline, TrendChart, Donut, FeatureBars } from '../components/DashboardCharts'

const CH = {
  indigo: 'var(--c-indigo)',
  cyan: 'var(--c-cyan)',
  green: 'var(--c-green)',
  amber: 'var(--c-amber)',
  rose: 'var(--c-rose)',
}
const PALETTE = [CH.indigo, CH.cyan, CH.green, CH.amber, CH.rose]

const KPI_STYLE = [
  { icon: 'layers', color: CH.indigo },
  { icon: 'book', color: CH.cyan },
  { icon: 'doc', color: CH.green },
  { icon: 'calendar', color: CH.amber },
]

const SERIES = {
  requests: { label: 'Requests', color: CH.indigo, get: (p) => Number(p.requests || 0), fmt: (n) => n.toLocaleString('en-US') },
  tokens: { label: 'Tokens', color: CH.green, get: (p) => Number(p.total_tokens || 0), fmt: (n) => n.toLocaleString('en-US') },
  cost: { label: 'Cost', color: CH.cyan, get: (p) => Number(p.cost_usd || 0), fmt: (n) => `$${Number(n).toFixed(4)}` },
}

const FEED_META = {
  viva: { icon: 'mic', color: CH.amber, chip: 'b-warn' },
  study: { icon: 'book', color: CH.cyan, chip: 'b-info' },
  paper: { icon: 'doc', color: CH.green, chip: 'b-good' },
  search: { icon: 'search', color: CH.indigo, chip: 'b-info' },
}
const feedMeta = (type) => FEED_META[String(type || '').toLowerCase()] || { icon: 'bolt', color: CH.indigo, chip: 'b-info' }

const jobBadge = (status) => {
  switch (String(status || '').toLowerCase()) {
    case 'completed':
    case 'ready':
      return { label: 'Ready', cls: 'b-good' }
    case 'processing':
      return { label: 'Processing', cls: 'b-warn' }
    case 'pending':
      return { label: 'Queued', cls: 'b-info' }
    case 'failed':
      return { label: 'Failed', cls: 'b-bad' }
    default:
      return { label: status || 'Unknown', cls: 'b-info' }
  }
}

const shortDate = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

const questionsOf = (p) => {
  const paper = p?.paper || {}
  if (Array.isArray(paper.questions)) return paper.questions.length
  if (Array.isArray(paper.sections)) {
    return paper.sections.reduce((a, s) => a + (Array.isArray(s.questions) ? s.questions.length : 0), 0)
  }
  const vals = Object.values(p?.distribution || {}).filter((v) => typeof v === 'number')
  if (vals.length) return vals.reduce((a, b) => a + b, 0)
  return '—'
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const [curSeries, setCurSeries] = useState('requests')
  const [curRange, setCurRange] = useState(14)

  // Gateway-backed analytics gate the page (these mirror the previous dashboard).
  const loadOverview = useCallback(() => api.getDashboardOverview(), [])
  const loadSummary = useCallback(() => api.getDashboardAnalyticsSummary(), [])
  const loadTimeseries = useCallback(() => api.getDashboardAnalyticsTimeseries(), [])
  const loadBreakdown = useCallback(() => api.getDashboardAnalyticsBreakdown(), [])
  const { data: overview, error: overviewError } = useAsyncResource(loadOverview)
  const { data: summary, error: summaryError } = useAsyncResource(loadSummary)
  const { data: timeseries, error: timeseriesError } = useAsyncResource(loadTimeseries)
  const { data: breakdown, error: breakdownError } = useAsyncResource(loadBreakdown)

  // Library / papers / vivas load defensively — they must never block the page.
  const [jobs, setJobs] = useState([])
  const [papers, setPapers] = useState([])
  const [vivas, setVivas] = useState([])
  useEffect(() => {
    let mounted = true
    const safe = (promise, setter) => promise.then((d) => { if (mounted) setter(Array.isArray(d) ? d : []) }).catch(() => {})
    safe(api.getAllJobs(), setJobs)
    safe(api.getQuestionPaperHistory({ limit: 6 }), setPapers)
    safe(api.getVivaHistory({ limit: 5 }), setVivas)
    return () => { mounted = false }
  }, [])

  const error = overviewError || summaryError || timeseriesError || breakdownError
  if (error) return <ErrorBanner message={error} />
  if (!overview || !summary || !timeseries || !breakdown) return <SpinnerState label="Loading dashboard data" />

  const metrics = Array.isArray(overview.metrics) ? overview.metrics : []
  const usage = summary.usage_volume || {}
  const points = Array.isArray(timeseries.points) ? timeseries.points : []
  const sparkData = points.map((p) => Number(p.requests || 0))

  // Trend windowing
  const meta = SERIES[curSeries]
  const win = points.slice(Math.max(0, points.length - curRange))
  const trendData = win.map(meta.get)
  const trendDates = win.map((p) => new Date(`${p.bucket}T00:00:00`))
  const total = trendData.reduce((a, b) => a + b, 0)
  const prevWin = points.slice(Math.max(0, points.length - curRange * 2), Math.max(0, points.length - curRange))
  const prev = prevWin.reduce((a, b) => a + meta.get(b), 0)
  const pct = prev ? ((total - prev) / prev) * 100 : 0
  const hasPrev = prevWin.length > 0 && prev > 0

  // Donut: requests by service
  const services = Array.isArray(breakdown.by_service) ? breakdown.by_service : []
  const donutSegments = services.map((s, i) => ({ nm: s.key, val: Number(s.requests || 0), color: PALETTE[i % PALETTE.length] }))
  const donutTotal = donutSegments.reduce((a, b) => a + b.val, 0)

  // Bars: feature usage
  const featureItems = [
    { nm: 'Search & Ask', val: Number(usage.searches || 0), color: CH.indigo },
    { nm: 'Question papers', val: Number(usage.generated_papers || 0), color: CH.green },
    { nm: 'Uploads', val: Number(usage.uploads || 0), color: CH.cyan },
    { nm: 'Viva sessions', val: Number(usage.viva_sessions || 0), color: CH.amber },
  ]

  const todayFocus = Array.isArray(overview.todayFocus) ? overview.todayFocus : []

  return (
    <>
      {/* toolbar */}
      <div className="toolbar">
        <div className="seg">
          {[7, 14, 30].map((r) => (
            <button key={r} className={curRange === r ? 'on' : ''} onClick={() => setCurRange(r)}>{r}d</button>
          ))}
        </div>
        <span className="muted-text">Last {curRange} days · {timeseries.source === 'live' ? 'live' : 'fallback'} data</span>
        <button className="btn" onClick={() => navigate('/learn/assistant')}>
          <Icon name="upload" /> Upload book
        </button>
        <button className="btn btn-primary" onClick={() => navigate('/learn/assistant')}>
          <Icon name="search" /> New search
        </button>
      </div>

      {/* KPI cards */}
      <div className="grid kpis">
        {metrics.map((m, i) => {
          const style = KPI_STYLE[i % KPI_STYLE.length]
          return (
            <div className="card kpi" key={m.label}>
              <div className="kpi-top">
                <div className="icobox" style={{ background: `color-mix(in oklch, ${style.color} 16%, transparent)`, color: style.color }}>
                  <Icon name={style.icon} />
                </div>
                <span className="lab">{m.label}</span>
              </div>
              <div>
                <div className="kpi-val">{m.value}</div>
                <div className="kpi-foot" style={{ marginTop: 8 }}>
                  <span className="ctx">across FixED</span>
                </div>
              </div>
              <Sparkline data={sparkData} color={style.color} />
            </div>
          )
        })}
      </div>

      {/* trend + feed */}
      <div className="grid cols-3" style={{ marginTop: 18 }}>
        <div className="card">
          <div className="chart-head">
            <div>
              <div className="card-h"><div><div className="t">Activity over time</div><div className="s">Requests, tokens and cost across FixED</div></div></div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginTop: 12 }}>
                <div className="kpi-val" style={{ fontSize: 26 }}>{meta.fmt(total)}</div>
                {hasPrev && (
                  <span className={`delta ${pct >= 0 ? 'up' : 'down'}`}>
                    <Icon name={pct >= 0 ? 'up' : 'down'} />{Math.abs(pct).toFixed(1)}%
                  </span>
                )}
                <span className="ctx" style={{ color: 'var(--faint)', fontSize: 12 }}>vs previous period</span>
              </div>
            </div>
            <div className="seg">
              {Object.keys(SERIES).map((key) => (
                <button key={key} className={curSeries === key ? 'on' : ''} onClick={() => setCurSeries(key)}>{SERIES[key].label}</button>
              ))}
            </div>
          </div>
          <TrendChart data={trendData} dates={trendDates} color={meta.color} label={meta.label} fmt={meta.fmt} />
        </div>

        <div className="card feed-card">
          <div className="card-h" style={{ marginBottom: 8 }}>
            <div><div className="t">Recent activity</div><div className="s">Live feed across your tools</div></div>
            <div className="icobox" style={{ marginLeft: 'auto', background: 'var(--accent-soft)', color: 'var(--accent-2)' }}><Icon name="bolt" /></div>
          </div>
          <div className="feed">
            {todayFocus.length === 0 ? (
              <div className="empty-row">No recent activity.</div>
            ) : todayFocus.map((f, i) => {
              const fm = feedMeta(f.type)
              return (
                <div className="feed-item" key={`${f.title}-${i}`}>
                  <div className="feed-dot" style={{ background: `color-mix(in oklch, ${fm.color} 16%, transparent)`, color: fm.color }}><Icon name={fm.icon} /></div>
                  <div className="feed-body">
                    <div className="feed-title">{f.title}</div>
                    <div className="feed-meta">{f.type || 'activity'}</div>
                  </div>
                  <div style={{ textAlign: 'right', display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-end' }}>
                    <span className={`chip ${fm.chip}`}>{f.type || 'activity'}</span>
                    <span className="feed-when">{f.time}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* breakdowns */}
      <div className="section-title">Breakdowns <span className="ln" /></div>
      <div className="grid cols-2">
        <div className="card">
          <div className="card-h"><div><div className="t">Requests by service</div><div className="s">Where backend activity is concentrated</div></div></div>
          <Donut segments={donutSegments} centerBig={donutTotal.toLocaleString('en-US')} centerSm="requests" />
        </div>
        <div className="card">
          <div className="card-h"><div><div className="t">Feature usage</div><div className="s">Volume across the platform tools</div></div></div>
          <FeatureBars items={featureItems} />
        </div>
      </div>

      {/* viva + library */}
      <div className="grid cols-3" style={{ marginTop: 18 }}>
        <div className="card">
          <div className="card-h">
            <div><div className="t">Viva — video test</div><div className="s">Open your camera and get examined live</div></div>
            <div className="icobox" style={{ marginLeft: 'auto', background: 'color-mix(in oklch, var(--c-cyan) 16%, transparent)', color: 'var(--c-cyan)' }}><Icon name="cam" /></div>
          </div>
          <div className="viva-grid">
            <div className="viva-cam">
              <span className="rec"><span className="rec-dot" />READY</span>
              <div className="cam-center">
                <Icon name="cam" />
                <div className="cam-label">Camera &amp; mic ready</div>
              </div>
              <button className="btn btn-primary cam-start" onClick={() => navigate('/viva')}>
                <Icon name="play" fill /> Start viva
              </button>
            </div>
            <div className="viva-list">
              {vivas.length === 0 ? (
                <div className="empty-row">No viva sessions yet.</div>
              ) : vivas.map((v, i) => {
                const m = v.metrics || {}
                const score = Math.round(Number(m.overall_score || 0))
                const max = Math.round(Number(m.max_score || 0))
                const ratio = max ? score / max : 0
                const color = ratio >= 0.75 ? 'var(--good)' : ratio >= 0.6 ? 'var(--warn)' : 'var(--bad)'
                const badge = jobBadge(v.session?.status)
                return (
                  <div className="vrow" key={v.session?.session_id || i}>
                    <div>
                      <div className="vrow-nm">{v.session?.topic || 'Viva session'}</div>
                      <div className="vrow-meta">{m.turn_count || 0} answers · {badge.label}</div>
                    </div>
                    <div className="vrow-right">
                      <span className="score" style={{ color }}>{score}<span style={{ color: 'var(--faint)', fontWeight: 400 }}>/{max || 100}</span></span>
                      <span className={`badge ${badge.cls}`}>{badge.label}</span>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-h">
            <div><div className="t">Your library</div><div className="s">Upload &amp; processing status</div></div>
            <NavLink className="link" to="/learn/books" style={{ marginLeft: 'auto' }}>All books →</NavLink>
          </div>
          <div className="lib-list" style={{ marginTop: 14 }}>
            {jobs.length === 0 ? (
              <div className="empty-row">No books uploaded yet.</div>
            ) : jobs.slice(0, 6).map((b, i) => {
              const color = PALETTE[i % PALETTE.length]
              const badge = jobBadge(b.status)
              const chapters = b.result_payload?.chapter_count
              return (
                <div className="lib-book" key={b.id}>
                  <div className="lib-spine" style={{ background: color }} />
                  <div className="lib-ico" style={{ color }}><Icon name="book" /></div>
                  <div className="lib-body">
                    <div className="lib-nm">{b.filename}</div>
                    <div className="lib-meta">{chapters ? `${chapters} chapters` : shortDate(b.created_at)}</div>
                  </div>
                  <span className={`badge ${badge.cls}`}>{badge.label}</span>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* recent question papers */}
      <div className="section-title">Recent question papers <span className="ln" /><NavLink className="link" to="/learn/assistant">View all →</NavLink></div>
      <div className="card" style={{ padding: '14px 6px 6px' }}>
        <table className="table">
          <thead><tr><th>Paper</th><th>Source</th><th>Marks</th><th>Questions</th><th>Created</th><th>Status</th></tr></thead>
          <tbody>
            {papers.length === 0 ? (
              <tr><td colSpan={6} className="empty-row">No question papers generated yet.</td></tr>
            ) : papers.map((p) => (
              <tr key={p.paper_id}>
                <td className="subj">{p.topic || 'Question paper'}</td>
                <td style={{ color: 'var(--muted)' }}>{p.mode || (p.file_id ? 'Single book' : 'All books')}</td>
                <td style={{ fontFamily: 'var(--mono)', color: 'var(--muted)' }}>{p.total_marks ?? '—'}</td>
                <td style={{ fontFamily: 'var(--mono)', color: 'var(--muted)' }}>{questionsOf(p)}</td>
                <td style={{ color: 'var(--muted)', fontFamily: 'var(--mono)', fontSize: 12.5 }}>{shortDate(p.created_at)}</td>
                <td><span className="badge b-good">Ready</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
