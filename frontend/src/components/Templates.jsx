import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch } from '../api'

function Templates({ token, user }) {
  const [allTemplates, setAllTemplates] = useState([])
  const [activeTab, setActiveTab] = useState('my')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    fetchTemplates()
  }, [token])

  const fetchTemplates = async () => {
    try {
      // Бэкенд отдаёт единым списком "мои + опубликованные общие" - разделяем
      // на вкладки уже на клиенте, отдельных /templates/my и /templates/common
      // эндпоинтов на бэкенде нет.
      const data = await apiFetch('/templates', { token })
      setAllTemplates(Array.isArray(data) ? data : [])
    } catch {
      setAllTemplates([])
      setError('Не удалось загрузить шаблоны')
    } finally {
      setLoading(false)
    }
  }

  const handlePublish = async (id) => {
    try {
      await apiFetch(`/templates/${id}/publish`, { method: 'POST', token })
      fetchTemplates()
    } catch {
      setError('Не удалось опубликовать')
    }
  }

  const handleDelete = async (id) => {
    if (!confirm('Удалить шаблон?')) return
    try {
      await apiFetch(`/templates/${id}`, { method: 'DELETE', token })
      fetchTemplates()
    } catch {
      setError('Не удалось удалить')
    }
  }

  const isAdmin = user?.role === 'admin'
  const myTemplates = allTemplates.filter(t => t.owner_id === user?.id)
  const commonTemplates = allTemplates.filter(t => t.owner_id !== user?.id && t.status === 'published')
  const templates = activeTab === 'my' ? myTemplates : commonTemplates

  if (loading) return <div className="text-center py-10">Загрузка...</div>

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-bold">Шаблоны писем</h2>
        <Link to="/templates/new"
          className="bg-signal-500 hover:bg-signal-600 text-white px-4 py-2 rounded transition">
          + Создать шаблон
        </Link>
      </div>

      {error && <div className="bg-warn-100 text-warn-600 p-3 rounded mb-4">{error}</div>}

      <div className="flex space-x-1 bg-line-200 p-1 rounded-lg mb-6 w-fit">
        <button onClick={() => setActiveTab('my')}
          className={`px-4 py-2 rounded-md text-sm font-medium transition ${activeTab === 'my' ? 'bg-canvas-0 shadow text-signal-600' : 'text-ink-500 hover:text-ink-900'}`}>
          Мои ({myTemplates.length})
        </button>
        <button onClick={() => setActiveTab('common')}
          className={`px-4 py-2 rounded-md text-sm font-medium transition ${activeTab === 'common' ? 'bg-canvas-0 shadow text-signal-600' : 'text-ink-500 hover:text-ink-900'}`}>
          Общие ({commonTemplates.length})
        </button>
      </div>

      <div className="grid gap-4">
        {templates.map(t => (
          <div key={t.id} className="bg-canvas-0 p-5 rounded-lg shadow hover:shadow-md transition">
            <div className="flex justify-between items-start">
              <div>
                <h3 className="font-semibold text-lg">{t.title}</h3>
                <span className={`inline-block mt-1 px-2 py-0.5 rounded text-xs font-medium ${
                  t.status === 'published' ? 'bg-ok-100 text-ok-600' : 'bg-line-200 text-ink-500'
                }`}>
                  {t.status === 'published' ? 'Опубликован' : 'Черновик'}
                </span>
              </div>
              <div className="flex space-x-2">
                {activeTab === 'my' && t.status === 'draft' && isAdmin && (
                  <button onClick={() => handlePublish(t.id)}
                    className="text-ok-600 hover:opacity-70 text-sm font-medium">
                    Опубликовать
                  </button>
                )}
                {activeTab === 'my' && (
                  <>
                    <Link to={`/templates/edit/${t.id}`} className="text-signal-600 hover:opacity-70 text-sm font-medium">
                      Редактировать
                    </Link>
                    <button onClick={() => handleDelete(t.id)}
                      className="text-warn-600 hover:opacity-70 text-sm font-medium">
                      Удалить
                    </button>
                  </>
                )}
              </div>
            </div>
            <div className="mt-3 p-3 bg-canvas-50 rounded text-sm text-ink-500 overflow-hidden" style={{maxHeight: '100px'}}>
              <code>{t.html_content.substring(0, 200)}{t.html_content.length > 200 ? '...' : ''}</code>
            </div>
          </div>
        ))}
        {templates.length === 0 && (
          <div className="text-center py-10 text-ink-500">Шаблонов пока нет</div>
        )}
      </div>
    </div>
  )
}

export default Templates
