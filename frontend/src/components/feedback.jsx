export function ErrorBanner({ message }) {
  if (!message) {
    return null
  }

  return (
    <p className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
      {message}
    </p>
  )
}

export function SpinnerState({ label }) {
  return <div className="spinner" aria-label={label} />
}
