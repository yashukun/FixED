import { useCallback } from 'react'
import { api } from '../services/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { ErrorBanner, SpinnerState } from '../components/feedback'
import { useAsyncResource } from '../hooks/useAsyncResource'

export default function LearnSubjectsPage() {
  const loadSubjects = useCallback(() => api.getLearnSubjects(), [])
  const { data, error } = useAsyncResource(loadSubjects)

  if (error) {
    return <ErrorBanner message={error} />
  }
  if (!data) return <SpinnerState label="Loading subjects" />

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-white">Learn • Subjects</h2>
        <p className="text-sm text-slate-400">Subjects assigned to you for this term.</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {data.subjects.map((subject) => (
          <Card key={subject.id}>
            <CardHeader>
              <CardTitle>{subject.name}</CardTitle>
              <CardDescription>{subject.teacher}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-400">Assignments</span>
                <span className="font-semibold text-white">{subject.pendingAssignments}</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-400">Progress</span>
                <Badge variant="info">{subject.progress}%</Badge>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      <p className="text-xs text-slate-500">Data source: {data.source}</p>
    </div>
  )
}
