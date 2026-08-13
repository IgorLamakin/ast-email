import { useState, useEffect } from 'react'
import { apiFetch } from '../api'

function StatusBadge({ status }) {
  const isPublished = status === 'published'
  return (
    <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium
      ${isPublished ? 'bg-ok-100 text-ok-600' : 'bg-line-200 text-ink-500'}`}>
      {isPublished ? 'Опубликован' : 'Черновик'}
    </span>
  )
}

function AccountCard({ account, expanded, onToggle, onPublishToggle, busyTemplateId }) {
  return (
    <div className="bg-canvas-0 border border-line-200 rounded-xl overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-canvas-50 transition-colors"
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="w-9 h-9 rounded-full bg-graphite-900 text-steel-100 flex items-center justify-center text-sm font-semibold shrink-0">
            {(account.full_name || account.email)[0].toUpperCase()}
          </span>
          <span className="min-w-0">
            <span className="flex items-center gap-2">
              <span className="font-medium text-ink-900 truncate">{account.full_name || account.email}</span>
              {account.role === 'admin' && (
                <span className="text-[11px] px-1.5 py-0.5 rounded bg-signal-100 text-signal-600 font-medium shrink-0">админ</span>
              )}
            </span>
            <span className="block text-xs text-ink-500 truncate font-mono">{account.email}</span>
          </span>
        </div>
        <div className="flex items-center gap-5 shrink-0 pl-3">
          <span className="text-right">
            <span className="block text-sm font-mono font-medium text-ink-900">{account.emails_sent_count}</span>
            <span className="block text-[11px] text-ink-500">писем</span>
          </span>
          <span className="text-right">
            <span className="block text-sm font-mono font-medium text-ink-900">{account.templates.length}</span>
            <span className="block text-[11px] text-ink-500">шаблонов</span>
          </span>
          <svg className={`w-4 h-4 text-ink-500 transition-transform ${expanded ? 'rotate-180' : ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="m6 9 6 6 6-6" />
          </svg>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-line-200 px-5 py-4 space-y-5">
          <div>
            <p className="text-[11px] uppercase tracking-wider text-ink-500 font-medium mb-2">Шаблоны</p>
            {account.templates.length === 0 ? (
              <p className="text-sm text-ink-500">Пока не создал ни одного шаблона</p>
            ) : (
              <div className="space-y-1.5">
                {account.templates.map(t => (
                  <div key={t.id} className="flex items-center justify-between gap-3 py-1.5">
                    <span className="text-sm text-ink-900 truncate">{t.title}</span>
                    <span className="flex items-center gap-2 shrink-0">
                      <StatusBadge status={t.status} />
                      <button
                        onClick={() => onPublishToggle(t)}
                        disabled={busyTemplateId === t.id}
                        className="text-xs px-2.5 py-1 rounded-md border border-line-200 text-ink-500 hover:border-signal-500 hover:text-signal-600 transition-colors disabled:opacity-50"
                      >
                        {busyTemplateId === t.id ? '...' : t.status === 'published' ? 'Снять с публикации' : 'Сделать общим'}
                      </button>
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div>
            <p className="text-[11px] uppercase tracking-wider text-ink-500 font-medium mb-2">Последние отправки</p>
            {account.recent_logs.length === 0 ? (
              <p className="text-sm text-ink-500">Ещё ничего не отправлял(а)</p>
            ) : (
              <div className="space-y-1">
                {account.recent_logs.map(log => (
                  <div key={log.id} className="flex items-center justify-between gap-3 text-sm py-1">
                    <span className="text-ink-900 font-mono truncate">{log.recipient_email}</span>
                    <span className="text-ink-500 truncate flex-1 px-3">{log.template_title}</span>
                    <span className={`text-xs shrink-0 ${log.status === 'sent' ? 'text-ok-600' : 'text-warn-600'}`}>
                      {log.status === 'sent' ? 'отправлено' : 'не отправлено'}
                    </span>
                    <span className="text-xs text-ink-500 font-mono shrink-0 w-32 text-right">
                      {new Date(log.sent_at).toLocaleString('ru-RU')}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function Accounts({ token }) {
  const [accounts, setAccounts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expandedId, setExpandedId] = useState(null)
  const [busyTemplateId, setBusyTemplateId] = useState(null)

  const fetchAccounts = () => {
    apiFetch('/admin/accounts', { token })
      .then(data => setAccounts(data.accounts))
      .catch(() => setError('Не удалось загрузить список аккаунтов'))
      .finally(() => setLoading(false))
  }

  useEffect(fetchAccounts, [token])

  const handlePublishToggle = async (template) => {
    setBusyTemplateId(template.id)
    try {
      const action = template.status === 'published' ? 'unpublish' : 'publish'
      await apiFetch(`/templates/${template.id}/${action}`, { method: 'POST', token })
      fetchAccounts()
    } catch {
      setError('Не удалось изменить статус шаблона')
    } finally {
      setBusyTemplateId(null)
    }
  }

  if (loading) return <div className="text-ink-500 text-sm">Загрузка...</div>
  if (error) return <div className="bg-warn-100 text-warn-600 text-sm rounded-lg px-4 py-3">{error}</div>

  const totalSent = accounts.reduce((sum, a) => sum + a.emails_sent_count, 0)
  const totalTemplates = accounts.reduce((sum, a) => sum + a.templates.length, 0)

  return (
    <div className="max-w-3xl">
      <p className="text-[11px] uppercase tracking-wider text-ink-500 font-medium mb-1">Администрирование</p>
      <h1 className="text-xl font-semibold text-ink-900 mb-6">Аккаунты</h1>

      <div className="grid grid-cols-3 gap-3 mb-6">
        <div className="bg-canvas-0 border border-line-200 rounded-xl px-4 py-3">
          <p className="text-2xl font-mono font-semibold text-ink-900">{accounts.length}</p>
          <p className="text-xs text-ink-500">пользователей</p>
        </div>
        <div className="bg-canvas-0 border border-line-200 rounded-xl px-4 py-3">
          <p className="text-2xl font-mono font-semibold text-ink-900">{totalSent}</p>
          <p className="text-xs text-ink-500">писем отправлено всего</p>
        </div>
        <div className="bg-canvas-0 border border-line-200 rounded-xl px-4 py-3">
          <p className="text-2xl font-mono font-semibold text-ink-900">{totalTemplates}</p>
          <p className="text-xs text-ink-500">шаблонов создано</p>
        </div>
      </div>

      <div className="space-y-3">
        {accounts.map(account => (
          <AccountCard
            key={account.id}
            account={account}
            expanded={expandedId === account.id}
            onToggle={() => setExpandedId(expandedId === account.id ? null : account.id)}
            onPublishToggle={handlePublishToggle}
            busyTemplateId={busyTemplateId}
          />
        ))}
      </div>
    </div>
  )
}

export default Accounts
