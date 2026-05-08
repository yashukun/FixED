import { Button } from './ui/button'

// Reserved for upcoming chapter-aware reading mode.
export default function ChapterSidebar({ chapters, selectedChapterNumber, onSelectChapter, onClearChapter }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/70">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <span className="text-sm font-semibold uppercase tracking-wide text-slate-400">Chapters</span>
        <Button type="button" variant="ghost" className="px-2 py-1 text-xs" onClick={onClearChapter}>
          All
        </Button>
      </div>
      <div className="max-h-[320px] overflow-y-auto">
        {chapters.length === 0 ? (
          <div className="p-4 text-sm text-slate-500">No chapters found for this book yet.</div>
        ) : (
          chapters.map((chapter) => (
            <button
              key={chapter.number}
              type="button"
              className={`w-full border-b border-slate-800 px-4 py-3 text-left transition hover:bg-slate-800/70 ${
                selectedChapterNumber === chapter.number ? 'bg-blue-500/10' : ''
              }`}
              onClick={() => onSelectChapter?.(chapter)}
            >
              <div className="text-sm font-medium text-slate-100">
                Chapter {chapter.number}: {chapter.title}
              </div>
              <div className="text-xs text-slate-400">
                Pages {chapter.start_page}-{chapter.end_page}
              </div>
            </button>
          ))
        )}
      </div>
    </div>
  )
}
