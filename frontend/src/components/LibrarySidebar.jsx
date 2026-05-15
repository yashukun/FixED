import { normalizeStatus } from '../lib/status'

const statusColors = {
  completed: 'bg-emerald-500/20 text-emerald-300',
  ready: 'bg-emerald-500/20 text-emerald-300',
  processing: 'bg-blue-500/20 text-blue-300',
  pending: 'bg-amber-500/20 text-amber-300',
  failed: 'bg-rose-500/20 text-rose-300',
}

export default function LibrarySidebar({
  jobs,
  activeJobId,
  onSelectJob,
  onSelectAllBooks,
  onNewUpload,
}) {
  const completedCount = jobs.filter((job) => normalizeStatus(job.status) === 'completed').length

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/70">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <span className="text-sm font-semibold uppercase tracking-wide text-slate-400">My Library</span>
        <button className="rounded-md bg-blue-500 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-blue-600" onClick={onNewUpload}>
          + Upload
        </button>
      </div>
      <div className="max-h-[620px] overflow-y-auto">
        {completedCount > 0 && (
          <div
            className={`cursor-pointer border-b border-slate-800 px-4 py-3 transition hover:bg-slate-800/80 ${
              !activeJobId ? 'bg-blue-500/10' : ''
            }`}
            onClick={() => onSelectAllBooks?.()}
          >
            <div className="mb-1 truncate text-sm font-medium text-slate-100">
              All Books
            </div>
            <div className="text-xs text-slate-400">
              Search across {completedCount} indexed {completedCount === 1 ? 'book' : 'books'}
            </div>
          </div>
        )}
        {jobs.length === 0 ? (
          <div className="p-6 text-center text-sm text-slate-500">
            No books uploaded yet.
          </div>
        ) : (
          jobs.map((job) => {
            const status = normalizeStatus(job.status)
            return (
              <div
                key={job.id}
                className={`cursor-pointer border-b border-slate-800 px-4 py-3 transition hover:bg-slate-800/80 ${
                  activeJobId === job.id ? 'bg-blue-500/10' : ''
                }`}
                onClick={() => onSelectJob(job)}
              >
                <div className="mb-1 truncate text-sm font-medium text-slate-100" title={job.filename}>
                  {job.filename}
                </div>
                <div className="flex items-center justify-between text-xs text-slate-400">
                  <span>{new Date(job.created_at).toLocaleDateString()}</span>
                  <span className={`rounded-full px-2 py-0.5 font-medium ${statusColors[status] || statusColors.pending}`}>
                    {status}
                  </span>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
