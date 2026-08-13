import { useState, useEffect } from 'react'
import { apiFetch } from '../api'

function Analytics({ token }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    fetchAnalytics()
  }, [token])

  const fetchAnalytics = async () => {
    try {
      const result = await apiFetch('/analytics', { token })
      setData(result)
    } catch (err) {
      setError(err.message || 'Доступ запрещён')
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="text-center py-10">Загрузка...</div>
  if (error) return <div className="bg-warn-100 text-warn-600 p-4 rounded">{error}</div>

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Аналитика отправок</h2>

      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="bg-canvas-0 p-5 rounded-lg shadow">
          <p className="text-sm text-ink-500">Всего отправлено</p>
          <p className="text-3xl font-bold text-signal-600">{data?.total_sent || 0}</p>
        </div>
      </div>

      <div className="bg-canvas-0 rounded-lg shadow overflow-hidden">
        <table className="w-full">
          <thead className="bg-line-200">
            <tr>
              <th className="text-left px-4 py-3 text-sm font-medium text-ink-500">Отправитель</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-ink-500">Получатель</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-ink-500">Обращение</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-ink-500">Шаблон</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-ink-500">Статус</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-ink-500">Дата</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {data?.logs?.map(log => (
              <tr key={log.id} className="hover:bg-canvas-50">
                <td className="px-4 py-3">{log.sender_email}</td>
                <td className="px-4 py-3">{log.recipient_email}</td>
                <td className="px-4 py-3 text-ink-500">{log.greeting || '—'}</td>
                <td className="px-4 py-3 text-ink-500">{log.template_title || '(шаблон удалён)'}</td>
                <td className="px-4 py-3">
                  {log.status === 'sent' ? (
                    <span className="text-ok-600 bg-ok-100 px-2 py-0.5 rounded text-xs font-medium">Отправлено</span>
                  ) : (
                    <span className="text-warn-600 bg-warn-100 px-2 py-0.5 rounded text-xs font-medium">Не отправлено</span>
                  )}
                </td>
                <td className="px-4 py-3 text-ink-500">{new Date(log.sent_at).toLocaleString('ru-RU')}</td>
              </tr>
            ))}
            {data?.logs?.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-ink-500">Пока нет отправок</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default Analytics
