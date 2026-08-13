import { useState, useEffect } from 'react'
import { apiFetch } from '../api'

const SMTP_PRESETS = [
  { label: 'Свой сервер', host: '', port: 587 },
  { label: 'Яндекс Почта', host: 'smtp.yandex.ru', port: 465 },
  { label: 'Mail.ru', host: 'smtp.mail.ru', port: 465 },
  { label: 'Gmail', host: 'smtp.gmail.com', port: 587 },
]

function Settings({ token }) {
  const [form, setForm] = useState({ smtp_host: '', smtp_port: 587, smtp_user: '', smtp_password: '', smtp_from: '' })
  const [passwordSet, setPasswordSet] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [message, setMessage] = useState(null) // { type: 'ok' | 'error', text }

  useEffect(() => {
    apiFetch('/settings', { token })
      .then(data => {
        setForm({
          smtp_host: data.smtp_host || '',
          smtp_port: data.smtp_port || 587,
          smtp_user: data.smtp_user || '',
          smtp_password: '',
          smtp_from: data.smtp_from || '',
        })
        setPasswordSet(data.smtp_password_set)
      })
      .catch(() => setMessage({ type: 'error', text: 'Не удалось загрузить настройки' }))
      .finally(() => setLoading(false))
  }, [token])

  const update = (field) => (e) => setForm(f => ({ ...f, [field]: e.target.value }))

  const applyPreset = (preset) => {
    if (!preset.host) return
    setForm(f => ({ ...f, smtp_host: preset.host, smtp_port: preset.port }))
  }

  const handleSave = async (e) => {
    e.preventDefault()
    setSaving(true)
    setMessage(null)
    try {
      const data = await apiFetch('/settings', {
        method: 'POST',
        token,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, smtp_port: parseInt(form.smtp_port) || 587 }),
      })
      setPasswordSet(data.smtp_password_set)
      setForm(f => ({ ...f, smtp_password: '' }))
      setMessage({ type: 'ok', text: 'Настройки сохранены' })
    } catch (err) {
      setMessage({ type: 'error', text: err.message || 'Не удалось сохранить настройки' })
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    setMessage(null)
    try {
      const data = await apiFetch('/email/test-smtp', {
        method: 'POST',
        token,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, smtp_port: parseInt(form.smtp_port) || 587 }),
      })
      if (data.auth_success) {
        setMessage({ type: 'ok', text: data.message || 'Подключение к SMTP успешно' })
      } else {
        setMessage({ type: 'error', text: data.error || 'Не удалось подключиться к SMTP-серверу' })
      }
    } catch (err) {
      setMessage({ type: 'error', text: err.message || 'Не удалось проверить подключение' })
    } finally {
      setTesting(false)
    }
  }

  if (loading) return <div className="text-ink-500 text-sm">Загрузка...</div>

  return (
    <div className="max-w-xl">
      <p className="text-[11px] uppercase tracking-wider text-ink-500 font-medium mb-1">Администрирование</p>
      <h1 className="text-xl font-semibold text-ink-900 mb-6">Настройки почтового сервера</h1>

      <div className="bg-canvas-0 border border-line-200 rounded-xl p-6">
        <div className="flex flex-wrap gap-2 mb-5">
          {SMTP_PRESETS.map(p => (
            <button
              key={p.label}
              type="button"
              onClick={() => applyPreset(p)}
              className="text-xs px-3 py-1.5 rounded-full border border-line-200 text-ink-500 hover:border-signal-500 hover:text-signal-600 transition-colors"
            >
              {p.label}
            </button>
          ))}
        </div>

        <form onSubmit={handleSave} className="space-y-4">
          <div className="grid grid-cols-3 gap-4">
            <label className="col-span-2 block">
              <span className="block text-sm font-medium text-ink-900 mb-1.5">SMTP-сервер</span>
              <input
                type="text" value={form.smtp_host} onChange={update('smtp_host')} required
                placeholder="smtp.yandex.ru"
                className="w-full rounded-lg border border-line-200 px-3 py-2 text-sm focus:border-signal-500"
              />
            </label>
            <label className="block">
              <span className="block text-sm font-medium text-ink-900 mb-1.5">Порт</span>
              <input
                type="number" value={form.smtp_port} onChange={update('smtp_port')} required
                className="w-full rounded-lg border border-line-200 px-3 py-2 text-sm font-mono focus:border-signal-500"
              />
            </label>
          </div>

          <label className="block">
            <span className="block text-sm font-medium text-ink-900 mb-1.5">Логин (обычно email)</span>
            <input
              type="text" value={form.smtp_user} onChange={update('smtp_user')} required
              placeholder="ivan@company.ru"
              className="w-full rounded-lg border border-line-200 px-3 py-2 text-sm focus:border-signal-500"
            />
          </label>

          <label className="block">
            <span className="block text-sm font-medium text-ink-900 mb-1.5">
              Пароль приложения
              {passwordSet && <span className="ml-2 text-xs font-normal text-ok-600">● сохранён</span>}
            </span>
            <input
              type="password" value={form.smtp_password} onChange={update('smtp_password')}
              placeholder={passwordSet ? 'Оставьте пустым, чтобы не менять' : 'Введите пароль приложения'}
              className="w-full rounded-lg border border-line-200 px-3 py-2 text-sm focus:border-signal-500"
            />
            <span className="block text-xs text-ink-500 mt-1.5">
              Это не обычный пароль от почты, а отдельный «пароль приложения» — его нужно
              создать в настройках безопасности вашего почтового провайдера.
            </span>
          </label>

          <label className="block">
            <span className="block text-sm font-medium text-ink-900 mb-1.5">Email отправителя (необязательно)</span>
            <input
              type="text" value={form.smtp_from} onChange={update('smtp_from')}
              placeholder="По умолчанию — тот же, что логин"
              className="w-full rounded-lg border border-line-200 px-3 py-2 text-sm focus:border-signal-500"
            />
          </label>

          {message && (
            <div className={`text-sm rounded-lg px-3 py-2 ${message.type === 'ok' ? 'bg-ok-100 text-ok-600' : 'bg-warn-100 text-warn-600'}`}>
              {message.text}
            </div>
          )}

          <div className="flex gap-3 pt-2">
            <button
              type="submit" disabled={saving}
              className="px-4 py-2 rounded-lg bg-signal-500 hover:bg-signal-600 text-white text-sm font-medium transition-colors disabled:opacity-50"
            >
              {saving ? 'Сохранение...' : 'Сохранить'}
            </button>
            <button
              type="button" onClick={handleTest} disabled={testing || !form.smtp_host || !form.smtp_user}
              className="px-4 py-2 rounded-lg border border-line-200 text-ink-900 hover:border-signal-500 text-sm font-medium transition-colors disabled:opacity-50"
            >
              {testing ? 'Проверка...' : 'Проверить подключение'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default Settings
