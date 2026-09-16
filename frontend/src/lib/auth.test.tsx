import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from './auth'

function Probe() {
  const { user, loading } = useAuth()
  if (loading) return <span>loading</span>
  return <span>{user ? `signed in as ${user.username}` : 'signed out'}</span>
}

function mockFetch(handler: (path: string) => Response) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async (path: string) => handler(path)),
  )
}

const ADMIN = {
  id: '1',
  username: 'admin',
  email: 'admin@test.com',
  display_name: 'Administrator',
  is_admin: true,
  created_at: '2026-01-01T00:00:00Z',
}

afterEach(() => vi.unstubAllGlobals())

describe('AuthProvider', () => {
  it('restores an existing session from the httpOnly cookie', async () => {
    mockFetch(() => new Response(JSON.stringify(ADMIN), { status: 200 }))
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await waitFor(() => expect(screen.getByText('signed in as admin')).toBeInTheDocument())
  })

  it('treats a 401 as signed out rather than an error', async () => {
    // The token lives in a cookie the browser cannot read, so the only way to
    // know is to ask — and "no" is a normal answer, not a failure.
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    mockFetch(
      () =>
        new Response(JSON.stringify({ error: { code: 'unauthorized', message: 'Not signed in.' } }), {
          status: 401,
        }),
    )
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await waitFor(() => expect(screen.getByText('signed out')).toBeInTheDocument())
    expect(consoleError).not.toHaveBeenCalled()
    consoleError.mockRestore()
  })

  it('shows loading until the session resolves, so routes do not flash', async () => {
    let release: (r: Response) => void = () => {}
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => new Promise<Response>((resolve) => (release = resolve))),
    )
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    expect(screen.getByText('loading')).toBeInTheDocument()

    release(new Response(JSON.stringify(ADMIN), { status: 200 }))
    await waitFor(() => expect(screen.getByText('signed in as admin')).toBeInTheDocument())
  })
})
