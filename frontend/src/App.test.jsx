import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi, describe, it, expect, afterEach } from 'vitest'
import App from './App'
import { CostProvider } from './context/CostContext'

function mockFetch(payloadByUrl) {
  globalThis.fetch = vi.fn((url) => {
    const body = payloadByUrl[url]
    if (!body) {
      return Promise.resolve({
        ok: false,
        json: async () => ({ detail: `No mock for ${url}` }),
        text: async () => `No mock for ${url}`,
      })
    }
    return Promise.resolve({
      ok: true,
      json: async () => body,
      text: async () => JSON.stringify(body),
    })
  })
}

function renderWithProviders(initialEntries) {
  return render(
    <CostProvider>
      <MemoryRouter initialEntries={initialEntries}>
        <App />
      </MemoryRouter>
    </CostProvider>,
  )
}

describe('LMS routes', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders dashboard route with overview data', async () => {
    mockFetch({
      '/api/gateway/dashboard/nav': {
        source: 'live',
        student: { id: 'global', name: 'Global Workspace', grade: 'All Features' },
        sections: [{ name: 'Dashboard', path: '/' }],
      },
      '/api/gateway/dashboard/overview': {
        source: 'live',
        metrics: [{ label: 'Assigned Subjects', value: 5 }],
        todayFocus: [{ title: 'Physics recap', time: '4:00 PM', type: 'study' }],
      },
      '/api/gateway/dashboard/analytics/summary': {
        source: 'live',
        total_cost_usd: 0.04,
        total_prompt_tokens: 100,
        total_completion_tokens: 40,
        total_tokens: 140,
        usage_volume: { searches: 2, generated_papers: 1, uploads: 3, viva_sessions: 1 },
      },
      '/api/gateway/dashboard/analytics/timeseries': {
        source: 'live',
        points: [{ bucket: '2026-05-21', cost_usd: 0.04, prompt_tokens: 100, completion_tokens: 40, total_tokens: 140, requests: 3 }],
      },
      '/api/gateway/dashboard/analytics/breakdown': {
        source: 'live',
        by_service: [{ key: 'search', cost_usd: 0.03, total_tokens: 100, requests: 2 }],
        by_model: [{ key: 'gpt-4o-mini', cost_usd: 0.03, total_tokens: 100, requests: 2 }],
        by_kind: [{ key: 'chat', cost_usd: 0.03, total_tokens: 100, requests: 2 }],
      },
    })

    renderWithProviders(['/'])

    expect(await screen.findByText('Dashboard')).toBeInTheDocument()
    expect(await screen.findByText('Assigned Subjects')).toBeInTheDocument()
  })

  it('renders books page and shows global books', async () => {
    mockFetch({
      '/api/gateway/dashboard/nav': {
        source: 'live',
        student: { id: 'global', name: 'Global Workspace', grade: 'All Features' },
        sections: [{ name: 'Learn / Books', path: '/learn/books' }],
      },
      '/api/gateway/learn/books': {
        source: 'live',
        books: [
          { id: '1', title: 'Class 10 Physics Essentials', subject: 'Physics', status: 'ready', lastOpened: '2026-05-06' },
        ],
      },
    })

    renderWithProviders(['/learn/books'])

    await waitFor(() => {
      expect(screen.getByText('Learn • Books')).toBeInTheDocument()
    })
    expect(screen.getByText('Class 10 Physics Essentials')).toBeInTheDocument()
  })

  it('renders viva setup page', async () => {
    mockFetch({
      '/api/gateway/dashboard/nav': {
        source: 'live',
        student: { id: 'global', name: 'Global Workspace', grade: 'All Features' },
        sections: [{ name: 'Mock Interview / Viva', path: '/viva' }],
      },
      '/api/ingest/jobs': [
        {
          id: 'job-1',
          filename: 'biology.pdf',
          status: 'completed',
        },
      ],
    })

    renderWithProviders(['/viva'])

    await waitFor(() => {
      expect(screen.getByText('Viva (Oral Examination)')).toBeInTheDocument()
    })
    expect(screen.getByText('Pre-Session Setup')).toBeInTheDocument()
  })
})
