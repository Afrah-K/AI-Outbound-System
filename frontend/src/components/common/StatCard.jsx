import Card from './Card'

// KPI tile: blue icon chip, muted label, large number, optional caption.
export default function StatCard({ icon: Icon, label, value, caption, valueClassName = 'text-gray-900' }) {
  return (
    <Card className="flex items-start gap-4">
      {Icon && (
        <div className="h-11 w-11 shrink-0 rounded-full bg-primary-600 flex items-center justify-center shadow-sm shadow-primary-600/30">
          <Icon className="h-5 w-5 text-white" />
        </div>
      )}
      <div className="min-w-0">
        <p className="text-sm text-gray-500">{label}</p>
        <p className={`mt-1 text-3xl font-semibold tracking-tight ${valueClassName}`}>{value}</p>
        {caption && <p className="mt-2 text-xs text-gray-500">{caption}</p>}
      </div>
    </Card>
  )
}
