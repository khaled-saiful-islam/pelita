import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Spinner } from '@/components/ui'
import { AuthProvider, useAuth } from '@/lib/auth'
import Chat from '@/pages/Chat'
import Profile from '@/pages/Profile'
import SignIn from '@/pages/SignIn'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/signin" element={<PublicOnly><SignIn /></PublicOnly>} />
          <Route path="/" element={<Protected><Chat /></Protected>} />
          <Route path="/c/:conversationId" element={<Protected><Chat /></Protected>} />
          <Route path="/profile" element={<Protected><Profile /></Protected>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}

/** Blocks render until the session is known, so routes do not flash. */
function Gate({ children }: { children: React.ReactNode }) {
  const { loading } = useAuth()
  if (loading) {
    return (
      <div className="grid min-h-dvh place-items-center">
        <Spinner className="size-6" />
      </div>
    )
  }
  return <>{children}</>
}

function Protected({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) return <Gate>{children}</Gate>
  if (!user) {
    // Remember where they were headed so sign-in can send them back.
    return <Navigate to="/signin" replace state={{ from: location.pathname }} />
  }
  return <>{children}</>
}

function PublicOnly({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <Gate>{children}</Gate>
  if (user) return <Navigate to="/" replace />
  return <>{children}</>
}
