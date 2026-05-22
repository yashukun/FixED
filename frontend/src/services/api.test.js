import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'

describe('api.searchBook', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('omits file_id in all-books mode', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ answer: 'ok', results: [] }),
    })
    globalThis.fetch = fetchMock

    await api.searchBook('test query', null, { topK: 3 })

    const [, options] = fetchMock.mock.calls[0]
    const payload = JSON.parse(options.body)
    expect(payload.file_id).toBeUndefined()
    expect(payload.query).toBe('test query')
  })

  it('keeps file_id when a book is selected', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ answer: 'ok', results: [] }),
    })
    globalThis.fetch = fetchMock

    await api.searchBook('test query', 'file-123', { topK: 3 })

    const [, options] = fetchMock.mock.calls[0]
    const payload = JSON.parse(options.body)
    expect(payload.file_id).toBe('file-123')
  })
})

describe('api.searchBookStream', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  const streamDonePayload = { answer: 'ok', results: [] }
  const encoder = new TextEncoder()

  const buildSseStream = () =>
    new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode(`event: done\ndata: ${JSON.stringify(streamDonePayload)}\n\n`),
        )
        controller.close()
      },
    })

  it('omits file_id in all-books mode', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: buildSseStream(),
    })
    globalThis.fetch = fetchMock

    await api.searchBookStream('test query', null, { topK: 3 }, {})

    const [, options] = fetchMock.mock.calls[0]
    const payload = JSON.parse(options.body)
    expect(payload.file_id).toBeUndefined()
    expect(payload.query).toBe('test query')
  })

  it('keeps file_id when a book is selected', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: buildSseStream(),
    })
    globalThis.fetch = fetchMock

    await api.searchBookStream('test query', 'file-123', { topK: 3 }, {})

    const [, options] = fetchMock.mock.calls[0]
    const payload = JSON.parse(options.body)
    expect(payload.file_id).toBe('file-123')
  })
})

describe('dashboard analytics API routes', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('calls dashboard analytics summary endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ source: 'live' }) })
    globalThis.fetch = fetchMock
    await api.getDashboardAnalyticsSummary()
    expect(fetchMock).toHaveBeenCalledWith('/api/gateway/dashboard/analytics/summary')
  })

  it('calls dashboard analytics breakdown endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ source: 'live' }) })
    globalThis.fetch = fetchMock
    await api.getDashboardAnalyticsBreakdown()
    expect(fetchMock).toHaveBeenCalledWith('/api/gateway/dashboard/analytics/breakdown')
  })
})
