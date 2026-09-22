import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Spinner } from '@/components/ui'
import { AuthProvider, useAuth } from '@/lib/auth'
import { ThemeProvider } from '@/lib/theme'
import Chat from '@/pages/Chat'
import Profile from '@/pages/Profile'
import Admin from '@/pages/Admin'
import Shared from '@/pages/Shared'
import SharedArtifact from '@/pages/SharedArtifact'
import Settings from '@/pages/Settings'
import SignIn from '@/pages/SignIn'

export default function App() {
  return (
    <BrowserRouter>
      <ThemeProvider>
      <AuthProvider>
        <Routes>
          <Route path="/signin" element={<PublicOnly><SignIn /></PublicOnly>} />
          {/* Deliberately outside Protected: needing an account to read a
              shared link would defeat the entire feature. */}
          <Route path="/s/:token" element={<Shared />} />
          <Route path="/a/:token" element={<SharedArtifact />} />
          <Route path="/" element={<Protected><Chat /></Protected>} />
          <Route path="/c/:conversationId" element={<Protected><Chat /></Protected>} />
          <Route path="/profile" element={<Protected><Profile /></Protected>} />
          <Route path="/settings" element={<Protected><Settings /></Protected>} />
          <Route path="/admin" element={<Protected><Admin /></Protected>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
      </ThemeProvider>
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
