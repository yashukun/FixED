import { useCallback, useEffect, useRef, useState } from 'react'
import BookUploader from '../../components/BookUploader'
import ProcessingIndicator from '../../components/ProcessingIndicator'
import SearchInterface from '../../components/SearchInterface'
import ResultsViewer from '../../components/ResultsViewer'
import LibrarySidebar from '../../components/LibrarySidebar'
import { api } from '../../services/api'
import { Card } from '../../components/ui/card'
import { normalizeStatus } from '../../lib/status'
import { ErrorBanner } from '../../components/feedback'
import { useCost } from '../../context/useCost'

const createChatSessionId = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export default function DocumentAssistant() {
  const TYPING_INTERVAL_MS = 30
  const [jobs, setJobs] = useState([])
  const [activeJob, setActiveJob] = useState(null)
  const [lastQuery, setLastQuery] = useState('')
  const [forceUploadMode, setForceUploadMode] = useState(false)
  const [appState, setAppState] = useState('IDLE')
  const [searchResults, setSearchResults] = useState(null)
  const [searchHistory, setSearchHistory] = useState([])
  const [chatSessionId, setChatSessionId] = useState(() => createChatSessionId())
  const [errorMsg, setErrorMsg] = useState('')
  const searchAbortRef = useRef(null)
  const typingQueueRef = useRef('')
  const typingTimerRef = useRef(null)
  const typingJobRef = useRef(0)
  const tokenStreamStartedRef = useRef(false)
  const doneStateRef = useRef(null)
  const { startLive, setLive, commitLive, clearLive, addCost } = useCost()
  const hasCompletedJobs = jobs.some((job) => normalizeStatus(job.status) === 'completed')

  const clearTypingState = useCallback(() => {
    typingJobRef.current += 1
    typingQueueRef.current = ''
    tokenStreamStartedRef.current = false
    doneStateRef.current = null
    if (typingTimerRef.current) {
      window.clearTimeout(typingTimerRef.current)
      typingTimerRef.current = null
    }
  }, [])

  const startTypingPump = useCallback(() => {
    if (typingTimerRef.current) return
    const runId = typingJobRef.current

    const tick = () => {
      if (typingJobRef.current !== runId) return
      const queue = typingQueueRef.current
      if (queue.length > 0) {
        if (typingTimerRef.current) {
          window.clearTimeout(typingTimerRef.current)
        }
        const step = queue.slice(0, 2)
        typingQueueRef.current = queue.slice(2)
        setSearchResults((prev) => ({
          ...(prev || {}),
          answer: `${prev?.answer || ''}${step}`,
          results: prev?.results || [],
          is_streaming: true,
        }))
        typingTimerRef.current = window.setTimeout(tick, TYPING_INTERVAL_MS)
      } else {
        const donePayload = doneStateRef.current
        if (donePayload) {
          if (typingTimerRef.current) {
            window.clearTimeout(typingTimerRef.current)
          }
          doneStateRef.current = null
          const restDone = { ...donePayload }
          delete restDone.answer
          setSearchResults((prev) => ({
            ...(prev || {}),
            ...restDone,
            answer: prev?.answer || '',
            is_streaming: false,
          }))
          typingTimerRef.current = null
        } else {
          typingTimerRef.current = window.setTimeout(tick, TYPING_INTERVAL_MS)
        }
      }
    }

    typingTimerRef.current = window.setTimeout(tick, TYPING_INTERVAL_MS)
  }, [TYPING_INTERVAL_MS])

  const fetchSearchHistory = useCallback(async (fileId) => {
    try {
      const rows = await api.getSearchHistory({
        fileId,
        limit: 20,
      })
      setSearchHistory(Array.isArray(rows) ? rows : [])
    } catch {
      // History should not block main assistant flow
    }
  }, [])

  const fetchJobs = useCallback(async () => {
    try {
      const data = await api.getAllJobs()
      setJobs(data)

      if (!activeJob && data.length > 0 && !forceUploadMode) {
        const hasReadyBooks = data.some((job) => normalizeStatus(job.status) === 'completed')
        if (hasReadyBooks) {
          setAppState('READY')
          fetchSearchHistory()
        }
      }
    } catch (err) {
      setErrorMsg(err.message)
    }
  }, [activeJob, forceUploadMode, fetchSearchHistory])

  useEffect(() => {
    const timerId = window.setTimeout(() => {
      fetchJobs()
    }, 0)

    return () => {
      window.clearTimeout(timerId)
    }
  }, [fetchJobs])

  const handleUploadStart = () => {
    setErrorMsg('')
    setForceUploadMode(false)
    setAppState('UPLOADING')
    setSearchResults(null)
    setLastQuery('')
    setChatSessionId(createChatSessionId())
  }

  const handleUploadSuccess = (jobId) => {
    setForceUploadMode(false)
    setAppState('PROCESSING')
    setActiveJob({ id: jobId })
  }

  const handleProcessingComplete = (job) => {
    setErrorMsg('')
    setForceUploadMode(false)
    setAppState('READY')
    setActiveJob(job)
    if (job?.cost_usd_total) {
      addCost(job.cost_usd_total)
    }
    fetchJobs()
    fetchSearchHistory(job?.id)
  }

  const handleLibrarySelect = (job) => {
    setForceUploadMode(false)
    setActiveJob(job)
    setErrorMsg('')
    setSearchResults(null)
    setLastQuery('')
    setChatSessionId(createChatSessionId())
    const status = normalizeStatus(job.status)

    if (status === 'completed') {
      setAppState('READY')
      fetchSearchHistory(job.id)
    } else if (status === 'pending' || status === 'processing') {
      setAppState('PROCESSING')
    } else {
      setAppState('IDLE')
      setErrorMsg('This book failed to process correctly.')
    }
  }

  const resetToUpload = () => {
    setForceUploadMode(true)
    setAppState('IDLE')
    setActiveJob(null)
    setSearchResults(null)
    setErrorMsg('')
    setLastQuery('')
    setSearchHistory([])
    setChatSessionId(createChatSessionId())
  }

  const handleSelectAllBooks = () => {
    setForceUploadMode(false)
    setActiveJob(null)
    setErrorMsg('')
    setSearchResults(null)
    setLastQuery('')
    setChatSessionId(createChatSessionId())
    if (hasCompletedJobs) {
      setAppState('READY')
      fetchSearchHistory()
    }
  }

  const searchInBook = async (query, overrides = {}) => {
    if (searchAbortRef.current) {
      searchAbortRef.current.abort()
    }
    clearTypingState()
    const controller = new AbortController()
    searchAbortRef.current = controller
    setErrorMsg('')
    setLastQuery(query)
    startLive('Search')
    setSearchResults({
      answer: '',
      results: [],
      response_kind: 'answer',
      needs_clarification: false,
      clarification_options: null,
      is_streaming: true,
    })
    try {
      await api.searchBookStream(query, activeJob?.id ?? null, {
        activePage: overrides.activePage ?? null,
        chapterNumber: overrides.chapterNumber ?? null,
        chatSessionId,
        signal: controller.signal,
      }, {
        onRetrieval: (evt) => {
          setSearchResults((prev) => ({
            ...(prev || {}),
            answer: prev?.answer || '',
            results: Array.isArray(evt?.results) ? evt.results : [],
            is_streaming: true,
          }))
        },
        onToken: (delta) => {
          if (!delta) return
          tokenStreamStartedRef.current = true
          typingQueueRef.current += delta
          startTypingPump()
        },
        onDone: (evt) => {
          const finalAnswer = String(evt?.answer || '')
          const donePayload = evt || {}
          const restDone = { ...donePayload }
          delete restDone.answer
          setSearchResults((prev) => ({
            ...(prev || {}),
            ...restDone,
            answer: prev?.answer || '',
            is_streaming: true,
          }))

          // Fallback: if token stream didn't arrive, type from final answer payload.
          if (!tokenStreamStartedRef.current && finalAnswer) {
            typingQueueRef.current += finalAnswer
          }
          doneStateRef.current = donePayload
          startTypingPump()
          const explicitUsd = evt?.cost?.usd
          if (typeof explicitUsd === 'number') {
            commitLive(explicitUsd)
          } else {
            commitLive()
          }
          fetchSearchHistory(activeJob?.id ?? null)
        },
        onStatus: (evt) => {
          if (!evt?.message) return
          setSearchResults((prev) => ({
            ...(prev || {}),
            answer: String(evt.message),
            results: prev?.results || [],
            is_streaming: true,
          }))
        },
        onCost: (evt) => {
          if (typeof evt?.usd === 'number') {
            setLive(evt.usd)
          }
        },
      })
    } catch (err) {
      if (err.name !== 'AbortError') {
        setErrorMsg(err.message)
      }
      clearLive()
    } finally {
      if (searchAbortRef.current === controller) {
        searchAbortRef.current = null
      }
    }
  }

  useEffect(() => () => {
    searchAbortRef.current?.abort()
    clearTypingState()
    clearLive()
  }, [clearTypingState, clearLive])

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <LibrarySidebar
        jobs={jobs}
        activeJobId={activeJob?.id}
        onSelectJob={handleLibrarySelect}
        onSelectAllBooks={handleSelectAllBooks}
        onNewUpload={resetToUpload}
      />
      <Card className="min-h-[560px]">
        {errorMsg && (
          <div className="mb-4">
            <ErrorBanner message={errorMsg} />
          </div>
        )}

        {appState === 'IDLE' && (
          <BookUploader
            onUploadStart={handleUploadStart}
            onUploadSuccess={handleUploadSuccess}
            onError={setErrorMsg}
          />
        )}

        {appState === 'UPLOADING' && (
          <div className="flex min-h-[360px] flex-col items-center justify-center gap-2 text-slate-300">
            <div className="spinner" />
            <h3>Uploading your book...</h3>
          </div>
        )}

        {appState === 'PROCESSING' && activeJob && (
          <ProcessingIndicator
            jobId={activeJob.id}
            onComplete={handleProcessingComplete}
            onError={(err) => {
              setErrorMsg(err)
              setAppState('IDLE')
            }}
          />
        )}

        {appState === 'READY' && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-lg font-semibold text-white">
                  Searching in: {activeJob?.filename || 'All Books'}
                </h3>
                <p className="text-sm text-emerald-300">
                  {activeJob ? 'Document ready and indexed.' : 'Global mode across indexed books.'}
                </p>
              </div>
              <button
                type="button"
                className="rounded-md bg-blue-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-600"
                onClick={resetToUpload}
              >
                Upload Another
              </button>
            </div>

            <div className="space-y-4">
              <SearchInterface
                onSearch={searchInBook}
                onQueryChange={setLastQuery}
              />

              {searchResults && (
                <ResultsViewer
                  searchData={searchResults}
                  isStreaming={Boolean(searchResults.is_streaming)}
                  onSelectClarification={(chapterNumber) =>
                    lastQuery
                      ? searchInBook(lastQuery, { chapterNumber })
                      : undefined
                  }
                />
              )}

              {searchHistory.length > 0 && (
                <div className="rounded-xl border border-slate-800 bg-slate-900/65 p-4">
                  <h4 className="mb-3 text-sm font-semibold text-slate-200">Recent Searches</h4>
                  <div className="space-y-2">
                    {searchHistory.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => setSearchResults({
                          answer: item.answer,
                          results: item.results,
                          response_kind: item.response_kind || 'answer',
                          cost: { usd: item.cost_usd, breakdown: [] },
                          is_streaming: false,
                        })}
                        className="w-full rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2 text-left transition hover:border-blue-500/40 hover:bg-slate-900"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <p className="truncate text-sm text-slate-200">{item.query}</p>
                          <span className="text-xs text-slate-500">
                            ${Number(item.cost_usd || 0).toFixed(4)}
                          </span>
                        </div>
                        <p className="mt-1 line-clamp-1 text-xs text-slate-400">{item.answer}</p>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}
