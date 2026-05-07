import { useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import { Button } from './ui/button'

import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()

export default function PdfViewerPane({ fileUrl, activePage, onPageChange }) {
  const [numPages, setNumPages] = useState(0)
  const pageNumber = Math.max(1, activePage || 1)
  const canGoPrev = pageNumber > 1
  const canGoNext = numPages > 0 && pageNumber < numPages

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm font-medium text-slate-300">Document Viewer</span>
        <span className="text-xs text-slate-400">
          Page {pageNumber}{numPages ? ` / ${numPages}` : ''}
        </span>
      </div>

      <div className="mb-3 flex items-center gap-2">
        <Button type="button" variant="outline" disabled={!canGoPrev} onClick={() => onPageChange?.(Math.max(1, pageNumber - 1))}>
          Prev
        </Button>
        <Button type="button" variant="outline" disabled={!canGoNext} onClick={() => onPageChange?.(numPages ? Math.min(numPages, pageNumber + 1) : pageNumber + 1)}>
          Next
        </Button>
      </div>

      <div className="flex max-h-[72vh] justify-center overflow-auto rounded-lg bg-slate-900 p-2">
        <Document
          file={fileUrl}
          loading={<div className="py-6 text-sm text-slate-400">Loading PDF...</div>}
          onLoadSuccess={({ numPages: loadedPages }) => {
            setNumPages(loadedPages)
            if (pageNumber > loadedPages) {
              onPageChange?.(loadedPages)
            }
          }}
          onLoadError={() => {
            setNumPages(0)
          }}
        >
          <Page pageNumber={pageNumber} width={520} renderTextLayer renderAnnotationLayer />
        </Document>
      </div>
    </div>
  )
}
