import { NavLink, Outlet } from 'react-router-dom'
import { useMemo, useState } from 'react'
import { cn } from '../lib/utils'
import { useCost } from '../context/useCost'

const navSections = [
  {
    title: 'Main',
    items: [{ label: 'Dashboard', to: '/' }],
  },
  {
    title: 'Learn',
    items: [
      { label: 'Books', to: '/learn/books' },
      { label: 'Subjects', to: '/learn/subjects' },
      { label: 'Ask From Books', to: '/learn/assistant' },
    ],
  },
  {
    title: 'Upcoming',
    items: [
      { label: 'Mock Interview / Viva', to: '/upcoming' },
      { label: 'Scheduled Tests', to: '/upcoming' },
    ],
  },
]

function RoleToggle() {
  const [role, setRole] = useState('student')
  const roleText = useMemo(() => (role === 'student' ? 'Student View' : 'Teacher View'), [role])

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/70 p-3">
      <p className="mb-2 text-xs uppercase tracking-wide text-slate-400">Temporary Role</p>
      <button
        type="button"
        onClick={() => setRole((prev) => (prev === 'student' ? 'teacher' : 'student'))}
        className="w-full rounded-md bg-slate-800 px-3 py-2 text-sm text-slate-200 transition hover:bg-slate-700"
      >
        {roleText}
      </button>
    </div>
  )
}

export default function LmsLayout() {
  const { sessionTotalUsd, liveCostUsd, liveLabel } = useCost()
  const formatUsd = (amount) => `$${Number(amount || 0).toFixed(4)}`
  const isLive = typeof liveCostUsd === 'number'

  return (
    <div className="min-h-screen bg-transparent text-slate-100">
      <div className="flex min-h-screen">
        <aside className="hidden w-72 border-r border-slate-800 bg-slate-950/90 p-4 md:block">
          <div className="mb-8 px-2">
            <h1 className="text-2xl font-bold text-white">FixED LMS</h1>
            <p className="mt-1 text-sm text-slate-400">Student learning workspace</p>
          </div>

          <nav className="space-y-6">
            {navSections.map((section) => (
              <div key={section.title}>
                <p className="mb-2 px-2 text-xs uppercase tracking-wide text-slate-500">{section.title}</p>
                <ul className="space-y-1">
                  {section.items.map((item) => (
                    <li key={item.to + item.label}>
                      <NavLink
                        to={item.to}
                        className={({ isActive }) =>
                          cn(
                            'block rounded-md px-3 py-2 text-sm transition',
                            isActive
                              ? 'bg-blue-500/20 text-blue-100 ring-1 ring-blue-500/40'
                              : 'text-slate-300 hover:bg-slate-800/80 hover:text-white',
                          )
                        }
                      >
                        {item.label}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>

          <div className="mt-8">
            <RoleToggle />
          </div>
        </aside>

        <main className="flex-1">
          <header className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/60 px-6 py-4 backdrop-blur-sm">
            <div className="flex items-center justify-between">
              <p className="text-sm text-slate-300">Welcome back, Student</p>
              <div className="flex items-center gap-3">
                <div className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-200">
                  <span>Session: {formatUsd(sessionTotalUsd)}</span>
                  {isLive && (
                    <span>
                      {' '}
                      · <span className="mr-1 inline-block h-2 w-2 animate-pulse rounded-full bg-emerald-300" />
                      Now: {formatUsd(liveCostUsd)} ({liveLabel || 'Request'})
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-500">Auth is mocked for UI preview</p>
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
