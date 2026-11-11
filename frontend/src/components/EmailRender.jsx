import { useState, useEffect, useMemo, useRef } from 'react'
import { apiFetch } from '../api'
import Combobox from './Combobox'
import { usedTimesLabel } from '../utils/plural'

function EmailRender({ token, user }) {
  const [templates, setTemplates] = useState([])
  const [contacts, setContacts] = useState([])
  // История адресов отправителя (GET /api/sender-emails, самый свежий - первым).
  // Запрос необязательный: если бэкенд ещё не знает маршрут или ответил ошибкой,
  // история просто пустая, а поле остаётся обычным вводом email.
  const [senderHistory, setSenderHistory] = useState([])
  const [senderEmail, setSenderEmail] = useState(user?.sender_email || '')
  const [recipientEmail, setRecipientEmail] = useState('')
  const [greeting, setGreeting] = useState('')
  const [selectedTemplate, setSelectedTemplate] = useState('')
  const [previewHtml, setPreviewHtml] = useState('')
  const [previewTitle, setPreviewTitle] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  // «Пользователь уже сам правил поле отправителя». Ответ истории приходит
  // асинхронно и не должен затирать введённый вручную адрес.
  const senderTouchedRef = useRef(false)

  useEffect(() => {
    fetchData()
  }, [token, user])

  // Раньше предпросмотр обновлялся только в момент выбора шаблона из списка -
  // если сначала выбрать шаблон, а потом ввести/поменять email получателя или
  // обращение, предпросмотр оставался старым (или пустым, если email ещё не
  // был введён на момент выбора шаблона). Теперь любое изменение полей заново
  // запрашивает предпросмотр - с небольшой задержкой (400мс), чтобы не слать
  // запрос на каждую нажатую клавишу.
  useEffect(() => {
    if (!selectedTemplate) return
    const timer = setTimeout(() => {
      loadPreview(selectedTemplate)
    }, 400)
    return () => clearTimeout(timer)
  }, [selectedTemplate, senderEmail, recipientEmail, greeting])

  const fetchData = async () => {
    // Promise.allSettled, а не Promise.all: история отправителя - необязательная
    // часть экрана. Если /api/sender-emails ещё не реализован (404) или упал,
    // отправка письма и предпросмотр должны продолжать работать.
    const [templatesResult, contactsResult, historyResult] = await Promise.allSettled([
      apiFetch('/templates', { token }),
      apiFetch('/contacts', { token }),
      apiFetch('/sender-emails', { token }),
    ])
    if (templatesResult.status === 'fulfilled') {
      setTemplates(Array.isArray(templatesResult.value) ? templatesResult.value : [])
    }
    if (contactsResult.status === 'fulfilled') {
      setContacts(Array.isArray(contactsResult.value) ? contactsResult.value : [])
    }
    if (templatesResult.status === 'rejected' || contactsResult.status === 'rejected') {
      setError('Не удалось загрузить данные')
    }
    const history = historyResult.status === 'fulfilled' && Array.isArray(historyResult.value)
      ? historyResult.value
      : []
    setSenderHistory(history)
    if (!senderTouchedRef.current) {
      // Последний использованный адрес вероятнее всего понадобится снова,
      // поэтому он приоритетнее адреса из профиля пользователя.
      setSenderEmail(history[0]?.email || user?.sender_email || '')
    }
  }

  const loadPreview = async (templateId) => {
    if (!templateId) {
      setPreviewHtml('')
      setPreviewTitle('')
      return
    }
    setPreviewLoading(true)
    try {
      // Реальный маршрут предпросмотра - POST /templates/{id}/preview,
      // не /email/preview (такого эндпоинта на бэкенде нет).
      const data = await apiFetch(`/templates/${parseInt(templateId)}/preview`, {
        method: 'POST',
        token,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sender_email: senderEmail,
          recipient_email: recipientEmail,
          greeting: greeting,
          template_id: parseInt(templateId)
        })
      })
      setPreviewHtml(data.html_preview)
      setPreviewTitle(data.template_title)
    } catch {
      setPreviewHtml('')
      setPreviewTitle('')
    } finally {
      setPreviewLoading(false)
    }
  }

  const handleTemplateChange = (e) => {
    const val = e.target.value
    setSelectedTemplate(val)
    setError('')
    setSuccess('')
    setResult(null)
    // Загрузку предпросмотра теперь единообразно делает useEffect выше (с
    // небольшой задержкой) - он сработает и на смену шаблона, и на изменение
    // остальных полей, не нужно дублировать вызов здесь.
  }

  const handleSend = async () => {
    if (!senderEmail || !recipientEmail || !selectedTemplate) {
      setError('Заполните все обязательные поля')
      return
    }
    setLoading(true)
    setError('')
    setSuccess('')
    setResult(null)
    try {
      // apiFetch сам бросает исключение на не-2xx ответах (например, если SMTP не
      // настроен - раньше бэкенд в этом случае мог вернуть "успех", не отправив
      // письмо; теперь он честно возвращает ошибку, а мы её здесь и ловим).
      // Успех определяется по тому, что запрос вообще не выбросил исключение,
      // а не по совпадению текста сообщения (это было ненадёжно и не совпадало
      // с реальным ответом бэкенда).
      const data = await apiFetch('/email/send', {
        method: 'POST',
        token,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sender_email: senderEmail,
          recipient_email: recipientEmail,
          greeting: greeting,
          template_id: parseInt(selectedTemplate)
        })
      })
      setResult(data)
      setSuccess(data.message)
      // Бэкенд сам запоминает sender_email, поэтому после успешной отправки
      // просто перечитываем историю - новый адрес появится в выпадающем списке.
      fetchData()
    } catch (err) {
      setError(err.message || 'Не удалось отправить письмо')
    } finally {
      setLoading(false)
    }
  }

  // Варианты для выпадающих списков. useMemo - чтобы не создавать новые массивы
  // на каждый рендер и не пересчитывать фильтр в Combobox без причины.
  const senderOptions = useMemo(
    () => senderHistory
      .filter(item => item && item.email)
      .map(item => ({
        value: item.email,
        label: item.email,
        // В списке видно не только адрес, но и «обкатанность»: пользователь
        // обычно хочет выбрать самый частый/свежий адрес.
        // Склонение по правилам русского языка: «1 раз», «2 раза», «5 раз»
        // (раньше при use_count=2 показывалось «использован 2 раз»).
        meta: item.use_count ? usedTimesLabel(item.use_count) : 'из истории',
      })),
    [senderHistory]
  )

  const contactOptions = useMemo(
    () => contacts
      .filter(contact => contact && contact.email)
      .map(contact => ({
        value: contact.email,
        label: contact.email,
        // meta участвует в поиске (filterFields ниже): так «иван» находит
        // контакт по обращению, даже если в самом адресе этой строки нет.
        meta: contact.greeting || '',
        greeting: contact.greeting || '',
      })),
    [contacts]
  )

  const handleSenderChange = (nextEmail) => {
    // Пользователь правит поле сам - автоподстановка из истории больше не нужна.
    senderTouchedRef.current = true
    setSenderEmail(nextEmail)
    setError('')
    setSuccess('')
  }

  // Комбобокс контакта - только выбор: произвольный текст из него в поле
  // получателя не попадает (allowFreeText={false}), поэтому onChange приходит
  // исключительно с выбранным вариантом.
  const handleContactSelect = (_value, option) => {
    if (!option) return
    setRecipientEmail(option.value)
    setGreeting(option.greeting || '')
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Отправка письма</h2>

      {error && <div className="bg-warn-100 text-warn-600 p-3 rounded mb-4">{error}</div>}
      {success && <div className="bg-ok-100 text-ok-600 p-3 rounded mb-4">{success}</div>}

      <div className="bg-canvas-0 p-6 rounded-lg shadow mb-6 space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="sender-email" className="block text-sm font-medium text-ink-900 mb-1">Email отправителя *</label>
            {/* Свободный ввод любого нового адреса + список ранее отправленных. */}
            <Combobox
              id="sender-email"
              type="email"
              value={senderEmail}
              onChange={handleSenderChange}
              options={senderOptions}
              placeholder="your@company.com"
              filterFields={['label']}
              emptyText={senderOptions.length
                ? 'Совпадений нет - можно ввести любой адрес'
                : 'История пуста - введите адрес'}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-ink-900 mb-1">Email получателя *</label>
            <input type="email" required value={recipientEmail} onChange={e => { setRecipientEmail(e.target.value); setError(''); setSuccess('') }}
              className="w-full px-3 py-2 border rounded focus:ring-2 focus:ring-signal-500 outline-none"
              placeholder="client@example.com" />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-ink-900 mb-1">Обращение</label>
          <input type="text" value={greeting} onChange={e => { setGreeting(e.target.value); setError(''); setSuccess('') }}
            className="w-full px-3 py-2 border rounded focus:ring-2 focus:ring-signal-500 outline-none"
            placeholder="Уважаемый, Иван Иванович!" />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-ink-900 mb-1">Шаблон *</label>
            <select value={selectedTemplate} onChange={handleTemplateChange}
              className="w-full px-3 py-2 border rounded focus:ring-2 focus:ring-signal-500 outline-none">
              <option value="">Выберите шаблон</option>
              {templates.map(t => (
                <option key={t.id} value={t.id}>{t.title}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="contact-search" className="block text-sm font-medium text-ink-900 mb-1">Быстрый выбор контакта</label>
            {/* Поиск по сохранённым контактам: по любой части email и по обращению. */}
            <Combobox
              id="contact-search"
              value={recipientEmail}
              onChange={handleContactSelect}
              options={contactOptions}
              allowFreeText={false}
              placeholder="Начните вводить email или обращение"
              filterFields={['label', 'meta']}
              emptyText={contactOptions.length ? 'Совпадений нет' : 'Сохранённых контактов пока нет'}
            />
          </div>
        </div>

        <button onClick={handleSend} disabled={loading}
          className="bg-signal-500 hover:bg-signal-600 text-white px-6 py-2 rounded font-medium transition disabled:opacity-50">
          {loading ? 'Отправка...' : 'Отправить письмо'}
        </button>
      </div>

      {/* Preview block - shown when template is selected */}
      {selectedTemplate && (
        <div className="bg-canvas-0 rounded-lg shadow overflow-hidden mb-6">
          <div className="bg-line-200 px-4 py-3 border-b flex justify-between items-center">
            <h3 className="font-medium flex items-center gap-2">
              Предпросмотр: {previewTitle || '...'}
              {templates.find(t => String(t.id) === String(selectedTemplate))?.attach_pdf && (
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-signal-100 text-signal-600 font-medium">
                  📎 PDF будет приложен
                </span>
              )}
            </h3>
            {previewLoading && <span className="text-xs text-ink-500">Загрузка...</span>}
          </div>
          <div className="p-0">
            {previewHtml ? (
              <iframe
                srcDoc={previewHtml}
                sandbox="allow-scripts"
                className="w-full"
                style={{ height: '500px', border: 'none' }}
                title="Email Preview"
              />
            ) : (
              <div className="p-8 text-center text-ink-500 text-sm">Заполните поля выше, чтобы увидеть предпросмотр</div>
            )}
          </div>
        </div>
      )}

      {/* Result block after sending */}
      {result && (
        <div className="bg-canvas-0 rounded-lg shadow overflow-hidden">
          <div className="bg-line-200 px-4 py-3 border-b">
            <h3 className="font-medium">Результат отправки</h3>
          </div>
          <div className="p-4">
            <p className="text-sm text-ink-900 mb-2">{result.message}</p>
            <p className="text-sm text-ink-500">Получатель: {result.recipient_email}</p>
          </div>
        </div>
      )}
    </div>
  )
}

export default EmailRender
