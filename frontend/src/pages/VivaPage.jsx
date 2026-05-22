import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../services/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Badge } from '../components/ui/badge'
import { ErrorBanner } from '../components/feedback'
import { useCost } from '../context/useCost'

export function shouldAutoSubmitCurrentQuestion({
  stage,
  questionId,
  secondsLeft,
  busy,
  submitInFlightQuestionId,
  timeoutAutoSubmitQuestionId,
  deadlineAtMs,
  nowMs = Date.now(),
}) {
  if (stage !== 'session' || !questionId) return false
  if (!Number.isFinite(deadlineAtMs)) return false
  if (secondsLeft > 0 || busy) return false
  if (nowMs < deadlineAtMs) return false
  if (submitInFlightQuestionId === questionId) return false
  if (timeoutAutoSubmitQuestionId === questionId) return false
  return true
}

export function isRecoverableSubmitConflict(message) {
  const normalized = String(message || '').toLowerCase()
  return (
    normalized.includes('no active question found for session') ||
    normalized.includes('next question not found for session') ||
    normalized.includes('session is not active') ||
    normalized.includes('submitted question is stale for current session state')
  )
}

function imageDataToBase64(dataUrl) {
  if (!dataUrl) return ''
  return dataUrl.replace(/^data:image\/\w+;base64,/, '')
}

function captureFrameBase64(videoEl) {
  if (!videoEl || !videoEl.videoWidth || !videoEl.videoHeight) return ''
  const canvas = document.createElement('canvas')
  const maxWidth = 420
  const scale = Math.min(1, maxWidth / videoEl.videoWidth)
  canvas.width = Math.max(1, Math.floor(videoEl.videoWidth * scale))
  canvas.height = Math.max(1, Math.floor(videoEl.videoHeight * scale))
  const ctx = canvas.getContext('2d')
  if (!ctx) return ''
  ctx.drawImage(videoEl, 0, 0, canvas.width, canvas.height)
  return imageDataToBase64(canvas.toDataURL('image/jpeg', 0.45))
}

function resolveFramePreview(sessionId, details) {
  const objectPath = details?.frame_object_path
  if (objectPath && sessionId) return api.getVivaMediaUrl(sessionId, objectPath)
  if (details?.frame_b64_fallback) return `data:image/jpeg;base64,${details.frame_b64_fallback}`
  return ''
}

