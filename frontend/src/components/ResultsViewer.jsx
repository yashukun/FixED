import { Button } from './ui/button'

export default function ResultsViewer({ searchData, onSelectClarification, isStreaming = false }) {
  if (!searchData) {
    return (
      <div className="mt-10 text-center text-sm text-slate-500">
        No results found. Try a different query.
      </div>
    )
  }

  if (searchData.needs_clarification) {
    const options = searchData.clarification_options || []
    return (
      <div className="mt-8 rounded-xl border border-amber-500/40 bg-amber-500/10 p-5">
        <h3 className="mb-2 text-base font-semibold text-amber-200">Chapter Needed</h3>
        <p className="mb-4 text-sm text-amber-100">{searchData.answer}</p>
        <div className="flex flex-wrap gap-2">
          {options.map((option) => (
            <Button
              key={option.number}
              type="button"
              variant="outline"
              onClick={() => onSelectClarification?.(option.number)}
            >
              Chapter {option.number}: {option.title}
            </Button>
          ))}
        </div>
      </div>
    )
  }

  const hasResults = Array.isArray(searchData.results) && searchData.results.length > 0
  const confidenceValues = hasResults ? searchData.results.map((row) => Number(row.score) || 0) : []
  const topConfidence = confidenceValues.length ? Math.max(...confidenceValues) : null
  const avgConfidence = confidenceValues.length
    ? confidenceValues.reduce((sum, score) => sum + score, 0) / confidenceValues.length
    : null

  return (
    <div className="mt-8 flex w-full max-w-4xl flex-col gap-4">
      {/* AI Answer Section */}
      <div className="rounded-xl border border-blue-500/40 bg-slate-900/80 p-5">
        <h3 className="mb-3 flex items-center gap-2 text-lg font-semibold text-white">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
          </svg>
          AI Answer
        </h3>
        <div className="leading-7 text-slate-100">
          {searchData.answer}
          {isStreaming && <span className="ml-1 inline-block animate-pulse text-blue-300">|</span>}
        </div>
      </div>

      {hasResults && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4">
          <h4 className="mb-2 text-sm font-semibold text-emerald-200">Confidence</h4>
          <div className="flex flex-wrap gap-3 text-sm text-emerald-100">
            <span className="rounded-full bg-emerald-500/20 px-3 py-1">
              Top: {((topConfidence || 0) * 100).toFixed(1)}%
            </span>
            <span className="rounded-full bg-emerald-500/20 px-3 py-1">
              Avg: {((avgConfidence || 0) * 100).toFixed(1)}%
            </span>
            <span className="rounded-full bg-emerald-500/20 px-3 py-1">
              Sources: {searchData.results.length}
            </span>
          </div>
        </div>
      )}

      {hasResults ? (
        <>
          <h4 className="mt-2 text-sm font-medium text-slate-400">Sources:</h4>
          {searchData.results.map((result, index) => (
            <div
              key={result.chunk_id || index}
              className="rounded-xl border border-slate-800 bg-slate-900/65 p-4"
            >
              <div className="mb-2 flex items-center justify-between">
                <span className="rounded-full bg-blue-500/20 px-2 py-0.5 text-xs font-medium text-blue-300">Confidence: {(result.score * 100).toFixed(1)}%</span>
                <span className="text-xs text-slate-500">{result.filename}</span>
              </div>
              <p className="text-sm text-slate-200">{result.text_content}</p>
            </div>
          ))}
        </>
      ) : (
        <div className="rounded-xl border border-slate-800 bg-slate-900/65 p-4 text-sm text-slate-300">
          No source excerpts for this response yet. Ask a book-specific question to see supporting passages.
        </div>
      )}
    </div>
  )
}
