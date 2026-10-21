import { clsx } from 'clsx'

export default function Card({ children, className, padding = true, ...props }) {
  return (
    <div
      className={clsx(
        'bg-white rounded-card',
        padding && 'p-6',
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}

Card.Header = function CardHeader({ children, className }) {
  return (
    <div className={clsx('mb-4', className)}>
      {children}
    </div>
  )
}

Card.Title = function CardTitle({ children, className }) {
  return (
    <h3 className={clsx('text-lg font-medium tracking-tight text-gray-900', className)}>
      {children}
    </h3>
  )
}

Card.Description = function CardDescription({ children, className }) {
  return (
    <p className={clsx('mt-1 text-sm text-gray-500', className)}>
      {children}
    </p>
  )
}
