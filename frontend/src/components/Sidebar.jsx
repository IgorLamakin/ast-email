import { Link, useLocation } from 'react-router-dom'

// Простые линейные иконки без внешних зависимостей (не тянем lucide-react ради
// нескольких иконок - меньше версий пакетов ломать при следующей установке).
const icons = {
  send: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 2 11 13" /><path d="M22 2 15 22l-4-9-9-4 20-7Z" />
    </svg>
  ),
  contacts: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  ),
  templates: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" />
      <rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" />
    </svg>
  ),
  analytics: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 3v18h18" /><rect x="7" y="12" width="3" height="6" /><rect x="13" y="8" width="3" height="10" /><rect x="19" y="5" width="0" height="13" />
      <path d="M13 8h3v10" />
    </svg>
  ),
  accounts: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
    </svg>
  ),
  settings: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.14.36.37.68.67.94a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" />
    </svg>
  ),
  profile: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.5-7 8-7s8 3 8 7" />
    </svg>
  ),
  logout: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="M16 17l5-5-5-5" /><path d="M21 12H9" />
    </svg>
  ),
}

function NavItem({ to, icon, label, active }) {
  return (
    <Link
      to={to}
      className={`group relative flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-sm font-medium transition-colors
        ${active ? 'bg-graphite-700 text-white' : 'text-steel-300 hover:text-steel-100 hover:bg-graphite-800'}`}
    >
      {/* Сигнальный индикатор активного пункта - единственный яркий акцент в
          интерфейсе, по аналогии с лампой на промышленной панели управления. */}
      <span className={`absolute left-0 top-1/2 -translate-y-1/2 h-5 w-[3px] rounded-r-full transition-opacity
        ${active ? 'bg-signal-500 opacity-100' : 'opacity-0'}`} />
      <span className="w-[18px] h-[18px] shrink-0">{icon}</span>
      <span>{label}</span>
    </Link>
  )
}

function Sidebar({ user, onLogout }) {
  const location = useLocation()
  const isActive = (path) => location.pathname.startsWith(path)
  const isAdmin = user?.role === 'admin'

  return (
    <aside className="w-60 shrink-0 h-screen sticky top-0 bg-graphite-950 flex flex-col">
      <div className="flex items-center gap-2.5 px-5 h-16 border-b border-graphite-800">
        <span className="w-7 h-7 rounded bg-signal-500 flex items-center justify-center text-graphite-950 font-bold text-xs">
          АСТ
        </span>
        <span className="text-steel-100 font-semibold text-sm tracking-wide">Email Templates</span>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        <p className="px-3.5 pb-1.5 text-[11px] uppercase tracking-wider text-steel-300/60 font-medium">Работа</p>
        <NavItem to="/send" icon={icons.send} label="Отправка" active={isActive('/send')} />
        <NavItem to="/contacts" icon={icons.contacts} label="Контакты" active={isActive('/contacts')} />
        <NavItem to="/templates" icon={icons.templates} label="Шаблоны" active={isActive('/templates')} />

        {isAdmin && (
          <>
            <p className="px-3.5 pt-4 pb-1.5 text-[11px] uppercase tracking-wider text-steel-300/60 font-medium">Администрирование</p>
            <NavItem to="/analytics" icon={icons.analytics} label="Аналитика" active={isActive('/analytics')} />
            <NavItem to="/accounts" icon={icons.accounts} label="Аккаунты" active={isActive('/accounts')} />
            <NavItem to="/settings" icon={icons.settings} label="Настройки" active={isActive('/settings')} />
          </>
        )}
      </nav>

      <div className="p-3 border-t border-graphite-800">
        <Link
          to="/profile"
          className={`flex items-center gap-2.5 px-2.5 py-2 rounded-lg mb-1 transition-colors
            ${isActive('/profile') ? 'bg-graphite-700' : 'hover:bg-graphite-800'}`}
        >
          <span className="w-7 h-7 rounded-full bg-graphite-700 flex items-center justify-center text-steel-100 shrink-0">
            <span className="w-4 h-4">{icons.profile}</span>
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-sm text-steel-100 truncate">{user?.email}</span>
            <span className="block text-[11px] text-steel-300">{isAdmin ? 'Администратор' : 'Сотрудник'}</span>
          </span>
        </Link>
        <button
          onClick={onLogout}
          className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-sm text-steel-300 hover:text-white hover:bg-graphite-800 transition-colors"
        >
          <span className="w-4 h-4">{icons.logout}</span>
          Выйти
        </button>
        <p className="px-2.5 pt-2 text-[11px] font-mono text-steel-300/50">
          версия {import.meta.env.VITE_APP_VERSION || 'dev'}
        </p>
      </div>
    </aside>
  )
}

export default Sidebar
