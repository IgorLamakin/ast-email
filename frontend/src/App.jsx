import { Routes, Route, Navigate } from 'react-router-dom'
import { useState, useEffect, useCallback } from 'react'
import Sidebar from './components/Sidebar'
import Login from './components/Login'
import Contacts from './components/Contacts'
import Templates from './components/Templates'
import BlockEditor from './components/BlockEditor'
import EmailRender from './components/EmailRender'
import Analytics from './components/Analytics'
import Accounts from './components/Accounts'
import Settings from './components/Settings'
import Profile from './components/Profile'
import { apiFetch } from './api'

function App() {
  const [token, setToken] = useState(localStorage.getItem('token') || '')
  const [user, setUser] = useState(null)

  const handleLogin = (newToken) => {
    localStorage.setItem('token', newToken)
    setToken(newToken)
  }

  const handleLogout = useCallback(() => {
    localStorage.removeItem('token')
    setToken('')
    setUser(null)
  }, [])

  useEffect(() => {
    if (token) {
      apiFetch('/auth/me', { token })
        .then(data => setUser(data))
        .catch(() => setUser(null))
    }
  }, [token])

  // Токен может протухнуть (или стать недействительным) в любой момент работы
  // приложения. Раньше это приводило только к тихим ошибкам "не удалось..." во всех
  // разделах без объяснения причины. Теперь при любом ответе 401 от бэкенда
  // пользователя автоматически возвращает на экран входа.
  useEffect(() => {
    const onUnauthorized = () => handleLogout()
    window.addEventListener('auth:unauthorized', onUnauthorized)
    return () => window.removeEventListener('auth:unauthorized', onUnauthorized)
  }, [handleLogout])

  if (!token) {
    return <Login onLogin={handleLogin} />
  }

  const isAdmin = user?.role === 'admin'
  // Разделы "Аналитика"/"Аккаунты"/"Настройки" и на бэкенде защищены (вернут 403
  // не-администратору), но дополнительно не показываем их и на фронтенде, если
  // кто-то наберёт адрес вручную - меньше пустых экранов с ошибкой доступа.
  const AdminOnly = ({ children }) => (isAdmin ? children : <Navigate to="/send" replace />)

  return (
    <div className="min-h-screen flex bg-canvas-50">
      <Sidebar user={user} onLogout={handleLogout} />
      <main className="flex-1 min-w-0 px-8 py-7">
        <Routes>
          <Route path="/" element={<Navigate to="/send" />} />
          <Route path="/send" element={<EmailRender token={token} user={user} />} />
          <Route path="/contacts" element={<Contacts token={token} />} />
          <Route path="/templates" element={<Templates token={token} user={user} />} />
          <Route path="/templates/new" element={<BlockEditor token={token} />} />
          <Route path="/templates/edit/:id" element={<BlockEditor token={token} />} />
          <Route path="/analytics" element={<AdminOnly><Analytics token={token} /></AdminOnly>} />
          <Route path="/accounts" element={<AdminOnly><Accounts token={token} /></AdminOnly>} />
          <Route path="/settings" element={<AdminOnly><Settings token={token} /></AdminOnly>} />
          <Route path="/profile" element={<Profile token={token} user={user} onUpdateUser={setUser} />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
