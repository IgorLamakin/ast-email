// Экран прогресса и отчёта кампании: /campaigns/:id (2.7.0, макет screen3.html).
//
// Данные: GET /campaigns/{id} каждые 4 секунды, последние отправки —
// GET /campaigns/{id}/recipients?status=sent&limit=10, отчёт —
// GET /campaigns/{id}/report, CSV — GET /campaigns/{id}/export.
//
// Таймер опроса обязательно чистится при размонтировании и сам останавливается
// на завершённой/остановленной кампании — иначе приложение продолжало бы
// дёргать бэкенд, даже когда смотреть уже нечего.
//
// CSV нельзя скачать через apiFetch: он всегда разбирает ответ как JSON.
// Поэтому здесь отдельный fetch с заголовком Authorization и Blob-скачивание
// через URL.createObjectURL (с обязательным revokeObjectURL).
import { useState, useEffect, useCallback, useRef } from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'
import { apiFetch, API_BASE, getAccessToken } from '../api'
import {
  formatNumber,
  formatMaybeNumber,
  formatCount,
  estimateRemaining,
  paceLabel,
  paceDescription,
  paceSeconds,
  progressPercent,
  campaignErrorMessage,
  campaignTotal,
  campaignSent,
  campaignFailed,
  campaignSkipped,
  campaignUnsubscribed,
  statusLabel,
  isTerminalStatus,
  canPause,
  canResume,
  canStop,
  formatDateTime,
  recipientStatusLabel,
  reportSummaryRows,
} from '../utils/campaign.js'
import {
  Card,
  ErrorBox,
  Note,
  StatusPill,
  CampaignProgressBar,
  PrimaryButton,
  SecondaryButton,
  RecipientBadge,
} from './CampaignUi.jsx'

const POLL_INTERVAL_MS = 4000
const LAST_SENDS_LIMIT = 10

