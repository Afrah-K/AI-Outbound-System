import { clsx } from 'clsx'

export default function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}) {
  return (
    <div className={clsx('text-center py-12', className)}>
      {Icon && (
        <div className="mx-auto h-14 w-14 rounded-full bg-primary-50 flex items-center justify-center">
          <Icon className="h-7 w-7 text-primary-600" />
        </div>
      )}
      <h3 className="mt-4 text-lg font-medium tracking-tight text-gray-900">{title}</h3>
      {description && (
        <p className="mt-2 text-sm text-gray-500">{description}</p>
      )}
      {action && (
        <div className="mt-6">{action}</div>
      )}
    </div>
  )
}
