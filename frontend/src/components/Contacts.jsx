import { useState, useEffect } from 'react'
import { apiFetch } from '../api'

function Contacts({ token }) {
  const [contacts, setContacts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    fetchContacts()
  }, [token])

  const fetchContacts = async () => {
    try {
      const data = await apiFetch('/contacts', { token })
      setContacts(Array.isArray(data) ? data : [])
    } catch {
      setContacts([])
      setError('Не удалось загрузить контакты')
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (id) => {
    if (!confirm('Удалить контакт?')) return
    try {
      // Раньше здесь был относительный URL '/api/contacts/{id}', который работал
      // только в dev-режиме через прокси Vite и не работал в собранном приложении.
      await apiFetch(`/contacts/${id}`, { method: 'DELETE', token })
      fetchContacts()
    } catch {
      setError('Не удалось удалить')
    }
  }

  if (loading) return <div className="text-center py-10">Загрузка...</div>

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-bold">Сохранённые контакты</h2>
        <span className="text-ink-500 text-sm">Контакты добавляются автоматически при отправке писем</span>
      </div>

      {error && <div className="bg-warn-100 text-warn-600 p-3 rounded mb-4">{error}</div>}

      <div className="bg-canvas-0 rounded-lg shadow overflow-hidden">
        <table className="w-full">
          <thead className="bg-line-200">
            <tr>
              <th className="text-left px-4 py-3 text-sm font-medium text-ink-500">Email</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-ink-500">Обращение</th>
              <th className="text-right px-4 py-3 text-sm font-medium text-ink-500"></th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {contacts.map(c => (
              <tr key={c.id} className="hover:bg-canvas-50">
                <td className="px-4 py-3">{c.email}</td>
                <td className="px-4 py-3 text-ink-500">{c.greeting || '—'}</td>
                <td className="px-4 py-3 text-right">
                  <button onClick={() => handleDelete(c.id)}
                    className="text-warn-600 hover:opacity-70 text-sm">Удалить</button>
                </td>
              </tr>
            ))}
            {contacts.length === 0 && (
              <tr><td colSpan={3} className="px-4 py-8 text-center text-ink-500">Контактов пока нет. Они появятся после отправки писем.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default Contacts
