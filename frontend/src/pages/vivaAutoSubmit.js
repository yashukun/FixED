// Pure helpers for viva auto-submit / conflict handling. Kept in their own module
// (not VivaPage.jsx) so the page file only exports a component — required by
// react-refresh — while these remain independently unit-testable.

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
