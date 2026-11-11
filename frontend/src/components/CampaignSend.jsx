// Шаг 4 мастера: параметры отправки и запуск (2.7.0, макет screen3.html).
//
// Настройки отправляются ДВУМЯ запросами, и это осознанно:
//   PUT  /campaigns/{id}       — темп, лимит, режим, PDF (контракт: только draft);
//   POST /campaigns/{id}/start — сам запуск, тело строго {consent:true}.
// Если backend ещё не умеет PUT (404/405), не блокируем запуск: настройки
// просто останутся серверными по умолчанию, а пользователь увидит предупреждение.
import { useState } from 'react'
import { apiFetch } from '../api'
import {
  PACE_ORDER,
  paceLabel,
  paceDescription,
  paceSeconds,
  clampDailyLimit,
  MIN_DAILY_LIMIT,
  MAX_DAILY_LIMIT,
  DEFAULT_DAILY_LIMIT,
  formatNumber,
  formatMaybeNumber,
  formatCount,
  estimateRemaining,
  campaignErrorMessage,
  campaignTotal,
  campaignFailed,
  campaignSkipped,
} from '../utils/campaign.js'
import {
  Card,
  ErrorBox,
  Note,
  FieldLabel,
  Select,
  TextInput,
  PrimaryButton,
  SecondaryButton,
} from './CampaignUi.jsx'

const SEND_MODES = [
  { id: 'now', label: 'Сейчас', description: 'Начнём сразу после запуска' },
  { id: 'work_hours', label: 'В рабочие часы', description: '09:00–18:00 МСК, выходные пропускаются' },
]

