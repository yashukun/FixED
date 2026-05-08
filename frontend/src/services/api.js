const GATEWAY_API = import.meta.env.VITE_GATEWAY_API || '/api/gateway'
const INGEST_API = import.meta.env.VITE_INGEST_API || '/api/ingest'
const SEARCH_API = import.meta.env.VITE_SEARCH_API || '/api/search'

const parseJsonSafe = async (res) => {
  try {
    return await res.json()
  } catch {
    return null
  }
}

const getErrorMessage = async (res, fallback) => {
  const json = await parseJsonSafe(res)
  if (json?.detail) return json.detail
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
  getDashboardOverview: async () => {
    const res = await fetch(`${GATEWAY_API}/dashboard/overview`)
    if (!res.ok) throw new Error(await getErrorMessage(res, 'Failed to fetch dashboard overview'))
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
      file_id: fileId,
      top_k: opts.topK ?? 5,
      active_page: opts.activePage ?? null,
      chapter_number: opts.chapterNumber ?? null,
    };
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
      file_id: fileId,
      top_k: opts.topK ?? 5,
      active_page: opts.activePage ?? null,
      chapter_number: opts.chapterNumber ?? null,
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
}
