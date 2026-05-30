import { useId, useState } from 'react'

const shortNum = (v) => {
  if (v >= 1000) return `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}k`
  return String(Math.round(v))
}

/* ---------- Sparkline ---------- */
export function Sparkline({ data, color }) {
  const gid = useId().replace(/:/g, '')
  if (!Array.isArray(data) || data.length < 2) {
    return <svg className="spark" viewBox="0 0 220 38" preserveAspectRatio="none" />
  }
  const w = 220, h = 38, n = data.length
  const mn = Math.min(...data), mx = Math.max(...data)
  const rng = mx - mn || 1
  const pts = data.map((v, i) => [(i / (n - 1)) * w, h - 4 - ((v - mn) / rng) * (h - 8)])
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ')
  const area = `${line} L${w} ${h} L0 ${h} Z`
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.28" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gid})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/* ---------- Main trend chart (interactive) ---------- */
export function TrendChart({ data, dates, color, label, fmt = (n) => n.toLocaleString('en-US') }) {
  const [hover, setHover] = useState(null)
  const gid = useId().replace(/:/g, '')

  if (!Array.isArray(data) || data.length < 2) {
    return <div className="chart-empty">No analytics events recorded yet.</div>
  }

  const W = 860, H = 300, padL = 52, padR = 16, padT = 16, padB = 34
  const iw = W - padL - padR, ih = H - padT - padB
  const mx = Math.max(...data) * 1.12 || 1, mn = 0
  const x = (i) => padL + (i / (data.length - 1)) * iw
  const y = (v) => padT + ih - ((v - mn) / (mx - mn || 1)) * ih

  const ticks = 4
  const gridLines = []
  for (let t = 0; t <= ticks; t++) {
    const gy = padT + (ih / ticks) * t
    const gv = mx - (mx / ticks) * t
    gridLines.push({ gy, gv })
  }
  const step = Math.max(1, Math.round(data.length / 6))
  const xLabels = []
  for (let i = 0; i < data.length; i += step) xLabels.push(i)

  const pts = data.map((v, i) => [x(i), y(v)])
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ')
  const area = `${line} L${x(data.length - 1).toFixed(1)} ${padT + ih} L${padL} ${padT + ih} Z`

  return (
    <div className="chart-wrap">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={color} stopOpacity="0.30" />
            <stop offset="1" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        <style>{`.ax{fill:var(--faint);font-size:11px;font-family:var(--mono)}`}</style>
        {gridLines.map(({ gy }, i) => (
          <line key={`g${i}`} x1={padL} y1={gy.toFixed(1)} x2={W - padR} y2={gy.toFixed(1)} stroke="var(--border)" />
        ))}
        {gridLines.map(({ gy, gv }, i) => (
          <text key={`yl${i}`} x={padL - 10} y={(gy + 4).toFixed(1)} textAnchor="end" className="ax">{shortNum(gv)}</text>
        ))}
        {xLabels.map((i) => (
          <text key={`xl${i}`} x={x(i).toFixed(1)} y={H - 10} textAnchor="middle" className="ax">
            {dates[i].toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
          </text>
        ))}
        <path d={area} fill={`url(#${gid})`} />
        <path d={line} fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        {hover != null && (
          <line x1={pts[hover][0]} y1={padT} x2={pts[hover][0]} y2={padT + ih} stroke={color} strokeOpacity="0.4" strokeDasharray="3 4" />
        )}
        {hover != null && (
          <circle cx={pts[hover][0]} cy={pts[hover][1]} r="4" fill={color} stroke="var(--bg)" strokeWidth="2" />
        )}
        {pts.map((p, i) => (
          <rect
            key={`hot${i}`}
            x={(x(i) - iw / data.length / 2).toFixed(1)}
            y={padT}
            width={(iw / data.length).toFixed(1)}
            height={ih}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}
      </svg>
      {hover != null && (
        <div
          className="tip"
          style={{ left: `${(pts[hover][0] / W) * 100}%`, top: `${(pts[hover][1] / H) * 100}%`, opacity: 1 }}
        >
          <div className="tip-d">{dates[hover].toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}</div>
          <div className="tip-r"><i style={{ background: color }} />{label}: <b>{fmt(data[hover])}</b></div>
        </div>
      )}
    </div>
  )
}

/* ---------- Donut ---------- */
export function Donut({ segments, centerBig, centerSm }) {
  const total = segments.reduce((a, b) => a + b.val, 0)
  if (!total) {
    return <div className="chart-empty" style={{ height: 140 }}>No data yet.</div>
  }
  const r = 58, cx = 70, cy = 70, c = 2 * Math.PI * r
  const lens = segments.map((s) => (s.val / total) * c)
  const offsets = lens.map((_, i) => lens.slice(0, i).reduce((a, b) => a + b, 0))
  const arcs = segments.map((s, i) => (
    <circle
      key={i}
      cx={cx} cy={cy} r={r} fill="none" stroke={s.color} strokeWidth="16"
      strokeDasharray={`${lens[i].toFixed(2)} ${(c - lens[i]).toFixed(2)}`}
      strokeDashoffset={(-offsets[i]).toFixed(2)}
      transform={`rotate(-90 ${cx} ${cy})`}
    />
  ))
  return (
    <div className="donut-wrap" style={{ marginTop: 14 }}>
      <div className="ring-c" style={{ width: 140, height: 140, position: 'relative' }}>
        <svg viewBox="0 0 140 140" style={{ width: 140, height: 140 }}>
          <circle cx={cx} cy={cy} r={r} fill="none" stroke="oklch(1 0 0 / 0.05)" strokeWidth="16" />
          {arcs}
        </svg>
        <div className="donut-center"><div><div className="big">{centerBig}</div><div className="sm">{centerSm}</div></div></div>
      </div>
      <div className="donut-legend">
        {segments.map((s, i) => (
          <div className="dl-row" key={i}>
            <i style={{ background: s.color }} />
            <span className="nm">{s.nm}</span>
            <span className="vl">{Math.round((s.val / total) * 100)}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ---------- Feature usage bars ---------- */
export function FeatureBars({ items }) {
  const mx = Math.max(1, ...items.map((s) => s.val))
  return (
    <div className="bars" style={{ marginTop: 18 }}>
      {items.map((s, i) => (
        <div className="bar-row" key={i}>
          <div className="bl"><span className="nm">{s.nm}</span><span className="vl">{s.val.toLocaleString('en-US')}</span></div>
          <div className="track"><div className="fill" style={{ width: `${(s.val / mx) * 100}%`, background: s.color }} /></div>
        </div>
      ))}
    </div>
  )
}
