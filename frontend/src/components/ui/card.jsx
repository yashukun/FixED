import { cn } from '../../lib/utils'

export function Card({ className, ...props }) {
  return (
    <div
      className={cn(
        'rounded-xl border border-slate-800 bg-slate-900/65 p-5 backdrop-blur-sm',
        className,
      )}
      {...props}
    />
  )
}

export function CardHeader({ className, ...props }) {
  return <div className={cn('mb-3', className)} {...props} />
}

export function CardTitle({ className, ...props }) {
  return <h3 className={cn('text-lg font-semibold text-white', className)} {...props} />
}

export function CardDescription({ className, ...props }) {
  return <p className={cn('text-sm text-slate-400', className)} {...props} />
}

export function CardContent({ className, ...props }) {
  return <div className={cn('text-sm text-slate-200', className)} {...props} />
}
