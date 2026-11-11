// Шаг 2 мастера: получатели — загрузка Excel/CSV, сопоставление колонок,
// счётчики, предпросмотр и ручное управление списком (2.7.0, макет screen2.html).
//
// Почему файл грузим через FormData и apiFetch без заголовка Content-Type:
// границу multipart браузер выставляет сам; вручную заданный Content-Type без
// boundary бэкенд не разберёт. apiFetch добавляет только Authorization.
import { useState, useEffect, useCallback, useRef } from 'react'
import { apiFetch } from '../api'
import {
  formatCount,
  formatBytes,
  estimateRemaining,
  paceSeconds,
  DEFAULT_PACE,
  recipientStatusLabel,
  emailHint,
  validateEmailLite,
  campaignErrorMessage,
  campaignTotal,
} from '../utils/campaign.js'
import {
  Card,
  ErrorBox,
  Note,
  FieldLabel,
  TextInput,
  Select,
  PrimaryButton,
  SecondaryButton,
  RecipientBadge,
} from './CampaignUi.jsx'

const PAGE_SIZE = 10
const MAX_PREVIEW_ROWS = 20
// Те же ограничения, что в backend/importer.py (MAX_FILE_BYTES, ALLOWED_EXTS):
// проверяем заранее, чтобы пользователь не ждал загрузку ради 413-й ошибки.
const MAX_FILE_BYTES = 10 * 1024 * 1024
const ALLOWED_EXTENSIONS = ['.xlsx', '.xls', '.csv', '.txt']

// Поля, которые бэкенд ждёт в mapping (см. контракт POST /import/remap).
const MAPPING_FIELDS = [
  { key: 'email', label: 'Колонка с email', required: true },
  { key: 'greeting', label: 'Колонка с обращением' },
  { key: 'name', label: 'Колонка с именем' },
  { key: 'company', label: 'Компания' },
  { key: 'position', label: 'Должность' },
]

