import DocumentAssistant from '../features/assistant/DocumentAssistant'

export default function LearnAssistantPage() {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-2xl font-semibold text-slate-50">Learn • Ask From Books</h2>
        <p className="text-sm text-slate-400">Upload books and ask contextual questions.</p>
      </div>
      <DocumentAssistant />
    </div>
  )
}
