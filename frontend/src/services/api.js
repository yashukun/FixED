const GATEWAY_API = import.meta.env.VITE_GATEWAY_API || '/api/gateway'
const INGEST_API = import.meta.env.VITE_INGEST_API || '/api/ingest'
const SEARCH_API = import.meta.env.VITE_SEARCH_API || '/api/search'
const QPAPER_API = import.meta.env.VITE_QPAPER_API || '/api/qpaper'
const VIVA_API = import.meta.env.VITE_VIVA_API || '/api/viva'

const parseJsonSafe = async (res) => {
  try {
    return await res.json()
  } catch {
    return null
  }
}

const getErrorMessage = async (res, fallback) => {
  const json = await parseJsonSafe(res)
  if (json?.detail) {
    if (typeof json.detail === 'string') return json.detail
    if (json.detail?.message) {
      const errors = Array.isArray(json.detail.errors) ? ` (${json.detail.errors.join('; ')})` : ''
      return `${json.detail.message}${errors}`
    }
    try {
      return JSON.stringify(json.detail)
    } catch {
      return fallback
    }
  }
  if (json?.message) return json.message

  try {
    const text = await res.text()
    if (text?.trim()) return text.trim()
  } catch {
    // Ignore and fall back
  }

  return fallback
}

const parseSseEvent = (rawEvent) => {
  const lines = rawEvent.split('\n')
  let event = 'message'
  const dataLines = []
  for (const line of lines) {
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim() || 'message'
      continue
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trim())
    }
  }
  if (!dataLines.length) return null
  const dataText = dataLines.join('\n')
  try {
    return { event, data: JSON.parse(dataText) }
  } catch {
    return { event, data: { message: dataText } }
  }
}

const splitSseEvents = (buffer) => {
  const normalized = buffer.replace(/\r\n/g, '\n')
  const events = normalized.split('\n\n')
  return {
    events: events.slice(0, -1),
    remainder: events.at(-1) || '',
  }
}

