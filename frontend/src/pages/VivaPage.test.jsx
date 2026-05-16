import { describe, expect, it } from 'vitest'
import { isRecoverableSubmitConflict, shouldAutoSubmitCurrentQuestion } from './VivaPage'

describe('shouldAutoSubmitCurrentQuestion', () => {
  it('does not auto-submit before question deadline is initialized', () => {
    const shouldSubmit = shouldAutoSubmitCurrentQuestion({
      stage: 'session',
      questionId: 'q-2',
      secondsLeft: 0,
      busy: false,
      submitInFlightQuestionId: '',
      timeoutAutoSubmitQuestionId: '',
      deadlineAtMs: null,
      nowMs: 1_000,
    })

    expect(shouldSubmit).toBe(false)
  })

  it('auto-submits when timer is expired and question is idle', () => {
    const shouldSubmit = shouldAutoSubmitCurrentQuestion({
      stage: 'session',
      questionId: 'q-2',
      secondsLeft: 0,
      busy: false,
      submitInFlightQuestionId: '',
      timeoutAutoSubmitQuestionId: '',
      deadlineAtMs: 1_000,
      nowMs: 1_001,
    })

    expect(shouldSubmit).toBe(true)
  })

  it('does not auto-submit when countdown shows zero before absolute deadline', () => {
    const shouldSubmit = shouldAutoSubmitCurrentQuestion({
      stage: 'session',
      questionId: 'q-2',
      secondsLeft: 0,
      busy: false,
      submitInFlightQuestionId: '',
      timeoutAutoSubmitQuestionId: '',
      deadlineAtMs: 1_500,
      nowMs: 1_001,
    })

    expect(shouldSubmit).toBe(false)
  })

  it('prevents duplicate submit when same question is already in flight', () => {
    const shouldSubmit = shouldAutoSubmitCurrentQuestion({
      stage: 'session',
      questionId: 'q-2',
      secondsLeft: 0,
      busy: false,
      submitInFlightQuestionId: 'q-2',
      timeoutAutoSubmitQuestionId: '',
      deadlineAtMs: 1_000,
      nowMs: 1_100,
    })

    expect(shouldSubmit).toBe(false)
  })
})

describe('isRecoverableSubmitConflict', () => {
  it('recognizes stale-question conflicts for session resync', () => {
    expect(isRecoverableSubmitConflict('Submitted question is stale for current session state')).toBe(true)
  })

  it('does not classify generic failures as conflict', () => {
    expect(isRecoverableSubmitConflict('Failed to submit answer')).toBe(false)
  })
})
