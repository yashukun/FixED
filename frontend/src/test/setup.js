import '@testing-library/jest-dom'
import { vi } from 'vitest'

vi.mock('react-pdf', () => ({
  Document: ({ children }) => children,
  Page: () => null,
  pdfjs: { GlobalWorkerOptions: { workerSrc: '' } },
}))
