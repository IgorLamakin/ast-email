// Список кампаний раздела «Рассылки» (2.7.0, макет screen1.html).
//
// Данные: GET /campaigns. Экран обязан переживать 404 — раздел и его эндпоинты
// пишутся параллельно с фронтендом, и пользователь не должен увидеть белый
// экран, если установлен ещё не обновлённый backend.
import { useState, useEffect, useMemo, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch } from '../api'
import {
  progressPercent,
  formatNumber,
  formatCount,
  formatDateTime,
  campaignErrorMessage,
  campaignTotal,
  campaignSent,
  campaignFailed,
} from '../utils/campaign.js'
import {
  StatusPill,
  CampaignProgressBar,
  Card,
  ErrorBox,
  Note,
} from './CampaignUi.jsx'

// Вкладки-фильтры как в макете. Значения — статусы бэкенда; 'all' — без фильтра.
const TABS = [
  { id: 'all', label: 'Все', statuses: null },
  { id: 'running', label: 'Идут', statuses: ['running'] },
  { id: 'paused', label: 'На паузе', statuses: ['paused'] },
  { id: 'draft', label: 'Черновики', statuses: ['draft'] },
  { id: 'finished', label: 'Завершены', statuses: ['completed', 'finished', 'stopped'] },
]

function Campaigns({ token, capabilities }) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tab, setTab] = useState('all')
  const [query, setQuery] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      // limit=200: бэкенд по умолчанию отдаёт 50 кампаний, а список в интерфейсе
      // показывает всё без серверной пагинации (фильтры и поиск — клиентские).
      const data = await apiFetch('/campaigns?limit=200', { token })
      // Бэкенд по контракту возвращает массив; на всякий случай принимаем и
      // обёртку {items: [...]}, чтобы экран не падал от небольшого расхождения.
      const list = Array.isArray(data) ? data : (Array.isArray(data?.items) ? data.items : [])
      setItems(list)
    } catch (err) {
      setItems([])
      setError(campaignErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    load()
  }, [load])

  const countsByTab = useMemo(() => {
    const counts = {}
    for (const t of TABS) {
      if (!t.statuses) {
        counts[t.id] = items.length
      } else {
        counts[t.id] = items.filter(item => t.statuses.includes(item.status)).length
      }
    }
    return counts
  }, [items])

  const visible = useMemo(() => {
    const activeTab = TABS.find(t => t.id === tab) || TABS[0]
    const search = query.trim().toLowerCase()
    return items.filter(item => {
      if (activeTab.statuses && !activeTab.statuses.includes(item.status)) return false
      if (!search) return true
      const haystack = [item.title, item.template_title, item.sender_email]
        .filter(Boolean).join(' ').toLowerCase()
      return haystack.includes(search)
    })
  }, [items, tab, query])

  // Сводка по всем кампаниям (не по отфильтрованным) — как блок KPI в макете,
  // только без «отписок»: в списке кампаний бэкенд их не отдаёт.
  const summary = useMemo(() => {
    const inWork = items.filter(i => i.status === 'running' || i.status === 'paused')
    const sent = items.reduce((sum, i) => sum + campaignSent(i), 0)
    const failed = items.reduce((sum, i) => sum + campaignFailed(i), 0)
    const delivered = Math.max(0, sent - failed)
    const percent = sent > 0 ? Math.round((delivered / sent) * 100) : 0
    return { inWork: inWork.length, running: inWork.filter(i => i.status === 'running').length, paused: inWork.filter(i => i.status === 'paused').length, sent, failed, delivered, percent }
  }, [items])

  // Остаток дневного лимита из capabilities; если backend ещё не отдал поля —
  // просто не показываем подпись, а не рисуем «undefined / undefined».
  const limitNote = useMemo(() => {
    if (capabilities?.remaining_today === null || capabilities?.remaining_today === undefined) return null
    const limit = Number(capabilities?.daily_limit)
    const remaining = Number(capabilities?.remaining_today)
    if (!Number.isFinite(limit) || limit <= 0 || !Number.isFinite(remaining)) return null
    const used = Math.max(0, limit - Math.max(0, remaining))
    return 'Лимит ящика сегодня: ' + formatNumber(used) + ' / ' + formatNumber(limit) + ' писем'
  }, [capabilities])

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div>
          <h2 className="text-2xl font-bold">Рассылки</h2>
          <p className="text-sm text-ink-500 mt-1">
            Массовые кампании по базе клиентов и партнёров
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={load}
            disabled={loading}
            className="px-4 py-2 rounded-lg border border-line-200 bg-canvas-0 text-ink-900 hover:border-signal-500 text-sm font-medium transition-colors disabled:opacity-50"
          >
            Обновить
          </button>
          <Link
            to="/campaigns/new"
            className="bg-signal-500 hover:bg-signal-600 text-white px-5 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            + Новая рассылка
          </Link>
        </div>
      </div>

      <ErrorBox onRetry={load}>{error}</ErrorBox>

      {!loading && items.length > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
          <div className="bg-canvas-0 border border-line-200 rounded-xl px-4 py-3">
            <p className="text-[11px] uppercase tracking-wider text-ink-500 font-medium">Кампаний в работе</p>
            <p className="mt-1 text-xl font-bold">
              {summary.inWork} <span className="text-xs font-medium text-ink-500">из {items.length}</span>
            </p>
            <p className="text-xs text-ink-500 mt-0.5">
              {summary.running} идёт · {summary.paused} на паузе
            </p>
          </div>
          <div className="bg-canvas-0 border border-line-200 rounded-xl px-4 py-3">
            <p className="text-[11px] uppercase tracking-wider text-ink-500 font-medium">Отправлено писем</p>
            <p className="mt-1 text-xl font-bold">{formatNumber(summary.sent)}</p>
            <p className="text-xs text-ink-500 mt-0.5">{formatCount(summary.sent)} по всем кампаниям</p>
          </div>
          <div className="bg-canvas-0 border border-line-200 rounded-xl px-4 py-3">
            <p className="text-[11px] uppercase tracking-wider text-ink-500 font-medium">Доставляемость</p>
            <p className="mt-1 text-xl font-bold">
              {summary.percent}<span className="text-xs font-medium text-ink-500">%</span>
            </p>
            <p className="text-xs text-ink-500 mt-0.5">
              {formatNumber(summary.delivered)} из {formatNumber(summary.sent)} доставлено
            </p>
          </div>
          <div className="bg-canvas-0 border border-line-200 rounded-xl px-4 py-3">
            <p className="text-[11px] uppercase tracking-wider text-ink-500 font-medium">Ошибок отправки</p>
            <p className={'mt-1 text-xl font-bold ' + (summary.failed > 0 ? 'text-warn-600' : '')}>{formatNumber(summary.failed)}</p>
            <p className="text-xs text-ink-500 mt-0.5">исключены из прогресса</p>
          </div>
        </div>
      )}

      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-b border-line-200">
          <div className="flex flex-wrap items-center gap-1">
            {TABS.map(t => (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                className={
                  'inline-flex items-center gap-1.5 h-8 px-3 rounded-md text-sm transition-colors ' +
                  (tab === t.id ? 'bg-canvas-50 text-ink-900 font-semibold' : 'text-ink-500 hover:text-ink-900 hover:bg-canvas-50')
                }
              >
                {t.label}
                <span className="text-[11px] font-semibold text-ink-500 bg-line-200 rounded-full px-1.5 py-px">{countsByTab[t.id] || 0}</span>
              </button>
            ))}
          </div>
          <input
            type="search"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Поиск по названию или шаблону"
            aria-label="Поиск по названию или шаблону"
            className="w-56 h-8 rounded-lg border border-line-200 px-3 text-sm focus:border-signal-500"
          />
        </div>

        {loading ? (
          <div className="px-4 py-10 text-center text-ink-500 text-sm">Загрузка кампаний...</div>
        ) : visible.length === 0 ? (
          <EmptyState
            hasAny={items.length > 0}
            filtered={items.length > 0}
            onReset={() => { setTab('all'); setQuery('') }}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-canvas-50 text-ink-500">
                  <th className="text-left font-medium px-4 py-2.5 whitespace-nowrap">Название</th>
                  <th className="text-left font-medium px-4 py-2.5 whitespace-nowrap">Шаблон</th>
                  <th className="text-left font-medium px-4 py-2.5 whitespace-nowrap">Получателей</th>
                  <th className="text-left font-medium px-4 py-2.5 whitespace-nowrap">Отправлено</th>
                  <th className="text-left font-medium px-4 py-2.5 whitespace-nowrap">Статус</th>
                  <th className="text-left font-medium px-4 py-2.5 whitespace-nowrap">Дата</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line-200">
                {visible.map(item => {
                  const total = campaignTotal(item)
                  const sent = campaignSent(item)
                  const percent = progressPercent(sent, total)
                  const when = formatDateTime(item.started_at || item.finished_at || item.created_at)
                  return (
                    <tr key={item.id} className="hover:bg-canvas-50 transition-colors">
                      <td className="px-4 py-3 min-w-[220px]">
                        <Link to={'/campaigns/' + item.id} className="font-semibold text-ink-900 hover:text-signal-600">
                          {item.title}
                        </Link>
                        <p className="text-xs text-ink-500 mt-0.5 truncate">
                          {item.sender_email || 'отправитель не выбран'}
                          {campaignFailed(item) > 0 && <span className="text-warn-600"> · ошибок: {formatNumber(campaignFailed(item))}</span>}
                        </p>
                      </td>
                      <td className="px-4 py-3 text-ink-500 min-w-[180px]">
                        <span className="line-clamp-2">{item.template_title || '—'}</span>
                      </td>
                      <td className="px-4 py-3 font-semibold whitespace-nowrap">{formatNumber(total)}</td>
                      <td className="px-4 py-3 min-w-[130px]">
                        <p className="font-semibold whitespace-nowrap">
                          {formatNumber(sent)} <span className="font-normal text-xs text-ink-500">из {formatNumber(total)}</span>
                        </p>
                        <div className="mt-1.5 w-24">
                          <CampaignProgressBar percent={percent} status={item.status} />
                        </div>
                      </td>
                      <td className="px-4 py-3"><StatusPill status={item.status} /></td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <p>{when.date}</p>
                        <p className="text-xs text-ink-500 mt-0.5">{when.time}</p>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-t border-line-200 bg-canvas-50/60 text-xs text-ink-500">
          <span>
            {loading ? 'Загрузка...' : 'Показаны ' + visible.length + ' из ' + items.length + ' кампаний'}
          </span>
          {limitNote && <span>{limitNote}</span>}
        </div>
      </Card>

      <Note className="mt-3">
        Отписки и стоп-лист учитываются при каждом запуске. Кампании старше 90 дней переносятся в архив.
      </Note>
    </div>
  )
}

// Пустое состояние. Отдельный компонент, потому что причин пустоты две:
// кампаний нет вообще и все скрыты фильтром/поиском — подсказки разные.
function EmptyState({ hasAny, filtered, onReset }) {
  if (hasAny && filtered) {
    return (
      <div className="px-4 py-12 text-center">
        <p className="text-ink-900 font-medium mb-1">Ничего не найдено</p>
        <p className="text-sm text-ink-500 mb-4">Измените фильтр или поисковый запрос.</p>
        <button type="button" onClick={onReset} className="text-signal-600 text-sm font-medium hover:opacity-70">
          Сбросить фильтры
        </button>
      </div>
    )
  }
  return (
    <div className="px-4 py-14 text-center">
      <div className="w-12 h-12 mx-auto rounded-full bg-signal-100 flex items-center justify-center mb-3">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" className="w-6 h-6 text-signal-600">
          <path d="M3 11v2a1 1 0 0 0 1 1h2l4 4V6L6 10H4a1 1 0 0 0-1 1Z" /><path d="M15 8a5 5 0 0 1 0 8" /><path d="M18 5a9 9 0 0 1 0 14" />
        </svg>
      </div>
      <p className="text-ink-900 font-medium mb-1">Рассылок пока нет</p>
      <p className="text-sm text-ink-500 mb-4">Создайте первую кампанию: выберите шаблон, загрузите базу и проверьте всё перед запуском.</p>
      <Link to="/campaigns/new" className="inline-block bg-signal-500 hover:bg-signal-600 text-white px-5 py-2 rounded-lg text-sm font-medium transition-colors">
        + Новая рассылка
      </Link>
    </div>
  )
}

export default Campaigns