function CampaignRecipients({ token, campaign, importData, setImportData, onBack, onNext }) {
  const [fileInfo, setFileInfo] = useState(importData ? { name: importData.file_name || 'загруженный файл', size: importData.file_size } : null)
  const [importing, setImporting] = useState(false)
  const [remapping, setRemapping] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [mapping, setMapping] = useState(importData?.mapping || {})
  const [dragging, setDragging] = useState(false)
  const [recipients, setRecipients] = useState([])
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState('')
  const [pageOffset, setPageOffset] = useState(0)
  const [total, setTotal] = useState(() => campaignTotal(campaign))
  const [manualEmail, setManualEmail] = useState('')
  const [manualGreeting, setManualGreeting] = useState('')
  const [manualBusy, setManualBusy] = useState(false)
  const [manualError, setManualError] = useState('')
  const fileInputRef = useRef(null)

  // mapping живёт отдельным состоянием, чтобы селекты отвечали сразу, не дожидаясь
  // ответа remap. Синхронизируем при появлении/обновлении ответа импорта.
  // total трогаем только когда сервер реально прислал число: ответ без counts
  // не должен обнулять уже известное количество получателей.
  useEffect(() => {
    setMapping(importData?.mapping || {})
    const countsTotal = Number(importData?.counts?.total)
    if (Number.isFinite(countsTotal) && countsTotal > 0) setTotal(countsTotal)
  }, [importData])

  const loadRecipients = useCallback(async (offset) => {
    setListLoading(true)
    setListError('')
    try {
      const data = await apiFetch(
        '/campaigns/' + campaign.id + '/recipients?limit=' + PAGE_SIZE + '&offset=' + offset,
        { token }
      )
      const list = Array.isArray(data) ? data : (Array.isArray(data?.items) ? data.items : [])
      setRecipients(list)
    } catch (err) {
      setRecipients([])
      setListError(campaignErrorMessage(err))
    } finally {
      setListLoading(false)
    }
  }, [campaign.id, token])

  useEffect(() => {
    loadRecipients(pageOffset)
  }, [loadRecipients, pageOffset])

  const handleFile = async (file) => {
    if (!file) return
    const name = String(file.name || '').toLowerCase()
    if (!ALLOWED_EXTENSIONS.some(ext => name.endsWith(ext))) {
      setError('Поддерживаются только файлы .xlsx, .xls, .csv и .txt')
      return
    }
    if (file.size > MAX_FILE_BYTES) {
      setError('Файл больше ' + formatBytes(MAX_FILE_BYTES) + ' — уменьшите количество строк')
      return
    }
    setImporting(true)
    setError('')
    setNotice('')
    try {
      const form = new FormData()
      form.append('file', file)
      const data = await apiFetch('/campaigns/' + campaign.id + '/import', {
        method: 'POST',
        token,
        body: form,
      })
      setImportData(data)
      setFileInfo({ name: file.name, size: file.size })
      setMapping(data?.mapping || {})
      setTotal(Number(data?.counts?.total) || 0)
      setPageOffset(0)
      loadRecipients(0)
      setNotice('Файл обработан: ' + formatCount(Number(data?.counts?.valid) || 0) + ' к отправке')
    } catch (err) {
      setError(campaignErrorMessage(err))
    } finally {
      setImporting(false)
    }
  }

  const handleDrop = (event) => {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer?.files?.[0]
    if (file) handleFile(file)
  }

  const handlePickFile = (event) => {
    const file = event.target.files?.[0]
    // Сбрасываем значение input: иначе повторный выбор того же файла не вызовет change.
    event.target.value = ''
    if (file) handleFile(file)
  }

  const handleMappingChange = async (key, value) => {
    const next = { ...mapping, [key]: value || null }
    setMapping(next)
    setError('')
    setRemapping(true)
    try {
      const data = await apiFetch('/campaigns/' + campaign.id + '/import/remap', {
        method: 'POST',
        token,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mapping: next }),
      })
      setImportData(data)
      // Как и при загрузке файла: не обнуляем количество, если ответ пришёл без counts.
      const remappedTotal = Number(data?.counts?.total)
      if (Number.isFinite(remappedTotal) && remappedTotal > 0) setTotal(remappedTotal)
      setNotice('Сопоставление колонок обновлено')
    } catch (err) {
      setError(campaignErrorMessage(err))
    } finally {
      setRemapping(false)
    }
  }

  // Оптимистично правим счётчики после ручного добавления/удаления: отдельного
  // эндпоинта «пересчитать импорт» нет, а гонять файл заново ради одной строки
  // бессмысленно. Следующая загрузка/remap вернёт точные числа.
  // В счётчиках импорта «всего строк» — это строки файла, а valid/unsubscribed —
  // сколько из них реально стали получателями; поэтому добавление адреса
  // увеличивает и то, и другое, а удаление отписавшегося не трогает valid.
  const bumpCounts = ({ valid = 0, unsubscribed = 0 } = {}) => {
    if (importData?.counts) {
      const counts = { ...importData.counts }
      counts.total = Math.max(0, (Number(counts.total) || 0) + valid + unsubscribed)
      counts.valid = Math.max(0, (Number(counts.valid) || 0) + valid)
      counts.unsubscribed = Math.max(0, (Number(counts.unsubscribed) || 0) + unsubscribed)
      setImportData({ ...importData, counts })
    }
    setTotal(prev => Math.max(0, prev + valid + unsubscribed))
  }

  const handleManualAdd = async (event) => {
    event.preventDefault()
    const email = manualEmail.trim()
    if (!validateEmailLite(email)) {
      setManualError(emailHint(email))
      return
    }
    setManualBusy(true)
    setManualError('')
    setNotice('')
    try {
      await apiFetch('/campaigns/' + campaign.id + '/recipients', {
        method: 'POST',
        token,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, greeting: manualGreeting.trim() || undefined }),
      })
      setManualEmail('')
      setManualGreeting('')
      setNotice('Адрес добавлен: ' + email)
      bumpCounts({ valid: 1 })
      loadRecipients(pageOffset)
    } catch (err) {
      setManualError(campaignErrorMessage(err))
    } finally {
      setManualBusy(false)
    }
  }

  const handleDeleteRecipient = async (recipient) => {
    if (!window.confirm('Удалить получателя ' + recipient.email + '?')) return
    setListError('')
    try {
      await apiFetch('/campaigns/' + campaign.id + '/recipients/' + recipient.id, { method: 'DELETE', token })
      // Отписавшиеся хранятся на бэкенде со статусом skipped: их удаление
      // уменьшает unsubscribed, но не число валидных адресов.
      if (recipient.status === 'skipped') bumpCounts({ unsubscribed: -1 })
      else bumpCounts({ valid: -1 })
      loadRecipients(pageOffset)
    } catch (err) {
      setListError(campaignErrorMessage(err))
    }
  }

  const counts = importData?.counts || null
  const columns = Array.isArray(importData?.columns) ? importData.columns : []
  const previewRows = Array.isArray(importData?.preview) ? importData.preview.slice(0, MAX_PREVIEW_ROWS) : []
  const validCount = counts ? Number(counts.valid) || 0 : total
  // На бэкенде хранятся только валидные адреса и отписавшиеся (skipped):
  // ошибочные и дубли в базу не попадают, поэтому листать список нужно по их сумме.
  const recipientsTotal = counts
    ? (Number(counts.valid) || 0) + (Number(counts.unsubscribed) || 0)
    : total
  // Дальше пропускаем только если есть кому отправлять: один стоп-лист
  // preflight всё равно завернёт с «нет адресов для отправки».
  const canNext = counts ? (Number(counts.valid) || 0) > 0 : total > 0
  const canGoNextPage = recipientsTotal > 0
    ? pageOffset + PAGE_SIZE < recipientsTotal
    : recipients.length === PAGE_SIZE

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_290px] gap-4 items-start">
      <div className="space-y-4 min-w-0">
        <Card className="p-5">
          <div className="flex items-start justify-between gap-3 mb-4">
            <div>
              <h3 className="font-semibold">Получатели</h3>
              <p className="text-sm text-ink-500 mt-1">Загрузите базу и сопоставьте колонки с полями письма</p>
            </div>
            <span className="text-xs text-ink-500 border border-line-200 rounded-full px-2.5 py-0.5 whitespace-nowrap">шаг 2 из 4</span>
          </div>

          <ErrorBox>{error}</ErrorBox>
          {notice && !error && (
            <div className="bg-ok-100 text-ok-600 px-4 py-2.5 rounded-lg text-sm mb-4">{notice}</div>
          )}

          {/* Зона загрузки: до загрузки — большая область, после — строка файла. */}
          <div
            onDragOver={e => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            className={
              'rounded-xl border-2 border-dashed transition-colors ' +
              (dragging ? 'border-signal-500 bg-signal-100/40' : 'border-line-200 bg-canvas-50')
            }
          >
            {fileInfo ? (
              <div className="flex flex-wrap items-center gap-3 px-4 py-3">
                <span className="w-8 h-8 rounded-lg bg-ok-100 text-ok-600 flex items-center justify-center shrink-0">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
                    <path d="m5 12 5 5L20 7" />
                  </svg>
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">
                    {fileInfo.name} {counts && <span className="text-xs text-ok-600">· {formatCount(counts.total)}</span>}
                  </p>
                  <p className="text-xs text-ink-500">
                    {formatBytes(fileInfo.size)}
                    {columns.length > 0 && ' · колонок: ' + columns.length}
                    {importing && ' · обработка...'}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <SecondaryButton type="button" onClick={() => fileInputRef.current?.click()} disabled={importing}>
                    Заменить
                  </SecondaryButton>
                  <button
                    type="button"
                    onClick={() => { setFileInfo(null); setImportData(null); setMapping({}); setNotice('') }}
                    className="text-sm text-ink-500 hover:text-warn-600 px-2"
                  >
                    Удалить
                  </button>
                </div>
              </div>
            ) : (
              <div className="px-4 py-8 text-center">
                <p className="text-sm font-medium text-ink-900">Перетащите Excel/CSV или выберите файл</p>
                <p className="text-xs text-ink-500 mt-1">.xlsx, .xls, .csv, .txt — до 50 000 строк и {formatBytes(MAX_FILE_BYTES)}</p>
                <SecondaryButton type="button" className="mt-3" onClick={() => fileInputRef.current?.click()} disabled={importing}>
                  {importing ? 'Обработка файла...' : 'Выбрать файл'}
                </SecondaryButton>
              </div>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.xls,.csv,.txt"
              className="hidden"
              onChange={handlePickFile}
            />
          </div>

          {!importData && total > 0 && (
            <Note className="mt-2">
              Получатели уже сохранены на сервере и показаны ниже. Сопоставление колонок и счётчики импорта
              появятся, если загрузить файл заново.
            </Note>
          )}

          {columns.length > 0 && (
            <>
              <div className="flex items-center justify-between gap-2 mt-4 mb-2">
                <h4 className="text-sm font-medium text-ink-900">Сопоставление колонок</h4>
                {remapping && <span className="text-xs text-ink-500">Пересчёт...</span>}
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {MAPPING_FIELDS.map(field => (
                  <label key={field.key} className="block">
                    <FieldLabel note={field.required ? 'обязательно' : undefined}>{field.label}</FieldLabel>
                    <Select
                      value={mapping[field.key] || ''}
                      onChange={e => handleMappingChange(field.key, e.target.value)}
                      disabled={remapping}
                    >
                      <option value="">— не выбрано —</option>
                      {columns.map(column => (
                        <option key={column} value={column}>{column}</option>
                      ))}
                    </Select>
                  </label>
                ))}
              </div>
              {!mapping.email && (
                <Note className="mt-2 text-warn-600">
                  Не выбрана колонка с email — без неё адреса не импортируются.
                </Note>
              )}
            </>
          )}

          {counts && (
            <div className="flex flex-wrap items-center gap-2 mt-4">
              <CountChip label="Всего" value={counts.total} />
              <CountChip label="Валидных" value={counts.valid} tone="ok" />
              <CountChip label="Дублей" value={counts.duplicates} tone="amber" />
              <CountChip label="Ошибок" value={counts.invalid} tone="warn" />
              <CountChip label="Отписавшихся" value={counts.unsubscribed} tone="neutral" />
            </div>
          )}

          {previewRows.length > 0 && (
            <>
              <div className="flex items-end justify-between gap-2 mt-5 mb-2">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-ink-500">
                  Предпросмотр — первые {previewRows.length} строк
                </h4>
                <span className="text-xs text-ink-500">Обращение подставится в приветствие письма</span>
              </div>
              <div className="overflow-x-auto border border-line-200 rounded-lg">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-canvas-50 text-ink-500 text-xs uppercase tracking-wider">
                      <th className="text-left font-medium px-3 py-2">E-mail</th>
                      <th className="text-left font-medium px-3 py-2">Обращение</th>
                      <th className="text-left font-medium px-3 py-2">Компания</th>
                      <th className="text-right font-medium px-3 py-2">Проверка</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line-200">
                    {previewRows.map((row, index) => (
                      <tr key={index} className={row.status === 'invalid' ? 'bg-warn-100/30' : ''}>
                        <td className="px-3 py-2 font-mono text-xs break-all">{row.email || '—'}</td>
                        <td className="px-3 py-2 text-ink-500">{row.greeting || '—'}</td>
                        <td className="px-3 py-2 text-ink-500">{row.company || '—'}</td>
                        <td className="px-3 py-2 text-right">
                          {recipientStatusLabel(row.status) ? <RecipientBadge status={row.status} /> : <span className="text-xs text-ink-500">OK</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 pt-5 mt-5 border-t border-line-200">
            <SecondaryButton type="button" onClick={onBack}>← Назад</SecondaryButton>
            <div className="flex items-center gap-3">
              {!canNext && <Note>Добавьте хотя бы одного получателя, чтобы перейти к проверке.</Note>}
              <PrimaryButton type="button" onClick={onNext} disabled={!canNext}>
                Далее: проверка →
              </PrimaryButton>
            </div>
          </div>
        </Card>

        <Card className="p-5">
          <div className="flex items-start justify-between gap-3 mb-3">
            <div>
              <h3 className="font-semibold">Список получателей</h3>
              <p className="text-sm text-ink-500 mt-1">Адреса можно добавлять и удалять вручную</p>
            </div>
            <span className="text-xs text-ink-500 whitespace-nowrap">{formatCount(recipientsTotal)}</span>
          </div>

          <form onSubmit={handleManualAdd} className="flex flex-wrap items-end gap-2 mb-4">
            <label className="block flex-1 min-w-[200px]">
              <FieldLabel>Email</FieldLabel>
              <TextInput
                type="email"
                value={manualEmail}
                onChange={e => { setManualEmail(e.target.value); setManualError('') }}
                placeholder="client@company.ru"
              />
            </label>
            <label className="block flex-1 min-w-[160px]">
              <FieldLabel note="необязательно">Обращение</FieldLabel>
              <TextInput
                type="text"
                value={manualGreeting}
                onChange={e => setManualGreeting(e.target.value)}
                placeholder="Иван Иванович"
              />
            </label>
            <PrimaryButton type="submit" disabled={manualBusy || !manualEmail.trim()} className="h-[38px]">
              {manualBusy ? 'Добавление...' : 'Добавить'}
            </PrimaryButton>
          </form>
          {manualError && <p className="text-sm text-warn-600 -mt-2 mb-3">{manualError}</p>}

          <ErrorBox>{listError}</ErrorBox>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-canvas-50 text-ink-500 text-xs uppercase tracking-wider">
                  <th className="text-left font-medium px-3 py-2">Email</th>
                  <th className="text-left font-medium px-3 py-2">Обращение</th>
                  <th className="text-left font-medium px-3 py-2">Статус</th>
                  <th className="text-left font-medium px-3 py-2">Детали</th>
                  <th className="text-right font-medium px-3 py-2"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line-200">
                {listLoading ? (
                  <tr><td colSpan={5} className="px-3 py-6 text-center text-ink-500">Загрузка списка...</td></tr>
                ) : recipients.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-3 py-6 text-center text-ink-500">
                      Получателей пока нет — загрузите файл или добавьте адрес вручную.
                    </td>
                  </tr>
                ) : recipients.map(recipient => (
                  <tr key={recipient.id} className="hover:bg-canvas-50">
                    <td className="px-3 py-2 font-mono text-xs break-all">{recipient.email}</td>
                    <td className="px-3 py-2 text-ink-500">{recipient.greeting || '—'}</td>
                    <td className="px-3 py-2">
                      {recipientStatusLabel(recipient.status)
                        ? <RecipientBadge status={recipient.status} />
                        : <span className="text-xs text-ink-500">{recipient.status || '—'}</span>}
                    </td>
                    <td className="px-3 py-2 text-xs text-ink-500">
                      {recipient.error_text || (recipient.attempts ? 'попыток: ' + recipient.attempts : '')}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        onClick={() => handleDeleteRecipient(recipient)}
                        className="text-xs text-ink-500 hover:text-warn-600"
                      >
                        Удалить
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 mt-3 text-xs text-ink-500">
            <span>
              {recipients.length > 0
                ? 'Показаны ' + (pageOffset + 1) + '–' + (pageOffset + recipients.length) + (recipientsTotal ? ' из ' + recipientsTotal : '')
                : 'Нет строк для показа'}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setPageOffset(Math.max(0, pageOffset - PAGE_SIZE))}
                disabled={pageOffset === 0 || listLoading}
                className="px-2.5 py-1 rounded border border-line-200 disabled:opacity-40 hover:border-signal-500"
              >
                ‹
              </button>
              <span className="px-2.5 py-1 rounded bg-ink-900 text-white font-semibold">{Math.floor(pageOffset / PAGE_SIZE) + 1}</span>
              <button
                type="button"
                onClick={() => setPageOffset(pageOffset + PAGE_SIZE)}
                disabled={!canGoNextPage || listLoading}
                className="px-2.5 py-1 rounded border border-line-200 disabled:opacity-40 hover:border-signal-500"
              >
                ›
              </button>
            </div>
          </div>
        </Card>
      </div>

      <aside className="space-y-4">
        <Card className="p-4">
          <p className="text-[11px] uppercase tracking-wider text-ink-500 font-medium">К отправке</p>
          <p className="mt-1.5 flex items-baseline gap-2">
            <span className="text-3xl font-bold">{validCount}</span>
            <span className="text-sm text-ink-500">писем{counts ? ' из ' + formatCount(counts.total) + ' строк' : ''}</span>
          </p>
          {counts && (
            <dl className="mt-3 pt-3 border-t border-line-200 space-y-1.5 text-xs">
              <div className="flex justify-between gap-2"><dt className="text-ink-500">Всего строк в файле</dt><dd className="font-semibold">{counts.total ?? 0}</dd></div>
              <div className="flex justify-between gap-2"><dt className="text-ink-500">Дубликаты</dt><dd className="font-semibold text-[#8A6415]">−{counts.duplicates ?? 0}</dd></div>
              <div className="flex justify-between gap-2"><dt className="text-ink-500">Ошибки в адресах</dt><dd className="font-semibold text-warn-600">−{counts.invalid ?? 0}</dd></div>
              <div className="flex justify-between gap-2"><dt className="text-ink-500">Отписавшиеся</dt><dd className="font-semibold">−{counts.unsubscribed ?? 0}</dd></div>
            </dl>
          )}
          <div className="mt-3 pt-3 border-t border-dashed border-line-200">
            <p className="text-sm font-semibold">≈ {estimateRemaining(validCount, paceSeconds(DEFAULT_PACE))}</p>
            <p className="text-xs text-ink-500 mt-1">при безопасном темпе. Точный темп задаётся на шаге 4.</p>
          </div>
        </Card>

        <Card className="p-4">
          <h3 className="text-sm font-semibold mb-2">Как подготовить базу</h3>
          <ul className="text-xs text-ink-500 space-y-1.5 list-disc pl-4">
            <li>Первая строка — заголовки колонок.</li>
            <li>Обязательна колонка с email; остальные — по желанию.</li>
            <li>Дубликаты и отписавшиеся отсеиваются автоматически.</li>
          </ul>
        </Card>
      </aside>
    </div>
  )
}

// Счётчик-«чип» из макета: цвет точки зависит от того, что считаем.
function CountChip({ label, value, tone = 'neutral' }) {
  const dot = {
    neutral: 'bg-ink-500/40',
    ok: 'bg-ok-600',
    amber: 'bg-[#C08A1E]',
    warn: 'bg-warn-600',
  }[tone] || 'bg-ink-500/40'
  return (
    <span className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full border border-line-200 bg-canvas-0 text-xs">
      <span className={'w-1.5 h-1.5 rounded-full ' + dot} />
      <span className="text-ink-500">{label}</span>
      <span className="font-semibold text-ink-900">{Number(value) || 0}</span>
    </span>
  )
}

export default CampaignRecipients
