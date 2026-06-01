import { cn } from '../../lib/utils'

const variants = {
  default: 'bg-slate-800 text-slate-200',
  success: 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-300',
  warning: 'bg-amber-500/20 text-amber-700 dark:text-amber-300',
  danger: 'bg-rose-500/20 text-rose-300',
  info: 'bg-blue-500/20 text-blue-700 dark:text-blue-300',
}

export function Badge({ className, variant = 'default', ...props }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium',
        variants[variant],
        className,
      )}
      {...props}
    />
  )
}
