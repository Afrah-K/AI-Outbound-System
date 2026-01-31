import { NavLink } from 'react-router-dom'
import {
  HomeIcon,
  InboxIcon,
  FireIcon,
  UserGroupIcon,
  MegaphoneIcon,
  QueueListIcon,
  ChartBarIcon,
} from '@heroicons/react/24/outline'
import { clsx } from 'clsx'

const navigation = [
  { name: 'Dashboard', href: '/dashboard', icon: HomeIcon },
  { name: 'Inboxes', href: '/inboxes', icon: InboxIcon },
  { name: 'Warmup', href: '/warmup', icon: FireIcon },
  { name: 'Leads', href: '/leads', icon: UserGroupIcon },
  { name: 'Campaigns', href: '/campaigns', icon: MegaphoneIcon },
  { name: 'Sequences', href: '/sequences', icon: QueueListIcon },
  { name: 'Analytics', href: '/analytics', icon: ChartBarIcon },
]

export default function Sidebar() {
  return (
    <div className="flex h-full w-64 flex-col bg-gray-900">
      {/* Logo */}
      <div className="flex h-16 shrink-0 items-center px-6">
        <div className="flex items-center gap-2">
          <div className="h-8 w-8 rounded-lg bg-primary-500 flex items-center justify-center">
            <MegaphoneIcon className="h-5 w-5 text-white" />
          </div>
          <span className="text-lg font-semibold text-white">Outbound</span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 px-3 py-4">
        {navigation.map((item) => (
          <NavLink
            key={item.name}
            to={item.href}
            className={({ isActive }) =>
              clsx(
                'group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-gray-800 text-white'
                  : 'text-gray-400 hover:bg-gray-800 hover:text-white'
              )
            }
          >
            <item.icon className="h-5 w-5 shrink-0" />
            {item.name}
          </NavLink>
        ))}
      </nav>

      {/* System Status */}
      <div className="border-t border-gray-800 p-4">
        <div className="rounded-lg bg-gray-800 p-3">
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 rounded-full bg-green-500"></div>
            <span className="text-xs font-medium text-gray-300">System Online</span>
          </div>
          <p className="mt-1 text-xs text-gray-500">All services running</p>
        </div>
      </div>
    </div>
  )
}
