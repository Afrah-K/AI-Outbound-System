import { clsx } from 'clsx'

const variants = {
  success: 'bg-green-100 text-green-800',
  warning: 'bg-yellow-100 text-yellow-800',
  danger: 'bg-red-100 text-red-800',
  info: 'bg-primary-50 text-primary-700',
  gray: 'bg-gray-100 text-gray-800',
  purple: 'bg-indigo-50 text-indigo-700',
}

// Map status values to variants
const statusVariantMap = {
  // Lead statuses
  new: 'info',
  contacted: 'purple',
  replied: 'success',
  bounced: 'danger',
  unsubscribed: 'gray',
  converted: 'success',
  do_not_contact: 'danger',

  // Campaign statuses
  draft: 'gray',
  active: 'success',
  paused: 'warning',
  completed: 'info',
  archived: 'gray',

  // Warmup stages
  not_started: 'gray',
  stage_1: 'warning',
  stage_2: 'warning',
  stage_3: 'info',

  // Queue statuses
  pending: 'warning',
  processing: 'info',
  failed: 'danger',

  // Generic
  healthy: 'success',
  unhealthy: 'danger',
}

export default function StatusBadge({ status, variant, className }) {
  const resolvedVariant = variant || statusVariantMap[status] || 'gray'

  return (
    <span
      className={clsx(
        'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium capitalize',
        variants[resolvedVariant],
        className
      )}
    >
      {status?.replace(/_/g, ' ')}
    </span>
  )
}