function CampaignSend({ token, campaign, capabilities, consent, onBack, onLaunched }) {
  const settings = campaign?.settings || {}
  const [pace, setPace] = useState(settings.pace || 'safe')
  const [dailyLimit, setDailyLimit] = useState(String(
    clampDailyLimit(settings.daily_limit ?? capabilities?.daily_limit ?? DEFAULT_DAILY_LIMIT)
  ))
  const [sendMode, setSendMode] = useState(settings.send_mode || 'now')
  // PDF по умолчанию выключен: вложение бьёт по доставляемости массовых писем.
  const [attachPdf, setAttachPdf] = useState(Boolean(settings.attach_pdf))
  const [launching, setLaunching] = useState(false)
  const [error, setError] = useState('')
  const [warning, setWarning] = useState('')

  // «К отправке» = база минус уже отвалившиеся адреса. Если бэкенд ещё не
  // посчитал failed/skipped, вычитание нулей ничего не испортит.
  const totalToSend = Math.max(0, campaignTotal(campaign) - campaignFailed(campaign) - campaignSkipped(campaign))
  const limit = clampDailyLimit(dailyLimit)
  const remainingTodayRaw = capabilities?.remaining_today
  const remainingToday = Number(remainingTodayRaw)
  const remainingTodayKnown = remainingTodayRaw !== null && remainingTodayRaw !== undefined && Number.isFinite(remainingToday)
  const limitHint = dailyLimit.trim() !== '' && String(limit) !== dailyLimit.trim()
    ? 'Значение приведено к диапазону ' + MIN_DAILY_LIMIT + '–' + MAX_DAILY_LIMIT
    : remainingTodayKnown
      ? 'Остаток на сегодня — ' + formatNumber(remainingToday) + ' писем'
      : 'Лимит на сутки для одного ящика'

  const handleLaunch = async () => {
    if (!consent) {
      setError('Без подтверждения согласия получателей запуск невозможен')
      return
    }
    setLaunching(true)
    setError('')
    setWarning('')
    try {
      // Сначала сохраняем параметры (best-effort, см. комментарий в шапке файла).
      try {
        await apiFetch('/campaigns/' + campaign.id, {
          method: 'PUT',
          token,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            pace,
            daily_limit: limit,
            send_mode: sendMode,
            attach_pdf: attachPdf,
          }),
        })
      } catch (settingsError) {
        const status = settingsError && settingsError.status
        if (status !== 404 && status !== 405) throw settingsError
        setWarning('Сервер не сохранил параметры (эндпоинт недоступен) — рассылка начнётся со значениями по умолчанию.')
      }

      await apiFetch('/campaigns/' + campaign.id + '/start', {
        method: 'POST',
        token,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ consent: true }),
      })
      onLaunched(campaign.id)
    } catch (err) {
      setError(campaignErrorMessage(err))
    } finally {
      setLaunching(false)
    }
  }

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_290px] gap-4 items-start">
      <div className="space-y-4 min-w-0">
        <Card className="p-5">
          <div className="flex items-start justify-between gap-3 mb-4">
            <div>
              <h3 className="font-semibold">Параметры отправки</h3>
              <p className="text-sm text-ink-500 mt-1">Их можно изменить до первого письма</p>
            </div>
            <span className="text-xs text-ink-500 border border-line-200 rounded-full px-2.5 py-0.5 whitespace-nowrap">шаг 4 из 4</span>
          </div>

          <ErrorBox>{error}</ErrorBox>
          {warning && (
            <div className="bg-[#FBF0D6] text-[#8A6415] px-4 py-2.5 rounded-lg text-sm mb-4">{warning}</div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <label className="block">
              <FieldLabel note={campaign?.template_title ? 'выбран на шаге 1' : undefined}>Шаблон</FieldLabel>
              <div className="w-full rounded-lg border border-line-200 bg-canvas-50 px-3 py-2 text-sm text-ink-900 truncate">
                {campaign?.template_title || '—'}
              </div>
            </label>
            <label className="block">
              <FieldLabel note={campaign?.sender_email ? 'выбран на шаге 1' : undefined}>Отправитель</FieldLabel>
              <div className="w-full rounded-lg border border-line-200 bg-canvas-50 px-3 py-2 text-sm font-mono text-ink-900 truncate">
                {campaign?.sender_email || '—'}
              </div>
            </label>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
            <label className="block">
              <FieldLabel note="рекомендуемый для холодных баз">Темп отправки</FieldLabel>
              <Select value={pace} onChange={e => setPace(e.target.value)}>
                {PACE_ORDER.map(id => (
                  <option key={id} value={id}>{paceLabel(id)}</option>
                ))}
              </Select>
              <Note className="mt-1.5">{paceDescription(pace)}</Note>
            </label>

            <label className="block">
              <FieldLabel note={'максимум ' + MAX_DAILY_LIMIT}>Дневной лимит</FieldLabel>
              <div className="relative">
                <TextInput
                  type="number"
                  min={MIN_DAILY_LIMIT}
                  max={MAX_DAILY_LIMIT}
                  value={dailyLimit}
                  onChange={e => setDailyLimit(e.target.value)}
                  onBlur={() => setDailyLimit(String(clampDailyLimit(dailyLimit)))}
                  className="pr-16"
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-ink-500 pointer-events-none">
                  из {MAX_DAILY_LIMIT}
                </span>
              </div>
              <Note className="mt-1.5">{limitHint}</Note>
            </label>
          </div>

          <div className="mt-4">
            <FieldLabel note="когда отправлять">Расписание</FieldLabel>
            <div className="inline-flex w-full max-w-md bg-canvas-50 rounded-lg p-1 gap-1">
              {SEND_MODES.map(mode => (
                <button
                  key={mode.id}
                  type="button"
                  onClick={() => setSendMode(mode.id)}
                  aria-pressed={sendMode === mode.id}
                  className={
                    'flex-1 h-8 px-2 rounded-md text-xs transition-colors ' +
                    (sendMode === mode.id
                      ? 'bg-canvas-0 text-ink-900 font-semibold shadow-sm'
                      : 'text-ink-500 hover:text-ink-900')
                  }
                >
                  {mode.label}
                </button>
              ))}
            </div>
            <Note className="mt-1.5">{SEND_MODES.find(m => m.id === sendMode)?.description}</Note>
          </div>

          <div className="flex items-center justify-between gap-4 mt-4 px-3 py-2.5 rounded-lg border border-line-200 bg-canvas-50">
            <div className="min-w-0">
              <p className="text-sm text-ink-900">Прикладывать PDF-версию</p>
              <p className="text-xs text-[#8A6415] mt-0.5">
                не рекомендуется для массовых писем — снижает доставляемость
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={attachPdf}
              aria-label="Прикладывать PDF-версию"
              onClick={() => setAttachPdf(value => !value)}
              className={'relative w-9 h-5 rounded-full transition-colors shrink-0 ' + (attachPdf ? 'bg-signal-500' : 'bg-line-200')}
            >
              <span className={'absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all ' + (attachPdf ? 'left-4' : 'left-0.5')} />
            </button>
          </div>

          <div className="flex items-start gap-2.5 mt-4 rounded-lg bg-signal-100/70 border border-signal-500/30 px-3.5 py-3 text-xs text-ink-900">
            <span className="shrink-0 mt-0.5 text-signal-600">⚠</span>
            <p>
              С одного ящика можно отправить <b>не более 300 писем в сутки</b>. Превышение блокирует отправку
              на 24 часа, и блокировка продлевается при каждой новой попытке.
            </p>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 pt-5 mt-5 border-t border-line-200">
            <SecondaryButton type="button" onClick={onBack}>← Назад</SecondaryButton>
            <div className="flex items-center gap-3">
              {!consent && <Note>Согласие 38-ФЗ не подтверждено — вернитесь на шаг проверки.</Note>}
              <PrimaryButton type="button" onClick={handleLaunch} disabled={launching || !consent}>
                {launching ? 'Запуск...' : 'Запустить рассылку'}
              </PrimaryButton>
            </div>
          </div>
        </Card>

        <Card className="px-4 py-3">
          <label className="flex items-start gap-3">
            <input
              type="checkbox"
              checked={consent}
              readOnly
              className="mt-0.5 w-4 h-4 accent-signal-500 shrink-0"
              aria-label="Согласие 38-ФЗ подтверждено"
            />
            <span>
              <span className="block text-sm font-medium text-ink-900">
                Подтверждено: у получателей есть согласие на получение писем (38-ФЗ)
              </span>
              <span className="block text-xs text-ink-500 mt-0.5">
                Галочка поставлена на шаге проверки. В каждом письме — ссылка «Отписаться» и данные отправителя.
              </span>
            </span>
          </label>
        </Card>
      </div>

      <aside className="space-y-4">
        <Card className="p-4">
          <p className="text-[11px] uppercase tracking-wider text-ink-500 font-medium">К отправке</p>
          <p className="mt-1.5 flex items-baseline gap-2">
            <span className="text-3xl font-bold">{formatNumber(totalToSend)}</span>
            <span className="text-sm text-ink-500">{formatCount(totalToSend)}</span>
          </p>
          <div className="h-1.5 rounded bg-line-200 overflow-hidden mt-2">
            <div className="h-full rounded bg-signal-500" style={{ width: '100%' }} />
          </div>
          <p className="mt-2 text-xs text-ink-500">
            ≈ {estimateRemaining(totalToSend, paceSeconds(pace))} при темпе «{paceLabel(pace)}»
          </p>
          <dl className="mt-3 pt-3 border-t border-line-200 space-y-1.5 text-xs">
            <div className="flex justify-between gap-2"><dt className="text-ink-500">Темп</dt><dd className="font-semibold">{paceLabel(pace)}</dd></div>
            <div className="flex justify-between gap-2"><dt className="text-ink-500">Писем в час</dt><dd className="font-semibold">{Math.round(3600 / paceSeconds(pace))}</dd></div>
            <div className="flex justify-between gap-2"><dt className="text-ink-500">Дневной лимит</dt><dd className="font-semibold">{formatNumber(limit)}</dd></div>
            <div className="flex justify-between gap-2"><dt className="text-ink-500">PDF-вложение</dt><dd className="font-semibold">{attachPdf ? 'да' : 'нет'}</dd></div>
          </dl>
        </Card>

        <Card className="p-4">
          <p className="text-[11px] uppercase tracking-wider text-ink-500 font-medium">Лимит ящика на сегодня</p>
          <p className="mt-1.5 text-lg font-bold">
            {formatMaybeNumber(capabilities?.remaining_today)}
            <span className="text-xs font-normal text-ink-500"> / {formatNumber(Number(capabilities?.daily_limit) || MAX_DAILY_LIMIT)}</span>
          </p>
          <p className="mt-1 text-xs text-ink-500">
            Если писем больше остатка, кампания продолжится на следующий день (лимит обновится в 00:00 МСК).
          </p>
        </Card>

        <Card className="p-4">
          <h3 className="text-sm font-semibold mb-2">Что произойдёт после запуска</h3>
          <ul className="text-xs text-ink-500 space-y-1.5 list-disc pl-4">
            <li>Темп «{paceLabel(pace)}»: {paceDescription(pace)}.</li>
            <li>Ошибки по адресу не останавливают кампанию.</li>
            <li>Отписавшиеся автоматически исключаются из следующих рассылок.</li>
            <li>Прогресс и отчёт доступны сразу после старта.</li>
          </ul>
        </Card>
      </aside>
    </div>
  )
}

export default CampaignSend
