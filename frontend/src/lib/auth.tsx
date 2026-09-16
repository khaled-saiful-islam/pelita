/**
 * Session state.
 *
 * The token lives in an httpOnly cookie the browser cannot read, so "am I
 * signed in?" is answered by asking the API, not by inspecting storage. That is
 * one request on load, and it is the price of the token being unreadable to
 * injected script.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { ApiError, apiFetch } from './api'

export interface User {
  id: string
  username: string
  email: string
  display_name: string | null
  is_admin: boolean
  created_at: string
}

interface AuthState {
  user: User | null
  /** True until the first /auth/me resolves, so routes do not flash. */
  loading: boolean
  signIn: (identifier: string, password: string) => Promise<void>
  signUp: (username: string, email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
  updateUser: (user: User) => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    apiFetch<User>('/auth/me')
      .then(setUser)
      .catch((error: unknown) => {
        // A 401 here is the normal "not signed in" case, not a failure.
        if (!(error instanceof ApiError) || error.status !== 401) {
          console.error('Could not restore session', error)
        }
        setUser(null)
      })
      .finally(() => setLoading(false))
  }, [])

  const signIn = useCallback(async (identifier: string, password: string) => {
    setUser(
      await apiFetch<User>('/auth/signin', {
        method: 'POST',
        body: JSON.stringify({ identifier, password }),
      }),
    )
  }, [])

  const signUp = useCallback(async (username: string, email: string, password: string) => {
    setUser(
      await apiFetch<User>('/auth/signup', {
        method: 'POST',
        body: JSON.stringify({ username, email, password }),
      }),
    )
  }, [])

  const signOut = useCallback(async () => {
    try {
      await apiFetch<void>('/auth/signout', { method: 'POST' })
    } finally {
      // Whatever the server said, this browser is signed out.
      setUser(null)
    }
  }, [])

  const value = useMemo(
    () => ({ user, loading, signIn, signUp, signOut, updateUser: setUser }),
    [user, loading, signIn, signUp, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}
