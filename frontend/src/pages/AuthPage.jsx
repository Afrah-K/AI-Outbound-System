import { useEffect, useState } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { MegaphoneIcon, EyeIcon, EyeSlashIcon } from '@heroicons/react/24/outline'
import { api, formatErrorDetail } from '../services/apiClient'
import { useAuth } from '../context/Auth'

function GoogleLogo() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
    </svg>
  )
}

const inputClass =
  'w-full rounded-xl border border-gray-200 px-3.5 py-2.5 text-sm focus:border-primary-500 focus:ring-2 focus:ring-primary-500'

/** Sign in and sign up on one page - `mode` picks which. */
export default function AuthPage({ mode = 'login' }) {
  const isSignup = mode === 'signup'
  const { status, login, signup } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = params.get('next') || '/'

  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState(params.get('error') || '')
  const [submitting, setSubmitting] = useState(false)

  const { data: config } = useQuery({
    queryKey: ['auth-config'],
    queryFn: async () => (await api.auth.config()).data,
  })

  useEffect(() => {
    setError(params.get('error') || '')
  }, [mode, params])

  if (status === 'signed_in') return <Navigate to={next} replace />

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    if (isSignup && password.length < 8) {
      setError('Use at least 8 characters for your password')
      return
    }
    setSubmitting(true)
    try {
      if (isSignup) await signup(name, email, password)
      else await login(email, password)
      navigate(next, { replace: true })
    } catch (err) {
      setError(formatErrorDetail(err.response?.data?.detail) || 'Something went wrong - please try again')
    } finally {
      setSubmitting(false)
    }
  }

  const otherLink = `${isSignup ? '/login' : '/signup'}${next !== '/' ? `?next=${encodeURIComponent(next)}` : ''}`

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary-600 shadow-sm shadow-primary-600/30">
            <MegaphoneIcon className="h-6 w-6 text-white" />
          </div>
          <h1 className="mt-4 text-2xl font-medium tracking-tight text-gray-900">
            {isSignup ? 'Create your account' : 'Sign in to Outbound'}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            {isSignup ? 'Your own workspace for finding and emailing leads' : 'Welcome back'}
          </p>
        </div>

        <div className="rounded-card bg-white p-6 shadow-sm">
          {config?.google_enabled !== false && (
            <>
              <a
                href={api.auth.googleUrl(next)}
                className="flex w-full items-center justify-center gap-3 rounded-full border border-gray-200 px-4 py-2.5 text-sm font-medium text-gray-800 hover:bg-gray-50"
              >
                <GoogleLogo />
                Continue with Google
              </a>
              <div className="my-5 flex items-center gap-3 text-xs text-gray-400">
                <span className="h-px flex-1 bg-gray-200" />
                or with email
                <span className="h-px flex-1 bg-gray-200" />
              </div>
            </>
          )}

          <form onSubmit={submit} className="space-y-4" noValidate>
            {isSignup && (
              <div>
                <label htmlFor="name" className="mb-1 block text-sm font-medium text-gray-700">Name</label>
                <input id="name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" className={inputClass} />
              </div>
            )}
            <div>
              <label htmlFor="email" className="mb-1 block text-sm font-medium text-gray-700">Email</label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
                autoFocus
                className={inputClass}
              />
            </div>
            <div>
              <label htmlFor="password" className="mb-1 block text-sm font-medium text-gray-700">Password</label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete={isSignup ? 'new-password' : 'current-password'}
                  required
                  className={`${inputClass} pr-10`}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-700"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeSlashIcon className="h-5 w-5" /> : <EyeIcon className="h-5 w-5" />}
                </button>
              </div>
              {isSignup && <p className="mt-1 text-xs text-gray-500">At least 8 characters</p>}
            </div>

            {error && (
              <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={submitting || !email || !password}
              className="w-full rounded-full bg-primary-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm shadow-primary-600/20 hover:bg-primary-700 disabled:opacity-50"
            >
              {submitting ? (isSignup ? 'Creating account...' : 'Signing in...') : isSignup ? 'Create account' : 'Sign in'}
            </button>
          </form>
        </div>

        <p className="mt-6 text-center text-sm text-gray-500">
          {isSignup ? 'Already have an account? ' : "Don't have an account? "}
          <Link to={otherLink} className="font-medium text-primary-700 hover:underline">
            {isSignup ? 'Sign in' : 'Create one'}
          </Link>
        </p>
      </div>
    </div>
  )
}
