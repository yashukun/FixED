import { cn } from '../../lib/utils'

const variants = {
  default:
    'bg-blue-500 text-white hover:bg-blue-600 focus-visible:ring-2 focus-visible:ring-blue-400',
  ghost: 'bg-transparent text-slate-200 hover:bg-slate-800/70',
  outline:
    'border border-slate-700 bg-slate-900/50 text-slate-200 hover:border-slate-500 hover:bg-slate-800/70',
}

export function Button({ className, variant = 'default', type = 'button', ...props }) {
  return (
    <button
      type={type}
      className={cn(
        'inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-medium transition focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50',
        variants[variant],
        className,
      )}
      {...props}
    />
  )
}
