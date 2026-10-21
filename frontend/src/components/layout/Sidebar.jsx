import { NavLink } from 'react-router-dom'
import { ArrowRightOnRectangleIcon } from '@heroicons/react/24/outline'
import { useAuth } from '../../context/Auth'
import {
  InboxIcon,
  FireIcon,
  UserGroupIcon,
  MegaphoneIcon,
  QueueListIcon,
  ChartBarIcon,
  MagnifyingGlassCircleIcon,
  GlobeAltIcon,
  ShieldCheckIcon,
  InboxStackIcon,
  SparklesIcon,
  PhoneIcon,
  CalendarDaysIcon,
  RocketLaunchIcon,
} from '@heroicons/react/24/outline'
import { clsx } from 'clsx'

const navigation = [
  { name: 'Start here', href: '/start', icon: RocketLaunchIcon },
  { name: 'Lead Box', href: '/leadbox', icon: InboxStackIcon },
  { name: 'Inboxes', href: '/inboxes', icon: InboxIcon },
  { name: 'Warmup', href: '/warmup', icon: FireIcon },
  { name: 'Prospects', href: '/prospects', icon: UserGroupIcon },
  { name: 'Scrapers', href: '/scrapers', icon: GlobeAltIcon },
  { name: 'Enricher', href: '/enricher', icon: MagnifyingGlassCircleIcon },
  { name: 'Verifier', href: '/verifier', icon: ShieldCheckIcon },
  { name: 'Personalizer', href: '/personalizer', icon: SparklesIcon },
  { name: 'Campaigns', href: '/campaigns', icon: MegaphoneIcon },
  { name: 'Sequences', href: '/sequences', icon: QueueListIcon },
  { name: 'Analytics', href: '/analytics', icon: ChartBarIcon },
  { name: 'Book a Call', href: '/booking', icon: PhoneIcon },
  { name: 'Calendar', href: '/calendar', icon: CalendarDaysIcon },
]

function initials(user) {
  const source = user.name || user.email
  return source
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join('')
}

export default function Sidebar() {
  const { user, logout } = useAuth()
  return (
    <div className="flex h-full w-64 flex-col bg-white border-r border-gray-100">
      {/* Logo */}
      <div className="flex h-20 shrink-0 items-center px-6">
        <div className="flex items-center gap-2.5">
          <div className="h-9 w-9 rounded-full bg-primary-600 flex items-center justify-center shadow-sm shadow-primary-600/30">
            <MegaphoneIcon className="h-5 w-5 text-white" />
          </div>
          <span className="text-xl font-semibold tracking-tight text-gray-900">Outbound</span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 overflow-y-auto px-4 py-2">
        {navigation.map((item) => (
          <NavLink
            key={item.name}
            to={item.href}
            className={({ isActive }) =>
              clsx(
                'group flex items-center gap-3 rounded-full px-4 py-2.5 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-primary-600 text-white shadow-sm shadow-primary-600/25'
                  : 'text-gray-500 hover:bg-gray-100 hover:text-gray-900'
              )
            }
          >
            <item.icon className="h-5 w-5 shrink-0" />
            {item.name}
          </NavLink>
        ))}
      </nav>

      {/* Signed-in account */}
      {user && (
        <div className="p-4">
          <div className="flex items-center gap-3 rounded-2xl bg-canvas p-3">
            {user.avatar_url ? (
              <img src={user.avatar_url} alt="" referrerPolicy="no-referrer" className="h-9 w-9 shrink-0 rounded-full" />
            ) : (
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary-100 text-xs font-semibold text-primary-700">
                {initials(user)}
              </div>
            )}
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-gray-900">{user.name || user.email}</p>
              <p className="truncate text-xs text-gray-500" title={user.email}>{user.email}</p>
            </div>
            <button
              type="button"
              onClick={logout}
              title="Sign out"
              aria-label="Sign out"
              className="rounded-full p-1.5 text-gray-400 hover:bg-white hover:text-gray-700"
            >
              <ArrowRightOnRectangleIcon className="h-5 w-5" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
