import { useCallback } from 'react'
import { api } from '../services/api'
import { Badge } from '../components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { ErrorBanner, SpinnerState } from '../components/feedback'
import { useAsyncResource } from '../hooks/useAsyncResource'
import { isCompletedStatus } from '../lib/status'

function BookList({ title, books }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{books.length} books</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {books.map((book) => (
          <div key={book.id} className="flex items-center justify-between rounded-lg border border-slate-800 p-3">
            <div>
              <p className="font-medium text-white">{book.title}</p>
              <p className="text-xs text-slate-400">{book.subject} • {book.lastOpened}</p>
            </div>
            <Badge variant={isCompletedStatus(book.status) ? 'success' : 'warning'}>{book.status}</Badge>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

export default function LearnBooksPage() {
  const loadBooks = useCallback(() => api.getLearnBooks(), [])
  const { data, error } = useAsyncResource(loadBooks)

  if (error) {
    return <ErrorBanner message={error} />
  }
  if (!data) return <SpinnerState label="Loading books" />

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-white">Learn • Books</h2>
        <p className="text-sm text-slate-400">All uploaded books are globally accessible in this workspace.</p>
      </div>
      <BookList title="All Uploaded Books" books={data.books || []} />
      <p className="text-xs text-slate-500">Live library data from processed uploads.</p>
    </div>
  )
}
