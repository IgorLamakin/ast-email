import { useState, useEffect } from 'react'
import { apiFetch } from '../api'

function Profile({ token, user, onUpdateUser }) {
  const [form, setForm] = useState({
    full_name: '',
    sender_email: '',
    position: '',
    company: '',
    phone: '',
    address: '',
    website: ''
  })
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  // --- Обновление приложения (личный кабинет) ---
  // В собранном Electron-приложении окно создаётся с nodeIntegration:true,
  // поэтому рендерер имеет доступ к require('electron'). В dev-режиме браузера
  // window.require отсутствует - тогда блок обновления просто не показываем.
  const electronApi = (typeof window !== 'undefined' && window.require) ? window.require('electron') : null
  const hasUpdater = Boolean(electronApi && electronApi.ipcRenderer)
  const [updateStatus, setUpdateStatus] = useState(null)
  const [updateBusy, setUpdateBusy] = useState(false)
  const [updateMsg, setUpdateMsg] = useState('')

  useEffect(() => {
    if (!hasUpdater) return
    const { ipcRenderer } = electronApi
    ipcRenderer.invoke('update:get-status').then(setUpdateStatus).catch(() => {})
    const onStatus = (_e, payload) => setUpdateStatus(payload)
    ipcRenderer.on('update:status', onStatus)
    return () => ipcRenderer.removeListener('update:status', onStatus)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasUpdater])

  const handleInstallUpdate = async () => {
    if (!electronApi) return
    setUpdateBusy(true)
    setUpdateMsg('')
    try {
      const res = await electronApi.ipcRenderer.invoke('update:install')
      if (res && !res.ok) setUpdateMsg(res.error || 'Не удалось начать установку обновления.')
    } catch {
      setUpdateMsg('Не удалось начать установку обновления.')
    } finally {
      setTimeout(() => setUpdateBusy(false), 800)
    }
  }

  useEffect(() => {
    if (user) {
      setForm({
        full_name: user.full_name || '',
        sender_email: user.sender_email || '',
        position: user.position || '',
        company: user.company || '',
        phone: user.phone || '',
        address: user.address || '',
        website: user.website || ''
      })
    }
  }, [user])

  const handleChange = (e) => {
    setForm({ ...form, [e.target.name]: e.target.value })
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setMessage('')
    setError('')
    try {
      // Раньше здесь был PUT /auth/me - такого маршрута на бэкенде нет вообще,
      // поэтому профиль никогда не сохранялся (запрос всегда падал с ошибкой).
      // Реальный маршрут для редактирования пользователя - PUT /users/{id}.
      const data = await apiFetch(`/users/${user.id}`, {
        method: 'PUT',
        token,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form)
      })
      onUpdateUser(data)
      setMessage('Профиль сохранён!')
    } catch {
      setError('Не удалось сохранить профиль')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Мой профиль</h2>

      {message && <div className="bg-ok-100 text-ok-600 p-3 rounded mb-4">{message}</div>}
      {error && <div className="bg-warn-100 text-warn-600 p-3 rounded mb-4">{error}</div>}

      <form onSubmit={handleSubmit} className="bg-canvas-0 p-6 rounded-lg shadow space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-ink-900 mb-1">ФИО</label>
            <input name="full_name" value={form.full_name} onChange={handleChange}
              className="w-full px-3 py-2 border rounded focus:ring-2 focus:ring-signal-500 outline-none"
              placeholder="Иванов Иван Иванович" />
          </div>
          <div>
            <label className="block text-sm font-medium text-ink-900 mb-1">Email для отправки</label>
            <input name="sender_email" type="email" value={form.sender_email} onChange={handleChange}
              className="w-full px-3 py-2 border rounded focus:ring-2 focus:ring-signal-500 outline-none"
              placeholder="your@company.com" />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-ink-900 mb-1">Должность</label>
            <input name="position" value={form.position} onChange={handleChange}
              className="w-full px-3 py-2 border rounded focus:ring-2 focus:ring-signal-500 outline-none"
              placeholder="Руководитель отдела продаж" />
          </div>
          <div>
            <label className="block text-sm font-medium text-ink-900 mb-1">Компания</label>
            <input name="company" value={form.company} onChange={handleChange}
              className="w-full px-3 py-2 border rounded focus:ring-2 focus:ring-signal-500 outline-none"
              placeholder='ООО "АСТ"' />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-ink-900 mb-1">Телефон</label>
            <input name="phone" value={form.phone} onChange={handleChange}
              className="w-full px-3 py-2 border rounded focus:ring-2 focus:ring-signal-500 outline-none"
              placeholder="+7 900 000-00-00" />
          </div>
          <div>
            <label className="block text-sm font-medium text-ink-900 mb-1">Сайт</label>
            <input name="website" value={form.website} onChange={handleChange}
              className="w-full px-3 py-2 border rounded focus:ring-2 focus:ring-signal-500 outline-none"
              placeholder="astkip.ru" />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-ink-900 mb-1">Адрес</label>
          <input name="address" value={form.address} onChange={handleChange}
            className="w-full px-3 py-2 border rounded focus:ring-2 focus:ring-signal-500 outline-none"
            placeholder="г. Краснодар, ул. Российская д. 208/1" />
        </div>

        <div className="bg-signal-100/40 p-4 rounded-lg text-sm text-ink-900">
          <p className="font-medium mb-2">Как будет выглядеть подпись в письмах:</p>
          <div className="bg-canvas-0 p-3 rounded border text-ink-900 text-xs">
            <p className="font-semibold">С уважением,</p>
            <p className="font-bold">{form.full_name || 'Иванов И.А.'}</p>
            <p>{form.position || 'Должность'}</p>
            <p className="font-semibold">{form.company || 'Компания'}</p>
            <p className="mt-1">{form.address || 'Адрес'}</p>
            <p>тел.: {form.phone || '+7 900 000-00-00'}</p>
            <p>email: {form.sender_email || 'email@company.com'}</p>
            <p>сайт: {form.website || 'company.ru'}</p>
          </div>
        </div>

        <button type="submit" disabled={loading}
          className="bg-signal-500 hover:bg-signal-600 text-white px-6 py-2 rounded font-medium transition disabled:opacity-50">
          {loading ? 'Сохранение...' : 'Сохранить профиль'}
        </button>
      </form>

      {hasUpdater && (
        <div className="mt-6 bg-canvas-0 p-6 rounded-lg shadow">
          <h3 className="text-lg font-semibold mb-2">Обновления приложения</h3>
          {updateMsg && <p className="text-sm text-warn-600 mb-2">{updateMsg}</p>}
          <p className="text-sm text-ink-500 mb-3">
            Текущая версия: <span className="font-medium text-ink-900">{updateStatus?.currentVersion || '—'}</span>
          </p>

          {(updateStatus?.state === 'available' || updateStatus?.state === 'downloading' || updateStatus?.state === 'downloaded') ? (
            <div>
              {updateStatus?.releaseNotes && (
                <div className="text-sm text-ink-700 whitespace-pre-line mb-3 bg-canvas-50 p-3 rounded border max-h-40 overflow-auto">
                  {updateStatus.releaseNotes}
                </div>
              )}
              <button onClick={handleInstallUpdate} disabled={updateBusy || updateStatus?.state === 'downloading' || updateStatus?.state === 'downloaded'}
                className="bg-signal-500 hover:bg-signal-600 text-white px-5 py-2 rounded font-medium transition disabled:opacity-50">
                {updateStatus?.state === 'downloading'
                  ? `Загрузка… ${updateStatus.progress != null ? updateStatus.progress + '%' : ''}`
                  : updateStatus?.state === 'downloaded'
                    ? 'Обновление загружено, применяем…'
                    : `Установить обновление (v${updateStatus.version})`}
              </button>
              <p className="text-xs text-ink-500 mt-2">
                Приложение закроется, обновится и запустится автоматически. Шаблоны, контакты и история отправок сохранятся.
              </p>
            </div>
          ) : updateStatus?.state === 'error' ? (
            <div>
              <p className="text-sm text-warn-600 mb-2">{updateStatus.message || 'Не удалось проверить обновления.'}</p>
              <button onClick={() => electronApi.ipcRenderer.invoke('update:check')}
                className="px-4 py-2 rounded font-medium border border-line-200 hover:border-signal-500 transition">
                Проверить ещё раз
              </button>
            </div>
          ) : updateStatus?.state === 'none' ? (
            <p className="text-sm text-ok-600">У вас установлена последняя версия.</p>
          ) : (
            <div>
              <p className="text-sm text-ink-500 mb-2">Проверьте наличие обновлений.</p>
              <button onClick={() => electronApi.ipcRenderer.invoke('update:check')}
                className="px-4 py-2 rounded font-medium border border-line-200 hover:border-signal-500 transition">
                Проверить обновления
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default Profile
