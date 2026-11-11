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
import Campaigns from './components/Campaigns'
import CampaignWizard from './components/CampaignWizard'
import CampaignProgress from './components/CampaignProgress'
import { apiFetch, setSessionFromResponse, getSession, logoutSession } from './api'
import { loadSession, clearSession } from './utils/authStorage'

function App() {
  // Сессия - пара access+refresh из localStorage ('auth', см. utils/authStorage.js).
  // Инициализируем её синхронно при первом рендере: если пользователь входил
  // раньше и refresh-токен ещё жив (180 дней), экран входа показывать не нужно.
  // Раньше здесь читался только одиночный 'token' на 12 часов - после его
  // протухания приложение встречало пользователя логином, хотя бэкенд умеет
  // молча обновлять пару.
  const [session, setSession] = useState(() => loadSession())
  const [user, setUser] = useState(null)
  // Возможности массовых рассылок: GET /campaigns/capabilities.
  // null = запрос ещё в пути, {allowed:false} = раздела нет/нет прав.
  // Трёхсостояние нужно, чтобы при обновлении страницы на /campaigns не
  // выкинуть пользователя на /send до получения ответа.
  const [campaignCapabilities, setCampaignCapabilities] = useState(null)

  const token = (session && session.accessToken) || ''

  // Вход: бэкенд отдаёт весь ответ {"access_token","refresh_token",...}.
  // setSessionFromResponse обновляет и модульное состояние api.js (чтобы
  // прозрачное обновление работало сразу), и localStorage.
  const handleLogin = useCallback((data) => {
    setSession(setSessionFromResponse(data) || loadSession())
  }, [])

  // Выход по кнопке (это НЕ выход по 401): сначала best-effort отзываем
  // refresh-токен на бэкенде, затем чистим локальную сессию и состояние.
  // logoutSession() ошибок не пробрасывает (сервер может быть недоступен -
  // выйти всё равно надо), clearSession() - страховка от рассинхронизации.
  const handleLogout = useCallback(async () => {
    await logoutSession()
    clearSession()
    setSession(null)
    setUser(null)
  }, [])

  // api.js при 401 сам обновляет пару и повторяет запрос, а нам присылает:
  //  - 'auth:refreshed'    -> подставляем новый access-токен в состояние,
  //                           чтобы дочерние компоненты ходили в API с ним;
  //  - 'auth:unauthorized' -> сессию обновить не удалось (refresh протух,
  //                           отозван или пользователь удалён) - разлогиниваем.
  // Подписку намеренно объявляем ДО эффекта с /auth/me: события от первых
  // же запросов уже должны обрабатываться.
  useEffect(() => {
    const onRefreshed = () => setSession(getSession())
    const onUnauthorized = () => {
      clearSession()
      setSession(null)
      setUser(null)
    }
    window.addEventListener('auth:refreshed', onRefreshed)
    window.addEventListener('auth:unauthorized', onUnauthorized)
    return () => {
      window.removeEventListener('auth:refreshed', onRefreshed)
      window.removeEventListener('auth:unauthorized', onUnauthorized)
    }
  }, [])

  useEffect(() => {
    if (!token) {
      setUser(null)
      return
    }
    // Флаг нужен, чтобы ответ устаревшего запроса не перезаписал user после
    // смены токена (например, сразу после обновления пары).
    let cancelled = false
    apiFetch('/auth/me', { token })
      .then(data => {
        if (!cancelled) setUser(data)
      })
      .catch(() => {
        if (!cancelled) setUser(null)
      })
    return () => {
      cancelled = true
    }
  }, [token])

  // Отдельный запрос (а не /auth/me): право на рассылки зависит и от роли, и
  // от настроек администратора, и меняется без перелогина. 404/403 — штатная
  // ситуация, если backend ещё без раздела рассылок или рассылки запрещены:
  // просто не показываем раздел, а не ломаем приложение.
  useEffect(() => {
    if (!token) {
      setCampaignCapabilities(null)
      return
    }
    let cancelled = false
    setCampaignCapabilities(null)
    apiFetch('/campaigns/capabilities', { token })
      .then(data => {
        if (!cancelled) setCampaignCapabilities({ ...(data || {}), allowed: Boolean(data && data.allowed) })
      })
      .catch(() => {
        if (!cancelled) setCampaignCapabilities({ allowed: false })
      })
    return () => { cancelled = true }
  }, [token])

  if (!token) {
    return <Login onLogin={handleLogin} />
  }

  const isAdmin = user?.role === 'admin'
  // Разделы "Аналитика"/"Аккаунты"/"Настройки" и на бэкенде защищены (вернут 403
  // не-администратору), но дополнительно не показываем их и на фронтенде, если
  // кто-то наберёт адрес вручную - меньше пустых экранов с ошибкой доступа.
  const AdminOnly = ({ children }) => (isAdmin ? children : <Navigate to="/send" replace />)

  // Доступ к разделу «Рассылки»: пока capabilities не пришли — ждём (иначе
  // можно несправедливо редиректить), после — либо экран, либо /send.
  const CampaignsOnly = ({ children }) => {
    if (campaignCapabilities === null) {
      return <div className="text-sm text-ink-500">Проверка доступа к рассылкам...</div>
    }
    return campaignCapabilities.allowed ? children : <Navigate to="/send" replace />
  }

  return (
    <div className="min-h-screen flex bg-canvas-50">
      <Sidebar user={user} onLogout={handleLogout} campaignsAllowed={Boolean(campaignCapabilities && campaignCapabilities.allowed)} />
      <main className="flex-1 min-w-0 px-8 py-7">
        <Routes>
          <Route path="/" element={<Navigate to="/send" />} />
          <Route path="/send" element={<EmailRender token={token} user={user} />} />
          <Route path="/campaigns" element={<CampaignsOnly><Campaigns token={token} capabilities={campaignCapabilities} /></CampaignsOnly>} />
          <Route path="/campaigns/new" element={<CampaignsOnly><CampaignWizard token={token} user={user} capabilities={campaignCapabilities} /></CampaignsOnly>} />
          <Route path="/campaigns/:id" element={<CampaignsOnly><CampaignProgress token={token} capabilities={campaignCapabilities} /></CampaignsOnly>} />
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
