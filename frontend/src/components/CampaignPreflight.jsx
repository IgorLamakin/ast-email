// Шаг 3 мастера: проверка перед запуском (2.7.0).
//
// Данные: GET /campaigns/{id}/preflight — чек-лист уровня ok/warn/fail,
// флаг can_start, «сколько к отправке» и остаток дневного лимита.
// Тестовое письмо: POST /campaigns/{id}/test-send.
//
// Почему здесь же чекбокс согласия 38-ФЗ: по закону рассылка без согласия
// получателей запрещена (штрафы до 500 000 ₽), поэтому запуск без галочки
// невозможен, а не спрятан «где-то в настройках». Согласие передаётся в
// POST /start как {consent: true}.
import { useState, useEffect, useCallback } from 'react'
import { apiFetch } from '../api'
import {
  formatNumber,
  formatMaybeNumber,
  formatCount,
  formatDateTime,
  estimateRemaining,
  paceSeconds,
  DEFAULT_PACE,
  campaignErrorMessage,
  campaignTotal,
} from '../utils/campaign.js'
import {
  Card,
  ErrorBox,
  Note,
  PrimaryButton,
  SecondaryButton,
} from './CampaignUi.jsx'

function CampaignPreflight({ token, campaign, capabilities, consent, setConsent, onBack, onNext }) {
  const [preflight, setPreflight] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null) // { type: 'ok' | 'error', text }

  // Бэкенд без ?consent=true считает пункт «Согласие получателей» проваленным
  // (fail), а can_start = отсутствие fail. Поэтому галочка согласия — не только
  // UI-состояние: при её изменении перезапрашиваем чек-лист с consent=true,
  // иначе кнопка «Далее» осталась бы заблокированной навсегда.
  const load = useCallback(async (consentGiven) => {
    setLoading(true)
    setError('')
    try {
      const data = await apiFetch(
        '/campaigns/' + campaign.id + '/preflight?consent=' + (consentGiven ? 'true' : 'false'),
        { token }
      )
      setPreflight(data)
    } catch (err) {
      setPreflight(null)
      setError(campaignErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [campaign.id, token])

  useEffect(() => {
    load(consent)
  }, [load, consent])

  const handleTestSend = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const data = await apiFetch('/campaigns/' + campaign.id + '/test-send', { method: 'POST', token })
      setTestResult({ type: 'ok', text: (data && data.message) || 'Тестовое письмо отправлено' })
      // Признак отправленного теста приходит в preflight/campaign — обновляем
      // чек-лист, чтобы пункт «тест отправлен» перестал быть замечанием.
      load(consent)
    } catch (err) {
      setTestResult({ type: 'error', text: campaignErrorMessage(err) })
    } finally {
      setTesting(false)
    }
  }

  const checks = Array.isArray(preflight?.checks) ? preflight.checks : []
  const okCount = checks.filter(check => check.level === 'ok').length
  const failCount = checks.filter(check => check.level === 'fail').length
  const canStart = Boolean(preflight?.can_start) && failCount === 0
  // Единственный fail «Согласие получателей» — это не дефект кампании, а
  // непоставленная галочка: подсказываем именно её, а не «устраните замечания».
  const consentCheckFailed = checks.some(check => check.id === 'consent' && check.level === 'fail')
  const onlyConsentFailed = failCount === 1 && consentCheckFailed
  const totalToSend = Number(preflight?.total_to_send) || 0
  const remainingToday = preflight?.remaining_today
  const limit = Number(capabilities?.daily_limit) || 0

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_290px] gap-4 items-start">
      <div className="space-y-4 min-w-0">
        <Card className="p-5">
          <div className="flex items-start justify-between gap-3 mb-4">
            <div>
              <h3 className="font-semibold">Проверка перед запуском</h3>
              <p className="text-sm text-ink-500 mt-1">Что уже готово к отправке, а что стоит поправить</p>
            </div>
            <span className="text-xs text-ink-500 border border-line-200 rounded-full px-2.5 py-0.5 whitespace-nowrap">шаг 3 из 4</span>
          </div>

          <ErrorBox onRetry={() => load(consent)}>{error}</ErrorBox>

          {loading ? (
            <p className="text-sm text-ink-500 py-6">Проверяем кампанию...</p>
          ) : checks.length === 0 ? (
            <p className="text-sm text-ink-500 py-6">
              Сервер не вернул пункты проверки. Убедитесь, что установлена актуальная версия backend.
            </p>
          ) : (
            <>
              <ul className="divide-y divide-line-200">
                {checks.map((check, index) => (
                  <li key={check.id || index} className="flex items-start gap-3 py-3">
                    <CheckIcon level={check.level} />
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-ink-900">{check.title || 'Пункт проверки'}</p>
                      {check.detail && <p className="text-xs text-ink-500 mt-0.5">{check.detail}</p>}
                    </div>
                  </li>
                ))}
              </ul>
              <div className="flex items-center justify-between gap-3 mt-4 pt-3 border-t border-line-200 text-xs text-ink-500">
                <span>Пройдено проверок: <b className="text-ink-900">{okCount}</b> из {checks.length}</span>
                <button type="button" onClick={() => load(consent)} className="text-signal-600 font-medium hover:opacity-70">
                  Обновить проверку
                </button>
              </div>
              <Note className="mt-2">
                Замечания (жёлтые) не блокируют запуск, но снижают доставляемость. Красные пункты запуск блокируют.
              </Note>
            </>
          )}

          <div className="mt-5 pt-4 border-t border-line-200">
            <div className="flex flex-wrap items-center gap-3">
              <SecondaryButton type="button" onClick={handleTestSend} disabled={testing}>
                {testing ? 'Отправка...' : 'Отправить тестовое письмо'}
              </SecondaryButton>
              <div className="text-xs text-ink-500">
                {campaign?.test_sent_at
                  ? 'Тестовое письмо отправлено ' + formatDateTime(campaign.test_sent_at).date + ' в ' + formatDateTime(campaign.test_sent_at).time
                  : 'Придёт на ваш адрес и не попадёт в статистику кампании'}
              </div>
            </div>
            {testResult && (
              <div className={'mt-3 text-sm px-3 py-2 rounded-lg ' + (testResult.type === 'ok' ? 'bg-ok-100 text-ok-600' : 'bg-warn-100 text-warn-600')}>
                {testResult.text}
              </div>
            )}
          </div>

          {/* Блок согласия 38-ФЗ. Текст намеренно подробный: человек должен
              понимать, что именно он подтверждает, прежде чем нажать «Запустить». */}
          <label className="flex items-start gap-3 mt-5 pt-5 border-t border-line-200 cursor-pointer">
            <input
              type="checkbox"
              checked={consent}
              onChange={e => setConsent(e.target.checked)}
              className="mt-1 w-4 h-4 accent-signal-500 shrink-0"
            />
            <span>
              <span className="block text-sm font-medium text-ink-900">
                Подтверждаю, что у получателей есть согласие на получение писем (38-ФЗ)
              </span>
              <span className="block text-xs text-ink-500 mt-1 leading-relaxed">
                В каждом письме есть ссылка «Отписаться» и данные отправителя. За рассылку без согласия —
                штраф до 500 000 ₽. Галочка обязательна для запуска и передаётся в запрос старта.
              </span>
            </span>
          </label>

          <div className="flex flex-wrap items-center justify-between gap-3 pt-5 mt-5 border-t border-line-200">
            <SecondaryButton type="button" onClick={onBack}>← Назад</SecondaryButton>
            <div className="flex items-center gap-3">
              {(!canStart || !consent) && (
                <Note>
                  {!consent
                    ? 'Отметьте согласие получателей, чтобы продолжить.'
                    : failCount > 0 && !onlyConsentFailed
                      ? 'Есть блокирующие замечания — устраните их или обновите проверку.'
                      : 'Сервер не разрешает запуск кампании — обновите проверку.'}
                </Note>
              )}
              <PrimaryButton type="button" onClick={onNext} disabled={!canStart || !consent}>
                Далее: отправка →
              </PrimaryButton>
            </div>
          </div>
        </Card>
      </div>

      <aside className="space-y-4">
        <Card className="p-4">
          <p className="text-[11px] uppercase tracking-wider text-ink-500 font-medium">К отправке</p>
          <p className="mt-1.5 flex items-baseline gap-2">
            <span className="text-3xl font-bold">{formatNumber(totalToSend)}</span>
            <span className="text-sm text-ink-500">{formatCount(totalToSend)}</span>
          </p>
          <p className="mt-2 text-xs text-ink-500">
            ≈ {estimateRemaining(totalToSend, paceSeconds(DEFAULT_PACE))} при безопасном темпе
          </p>
          <dl className="mt-3 pt-3 border-t border-line-200 space-y-1.5 text-xs">
            <div className="flex justify-between gap-2"><dt className="text-ink-500">В базе</dt><dd className="font-semibold">{formatNumber(campaignTotal(campaign))}</dd></div>
            <div className="flex justify-between gap-2"><dt className="text-ink-500">Исключено</dt><dd className="font-semibold">{formatNumber(Math.max(0, campaignTotal(campaign) - totalToSend))}</dd></div>
          </dl>
        </Card>

        <Card className="p-4">
          <p className="text-[11px] uppercase tracking-wider text-ink-500 font-medium">Остаток лимита на сегодня</p>
          <p className="mt-1.5 text-lg font-bold">
            {formatMaybeNumber(remainingToday)}
            {limit > 0 && <span className="text-xs font-normal text-ink-500"> из {formatNumber(limit)}</span>}
          </p>
          <p className="mt-1 text-xs text-ink-500">
            Лимит обновляется в 00:00 МСК. Если к отправке больше остатка, кампания продолжится на следующий день.
          </p>
        </Card>

        <Card className="p-4">
          <h3 className="text-sm font-semibold mb-2">Готовность к запуску</h3>
          {loading ? (
            <p className="text-xs text-ink-500">Проверяем...</p>
          ) : (
            <ul className="text-xs space-y-1.5">
              <ReadyRow ok label={'Пройдено проверок: ' + okCount + ' из ' + checks.length} />
              <ReadyRow ok={!error} label={error ? 'Проверка недоступна' : 'Чек-лист получен'} />
              <ReadyRow ok={canStart} label={canStart ? 'Сервер разрешает запуск' : 'Запуск заблокирован'} />
              <ReadyRow ok={consent} label={consent ? 'Согласие 38-ФЗ подтверждено' : 'Согласие не подтверждено'} />
            </ul>
          )}
        </Card>
      </aside>
    </div>
  )
}

