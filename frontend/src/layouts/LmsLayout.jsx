import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useCallback, useState } from 'react'
import { useCost } from '../context/useCost'
import { api } from '../services/api'
import { useAsyncResource } from '../hooks/useAsyncResource'
import { ErrorBanner, SpinnerState } from '../components/feedback'
import Icon from '../components/Icon'

// Static nav mapped to the real router routes, styled per the new design.
// Counts are overlaid from the gateway nav payload when available.
const NAV_GROUPS = [
  {
    items: [{ label: 'Dashboard', to: '/', icon: 'grid', end: true }],
  },
  {
    label: 'Features',
    items: [
      { label: 'Search & Ask', to: '/learn/assistant', icon: 'search' },
      { label: 'Subjects', to: '/learn/subjects', icon: 'layers' },
      { label: 'Viva', to: '/viva', icon: 'mic' },
    ],
  },
  {
    label: 'Library',
    items: [
      { label: 'My books', to: '/learn/books', icon: 'book' },
      { label: 'Upcoming', to: '/upcoming', icon: 'calendar' },
    ],
  },
]

const greeting = () => {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

const initials = (name) => {
  const parts = String(name || '').trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return 'Fx'
  return (parts[0][0] + (parts[1]?.[0] || '')).toUpperCase()
}

const formatUsd = (amount) => `$${Number(amount || 0).toFixed(4)}`

export default function LmsLayout() {
  const navigate = useNavigate()
  const [headerQuery, setHeaderQuery] = useState('')
  const loadNav = useCallback(() => api.getDashboardNav(), [])
  const { data: navData, error: navError } = useAsyncResource(loadNav)
  const { sessionTotalUsd, liveCostUsd, liveLabel } = useCost()
  const isLive = typeof liveCostUsd === 'number'

  if (navError) {
    return <ErrorBanner message={navError} />
  }
  if (!navData) {
    return <SpinnerState label="Loading workspace navigation" />
  }

  const countByPath = new Map(
    (Array.isArray(navData.sections) ? navData.sections : []).map((s) => [s.path, s.count]),
  )
  const studentName = navData.student?.name || 'Workspace User'
  const studentSub = navData.student?.grade || 'LMS Workspace'

  const onHeaderSearch = (e) => {
    e.preventDefault()
    navigate('/learn/assistant')
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <NavLink to="/" end className="brand">
          <div className="brand-mark">Fx</div>
          <div>
            <div className="brand-name">Fix<span>ED</span></div>
            <div className="brand-sub">LMS Workspace</div>
          </div>
        </NavLink>

        {NAV_GROUPS.map((group, gi) => (
          <nav className="nav-group" key={group.label || `g${gi}`}>
            {group.label && <div className="nav-label">{group.label}</div>}
            {group.items.map((item) => {
              const count = countByPath.get(item.to)
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
                >
                  <Icon name={item.icon} />
                  {item.label}
                  {count ? <span className="nav-badge">{count}</span> : null}
                </NavLink>
              )
            })}
          </nav>
        ))}

        <div className="side-foot">
          <div className="user">
            <div className="avatar">{initials(studentName)}</div>
            <div style={{ minWidth: 0 }}>
              <div className="user-name">{studentName}</div>
              <div className="user-mail">{studentSub}</div>
            </div>
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="header">
          <div className="h-title">
            <h1>{greeting()}, {studentName.split(' ')[0]}</h1>
            <p>Search, generate papers and take vivas — all from your books.</p>
          </div>

          <form className="search" onSubmit={onHeaderSearch}>
            <Icon name="search" />
            <input
              placeholder="Ask a question, or “generate a paper…”"
              value={headerQuery}
              onChange={(e) => setHeaderQuery(e.target.value)}
            />
          </form>

          <div className="spacer" />

          <div className="cost-meter">
            <div className="cost-col">
              <div className="lab">Session cost</div>
              <div className="val">{formatUsd(sessionTotalUsd)}</div>
            </div>
            <div className="cost-div" />
            <div className="cost-col">
              <div className="lab">{isLive ? (liveLabel || 'Now') : 'Now'}</div>
              <div className="val cost-now">
                {isLive ? <><span className="pulse-dot" />{formatUsd(liveCostUsd)}</> : '—'}
              </div>
            </div>
          </div>

          <div className="tag-live">
            <span className="pulse-dot" />
            {navData.source === 'live' ? 'Live data' : 'Fallback data'}
          </div>
        </header>

        <section className="content">
          <Outlet />
        </section>
      </div>
    </div>
  )
}