function CampaignProgress({ token, capabilities }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const [campaign, setCampaign] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionError, setActionError] = useState('')
  const [pendingAction, setPendingAction] = useState('')
  const [lastSends, setLastSends] = useState([])
  const [sendsLoading, setSendsLoading] = useState(true)
  const [sendsError, setSendsError] = useState('')
  const [report, setReport] = useState(null)
  const [reportError, setReportError] = useState('')
  const [reportLoading, setReportLoading] = useState(false)
  const [csvBusy, setCsvBusy] = useState(false)
  const [csvError, setCsvError] = useState('')
  // Статус в ref нужен таймеру: внутри setInterval нельзя брать campaign из
  // замыкания (там навсегда осталось бы первое значение).
  const statusRef = useRef(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  const loadCampaign = useCallback(async () => {
    try {
      const data = await apiFetch('/campaigns/' + id, { token })
      if (!mountedRef.current) return
      setCampaign(data)
      statusRef.current = data?.status || null
      setError('')
    } catch (err) {
      if (!mountedRef.current) return
      setError(campaignErrorMessage(err, { resource: 'campaign' }))
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [id, token])

  // Переход между кампаниями (#/campaigns/1 -> #/campaigns/2 или на удалённую):
  // сбрасываем данные прошлой кампании ДО нового запроса. Иначе при 404 на новом
  // id на экране оставались бы старые цифры, а текст ошибки не показывался
  // (ветка ошибки рендерится только когда campaign ещё нет).
  useEffect(() => {
    setCampaign(null)
    setError('')
    setLoading(true)
    setLastSends([])
    setSendsError('')
    setReport(null)
    setReportError('')
    setActionError('')
    statusRef.current = null
  }, [id])

  useEffect(() => {
    loadCampaign()
    const timer = setInterval(() => {
      // На терминальном статусе опрос прекращается: цифры уже не меняются.
      if (isTerminalStatus(statusRef.current)) return
      loadCampaign()
    }, POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [loadCampaign])

  const sentCount = campaignSent(campaign)

  // Последние отправки: перезапрашиваем при изменении числа отправленных писем,
  // а не на каждый тик опроса — иначе было бы 2 запроса в 4 секунды.
  useEffect(() => {
    let cancelled = false
    setSendsLoading(true)
    setSendsError('')
    apiFetch('/campaigns/' + id + '/recipients?status=sent&limit=' + LAST_SENDS_LIMIT, { token })
      .then(data => {
        if (cancelled) return
        const list = Array.isArray(data) ? data : (Array.isArray(data?.items) ? data.items : [])
        setLastSends(list)
      })
      .catch(err => {
        if (cancelled) return
        setLastSends([])
        setSendsError(campaignErrorMessage(err))
      })
      .finally(() => {
        if (!cancelled) setSendsLoading(false)
      })
    return () => { cancelled = true }
  }, [id, token, sentCount])

  const loadReport = useCallback(async () => {
    setReportLoading(true)
    setReportError('')
    try {
      const data = await apiFetch('/campaigns/' + id + '/report', { token })
      if (!mountedRef.current) return
      setReport(data)
    } catch (err) {
      if (!mountedRef.current) return
      setReport(null)
      setReportError(campaignErrorMessage(err))
    } finally {
      if (mountedRef.current) setReportLoading(false)
    }
  }, [id, token])

  // Отчёт запрашиваем автоматически, когда кампания завершилась/остановилась.
  useEffect(() => {
    if (isTerminalStatus(campaign?.status) && !report && !reportLoading) {
      loadReport()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaign?.status, report])

  const handleAction = async (action) => {
    if (action === 'stop' && !window.confirm('Остановить рассылку? Продолжить её будет нельзя.')) return
    setPendingAction(action)
    setActionError('')
    try {
      await apiFetch('/campaigns/' + id + '/' + action, { method: 'POST', token })
      await loadCampaign()
    } catch (err) {
      setActionError(campaignErrorMessage(err))
    } finally {
      setPendingAction('')
    }
  }

  const handleDeleteDraft = async () => {
    if (!window.confirm('Удалить черновик кампании? Действие нельзя отменить.')) return
    setPendingAction('delete')
    setActionError('')
    try {
      await apiFetch('/campaigns/' + id, { method: 'DELETE', token })
      navigate('/campaigns')
    } catch (err) {
      setActionError(campaignErrorMessage(err))
      setPendingAction('')
    }
  }

  const handleExportCsv = async () => {
    setCsvBusy(true)
    setCsvError('')
    try {
      const url = API_BASE + '/campaigns/' + id + '/export'
      let response = await fetch(url, { headers: token ? { Authorization: 'Bearer ' + token } : {} })
      // Отдельный fetch не проходит через автообновление токена из apiFetch.
      // Если access-токен успел истечь (живёт 12 часов), одним запросом к
      // обычному эндпоинту заставляем api.js обновить пару и повторяем выгрузку
      // с новым токеном — иначе длинная сессия ломала бы скачивание CSV.
      if (response.status === 401) {
        try {
          await apiFetch('/campaigns/' + id, { token })
        } catch {
          // обновить сессию не удалось — покажем ошибку ниже
        }
        const freshToken = getAccessToken()
        if (freshToken && freshToken !== token) {
          response = await fetch(url, { headers: { Authorization: 'Bearer ' + freshToken } })
        }
      }
      if (!response.ok) {
        // Ошибку бэкенд отдаёт JSON-ом — достаём detail, чтобы показать причину,
        // а не «Ошибка 404».
        let message = 'Не удалось скачать CSV (' + response.status + ')'
        try {
          const data = await response.json()
          message = (data && (data.detail || data.message)) || message
        } catch {
          // тело не JSON — оставляем общий текст
        }
        throw new Error(message)
      }
      const blob = await response.blob()
      const objectUrl = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = csvFileName(campaign, id)
      document.body.appendChild(link)
      link.click()
      link.remove()
      // revoke сразу после click в Electron иногда обрывает скачивание —
      // освобождаем память с небольшой задержкой.
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
    } catch (err) {
      if (mountedRef.current) setCsvError(err.message || 'Не удалось скачать CSV')
    } finally {
      if (mountedRef.current) setCsvBusy(false)
    }
  }

  if (loading) return <Card className="p-6 text-sm text-ink-500">Загрузка кампании...</Card>

  if (error && !campaign) {
    return (
      <div>
        <ErrorBox onRetry={loadCampaign}>{error}</ErrorBox>
        <Link to="/campaigns" className="text-sm text-signal-600 font-medium">← К списку рассылок</Link>
      </div>
    )
  }

  if (!campaign) return null

  const total = campaignTotal(campaign)
  const sent = campaignSent(campaign)
  const failed = campaignFailed(campaign)
  const skipped = campaignSkipped(campaign)
  const unsubscribed = campaignUnsubscribed(campaign)
  const delivered = Math.max(0, sent - failed)
  const percent = progressPercent(sent, total)
  const remaining = Math.max(0, total - sent)
  const pace = campaign.settings?.pace || 'safe'
  const status = campaign.status
  const canDownloadCsv = status !== 'draft'

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-4 mb-5">
        <div className="min-w-0">
          <nav className="flex items-center gap-1.5 text-xs text-ink-500 mb-1" aria-label="Хлебные крошки">
            <Link to="/campaigns" className="hover:text-ink-900">Рассылки</Link>
            <span>/</span>
            <span className="text-ink-900 font-medium truncate">{campaign.title}</span>
          </nav>
          <h2 className="text-2xl font-bold truncate">{campaign.title}</h2>
          <p className="text-sm text-ink-500 mt-1">
            {campaign.template_title || 'шаблон не выбран'} · {campaign.sender_email || 'отправитель не выбран'}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <StatusPill status={status} />
          <SecondaryButton onClick={() => navigate('/campaigns')}>К списку</SecondaryButton>
        </div>
      </div>

      <ErrorBox onRetry={loadCampaign}>{error}</ErrorBox>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_300px] gap-4 items-start">
        <div className="space-y-4 min-w-0">
          <Card className="p-5">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="text-[11px] uppercase tracking-wider text-ink-500 font-medium">Отправлено</p>
                <p className="mt-1 flex items-baseline gap-2">
                  <span className="text-3xl font-bold">{formatNumber(sent)}</span>
                  <span className="text-sm text-ink-500">из {formatNumber(total)} · {percent} %</span>
                </p>
              </div>
              <div className="text-right">
                <p className="text-sm font-semibold">
                  {status === 'running' ? 'Осталось ~' + estimateRemaining(remaining, paceSeconds(pace)) : statusLabel(status)}
                </p>
                <p className="text-xs text-ink-500 mt-0.5 max-w-[260px]">
                  темп: {paceLabel(pace)} · {paceDescription(pace)}
                </p>
              </div>
            </div>

            <div className="mt-3">
              <CampaignProgressBar percent={percent} status={status} height="h-2" />
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-5">
              <Counter label="Доставлено" value={delivered} tone="ok" />
              <Counter label="Ошибки" value={failed} tone={failed > 0 ? 'warn' : 'neutral'} />
              <Counter label="Пропущено" value={skipped} />
              <Counter label="Отписались" value={unsubscribed} />
            </div>

            {campaign.last_error && (
              <div className="mt-4 rounded-lg bg-warn-100 text-warn-600 px-3.5 py-2.5 text-sm">
                <b className="font-medium">Последняя ошибка:</b> {campaign.last_error}
              </div>
            )}

            {actionError && <div className="mt-4 text-sm text-warn-600">{actionError}</div>}

            <div className="flex flex-wrap items-center gap-2 mt-5 pt-4 border-t border-line-200">
              {canPause(status) && (
                <PrimaryButton type="button" onClick={() => handleAction('pause')} disabled={Boolean(pendingAction)}>
                  {pendingAction === 'pause' ? 'Пауза...' : 'Пауза'}
                </PrimaryButton>
              )}
              {canResume(status) && (
                <PrimaryButton type="button" onClick={() => handleAction('resume')} disabled={Boolean(pendingAction)}>
                  {pendingAction === 'resume' ? 'Продолжение...' : 'Продолжить'}
                </PrimaryButton>
              )}
              {canStop(status) && (
                <SecondaryButton
                  type="button"
                  onClick={() => handleAction('stop')}
                  disabled={Boolean(pendingAction)}
                  className="!text-warn-600 !border-warn-100 hover:!border-warn-600"
                >
                  {pendingAction === 'stop' ? 'Остановка...' : 'Остановить'}
                </SecondaryButton>
              )}
              {status === 'draft' && (
                <>
                  <Link
                    to={'/campaigns/new?draft=' + id}
                    className="inline-flex items-center justify-center gap-2 px-5 py-2 rounded-lg bg-signal-500 hover:bg-signal-600 text-white text-sm font-medium transition-colors"
                  >
                    Продолжить настройку
                  </Link>
                  <SecondaryButton type="button" onClick={handleDeleteDraft} disabled={Boolean(pendingAction)}>
                    Удалить черновик
                  </SecondaryButton>
                  <Note>
                    Черновик ещё не запускался: продолжите мастер, чтобы загрузить получателей, пройти проверку и запустить рассылку.
                  </Note>
                </>
              )}
              <button
                type="button"
                onClick={loadCampaign}
                className="ml-auto text-sm text-ink-500 hover:text-ink-900 px-2 py-2"
              >
                Обновить
              </button>
            </div>
          </Card>

          <Card className="overflow-hidden">
            <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-line-200">
              <h3 className="font-semibold text-sm">Последние отправки</h3>
              <span className="text-xs text-ink-500">до {LAST_SENDS_LIMIT} писем</span>
            </div>
            <ErrorBox>{sendsError}</ErrorBox>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-canvas-50 text-ink-500 text-xs uppercase tracking-wider">
                    <th className="text-left font-medium px-4 py-2">Email</th>
                    <th className="text-left font-medium px-4 py-2">Обращение</th>
                    <th className="text-left font-medium px-4 py-2">Статус</th>
                    <th className="text-left font-medium px-4 py-2">Время</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line-200">
                  {sendsLoading ? (
                    <tr><td colSpan={4} className="px-4 py-6 text-center text-ink-500">Загрузка отправок...</td></tr>
                  ) : lastSends.length === 0 ? (
                    <tr><td colSpan={4} className="px-4 py-6 text-center text-ink-500">Отправок пока нет</td></tr>
                  ) : lastSends.map(item => {
                    const when = formatDateTime(item.sent_at)
                    return (
                      <tr key={item.id} className="hover:bg-canvas-50">
                        <td className="px-4 py-2 font-mono text-xs break-all">{item.email}</td>
                        <td className="px-4 py-2 text-ink-500">{item.greeting || '—'}</td>
                        <td className="px-4 py-2">
                          {recipientStatusLabel(item.status) ? <RecipientBadge status={item.status} /> : '—'}
                        </td>
                        <td className="px-4 py-2 text-ink-500 whitespace-nowrap">
                          {when.time || '—'} {when.date && <span className="text-xs">· {when.date}</span>}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          <Card className="p-5">
            <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
              <div>
                <h3 className="font-semibold">Отчёт по кампании</h3>
                <p className="text-sm text-ink-500 mt-1">
                  Сводка и выгрузка по всем получателям (CSV с Authorization-заголовком)
                </p>
              </div>
              <div className="flex items-center gap-2">
                <SecondaryButton type="button" onClick={loadReport} disabled={reportLoading}>
                  {reportLoading ? 'Загрузка...' : 'Обновить отчёт'}
                </SecondaryButton>
                <PrimaryButton type="button" onClick={handleExportCsv} disabled={csvBusy || !canDownloadCsv}>
                  {csvBusy ? 'Скачивание...' : 'Скачать CSV'}
                </PrimaryButton>
              </div>
            </div>

            {csvError && (
              <div className="bg-warn-100 text-warn-600 px-3.5 py-2.5 rounded-lg text-sm mb-3">{csvError}</div>
            )}
            {!canDownloadCsv && (
              <Note className="mb-3">У черновика ещё нет данных для выгрузки — CSV появится после запуска.</Note>
            )}
            <ErrorBox onRetry={loadReport}>{reportError}</ErrorBox>

            {reportLoading && !report ? (
              <p className="text-sm text-ink-500 py-4">Загружаем отчёт...</p>
            ) : report ? (
              <ReportBody report={report} />
            ) : (
              <Note>
                Отчёт откроется автоматически после завершения или остановки кампании. Кнопка «Скачать CSV» работает
                и во время отправки.
              </Note>
            )}
          </Card>
        </div>

        <aside className="space-y-4">
          <Card className="p-4">
            <p className="text-[11px] uppercase tracking-wider text-ink-500 font-medium">Лимит ящика на сегодня</p>
            <p className="mt-1.5 text-lg font-bold">
              {formatMaybeNumber(capabilities?.remaining_today)}
              <span className="text-xs font-normal text-ink-500">
                {Number(capabilities?.daily_limit) > 0 ? ' из ' + formatNumber(capabilities.daily_limit) : ''}
              </span>
            </p>
            <p className="mt-1 text-xs text-ink-500">Обновится в 00:00 МСК. Превышение лимита блокирует отправку на 24 часа.</p>
          </Card>

          <Card className="p-4">
            <h3 className="text-sm font-semibold mb-2">О кампании</h3>
            <dl className="space-y-1.5 text-xs">
              <InfoRow label="Создана" value={formatDateTime(campaign.created_at).date} />
              <InfoRow label="Запущена" value={campaign.started_at ? formatDateTime(campaign.started_at).date : '—'} />
              <InfoRow label="Завершена" value={campaign.finished_at ? formatDateTime(campaign.finished_at).date : '—'} />
              <InfoRow label="Согласие 38-ФЗ" value={campaign.consent_confirmed ? 'подтверждено' : 'нет'} />
              <InfoRow label="Тестовое письмо" value={campaign.test_sent_at ? 'отправлено' : 'нет'} />
              <InfoRow label="В базе" value={formatCount(total)} />
            </dl>
          </Card>

          <Card className="p-4">
            <h3 className="text-sm font-semibold mb-2">Что учитывается</h3>
            <ul className="text-xs text-ink-500 space-y-1.5 list-disc pl-4">
              <li>Ошибки по адресу не останавливают кампанию.</li>
              <li>Отписавшиеся исключаются из следующих рассылок.</li>
              <li>Пауза сохраняет прогресс, «Остановить» — уже необратимо.</li>
            </ul>
          </Card>
        </aside>
      </div>
    </div>
  )
}

// Имя CSV-файла: название кампании без служебных символов. Кириллица в имени
// файла допустима, но кавычки/слэши и переводы строк из названия вырезаем.
function csvFileName(campaign, id) {
  const base = String((campaign && campaign.title) || 'campaign-' + id)
    .replace(/[\\/:*?"<>|\r\n]+/g, ' ')
    .trim()
    .slice(0, 80)
  return (base || 'campaign-' + id) + '.csv'
}

function Counter({ label, value, tone = 'neutral' }) {
  const color = tone === 'ok' ? 'text-ok-600' : tone === 'warn' ? 'text-warn-600' : 'text-ink-900'
  return (
    <div className="rounded-lg border border-line-200 bg-canvas-50 px-3 py-2">
      <p className="text-[11px] uppercase tracking-wider text-ink-500 font-medium">{label}</p>
      <p className={'text-lg font-bold mt-0.5 ' + color}>{formatNumber(value)}</p>
    </div>
  )
}

function InfoRow({ label, value }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-ink-500">{label}</dt>
      <dd className="font-medium text-ink-900 text-right">{value}</dd>
    </div>
  )
}

// Сводка отчёта считается в utils/campaign.js (reportSummaryRows) — там она
// покрыта node-тестами под реальную схему бэкенда. Здесь остаются только списки
// ошибок и пропущенных адресов, которые удобнее рисовать таблицей.
function ReportBody({ report }) {
  const rows = reportSummaryRows(report)
  const errors = Array.isArray(report && report.errors) ? report.errors : []
  const skippedRows = Array.isArray(report && report.skipped) ? report.skipped : []
  const shownErrors = errors.slice(0, 10)
  const shownSkipped = skippedRows.slice(0, 10)

  if (rows.length === 0 && errors.length === 0 && skippedRows.length === 0) {
    return <JsonFallback report={report} />
  }

  return (
    <div>
      {rows.length > 0 && (
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
          {rows.map(([label, value], index) => (
            <div key={label + '-' + index} className="flex justify-between gap-3 py-1 border-b border-line-200/60">
              <dt className="text-ink-500">{label}</dt>
              <dd className="font-semibold text-ink-900">{value}</dd>
            </div>
          ))}
        </dl>
      )}

      {errors.length > 0 && (
        <div className="mt-4">
          <h4 className="text-sm font-semibold mb-2">
            Ошибки доставки <span className="text-xs font-normal text-ink-500">({errors.length})</span>
          </h4>
          <div className="overflow-x-auto border border-line-200 rounded-lg">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-canvas-50 text-ink-500 uppercase tracking-wider">
                  <th className="text-left font-medium px-3 py-1.5">Email</th>
                  <th className="text-left font-medium px-3 py-1.5">Попыток</th>
                  <th className="text-left font-medium px-3 py-1.5">Причина</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line-200">
                {shownErrors.map((item, index) => (
                  <tr key={(item && item.email) || index}>
                    <td className="px-3 py-1.5 font-mono break-all">{item && item.email}</td>
                    <td className="px-3 py-1.5 text-ink-500">{item && item.attempts ? item.attempts : '—'}</td>
                    <td className="px-3 py-1.5 text-ink-500">
                      {(item && (item.error_text || item.error_code)) || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {errors.length > shownErrors.length && (
            <Note className="mt-1.5">
              Показаны первые {shownErrors.length} из {errors.length} — полный список в CSV.
            </Note>
          )}
        </div>
      )}

      {skippedRows.length > 0 && (
        <div className="mt-4">
          <h4 className="text-sm font-semibold mb-2">
            Пропущенные адреса <span className="text-xs font-normal text-ink-500">({skippedRows.length})</span>
          </h4>
          <ul className="text-xs text-ink-500 space-y-1">
            {shownSkipped.map((item, index) => (
              <li key={(item && item.email) || index} className="flex justify-between gap-3 border-b border-line-200/60 py-1">
                <span className="font-mono break-all text-ink-900">{item && item.email}</span>
                <span>{(item && item.reason) || 'пропущен'}</span>
              </li>
            ))}
          </ul>
          {skippedRows.length > shownSkipped.length && (
            <Note className="mt-1.5">Показаны первые {shownSkipped.length} из {skippedRows.length}.</Note>
          )}
        </div>
      )}

      <details className="mt-3">
        <summary className="text-xs text-ink-500 cursor-pointer hover:text-ink-900">Показать все поля отчёта</summary>
        <pre className="mt-2 text-[11px] leading-relaxed bg-canvas-50 border border-line-200 rounded-lg p-3 overflow-auto max-h-48">
{JSON.stringify(report, null, 2)}
        </pre>
      </details>
    </div>
  )
}

function JsonFallback({ report }) {
  return (
    <div>
      <Note className="mb-2">Сервер вернул отчёт в незнакомом формате — показываем как есть.</Note>
      <pre className="text-[11px] leading-relaxed bg-canvas-50 border border-line-200 rounded-lg p-3 overflow-auto max-h-64">
{JSON.stringify(report, null, 2)}
      </pre>
    </div>
  )
}

// ReportBody экспортируется именованно: он не зависит от сети и его рендер
// проверяется в smoke-тесте без поднятия браузера (разные схемы отчёта).
export { ReportBody }
export default CampaignProgress
