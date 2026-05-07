import { useState } from 'react'
import { Button } from './ui/button'
import { Input } from './ui/input'

export default function SearchInterface({
  onSearch,
  onQueryChange,
}) {
  const [query, setQuery] = useState('')
  const [isSearching, setIsSearching] = useState(false)

  const handleSearch = async (e) => {
    e.preventDefault()
    if (!query.trim()) return
    setIsSearching(true)
    onQueryChange?.(query)
    try {
      await onSearch?.(query)
    } finally {
      setIsSearching(false)
    }
  }

  return (
    <div className="w-full max-w-3xl">
      <form onSubmit={handleSearch} className="flex gap-3">
        <Input
          type="text"
          placeholder="Ask a question or search within the book..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={isSearching}
          className="h-11"
        />
        <Button type="submit" className="h-11 min-w-24" disabled={isSearching}>
          {isSearching ? 'Searching' : 'Search'}
        </Button>
      </form>
    </div>
  )
}
