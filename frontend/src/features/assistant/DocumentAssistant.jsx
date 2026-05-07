import { useCallback, useEffect, useState } from 'react'
import BookUploader from '../../components/BookUploader'
import ProcessingIndicator from '../../components/ProcessingIndicator'
import SearchInterface from '../../components/SearchInterface'
import ResultsViewer from '../../components/ResultsViewer'
import LibrarySidebar from '../../components/LibrarySidebar'
import { api } from '../../services/api'
import { Card } from '../../components/ui/card'

const normalizeStatus = (status) => String(status || '').toLowerCase()

export default function DocumentAssistant() {
  const [jobs, setJobs] = useState([])
  const [activeJob, setActiveJob] = useState(null)
  const [lastQuery, setLastQuery] = useState('')
  const [forceUploadMode, setForceUploadMode] = useState(false)
  const [appState, setAppState] = useState('IDLE')
  const [searchResults, setSearchResults] = useState(null)
  const [errorMsg, setErrorMsg] = useState('')

  const fetchJobs = useCallback(async () => {
    try {
      const data = await api.getAllJobs()
      setJobs(data)

      if (!activeJob && data.length > 0 && !forceUploadMode) {
        const readyJob = data.find((job) => normalizeStatus(job.status) === 'completed')
        if (readyJob) {
          setActiveJob(readyJob)
          setAppState('READY')
        }
      }
    } catch (err) {
      setErrorMsg(err.message)
    }
  }, [activeJob, forceUploadMode])

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
    fetchJobs()
  }

  const handleLibrarySelect = (job) => {
    setForceUploadMode(false)
    setActiveJob(job)
    setErrorMsg('')
    setSearchResults(null)
    setLastQuery('')
    const status = normalizeStatus(job.status)

    if (status === 'completed') {
      setAppState('READY')
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
  }

  const searchInBook = async (query, overrides = {}) => {
    if (!activeJob?.id) return
    setErrorMsg('')
    setLastQuery(query)
    try {
      const data = await api.searchBook(query, activeJob.id, {
        activePage: overrides.activePage ?? null,
        chapterNumber: overrides.chapterNumber ?? null,
      })
      setSearchResults(data)
    } catch (err) {
      setErrorMsg(err.message)
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <LibrarySidebar
        jobs={jobs}
        activeJobId={activeJob?.id}
        onSelectJob={handleLibrarySelect}
        onNewUpload={resetToUpload}
      />
      <Card className="min-h-[560px]">
        {errorMsg && (
          <div className="mb-4 rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
            {errorMsg}
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

        {appState === 'READY' && activeJob && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-lg font-semibold text-white">Searching in: {activeJob.filename}</h3>
                <p className="text-sm text-emerald-300">Document ready and indexed.</p>
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
                  onSelectClarification={(chapterNumber) =>
                    lastQuery
                      ? searchInBook(lastQuery, { chapterNumber })
                      : undefined
                  }
                />
              )}
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}