export default function VivaPage() {
  const { startLive, commitLive, clearLive, addCost } = useCost()
  const [jobs, setJobs] = useState([])
  const [chapters, setChapters] = useState([])
  const [loadError, setLoadError] = useState('')
  const [stage, setStage] = useState('setup')

  const [fileId, setFileId] = useState('')
  const [topic, setTopic] = useState('')
  const [chapterNumber, setChapterNumber] = useState('')
  const [questionCount, setQuestionCount] = useState('5')
  const [perQuestionLimit, setPerQuestionLimit] = useState('60')

  const [mediaReady, setMediaReady] = useState(false)
  const [referenceCaptured, setReferenceCaptured] = useState(false)
  const [referenceImageB64, setReferenceImageB64] = useState('')
  const [busy, setBusy] = useState(false)

  const [session, setSession] = useState(null)
  const [currentQuestion, setCurrentQuestion] = useState(null)
  const [warnings, setWarnings] = useState(0)
  const [sessionError, setSessionError] = useState('')
  const [answerText, setAnswerText] = useState('')
  const [results, setResults] = useState(null)
  const [secondsLeft, setSecondsLeft] = useState(0)
  const [questionDeadlineAtMs, setQuestionDeadlineAtMs] = useState(null)
  const [lastProctorAt, setLastProctorAt] = useState(null)
  const [history, setHistory] = useState([])
  const [historyError, setHistoryError] = useState('')
  const [selectedAudit, setSelectedAudit] = useState(null)

  const videoRef = useRef(null)
  const streamRef = useRef(null)
  const proctorIntervalRef = useRef(null)
  const speechRecognitionRef = useRef(null)
  const proctorInFlightRef = useRef(false)
  const timeoutAutoSubmitRef = useRef('')
  const submitInFlightQuestionRef = useRef('')

  const readyJobs = useMemo(() => {
    if (!Array.isArray(jobs)) return []
    return jobs.filter((job) => {
      const status = String(job.status || '').toLowerCase()
      return status === 'completed' || status === 'ready'
    })
  }, [jobs])

  useEffect(() => {
    let mounted = true
    api
      .getAllJobs()
      .then((rows) => {
        if (!mounted) return
        setJobs(rows || [])
      })
      .catch((err) => {
        if (!mounted) return
        setLoadError(err.message || 'Failed to load books')
      })
    return () => {
      mounted = false
    }
  }, [])

  const refreshHistory = async () => {
    try {
      setHistoryError('')
      const rows = await api.getVivaHistory({ limit: 20 })
      setHistory(Array.isArray(rows) ? rows : [])
    } catch (err) {
      setHistoryError(err.message || 'Failed to load viva history')
    }
  }

  useEffect(() => {
    refreshHistory()
  }, [])

  useEffect(() => {
    if (!fileId) {
      setChapters([])
      return
    }
    api
      .getBookChapters(fileId)
      .then((rows) => setChapters(rows || []))
      .catch(() => setChapters([]))
  }, [fileId])

  useEffect(() => {
    if (!session?.session_id || stage !== 'session') return undefined
    const runProctorCheck = async () => {
      if (proctorInFlightRef.current) return
      const frame = captureFrameBase64(videoRef.current)
      if (!frame) return
      try {
        proctorInFlightRef.current = true
        const resp = await api.vivaProctorFrame(session.session_id, frame)
        if (typeof resp?.cost?.usd === 'number') {
          addCost(resp.cost.usd)
        }
        setWarnings((prev) => Math.max(prev, Number(resp.warnings || 0)))
        setLastProctorAt(new Date().toISOString())
        if (resp.action === 'terminated') {
          setSession(resp.session || null)
          const result = await api.getVivaResults(session.session_id)
          setResults(result?.result ? { ...result.result, session: result.session } : null)
          setStage('results')
          refreshHistory()
        }
      } catch (err) {
        setSessionError(err.message || 'Proctor check failed')
      } finally {
        proctorInFlightRef.current = false
      }
    }
    runProctorCheck()
    proctorIntervalRef.current = window.setInterval(runProctorCheck, 5000)

    return () => {
      if (proctorIntervalRef.current) {
        window.clearInterval(proctorIntervalRef.current)
        proctorIntervalRef.current = null
      }
    }
  }, [session?.session_id, stage])

  useEffect(() => {
    if (!currentQuestion || stage !== 'session') return undefined
    const maxSeconds = Number(session?.per_question_limit_seconds || perQuestionLimit || 60)
    const deadlineAt = Date.now() + (maxSeconds * 1000)
    setQuestionDeadlineAtMs(deadlineAt)
    setSecondsLeft(maxSeconds)
    const timer = window.setInterval(() => {
      const next = Math.max(Math.ceil((deadlineAt - Date.now()) / 1000), 0)
      setSecondsLeft(next)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [currentQuestion, stage, session?.per_question_limit_seconds, perQuestionLimit])

  useEffect(() => {
    return () => {
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop())
      }
      if (speechRecognitionRef.current) {
        speechRecognitionRef.current.stop?.()
      }
    }
  }, [])

  const requestMedia = async () => {
    setLoadError('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true })
      streamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
      }
      setMediaReady(true)
    } catch (err) {
      setLoadError(err.message || 'Camera/microphone permissions are required.')
    }
  }

  const captureReference = () => {
    const frame = captureFrameBase64(videoRef.current)
    if (!frame) {
      setLoadError('Unable to capture reference photo.')
      return
    }
    setReferenceImageB64(frame)
    setReferenceCaptured(true)
  }

  const speakQuestion = (text) => {
    if (!text || !window.speechSynthesis) return
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.rate = 1
    utterance.pitch = 1
    window.speechSynthesis.cancel()
    window.speechSynthesis.speak(utterance)
  }

  const startListening = () => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognition) {
      setSessionError('Speech recognition is not supported in this browser. Type your answer manually.')
      return
    }
    const recognizer = new SpeechRecognition()
    speechRecognitionRef.current = recognizer
    recognizer.lang = 'en-US'
    recognizer.interimResults = true
    recognizer.continuous = false
    recognizer.onresult = (event) => {
      const text = Array.from(event.results)
        .map((res) => res[0]?.transcript || '')
        .join(' ')
      setAnswerText(text.trim())
    }
    recognizer.start()
  }

  const handleStart = async () => {
    setSessionError('')
    if (!fileId || !topic.trim()) {
      setSessionError('Book and topic are required.')
      return
    }
    const parsedQuestionCount = Number(questionCount || 0)
    if (!Number.isFinite(parsedQuestionCount) || parsedQuestionCount < 5 || parsedQuestionCount > 10) {
      setSessionError('Question count must be between 5 and 10.')
      return
    }
    if (!mediaReady || !referenceCaptured || !referenceImageB64) {
      setSessionError('Camera/mic permissions and reference photo are required before starting.')
      return
    }
    setBusy(true)
    startLive('Viva start')
    try {
      const started = await api.startVivaSession({
        file_id: fileId,
        topic: topic.trim(),
        chapter_number: chapterNumber ? Number(chapterNumber) : null,
        question_count: parsedQuestionCount,
        per_question_limit_seconds: Number(perQuestionLimit || 60),
      })
      const sessionId = started?.session?.session_id
      await api.setVivaReferencePhoto(sessionId, referenceImageB64)
      if (typeof started?.cost?.usd === 'number') {
        commitLive(started.cost.usd)
      } else {
        clearLive()
      }
      setSession(started.session)
      setCurrentQuestion(started.current_question)
      setWarnings(0)
      setStage('session')
      speakQuestion(started.current_question?.question_text)
    } catch (err) {
      clearLive()
      setSessionError(err.message || 'Failed to start viva session')
    } finally {
      setBusy(false)
    }
  }

  const submitAnswer = async (opts = {}) => {
    const allowEmpty = Boolean(opts?.allowEmpty)
    const source = opts?.source === 'auto' ? 'auto' : 'manual'
    const questionId = currentQuestion?.question_id || ''
    const transcript = answerText.trim()
    if (!session?.session_id) return
    if (!questionId) return
    if (!allowEmpty && !transcript) {
      setSessionError('Please provide an answer before submitting.')
      return
    }
    if (submitInFlightQuestionRef.current === questionId) return
    if (source === 'manual') {
      // Manual submit should always win over timer fallback for this question.
      timeoutAutoSubmitRef.current = questionId
    }
    setSessionError('')
    submitInFlightQuestionRef.current = questionId
    setBusy(true)
    startLive('Viva answer')
    try {
      const response = await api.submitVivaAnswer(session.session_id, {
        transcript,
        question_id: questionId,
      })
      if (typeof response?.cost?.usd === 'number') {
        commitLive(response.cost.usd)
      } else {
        clearLive()
      }
      setSession(response.session || session)
      setAnswerText('')
      if (response.done || response.terminated || (response.result && !response.next_question)) {
        timeoutAutoSubmitRef.current = ''
        setResults(response?.result ? { ...response.result, session: response.session } : null)
        setStage('results')
        refreshHistory()
        return
      }
      timeoutAutoSubmitRef.current = ''
      setQuestionDeadlineAtMs(null)
      setCurrentQuestion(response.next_question || null)
      speakQuestion(response.next_question?.question_text)
    } catch (err) {
      clearLive()
      const message = err?.message || 'Failed to submit answer'
      const isConflict = isRecoverableSubmitConflict(message)

      if (isConflict && session?.session_id) {
        // Prevent timer-driven resubmission loops while we reconcile server state.
        timeoutAutoSubmitRef.current = questionId
        try {
          const latest = await api.getVivaSession(session.session_id)
          if (latest?.session) {
            setSession(latest.session)
          }
          if (latest?.current_question?.question_id) {
            const nextId = latest.current_question.question_id
            if (nextId !== questionId) {
              setQuestionDeadlineAtMs(null)
              setCurrentQuestion(latest.current_question)
              setAnswerText('')
              setSessionError('')
              speakQuestion(latest.current_question.question_text)
            } else {
              // If IDs match but server still returns conflict, retry once without question_id.
              const retryResponse = await api.submitVivaAnswer(session.session_id, {
                transcript,
              })
              setSession(retryResponse.session || latest.session || session)
              setAnswerText('')
              if (
                retryResponse.done ||
                retryResponse.terminated ||
                (retryResponse.result && !retryResponse.next_question)
              ) {
                timeoutAutoSubmitRef.current = ''
                setResults(retryResponse?.result ? { ...retryResponse.result, session: retryResponse.session } : null)
                setStage('results')
                refreshHistory()
              } else {
                timeoutAutoSubmitRef.current = ''
                setQuestionDeadlineAtMs(null)
                setCurrentQuestion(retryResponse.next_question || latest.current_question)
                setSessionError('')
                speakQuestion(retryResponse.next_question?.question_text || latest.current_question.question_text)
              }
            }
            return
          }

          const finalized = await api.getVivaResults(session.session_id)
          if (finalized?.result) {
            setResults({ ...finalized.result, session: finalized.session })
            setStage('results')
            refreshHistory()
            return
          }
        } catch {
          // Fall through to show the original submit error.
        }
      }
      if (source !== 'auto' && timeoutAutoSubmitRef.current === questionId) {
        timeoutAutoSubmitRef.current = ''
      }
      setSessionError(message)
    } finally {
      if (submitInFlightQuestionRef.current === questionId) {
        submitInFlightQuestionRef.current = ''
      }
      setBusy(false)
    }
  }

  useEffect(() => {
    if (
      !shouldAutoSubmitCurrentQuestion({
        stage,
        questionId: currentQuestion?.question_id,
        secondsLeft,
        busy,
        submitInFlightQuestionId: submitInFlightQuestionRef.current,
        timeoutAutoSubmitQuestionId: timeoutAutoSubmitRef.current,
        deadlineAtMs: questionDeadlineAtMs,
      })
    ) {
      return
    }
    timeoutAutoSubmitRef.current = currentQuestion.question_id
    submitAnswer({ allowEmpty: true, source: 'auto' })
  }, [secondsLeft, stage, currentQuestion?.question_id, busy, questionDeadlineAtMs])

  const finishNow = async () => {
    if (!session?.session_id) return
    setBusy(true)
    startLive('Viva finish')
    try {
      const resp = await api.finishVivaSession(session.session_id)
      clearLive()
      setResults(resp?.result ? { ...resp.result, session: resp.session } : null)
      setSession(resp.session || session)
      setStage('results')
      refreshHistory()
    } catch (err) {
      clearLive()
      setSessionError(err.message || 'Failed to finish session')
    } finally {
      setBusy(false)
    }
  }

  const openAudit = async (sessionId) => {
    try {
      const payload = await api.getVivaSessionAudit(sessionId)
      setSelectedAudit(payload)
    } catch (err) {
      setSessionError(err.message || 'Failed to load viva audit')
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-white">Viva (Oral Examination)</h2>
        <p className="text-sm text-slate-400">Identity-verified AI viva with live proctor checks and auto-scored results.</p>
      </div>

      <ErrorBanner message={loadError || sessionError} />

      <Card>
        <CardHeader>
          <CardTitle>Live Camera Feed</CardTitle>
          <CardDescription>Camera stays on before and during viva session.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <video ref={videoRef} autoPlay playsInline muted className="max-h-72 w-full rounded-md border border-slate-800 bg-slate-950" />
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={requestMedia}>Grant Camera + Mic</Button>
            <Button variant="outline" onClick={captureReference} disabled={!mediaReady}>Capture Reference Photo</Button>
            <Badge variant={mediaReady ? 'success' : 'default'}>{mediaReady ? 'Media Ready' : 'Media Missing'}</Badge>
            <Badge variant={referenceCaptured ? 'success' : 'default'}>
              {referenceCaptured ? 'Reference Captured' : 'Reference Missing'}
            </Badge>
            {stage === 'session' ? (
              <Badge variant={warnings >= 3 ? 'danger' : 'warning'}>Warnings: {warnings}/4</Badge>
            ) : null}
          </div>
        </CardContent>
      </Card>

      {stage === 'setup' ? (
        <Card>
          <CardHeader>
            <CardTitle>Pre-Session Setup</CardTitle>
            <CardDescription>Select book/chapter/topic and start when ready.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Book</label>
                <select
                  value={fileId}
                  onChange={(e) => setFileId(e.target.value)}
                  className="h-10 w-full rounded-md border border-slate-700 bg-slate-900/70 px-3 text-sm text-slate-100"
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
                <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Chapter (optional)</label>
                <select
                  value={chapterNumber}
                  onChange={(e) => setChapterNumber(e.target.value)}
                  className="h-10 w-full rounded-md border border-slate-700 bg-slate-900/70 px-3 text-sm text-slate-100"
                >
                  <option value="">Any chapter</option>
                  {chapters.map((chapter) => (
                    <option key={chapter.number} value={chapter.number}>
                      {chapter.number}: {chapter.title}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="space-y-2 md:col-span-2">
                <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Topic</label>
                <Input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="e.g. Thermodynamics laws and applications" />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Question count (5-10)</label>
                <Input type="number" min="5" max="10" value={questionCount} onChange={(e) => setQuestionCount(e.target.value)} />
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Per-question limit (seconds)</label>
                <Input
                  type="number"
                  min="20"
                  value={perQuestionLimit}
                  onChange={(e) => setPerQuestionLimit(e.target.value)}
                />
              </div>
            </div>
            <div className="flex justify-end">
              <Button onClick={handleStart} disabled={busy}>{busy ? 'Starting...' : 'I am ready, start viva'}</Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {stage === 'session' ? (
        <Card>
          <CardHeader>
            <CardTitle>Live Viva Session</CardTitle>
            <CardDescription>
              {session?.current_question_index || 0}/
              {session?.total_question_target || session?.question_count || 0} answered • {secondsLeft}s left for current question
              {lastProctorAt ? ` • Last proctor check: ${new Date(lastProctorAt).toLocaleTimeString()}` : ''}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-lg border border-slate-800 p-3">
              <p className="text-xs uppercase tracking-wide text-slate-500">Current question</p>
              <p className="mt-1 text-sm text-slate-100">{currentQuestion?.question_text}</p>
            </div>
            <div className="space-y-2">
              <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Your verbal answer transcript</label>
              <textarea
                className="min-h-28 w-full rounded-md border border-slate-700 bg-slate-900/70 p-2 text-sm text-slate-100"
                value={answerText}
                onChange={(e) => setAnswerText(e.target.value)}
                placeholder="Speak or type your answer..."
              />
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => speakQuestion(currentQuestion?.question_text)}>Repeat Question</Button>
                <Button variant="outline" onClick={startListening}>Start Speech-to-Text</Button>
                <Button onClick={submitAnswer} disabled={busy || !answerText.trim()}>
                  {busy ? 'Submitting...' : 'Submit Answer'}
                </Button>
                <Button variant="outline" onClick={finishNow} disabled={busy}>Finish Session</Button>
              </div>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {stage === 'results' ? (
        <Card>
          <CardHeader>
            <CardTitle>Viva Results Dashboard</CardTitle>
            <CardDescription>Core score, per-question breakdown, and AI recommendations.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-lg border border-slate-800 p-3">
              <p className="text-sm text-slate-100">
                Overall score: {Number(results?.overall_score || 0).toFixed(1)}/{Number(results?.max_score || 0).toFixed(1)}
              </p>
              <p className="mt-1 text-xs text-slate-400">{results?.summary}</p>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="rounded-lg border border-slate-800 p-3">
                <p className="text-xs uppercase tracking-wide text-slate-500">Session status</p>
                <p className="mt-1 text-sm text-slate-100">{results?.session?.status || session?.status || 'unknown'}</p>
                <p className="mt-1 text-xs text-slate-400">Warnings: {Number(results?.session?.warning_count ?? warnings ?? 0)}</p>
              </div>
              <div className="rounded-lg border border-slate-800 p-3">
                <p className="text-xs uppercase tracking-wide text-slate-500">Termination reason</p>
                <p className="mt-1 text-sm text-slate-100">{results?.session?.termination_reason || 'not terminated'}</p>
              </div>
              <div className="rounded-lg border border-slate-800 p-3">
                <p className="text-xs uppercase tracking-wide text-slate-500">Total model cost</p>
                <p className="mt-1 text-sm text-slate-100">${Number(results?.cost?.usd || 0).toFixed(6)}</p>
                <p className="mt-1 text-xs text-slate-400">Tokens: {Number(results?.cost?.total_tokens || 0).toLocaleString()}</p>
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="rounded-lg border border-slate-800 p-3">
                <p className="text-xs uppercase tracking-wide text-slate-500">Strengths</p>
                <ul className="mt-2 space-y-1 text-sm text-slate-200">
                  {(results?.strengths || []).map((item) => <li key={item}>- {item}</li>)}
                </ul>
              </div>
              <div className="rounded-lg border border-slate-800 p-3">
                <p className="text-xs uppercase tracking-wide text-slate-500">Weak areas</p>
                <ul className="mt-2 space-y-1 text-sm text-slate-200">
                  {(results?.weak_areas || []).map((item) => <li key={item}>- {item}</li>)}
                </ul>
              </div>
              <div className="rounded-lg border border-slate-800 p-3">
                <p className="text-xs uppercase tracking-wide text-slate-500">Recommendations</p>
                <ul className="mt-2 space-y-1 text-sm text-slate-200">
                  {(results?.recommendations || []).map((item) => <li key={item}>- {item}</li>)}
                </ul>
              </div>
            </div>
            <div className="space-y-2">
              <p className="text-xs uppercase tracking-wide text-slate-500">Per-question breakdown</p>
              {(results?.question_breakdown || []).map((item) => (
                <div key={item.question_id} className="rounded-lg border border-slate-800 p-3 text-sm">
                  <p className="text-slate-100">{item.question}</p>
                  <p className="text-xs text-slate-400">
                    Score: {Number(item.score || 0).toFixed(1)}/{Number(item.max_score || 0).toFixed(1)}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">{item.feedback}</p>
                </div>
              ))}
            </div>
            <div className="space-y-2">
              <p className="text-xs uppercase tracking-wide text-slate-500">Session cost breakdown</p>
              {!results?.cost?.events?.length ? (
                <p className="text-xs text-slate-500">No cost events recorded.</p>
              ) : (
                <div className="space-y-2">
                  {(results.cost.events || []).map((event, idx) => (
                    <div key={`${event.created_at || idx}-${idx}`} className="rounded-lg border border-slate-800 p-3 text-xs text-slate-300">
                      <p>
                        {event.kind} • {event.model} • tokens: {Number(event.total_tokens || 0).toLocaleString()} • $
                        {Number(event.usd || 0).toFixed(6)}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="space-y-2">
              <p className="text-xs uppercase tracking-wide text-slate-500">Proctoring audit trail</p>
              {(results?.proctor_events || []).length === 0 ? (
                <p className="text-xs text-slate-500">No proctor events captured.</p>
              ) : (
                (results?.proctor_events || []).map((event) => (
                  <div key={event.id} className="rounded-lg border border-slate-800 p-3 text-xs text-slate-300">
                    <p>
                      {new Date(event.created_at).toLocaleString()} • action: {event.action} • confidence:{' '}
                      {Number(event.confidence || 0).toFixed(3)} • warnings: {event.warning_count}
                    </p>
                    <p className="mt-1 text-slate-400">
                      reason: {event?.details?.reason || 'n/a'} • decision: {event?.details?.decision_reason || 'n/a'}
                    </p>
                    {event?.details?.frame_object_path ? (
                      <p className="mt-1 break-all text-slate-400">frame object: {event.details.frame_object_path}</p>
                    ) : null}
                    {resolveFramePreview(results?.session?.session_id || session?.session_id, event?.details) ? (
                      <img
                        src={resolveFramePreview(results?.session?.session_id || session?.session_id, event?.details)}
                        alt="Proctor frame snapshot"
                        className="mt-2 max-h-36 rounded border border-slate-700"
                      />
                    ) : null}
                  </div>
                ))
              )}
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Past Viva Sessions</CardTitle>
          <CardDescription>Every interview attempt is saved for evaluator review.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <ErrorBanner message={historyError} />
          {!history.length ? (
            <p className="text-sm text-slate-400">No viva sessions recorded yet.</p>
          ) : (
            history.map((item) => (
              <div key={item.session.session_id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-800 p-3">
                <div>
                  <p className="text-sm text-white">{item.session.topic}</p>
                  <p className="text-xs text-slate-400">
                    {new Date(item.session.started_at || item.session.finished_at || Date.now()).toLocaleString()} • status:{' '}
                    {item.session.status} • score: {Number(item.metrics?.overall_score || 0).toFixed(1)}/
                    {Number(item.metrics?.max_score || 0).toFixed(1)} • warnings: {item.session.warning_count}
                  </p>
                </div>
                <Button variant="outline" onClick={() => openAudit(item.session.session_id)}>View Audit</Button>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {selectedAudit ? (
        <Card>
          <CardHeader>
            <CardTitle>Session Audit Detail</CardTitle>
            <CardDescription>
              {selectedAudit.session.topic} • {selectedAudit.session.status}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-end">
              <Button variant="outline" onClick={() => setSelectedAudit(null)}>Close Audit</Button>
            </div>
            <div className="rounded-lg border border-slate-800 p-3 text-xs text-slate-300">
              Questions: {selectedAudit.questions?.length || 0} • Turns: {selectedAudit.turns?.length || 0} • Proctor events:{' '}
              {selectedAudit.proctor_events?.length || 0}
            </div>
            {(selectedAudit.proctor_events || []).map((event) => (
              <div key={event.id} className="rounded-lg border border-slate-800 p-3 text-xs text-slate-300">
                <p>
                  {new Date(event.created_at).toLocaleString()} • {event.event_type} • {event.action} • confidence:{' '}
                  {Number(event.confidence || 0).toFixed(3)}
                </p>
                <p className="mt-1 text-slate-400">
                  reason: {event?.details?.reason || 'n/a'} • decision: {event?.details?.decision_reason || 'n/a'}
                </p>
                {event?.details?.frame_object_path ? (
                  <p className="mt-1 break-all text-slate-400">frame object: {event.details.frame_object_path}</p>
                ) : null}
                {resolveFramePreview(selectedAudit?.session?.session_id, event?.details) ? (
                  <img
                    src={resolveFramePreview(selectedAudit?.session?.session_id, event?.details)}
                    alt="Audit frame"
                    className="mt-2 max-h-36 rounded border border-slate-700"
                  />
                ) : null}
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}