export const api = {
  getDashboardNav: async () => {
    const res = await fetch(`${GATEWAY_API}/dashboard/nav`)
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch dashboard navigation'))
    return res.json()
  },

  getDashboardOverview: async () => {
    const res = await fetch(`${GATEWAY_API}/dashboard/overview`)
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch dashboard overview'))
    return res.json()
  },

  getDashboardAnalyticsSummary: async () => {
    const res = await fetch(`${GATEWAY_API}/dashboard/analytics/summary`)
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch analytics summary'))
    return res.json()
  },

  getDashboardAnalyticsTimeseries: async () => {
    const res = await fetch(`${GATEWAY_API}/dashboard/analytics/timeseries`)
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch analytics timeseries'))
    return res.json()
  },

  getDashboardAnalyticsBreakdown: async () => {
    const res = await fetch(`${GATEWAY_API}/dashboard/analytics/breakdown`)
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch analytics breakdown'))
    return res.json()
  },

  getLearnBooks: async () => {
    const res = await fetch(`${GATEWAY_API}/learn/books`)
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch books'))
    return res.json()
  },

  getLearnSubjects: async () => {
    const res = await fetch(`${GATEWAY_API}/learn/subjects`)
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch subjects'))
    return res.json()
  },

  getUpcomingEvents: async () => {
    const res = await fetch(`${GATEWAY_API}/upcoming/events`)
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch upcoming events'))
    return res.json()
  },

  uploadBook: async (file) => {
    const formData = new FormData()
    formData.append('file', file)

    const res = await fetch(`${INGEST_API}/upload`, {
      method: 'POST',
      body: formData,
    })

    if (!res.ok) {
      throw new Error(await getErrorMessage(res, 'Upload failed'))
    }
    return res.json()
  },

  getJobStatus: async (jobId) => {
    const res = await fetch(`${INGEST_API}/job/${jobId}`)
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch job status'))
    return res.json()
  },

  getAllJobs: async () => {
    const res = await fetch(`${INGEST_API}/jobs`)
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch library'))
    return res.json()
  },

  // Reserved for chapter-aware viewer mode.
  getBookChapters: async (jobId) => {
    const res = await fetch(`${INGEST_API}/job/${jobId}/chapters`)
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch chapters'))
    return res.json()
  },

  // Reserved for chapter-aware viewer mode.
  getBookFileUrl: (jobId) => `${INGEST_API}/job/${jobId}/file`,

  searchBook: async (query, fileId, opts = {}) => {
    const payload = {
      query,
      top_k: opts.topK ?? 5,
      active_page: opts.activePage ?? null,
      chapter_number: opts.chapterNumber ?? null,
      chat_session_id: opts.chatSessionId ?? null,
    }
    if (fileId) {
      payload.file_id = fileId
    }
    const res = await fetch(`${SEARCH_API}/search`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    })

    if (!res.ok) {
      throw new Error(await getErrorMessage(res, 'Search failed'))
    }
    return res.json()
  },

  getSearchHistory: async (opts = {}) => {
    const params = new URLSearchParams()
    if (opts.fileId) params.set('file_id', opts.fileId)
    if (opts.chatSessionId) params.set('chat_session_id', opts.chatSessionId)
    if (opts.limit != null) params.set('limit', String(opts.limit))
    if (opts.offset != null) params.set('offset', String(opts.offset))
    const query = params.toString()
    const res = await fetch(`${SEARCH_API}/history/search${query ? `?${query}` : ''}`)
    if (!res.ok) {
      throw new Error(await getErrorMessage(res, 'Failed to fetch search history'))
    }
    return res.json()
  },

  searchBookStream: async (query, fileId, opts = {}, handlers = {}) => {
    const payload = {
      query,
      top_k: opts.topK ?? 5,
      active_page: opts.activePage ?? null,
      chapter_number: opts.chapterNumber ?? null,
      chat_session_id: opts.chatSessionId ?? null,
    }
    if (fileId) {
      payload.file_id = fileId
    }
    const res = await fetch(`${SEARCH_API}/search/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
      signal: opts.signal,
    })
    if (!res.ok) {
      throw new Error(await getErrorMessage(res, 'Search stream failed'))
    }
    if (!res.body) {
      throw new Error('Search stream is not available in this environment.')
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    const handleParsedEvent = (parsed) => {
      if (!parsed) return null
      if (parsed.event === 'retrieval') {
        handlers.onRetrieval?.(parsed.data)
        return null
      }
      if (parsed.event === 'token') {
        handlers.onToken?.(parsed.data?.delta || '')
        return null
      }
      if (parsed.event === 'done') {
        handlers.onDone?.(parsed.data)
        return parsed.data
      }
      if (parsed.event === 'cost') {
        handlers.onCost?.(parsed.data)
        return null
      }
      if (parsed.event === 'status') {
        handlers.onStatus?.(parsed.data)
        return null
      }
      if (parsed.event === 'error') {
        throw new Error(parsed.data?.message || 'Search stream failed')
      }
      return null
    }

    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: true })
      const { events, remainder } = splitSseEvents(buffer)
      buffer = remainder
      for (const rawEvent of events) {
        const parsed = parseSseEvent(rawEvent.trim())
        const maybeDonePayload = handleParsedEvent(parsed)
        if (maybeDonePayload !== null) {
          return maybeDonePayload
        }
      }
      if (done) break
    }

    const tail = decoder.decode()
    if (tail) {
      buffer += tail
    }
    const finalText = buffer.trim()
    if (finalText) {
      const parsed = parseSseEvent(finalText)
      const maybeDonePayload = handleParsedEvent(parsed)
      if (maybeDonePayload !== null) {
        return maybeDonePayload
      }
    }

    return null
  },

  generateQuestionPaper: async (payload) => {
    const res = await fetch(`${QPAPER_API}/generate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      throw new Error(await getErrorMessage(res, 'Question paper generation failed'))
    }
    return res.json()
  },

  getQuestionPaperHistory: async (opts = {}) => {
    const params = new URLSearchParams()
    if (opts.fileId) params.set('file_id', opts.fileId)
    if (opts.limit != null) params.set('limit', String(opts.limit))
    if (opts.offset != null) params.set('offset', String(opts.offset))
    const query = params.toString()
    const res = await fetch(`${QPAPER_API}/history/papers${query ? `?${query}` : ''}`)
    if (!res.ok) {
      throw new Error(await getErrorMessage(res, 'Failed to fetch question paper history'))
    }
    return res.json()
  },

  startVivaSession: async (payload) => {
    const res = await fetch(`${VIVA_API}/viva/sessions/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to start viva session'))
    return res.json()
  },

  setVivaReferencePhoto: async (sessionId, imageB64) => {
    const res = await fetch(`${VIVA_API}/viva/sessions/${sessionId}/reference-photo`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_b64: imageB64 }),
    })
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to upload reference photo'))
    return res.json()
  },

  vivaProctorFrame: async (sessionId, frameB64, threshold = 0.9) => {
    const res = await fetch(`${VIVA_API}/viva/sessions/${sessionId}/proctor/frame`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ frame_b64: frameB64, threshold }),
    })
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Proctor frame check failed'))
    return res.json()
  },

  submitVivaAnswer: async (sessionId, payload) => {
    const res = await fetch(`${VIVA_API}/viva/sessions/${sessionId}/answer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to submit viva answer'))
    return res.json()
  },

  finishVivaSession: async (sessionId) => {
    const res = await fetch(`${VIVA_API}/viva/sessions/${sessionId}/finish`, { method: 'POST' })
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to finish viva session'))
    return res.json()
  },

  getVivaSession: async (sessionId) => {
    const res = await fetch(`${VIVA_API}/viva/sessions/${sessionId}`)
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch viva session'))
    return res.json()
  },

  getVivaResults: async (sessionId) => {
    const res = await fetch(`${VIVA_API}/viva/sessions/${sessionId}/results`)
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch viva results'))
    return res.json()
  },

  getVivaHistory: async (opts = {}) => {
    const params = new URLSearchParams()
    if (opts.fileId) params.set('file_id', opts.fileId)
    if (opts.status) params.set('status', opts.status)
    if (opts.limit != null) params.set('limit', String(opts.limit))
    if (opts.offset != null) params.set('offset', String(opts.offset))
    const query = params.toString()
    const res = await fetch(`${VIVA_API}/viva/history/sessions${query ? `?${query}` : ''}`)
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch viva history'))
    return res.json()
  },

  getVivaSessionAudit: async (sessionId) => {
    const res = await fetch(`${VIVA_API}/viva/sessions/${sessionId}/audit`)
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch viva audit'))
    return res.json()
  },

  getVivaMediaUrl: (sessionId, objectPath) => {
    if (!sessionId || !objectPath) return ''
    return `${VIVA_API}/viva/sessions/${sessionId}/media?object_path=${encodeURIComponent(objectPath)}`
  },
}
