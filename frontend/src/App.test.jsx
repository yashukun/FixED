import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi, describe, it, expect, afterEach } from 'vitest'
import App from './App'

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

describe('LMS routes', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders dashboard route with overview data', async () => {
    mockFetch({
      '/api/gateway/dashboard/overview': {
        source: 'mock',
        metrics: [{ label: 'Assigned Subjects', value: 5 }],
        todayFocus: [{ title: 'Physics recap', time: '4:00 PM', type: 'study' }],
      },
    })

    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Student Dashboard')).toBeInTheDocument()
    expect(await screen.findByText('Assigned Subjects')).toBeInTheDocument()
  })

  it('renders books page and shows teacher books', async () => {
    mockFetch({
      '/api/gateway/learn/books': {
        source: 'mock',
        teacherUploaded: [
          { id: '1', title: 'Class 10 Physics Essentials', subject: 'Physics', status: 'ready', lastOpened: '2026-05-06' },
        ],
        studentUploaded: [],
      },
    })

    render(
      <MemoryRouter initialEntries={['/learn/books']}>
        <App />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('Learn • Books')).toBeInTheDocument()
    })
    expect(screen.getByText('Class 10 Physics Essentials')).toBeInTheDocument()
  })
})
