// Inline icon set ported from the new dashboard mockup (dashboard.js / HTML).
// Usage: <Icon name="search" /> — stroked by default, filled when fill is true.

const PATHS = {
  grid: <path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z" />,
  book: <path d="M4 5a2 2 0 0 1 2-2h11a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1H6a2 2 0 0 1-2-2zM8 3v18" />,
  layers: <path d="m12 3 9 5-9 5-9-5zM3 13l9 5 9-5" />,
  mic: <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></>,
  doc: <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h6" />,
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>,
  up: <path d="M7 14l5-5 5 5" />,
  down: <path d="M7 10l5 5 5-5" />,
  bolt: <path d="M13 2 4 14h6l-1 8 9-12h-6z" />,
  cam: <path d="M3 7a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM15 10l6-3v10l-6-3" />,
  upload: <path d="M12 16V4M7 9l5-5 5 5M5 20h14" />,
  play: <path d="M8 5v14l11-7z" />,
  calendar: <><rect x="3" y="4" width="18" height="17" rx="2" /><path d="M3 9h18M8 2v4M16 2v4" /></>,
}

export default function Icon({ name, fill = false, className }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill={fill ? 'currentColor' : 'none'}
      stroke={fill ? 'none' : 'currentColor'}
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      {PATHS[name] || null}
    </svg>
  )
}
