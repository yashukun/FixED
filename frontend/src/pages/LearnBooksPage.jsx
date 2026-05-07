import { useEffect, useState } from 'react'
import { api } from '../services/api'
import { Badge } from '../components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'

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
            <Badge variant={book.status === 'ready' ? 'success' : 'warning'}>{book.status}</Badge>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

export default function LearnBooksPage() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let mounted = true
    const load = async () => {
      try {
        const payload = await api.getLearnBooks()
        if (mounted) setData(payload)
      } catch (err) {
        if (mounted) setError(err.message)
      }
    }
    load()
    return () => {
      mounted = false
    }
  }, [])

  if (error) {
    return <p className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</p>
  }
  if (!data) return <div className="spinner" aria-label="Loading books" />

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-white">Learn • Books</h2>
        <p className="text-sm text-slate-400">Your learning books, including teacher-shared and personal uploads.</p>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <BookList title="Teacher Uploaded" books={data.teacherUploaded} />
        <BookList title="My Uploads" books={data.studentUploaded} />
      </div>
      <p className="text-xs text-slate-500">Data source: {data.source}</p>
    </div>
  )
}
