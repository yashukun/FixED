import { useCallback, useMemo, useState } from 'react'
import { api } from '../services/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { ErrorBanner, SpinnerState } from '../components/feedback'
import { useAsyncResource } from '../hooks/useAsyncResource'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { downloadPaperPdf } from '../lib/questionPaperPdf'
import { flattenQuestions, normalizePaperEntry } from '../lib/questionPaperFormat'

function EventList({ events }) {
  return (
    <CardContent className="space-y-3">
      {events.map((event) => (
        <div key={event.id} className="flex items-center justify-between rounded-lg border border-slate-800 p-3">
          <div>
            <p className="font-medium text-white">{event.title}</p>
            <p className="text-xs text-slate-400">{event.when} • {event.subject}</p>
          </div>
          <Badge variant={event.kind === 'viva' ? 'warning' : 'info'}>{event.kind}</Badge>
        </div>
      ))}
    </CardContent>
  )
}

const objectiveSections = new Set(['mcq', 'true_false', 'fill_blank'])

export default function UpcomingPage() {
  const loadUpcoming = useCallback(() => api.getUpcomingEvents(), [])
  const loadBooks = useCallback(() => api.getAllJobs(), [])
  const loadHistory = useCallback(() => api.getQuestionPaperHistory({ limit: 8 }), [])
  const { data, error } = useAsyncResource(loadUpcoming)
  const { data: jobs, error: jobsError } = useAsyncResource(loadBooks)
  const { data: paperHistory, error: paperError, setData: setPaperHistory } = useAsyncResource(loadHistory)

  const [topic, setTopic] = useState('')
  const [examTitle, setExamTitle] = useState('')
  const [scheduledAt, setScheduledAt] = useState('')
  const [docId, setDocId] = useState('')
  const [totalMarks, setTotalMarks] = useState('70')
  const [topK, setTopK] = useState('20')
  const [mode, setMode] = useState('official')
  const [mcqPct, setMcqPct] = useState('70')
  const [subjectivePct, setSubjectivePct] = useState('20')
  const [trueFalsePct, setTrueFalsePct] = useState('10')
  const [fillBlankPct, setFillBlankPct] = useState('0')
  const [chapterNumber, setChapterNumber] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')
  const [activePaperId, setActivePaperId] = useState('')
  const [answersByQid, setAnswersByQid] = useState({})
  const [testResult, setTestResult] = useState(null)

  const readyJobs = useMemo(() => {
    if (!Array.isArray(jobs)) return []
    return jobs.filter((job) => {
      const status = String(job.status || '').toLowerCase()
      return status === 'completed' || status === 'ready'
    })
  }, [jobs])

  const mergedEvents = useMemo(() => {
    const base = Array.isArray(data?.events) ? data.events : []
    const scheduled = Array.isArray(paperHistory)
      ? paperHistory.slice(0, 3).map((paper) => ({
          id: `paper-${paper.paper_id}`,
          title: `${paper.topic} (${paper.mode})`,
          when: new Date(paper.created_at).toLocaleString(),
          subject: paper.file_id,
          kind: 'exam',
        }))
      : []
    return [...scheduled, ...base]
  }, [data, paperHistory])

  const normalizedPapers = useMemo(
    () => (Array.isArray(paperHistory) ? paperHistory.map(normalizePaperEntry).filter(Boolean) : []),
    [paperHistory],
  )

  const activePaper = useMemo(
    () => normalizedPapers.find((paper) => paper.paper_id === activePaperId) || null,
    [normalizedPapers, activePaperId],
  )

  const activeQuestions = useMemo(
    () => flattenQuestions(activePaper, { numbering: 'global' }),
    [activePaper],
  )

  const distributionTotal = useMemo(
    () =>
      Number(mcqPct || 0) +
      Number(subjectivePct || 0) +
      Number(trueFalsePct || 0) +
      Number(fillBlankPct || 0),
    [mcqPct, subjectivePct, trueFalsePct, fillBlankPct],
  )

  const handleScheduleExam = async (event) => {
    event.preventDefault()
    setSubmitError('')
    setSuccessMessage('')

    if (!docId) {
      setSubmitError('Please select a processed book.')
      return
    }
    if (!topic.trim()) {
      setSubmitError('Please enter a topic/chapter for the exam.')
      return
    }
    if (!scheduledAt) {
      setSubmitError('Please choose an exam schedule date/time.')
      return
    }
    if (distributionTotal !== 100) {
      setSubmitError(`Distribution must total 100. Current total is ${distributionTotal}.`)
      return
    }

    const payload = {
      doc_id: docId,
      topic: topic.trim(),
      total_marks: Number(totalMarks || 0),
      distribution: {
        mcq: Number(mcqPct || 0),
        subjective: Number(subjectivePct || 0),
        true_false: Number(trueFalsePct || 0),
        fill_blank: Number(fillBlankPct || 0),
      },
      mode,
      top_k: Number(topK || 20),
    }
    if (chapterNumber) {
      payload.chapter_number = Number(chapterNumber)
    }

    try {
      setSubmitting(true)
      const result = await api.generateQuestionPaper(payload)
      const normalizedResult = normalizePaperEntry(result)
      const name = examTitle.trim() || result.topic
      setSuccessMessage(
        `Scheduled "${name}" for ${new Date(scheduledAt).toLocaleString()} • Paper ID: ${result.paper_id}`,
      )
      setPaperHistory((prev) => [normalizedResult, ...(Array.isArray(prev) ? prev : [])].slice(0, 8))
      setActivePaperId(result.paper_id)
      setAnswersByQid({})
      setTestResult(null)
    } catch (err) {
      setSubmitError(err.message || 'Failed to schedule exam.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleStartTest = (paperId) => {
    setActivePaperId(paperId)
    setAnswersByQid({})
    setTestResult(null)
  }

  const setAnswer = (qid, value) => {
    setAnswersByQid((prev) => ({ ...prev, [qid]: value }))
  }

  const handleSubmitTest = () => {
    if (!activePaper) return
    const questions = flattenQuestions(activePaper, { numbering: 'global' })
    let objectiveScored = 0
    let objectiveTotal = 0
    let answered = 0

    for (const q of questions) {
      const given = String(answersByQid[q.qid] || '').trim()
      if (given) {
        answered += 1
      }
      if (objectiveSections.has(q.section)) {
        objectiveTotal += q.marks
        const expected = String(q.answer || '').trim().toLowerCase()
        if (given && expected && given.toLowerCase() === expected) {
          objectiveScored += q.marks
        }
      }
    }
    setTestResult({
      answered,
      totalQuestions: questions.length,
      objectiveScored,
      objectiveTotal,
      submittedAt: new Date().toISOString(),
    })
  }

  if (error || jobsError || paperError) {
    return <ErrorBanner message={error || jobsError || paperError} />
  }
  if (!data || !jobs || !paperHistory) return <SpinnerState label="Loading upcoming schedule" />

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-white">Upcoming</h2>
        <p className="text-sm text-slate-400">Scheduled tests and upcoming viva/mock interview modules.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Scheduled Tests</CardTitle>
          <CardDescription>Timeline from teacher scheduling feed</CardDescription>
        </CardHeader>
        <EventList events={mergedEvents} />
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Schedule Exam</CardTitle>
          <CardDescription>Create a question paper directly from uploaded books.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleScheduleExam}>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-2">
                <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Exam title</label>
                <Input
                  value={examTitle}
                  onChange={(e) => setExamTitle(e.target.value)}
                  placeholder="Mid-term science mock test"
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Schedule date/time</label>
                <Input type="datetime-local" value={scheduledAt} onChange={(e) => setScheduledAt(e.target.value)} />
              </div>
            </div>

            <div className="grid gap-4 lg:grid-cols-3">
              <div className="space-y-2 lg:col-span-2">
                <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Book (doc_id)</label>
                <select
                  value={docId}
                  onChange={(e) => setDocId(e.target.value)}
                  className="h-10 w-full rounded-md border border-slate-700 bg-slate-900/70 px-3 text-sm text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
                >
                  <option value="">Select completed upload</option>
                  {readyJobs.map((job) => (
                    <option key={job.id} value={job.id}>
                      {job.filename} ({job.id.slice(0, 8)}...)
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Mode</label>
                <select
                  value={mode}
                  onChange={(e) => setMode(e.target.value)}
                  className="h-10 w-full rounded-md border border-slate-700 bg-slate-900/70 px-3 text-sm text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
                >
                  <option value="official">official</option>
                  <option value="practice">practice</option>
                </select>
              </div>
            </div>

            <div className="grid gap-4 lg:grid-cols-3">
              <div className="space-y-2 lg:col-span-2">
                <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Topic / chapter prompt</label>
                <Input
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  placeholder="e.g. Photosynthesis in chapter 4"
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Chapter number (optional)</label>
                <Input type="number" min="1" value={chapterNumber} onChange={(e) => setChapterNumber(e.target.value)} />
              </div>
            </div>

            <div className="grid gap-4 lg:grid-cols-4">
              <div className="space-y-2">
                <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Total marks</label>
                <Input type="number" min="1" value={totalMarks} onChange={(e) => setTotalMarks(e.target.value)} />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Top-K chunks</label>
                <Input type="number" min="1" max="40" value={topK} onChange={(e) => setTopK(e.target.value)} />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium uppercase tracking-wide text-slate-400">MCQ %</label>
                <Input type="number" min="0" max="100" value={mcqPct} onChange={(e) => setMcqPct(e.target.value)} />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Subjective %</label>
                <Input type="number" min="0" max="100" value={subjectivePct} onChange={(e) => setSubjectivePct(e.target.value)} />
              </div>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-2">
                <label className="text-xs font-medium uppercase tracking-wide text-slate-400">True/False %</label>
                <Input type="number" min="0" max="100" value={trueFalsePct} onChange={(e) => setTrueFalsePct(e.target.value)} />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Fill blank %</label>
                <Input type="number" min="0" max="100" value={fillBlankPct} onChange={(e) => setFillBlankPct(e.target.value)} />
              </div>
            </div>

            <p className={`text-xs ${distributionTotal === 100 ? 'text-emerald-400' : 'text-amber-300'}`}>
              Distribution total: {distributionTotal}%
            </p>
            <ErrorBanner message={submitError} />
            {successMessage ? (
              <p className="rounded-md border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-200">
                {successMessage}
              </p>
            ) : null}
            <div className="flex justify-end">
              <Button type="submit" disabled={submitting}>
                {submitting ? 'Scheduling...' : 'Schedule Exam'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Generated Papers</CardTitle>
          <CardDescription>Start test from here or download the paper as PDF.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {normalizedPapers.length === 0 ? (
            <p className="text-sm text-slate-400">No generated papers yet.</p>
          ) : (
            normalizedPapers.map((paper) => (
              <div key={paper.paper_id} className="rounded-lg border border-slate-800 p-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-medium text-white">{paper.topic}</p>
                    <p className="text-xs text-slate-400">
                      {new Date(paper.created_at).toLocaleString()} • {paper.total_marks} marks • {paper.mode}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="outline" onClick={() => handleStartTest(paper.paper_id)}>
                      Start Test
                    </Button>
                    <Button variant="outline" onClick={() => downloadPaperPdf(paper)}>
                      Download PDF
                    </Button>
                  </div>
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {activePaper ? (
        <Card>
          <CardHeader>
            <CardTitle>{activePaper.topic}</CardTitle>
            <CardDescription>
              Test mode • {activePaper.total_marks} marks • {activeQuestions.length} questions
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {activeQuestions.map((q) => (
              <div key={q.qid} className="rounded-lg border border-slate-800 p-3">
                <p className="font-medium text-white">
                  {q.number}. [{q.sectionLabel}] ({q.marks} marks)
                </p>
                <p className="mt-1 text-sm text-slate-200">{q.question}</p>
                {q.section === 'mcq' && q.options.length ? (
                  <div className="mt-2 space-y-2">
                    {q.options.map((option, idx) => (
                      <label key={`${q.qid}-${option}`} className="flex items-center gap-2 text-sm text-slate-300">
                        <input
                          type="radio"
                          name={q.qid}
                          value={option}
                          checked={answersByQid[q.qid] === option}
                          onChange={(e) => setAnswer(q.qid, e.target.value)}
                        />
                        <span>{String.fromCharCode(65 + idx)}. {option}</span>
                      </label>
                    ))}
                  </div>
                ) : q.section === 'true_false' ? (
                  <div className="mt-2 space-y-2">
                    {['True', 'False'].map((option) => (
                      <label key={`${q.qid}-${option}`} className="flex items-center gap-2 text-sm text-slate-300">
                        <input
                          type="radio"
                          name={q.qid}
                          value={option}
                          checked={answersByQid[q.qid] === option}
                          onChange={(e) => setAnswer(q.qid, e.target.value)}
                        />
                        <span>{option}</span>
                      </label>
                    ))}
                  </div>
                ) : q.section === 'fill_blank' ? (
                  <Input
                    className="mt-2"
                    placeholder="Type the missing term..."
                    value={answersByQid[q.qid] || ''}
                    onChange={(e) => setAnswer(q.qid, e.target.value)}
                  />
                ) : (
                  <textarea
                    className="mt-2 min-h-20 w-full rounded-md border border-slate-700 bg-slate-900/70 p-2 text-sm text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
                    placeholder="Type your answer..."
                    value={answersByQid[q.qid] || ''}
                    onChange={(e) => setAnswer(q.qid, e.target.value)}
                  />
                )}
              </div>
            ))}

            {testResult ? (
              <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-200">
                Answered {testResult.answered}/{testResult.totalQuestions} questions.
                Objective score: {testResult.objectiveScored}/{testResult.objectiveTotal}
              </div>
            ) : null}

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setActivePaperId('')}>
                Close Test
              </Button>
              <Button onClick={handleSubmitTest}>Submit Test</Button>
            </div>
          </CardContent>
        </Card>
      ) : null}
      <p className="text-xs text-slate-500">Data source: {data.source}</p>
    </div>
  )
}
