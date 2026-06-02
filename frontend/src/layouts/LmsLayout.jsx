import { NavLink, Outlet } from 'react-router-dom'
import { useCallback } from 'react'
import { cn } from '../lib/utils'
import { useCost } from '../context/useCost'
import { api } from '../services/api'
import { useAsyncResource } from '../hooks/useAsyncResource'
import { ErrorBanner, SpinnerState } from '../components/feedback'
import ThemeToggle from '../components/ThemeToggle'

const fallbackNav = [
  { label: 'Dashboard', to: '/' },
  { label: 'Search', to: '/learn/assistant' },
  { label: 'Upcoming', to: '/upcoming' },
  { label: 'Mock Interview / Viva', to: '/viva' },
]

export default function LmsLayout() {
  const loadNav = useCallback(() => api.getDashboardNav(), [])
  const { data: navData, error: navError } = useAsyncResource(loadNav)
  const { sessionTotalUsd, liveCostUsd, liveLabel } = useCost()
  const formatUsd = (amount) => `$${Number(amount || 0).toFixed(4)}`
  const isLive = typeof liveCostUsd === 'number'
  const navItems = Array.isArray(navData?.sections)
    ? [
        ...navData.sections.map((section) => ({
          label: section.name || 'Untitled',
          to: section.path || '/',
        })),
        ...fallbackNav.filter((item) => !navData.sections.some((section) => section.path === item.to)),
      ]
    : fallbackNav

  if (navError) {
    return <ErrorBanner message={navError} />
  }

  if (!navData) {
    return <SpinnerState label="Loading workspace navigation" />
  }

  return (
    <div className="min-h-screen bg-transparent text-slate-100">
      <div className="flex min-h-screen">
        <aside className="hidden w-72 border-r border-slate-800 bg-slate-950/90 p-4 md:block">
          <div className="mb-8 px-2">
            <h1 className="text-2xl font-bold text-slate-50">FixED LMS</h1>
            <p className="mt-1 text-sm text-slate-400">Student learning workspace</p>
          </div>

          <nav className="space-y-6">
            <div>
              <p className="mb-2 px-2 text-xs uppercase tracking-wide text-slate-500">Workspace</p>
              <ul className="space-y-1">
                {navItems.map((item) => (
                  <li key={item.to + item.label}>
                    <NavLink
                      to={item.to}
                      className={({ isActive }) =>
                        cn(
                          'block rounded-md px-3 py-2 text-sm transition',
                          isActive
                            ? 'bg-blue-500/20 text-blue-700 ring-1 ring-blue-500/40 dark:text-blue-100'
                            : 'text-slate-300 hover:bg-slate-800/80 hover:text-slate-50',
                        )
                      }
                    >
                      {item.label}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          </nav>
        </aside>

        <main className="flex-1">
          <header className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/60 px-6 py-4 backdrop-blur-sm">
            <div className="flex items-center justify-between">
              <p className="text-sm text-slate-300">Welcome, {navData.student?.name || 'Workspace User'}</p>
              <div className="flex items-center gap-3">
                <div className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-700 dark:text-emerald-200">
                  <span>Session: {formatUsd(sessionTotalUsd)}</span>
                  {isLive && (
                    <span>
                      {' '}
                      · <span className="mr-1 inline-block h-2 w-2 animate-pulse rounded-full bg-emerald-300" />
                      Now: {formatUsd(liveCostUsd)} ({liveLabel || 'Request'})
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-500">{navData.source === 'live' ? 'Live dashboard data' : 'Fallback data'}</p>
                <ThemeToggle />
              </div>
            </div>
          </header>
          <section className="p-6">
            <Outlet />
          </section>
        </main>
      </div>
    </div>
  )
}