// Иконка пункта проверки: зелёная галочка / жёлтый «!» / красный крест.
function CheckIcon({ level }) {
  if (level === 'ok') {
    return (
      <span className="w-5 h-5 rounded-full bg-ok-100 text-ok-600 flex items-center justify-center shrink-0 mt-0.5">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="w-3 h-3">
          <path d="m5 12 5 5L20 7" />
        </svg>
      </span>
    )
  }
  if (level === 'fail') {
    return (
      <span className="w-5 h-5 rounded-full bg-warn-100 text-warn-600 flex items-center justify-center shrink-0 mt-0.5 text-[11px] font-bold">✕</span>
    )
  }
  if (level === 'warn') {
    return (
      <span className="w-5 h-5 rounded-full bg-[#FBF0D6] text-[#8A6415] flex items-center justify-center shrink-0 mt-0.5 text-[11px] font-bold">!</span>
    )
  }
  return <span className="w-5 h-5 rounded-full bg-line-200 text-ink-500 flex items-center justify-center shrink-0 mt-0.5 text-[11px]">?</span>
}

function ReadyRow({ ok, label }) {
  return (
    <li className="flex items-start gap-2">
      <span className={'w-4 h-4 rounded-full flex items-center justify-center shrink-0 mt-0.5 ' + (ok ? 'bg-ok-100 text-ok-600' : 'bg-[#FBF0D6] text-[#8A6415]')}>
        <span className="text-[9px] font-bold">{ok ? '✓' : '!'}</span>
      </span>
      <span className="text-ink-500">{label}</span>
    </li>
  )
}

export default CampaignPreflight
