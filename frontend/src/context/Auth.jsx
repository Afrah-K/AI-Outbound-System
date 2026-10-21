import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { api, UNAUTHORIZED_EVENT } from '../services/apiClient'
import LoadingSpinner from '../components/common/LoadingSpinner'

/**
 * Who's signed in. The session itself is an HttpOnly cookie set by the API,
 * so the browser never sees the token - this just asks /auth/me.
 */

const LAST_USER_KEY = 'outbound_last_user_id'
const AuthContext = createContext(null)

// Pages cache results in localStorage; they belong to whoever was signed in
function clearCachedWorkspaceData() {
  try {
    const keep = new Set([LAST_USER_KEY])
    Object.keys(localStorage)
      .filter((key) => !keep.has(key))
      .forEach((key) => localStorage.removeItem(key))
  } catch {
    // storage disabled - nothing cached anyway
  }
}

export function AuthProvider({ children }) {
  const queryClient = useQueryClient()
  const [user, setUser] = useState(null)
  const [status, setStatus] = useState('loading') // loading | signed_in | signed_out

  // A different account than last time on this browser -> drop the old one's cached data
  const adoptUser = useCallback(
    (nextUser) => {
      try {
        const last = localStorage.getItem(LAST_USER_KEY)
        if (last && last !== String(nextUser.id)) {
          clearCachedWorkspaceData()
          queryClient.clear()
        }
        localStorage.setItem(LAST_USER_KEY, String(nextUser.id))
      } catch {
        // ignore
      }
      setUser(nextUser)
      setStatus('signed_in')
    },
    [queryClient]
  )

  useEffect(() => {
    api.auth
      .me()
      .then((response) => adoptUser(response.data.user))
      .catch(() => setStatus('signed_out'))
  }, [adoptUser])

  // Any API call answering 401 (session expired, signed out elsewhere) -> back to sign-in
  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null)
      setStatus('signed_out')
    }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [])

  const login = useCallback(
    async (email, password) => adoptUser((await api.auth.login(email, password)).data.user),
    [adoptUser]
  )
  const signup = useCallback(
    async (name, email, password) => adoptUser((await api.auth.signup(name, email, password)).data.user),
    [adoptUser]
  )
  const logout = useCallback(async () => {
    try {
      await api.auth.logout()
    } finally {
      clearCachedWorkspaceData()
      queryClient.clear()
      setUser(null)
      setStatus('signed_out')
    }
  }, [queryClient])

  const value = useMemo(() => ({ user, status, login, signup, logout }), [user, status, login, signup, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}

/** Renders its children only when signed in; otherwise sends you to /login and back afterwards. */
export function RequireAuth({ children }) {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return (
      <div className="flex h-screen items-center justify-center bg-canvas">
        <LoadingSpinner size="lg" />
      </div>
    )
  }
  if (status === 'signed_out') {
    const next = location.pathname + location.search
    return <Navigate to={`/login${next && next !== '/' ? `?next=${encodeURIComponent(next)}` : ''}`} replace />
  }
  return children
}
