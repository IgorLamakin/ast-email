// Тесты чистых функций раздела «Рассылки» (2.7.0).
//
// Проверяем не только «счастливый путь»: для каждой функции есть границы
// (0/1/2/5/11/21), деление на ноль и мусорные значения — именно на них чаще
// всего ломаются подписи в интерфейсе.
import { test } from 'node:test'
import assert from 'node:assert'
import {
  statusLabel,
  statusClass,
  progressBarClass,
  isTerminalStatus,
  canPause,
  canResume,
  canStop,
  progressPercent,
  formatRemainingMinutes,
  estimateRemaining,
  paceLabel,
  paceDescription,
  paceSeconds,
  PACE_ORDER,
  DEFAULT_PACE,
  clampDailyLimit,
  MIN_DAILY_LIMIT,
  MAX_DAILY_LIMIT,
  DEFAULT_DAILY_LIMIT,
  formatNumber,
  formatMaybeNumber,
  countWord,
  formatCount,
  formatBytes,
  formatDate,
  formatTime,
  formatDateTime,
  validateEmailLite,
  emailHint,
  recipientStatusLabel,
  recipientStatusClass,
  campaignErrorMessage,
  campaignTotal,
  campaignSent,
  campaignFailed,
  campaignSkipped,
  campaignUnsubscribed,
  reportSummaryRows,
} from '../src/utils/campaign.js'

test('statusLabel: русские подписи всех статусов', () => {
  assert.equal(statusLabel('draft'), 'Черновик')
  assert.equal(statusLabel('running'), 'Идёт')
  assert.equal(statusLabel('paused'), 'Пауза')
  assert.equal(statusLabel('completed'), 'Завершена')
  // Синоним из контракта: старый/новый backend не должны давать «Неизвестно».
  assert.equal(statusLabel('finished'), 'Завершена')
  assert.equal(statusLabel('stopped'), 'Остановлена')
})

test('statusLabel: неизвестные и мусорные статусы не роняют экран', () => {
  assert.equal(statusLabel('archived'), 'Неизвестно')
  assert.equal(statusLabel(''), 'Неизвестно')
  assert.equal(statusLabel(null), 'Неизвестно')
  assert.equal(statusLabel(undefined), 'Неизвестно')
})

test('statusClass: бейджи статусов и фолбэк', () => {
  assert.match(statusClass('running'), /signal-100/)
  assert.match(statusClass('completed'), /ok-100/)
  assert.match(statusClass('finished'), /ok-100/)
  assert.match(statusClass('stopped'), /warn-100/)
  assert.match(statusClass('draft'), /line-200/)
  assert.match(statusClass('paused'), /#FBF0D6/)
  assert.equal(statusClass('nonsense'), statusClass('draft'))
  assert.equal(statusClass(undefined), statusClass('draft'))
})

test('progressBarClass: цвет полосы прогресса по статусу', () => {
  assert.match(progressBarClass('running'), /signal-500/)
  assert.match(progressBarClass('completed'), /ok-600/)
  assert.match(progressBarClass('finished'), /ok-600/)
  assert.match(progressBarClass('stopped'), /warn-600/)
  assert.match(progressBarClass('paused'), /#C08A1E/)
  assert.equal(progressBarClass('unknown'), progressBarClass('draft'))
})

test('терминальные статусы и доступность кнопок', () => {
  assert.equal(isTerminalStatus('completed'), true)
  assert.equal(isTerminalStatus('finished'), true)
  assert.equal(isTerminalStatus('stopped'), true)
  assert.equal(isTerminalStatus('running'), false)
  assert.equal(isTerminalStatus('paused'), false)
  assert.equal(isTerminalStatus('draft'), false)
  assert.equal(isTerminalStatus(undefined), false)

  assert.equal(canPause('running'), true)
  assert.equal(canPause('paused'), false)
  assert.equal(canResume('paused'), true)
  assert.equal(canResume('running'), false)
  assert.equal(canStop('running'), true)
  assert.equal(canStop('paused'), true)
  assert.equal(canStop('finished'), false)
  assert.equal(canStop('draft'), false)
})

test('progressPercent: проценты и деление на ноль', () => {
  assert.equal(progressPercent(0, 0), 0)
  assert.equal(progressPercent(5, 0), 0)
  assert.equal(progressPercent(5, -10), 0)
  assert.equal(progressPercent(0, 100), 0)
  assert.equal(progressPercent(1, 100), 1)
  assert.equal(progressPercent(50, 100), 50)
  assert.equal(progressPercent(1, 3), 33)
  assert.equal(progressPercent(2, 3), 67)
  assert.equal(progressPercent(100, 100), 100)
  assert.equal(progressPercent(200, 100), 100)
  assert.equal(progressPercent(180, 214), 84)
  assert.equal(progressPercent('5', '10'), 50)
  assert.equal(progressPercent(undefined, 100), 0)
  assert.equal(progressPercent(5, undefined), 0)
  assert.equal(progressPercent(5, null), 0)
  assert.equal(progressPercent(-5, 100), 0)
  assert.equal(progressPercent(Number.NaN, 100), 0)
})

test('formatRemainingMinutes: минуты, часы и границы', () => {
  assert.equal(formatRemainingMinutes(0), 'меньше минуты')
  assert.equal(formatRemainingMinutes(0.4), 'меньше минуты')
  assert.equal(formatRemainingMinutes(1), '1 мин')
  assert.equal(formatRemainingMinutes(2), '2 мин')
  assert.equal(formatRemainingMinutes(45), '45 мин')
  assert.equal(formatRemainingMinutes(59), '59 мин')
  assert.equal(formatRemainingMinutes(60), '1 ч')
  assert.equal(formatRemainingMinutes(61), '1 ч 1 мин')
  assert.equal(formatRemainingMinutes(90), '1 ч 30 мин')
  assert.equal(formatRemainingMinutes(160), '2 ч 40 мин')
  assert.equal(formatRemainingMinutes(90.6), '1 ч 31 мин')
  assert.equal(formatRemainingMinutes(1440), '24 ч')
})

test('formatRemainingMinutes: битые значения дают прочерк, а не «0 мин»', () => {
  assert.equal(formatRemainingMinutes(-1), '—')
  assert.equal(formatRemainingMinutes(null), '—')
  assert.equal(formatRemainingMinutes(undefined), '—')
  assert.equal(formatRemainingMinutes('abc'), '—')
  assert.equal(formatRemainingMinutes(Number.NaN), '—')
})

test('estimateRemaining: оценка по количеству писем и паузе', () => {
  assert.equal(estimateRemaining(0, 180), 'меньше минуты')
  assert.equal(estimateRemaining(1, 180), '3 мин')
  assert.equal(estimateRemaining(5, 180), '15 мин')
  assert.equal(estimateRemaining(60, 60), '1 ч')
  assert.equal(estimateRemaining(208, 180), '10 ч 24 мин')
  assert.equal(estimateRemaining(100, 360), '10 ч')
  assert.equal(estimateRemaining('100', '180'), '5 ч')
  // Оценка по реальному темпу из backend PACE_CONFIG: 208 * 32 c ≈ 111 мин.
  assert.equal(estimateRemaining(208, paceSeconds('safe')), '1 ч 51 мин')
  // 30 * 10,4 с = 312 с = 5,2 мин -> округляем вверх до 6 мин.
  assert.equal(estimateRemaining(30, paceSeconds('fast')), '6 мин')
})

test('estimateRemaining: некорректный темп или количество — прочерк', () => {
  assert.equal(estimateRemaining(-1, 180), '—')
  assert.equal(estimateRemaining(null, 180), '—')
  assert.equal(estimateRemaining(100, 0), '—')
  assert.equal(estimateRemaining(100, -60), '—')
  assert.equal(estimateRemaining(100, null), '—')
  assert.equal(estimateRemaining(undefined, undefined), '—')
})

test('paceLabel/paceDescription/paceSeconds: темпы отправки', () => {
  assert.equal(paceLabel('careful'), 'Осторожный')
  assert.equal(paceLabel('safe'), 'Безопасный')
  assert.equal(paceLabel('fast'), 'Быстрый')
  assert.equal(paceLabel('unknown'), 'Безопасный')
  assert.equal(paceLabel(null), 'Безопасный')
  // Значения согласованы с backend/campaign_worker.py (PACE_CONFIG).
  assert.equal(paceSeconds('careful'), 90)
  assert.equal(paceSeconds('safe'), 32)
  assert.equal(paceSeconds('fast'), 10.4)
  assert.equal(paceSeconds('unknown'), 32)
  assert.match(paceDescription('fast'), /8 секунд/)
  assert.match(paceDescription('safe'), /20 секунд/)
  assert.match(paceDescription('careful'), /минуту/)
  assert.match(paceDescription(null), /20 секунд/)
  assert.deepEqual(PACE_ORDER, ['careful', 'safe', 'fast'])
  assert.equal(DEFAULT_PACE, 'safe')
})

test('clampDailyLimit: диапазон 1..300 и дефолт из capabilities', () => {
  assert.equal(MIN_DAILY_LIMIT, 1)
  assert.equal(MAX_DAILY_LIMIT, 300)
  assert.equal(clampDailyLimit(0), DEFAULT_DAILY_LIMIT)
  assert.equal(clampDailyLimit(-5), DEFAULT_DAILY_LIMIT)
  assert.equal(clampDailyLimit(1), 1)
  assert.equal(clampDailyLimit(150), 150)
  assert.equal(clampDailyLimit(150.6), 151)
  assert.equal(clampDailyLimit(300), 300)
  assert.equal(clampDailyLimit(400), 300)
  assert.equal(clampDailyLimit('150'), 150)
  assert.equal(clampDailyLimit(undefined), DEFAULT_DAILY_LIMIT)
  assert.equal(clampDailyLimit(null, 120), 120)
  assert.equal(clampDailyLimit('abc', 120), 120)
  assert.equal(clampDailyLimit(0, 100), 100)
  // Дефолт-фолбэк тоже не должен вылезать за границы.
  assert.equal(clampDailyLimit(0, 1000), MAX_DAILY_LIMIT)
  assert.equal(clampDailyLimit(0, 0), DEFAULT_DAILY_LIMIT)
})

test('formatNumber: разряды через пробел', () => {
  assert.equal(formatNumber(0), '0')
  assert.equal(formatNumber(1), '1')
  assert.equal(formatNumber(999), '999')
  assert.equal(formatNumber(1000), '1 000')
  assert.equal(formatNumber(1066), '1 066')
  assert.equal(formatNumber(1234567), '1 234 567')
  assert.equal(formatNumber(-1500), '-1 500')
  assert.equal(formatNumber('12'), '12')
  assert.equal(formatNumber(null), '0')
  assert.equal(formatNumber(undefined), '0')
  assert.equal(formatNumber(Number.NaN), '0')
})

test('formatMaybeNumber: нет данных — прочерк, а не ноль', () => {
  assert.equal(formatMaybeNumber(0), '0')
  assert.equal(formatMaybeNumber(214), '214')
  assert.equal(formatMaybeNumber(1066), '1 066')
  assert.equal(formatMaybeNumber('42'), '42')
  assert.equal(formatMaybeNumber(null), '—')
  assert.equal(formatMaybeNumber(undefined), '—')
  assert.equal(formatMaybeNumber(''), '—')
  assert.equal(formatMaybeNumber('abc'), '—')
  assert.equal(formatMaybeNumber(Number.NaN), '—')
})

test('countWord: склонение «письмо/письма/писем»', () => {
  assert.equal(countWord(0), 'писем')
  assert.equal(countWord(1), 'письмо')
  assert.equal(countWord(2), 'письма')
  assert.equal(countWord(3), 'письма')
  assert.equal(countWord(5), 'писем')
  assert.equal(countWord(11), 'писем')
  assert.equal(countWord(12), 'писем')
  assert.equal(countWord(14), 'писем')
  assert.equal(countWord(21), 'письмо')
  assert.equal(countWord(22), 'письма')
  assert.equal(countWord(25), 'писем')
  assert.equal(countWord(101), 'письмо')
  assert.equal(countWord(111), 'писем')
  assert.equal(countWord(null), 'писем')
})

test('formatCount: число со склонением', () => {
  assert.equal(formatCount(0), '0 писем')
  assert.equal(formatCount(1), '1 письмо')
  assert.equal(formatCount(2), '2 письма')
  assert.equal(formatCount(5), '5 писем')
  assert.equal(formatCount(11), '11 писем')
  assert.equal(formatCount(21), '21 письмо')
  assert.equal(formatCount(22), '22 письма')
  assert.equal(formatCount(214), '214 писем')
  assert.equal(formatCount(1066), '1 066 писем')
  assert.equal(formatCount(undefined), '0 писем')
})

test('formatBytes: байты, килобайты, мегабайты, гигабайты', () => {
  assert.equal(formatBytes(0), '0 Б')
  assert.equal(formatBytes(512), '512 Б')
  assert.equal(formatBytes(1024), '1 КБ')
  assert.equal(formatBytes(38400), '37,5 КБ')
  assert.equal(formatBytes(1024 * 1024), '1 МБ')
  assert.equal(formatBytes(1024 * 1024 * 1.5), '1,5 МБ')
  assert.equal(formatBytes(1024 * 1024 * 1024), '1 ГБ')
  assert.equal(formatBytes(null), '—')
  assert.equal(formatBytes(-5), '—')
  assert.equal(formatBytes('abc'), '—')
})

test('formatDate/formatTime: ISO-строки без сдвига дня', () => {
  assert.equal(formatDate('2026-11-11T09:40:00'), '11.11.2026')
  assert.equal(formatTime('2026-11-11T09:40:00'), '09:40')
  assert.equal(formatDate('2026-01-05'), '05.01.2026')
  assert.equal(formatTime('2026-01-05'), '00:00')
  // «Z» не должен сдвигать дату: разбираем компоненты как есть.
  assert.equal(formatDate('2026-01-05T23:05:00Z'), '05.01.2026')
  assert.equal(formatTime('2026-01-05T23:05:00Z'), '23:05')
  assert.equal(formatDate(''), '—')
  assert.equal(formatDate(null), '—')
  assert.equal(formatDate('not-a-date'), '—')
  assert.equal(formatTime(''), '')
  assert.deepEqual(formatDateTime('2026-11-11T09:40:00'), { date: '11.11.2026', time: '09:40' })
  assert.deepEqual(formatDateTime(null), { date: '—', time: '' })
})

test('validateEmailLite: ручное добавление адреса', () => {
  assert.equal(validateEmailLite('a@b.ru'), true)
  assert.equal(validateEmailLite('a.b+c@sub.domain.ru'), true)
  assert.equal(validateEmailLite(' user@mail.ru '), true)
  assert.equal(validateEmailLite('n.fedorova@agregat-prom'), false)
  assert.equal(validateEmailLite('a@b'), false)
  assert.equal(validateEmailLite('a@@b.ru'), false)
  assert.equal(validateEmailLite('a b@c.ru'), false)
  assert.equal(validateEmailLite('@b.ru'), false)
  assert.equal(validateEmailLite('a@.ru'), false)
  assert.equal(validateEmailLite(''), false)
  assert.equal(validateEmailLite(null), false)
  assert.equal(validateEmailLite(undefined), false)
  assert.equal(validateEmailLite('a@' + 'b'.repeat(300) + '.ru'), false)
})

test('emailHint: понятная причина вместо «неверный email»', () => {
  assert.match(emailHint(''), /Введите адрес/)
  assert.match(emailHint('a b@c.ru'), /пробелов/)
  assert.match(emailHint('abc'), /нет «@»/)
  assert.match(emailHint('a@@b.ru'), /одна «@»/)
  assert.match(emailHint('a@'), /домен/)
  assert.match(emailHint('a@b'), /точка/)
  assert.match(emailHint('a@b.ru'), /^$/)
  assert.equal(emailHint('a@b.ru'), '')
})

test('recipientStatusLabel/recipientStatusClass: статусы получателей', () => {
  assert.equal(recipientStatusLabel('ok'), 'OK')
  assert.equal(recipientStatusLabel('valid'), 'Валидный')
  assert.equal(recipientStatusLabel('sending'), 'Отправляется')
  assert.equal(recipientStatusLabel('unknown'), 'Неизвестно')
  assert.equal(recipientStatusLabel('duplicate'), 'Дубль')
  assert.equal(recipientStatusLabel('invalid'), 'Ошибка')
  assert.equal(recipientStatusLabel('unsubscribed'), 'Отписался')
  assert.equal(recipientStatusLabel('sent'), 'Отправлено')
  assert.equal(recipientStatusLabel('failed'), 'Ошибка')
  assert.equal(recipientStatusLabel('skipped'), 'Пропущено')
  assert.equal(recipientStatusLabel('pending'), 'Ожидает')
  assert.equal(recipientStatusLabel('???'), '')
  assert.match(recipientStatusClass('duplicate'), /#FBF0D6/)
  assert.match(recipientStatusClass('invalid'), /warn-100/)
  assert.equal(recipientStatusClass('???'), recipientStatusClass('pending'))
})

test('счётчики кампании: короткие имена и *_count', () => {
  assert.equal(campaignTotal({ total: 214 }), 214)
  assert.equal(campaignTotal({ total_count: 214 }), 214)
  // Короткое имя приоритетнее даже нулевое — это актуальное значение карточки.
  assert.equal(campaignTotal({ total: 0, total_count: 5 }), 0)
  assert.equal(campaignSent({ sent: 10 }), 10)
  assert.equal(campaignSent({ sent_count: 11 }), 11)
  assert.equal(campaignFailed({ failed: 3 }), 3)
  assert.equal(campaignFailed({ failed_count: 4 }), 4)
  assert.equal(campaignSkipped({ skipped: 1 }), 1)
  assert.equal(campaignSkipped({ skipped_count: 2 }), 2)
  assert.equal(campaignUnsubscribed({ unsubscribed: 7 }), 7)
  assert.equal(campaignUnsubscribed({ unsubscribed_count: 8 }), 8)
  // Нет данных — 0, а не NaN в прогрессе.
  assert.equal(campaignTotal(null), 0)
  assert.equal(campaignTotal({}), 0)
  assert.equal(campaignTotal({ total: 'abc' }), 0)
  assert.equal(campaignSent(undefined), 0)
  assert.equal(campaignUnsubscribed({}), 0)
})

test('reportSummaryRows: реальная схема отчёта (campaign + counts)', () => {
  const report = {
    campaign: { total_count: 214, sent_count: 180, failed_count: 2, skipped_count: 3, status: 'completed' },
    counts: { total: 214, pending: 29, sent: 180, failed: 2, skipped: 3, unknown: 0 },
    remaining_today: 128,
    started_at: '2026-11-11T09:40:00',
    finished_at: '2026-11-11T11:20:00',
  }
  const rows = reportSummaryRows(report)
  const map = Object.fromEntries(rows)
  assert.equal(map['Всего получателей'], '214')
  assert.equal(map['Отправлено'], '180')
  assert.equal(map['Ошибок доставки'], '2')
  assert.equal(map['Пропущено (отписки/стоп-лист)'], '3')
  assert.equal(map['Осталось в очереди'], '29')
  assert.equal(map['Остаток лимита на сегодня'], '128')
  assert.equal(map['Начало'], '11.11.2026 09:40')
  assert.equal(map['Завершение'], '11.11.2026 11:20')
  // При наличии campaign дублирующих строк из counts быть не должно.
  assert.equal(rows.filter(([label]) => label === 'Отправлено').length, 1)
})

test('reportSummaryRows: только counts и плоский ответ', () => {
  const countsOnly = reportSummaryRows({ counts: { total: 10, pending: 4, sent: 5, failed: 1, skipped: 0 } })
  const map = Object.fromEntries(countsOnly)
  assert.equal(map['Всего получателей'], '10')
  assert.equal(map['Ожидает отправки'], '4')
  assert.equal(map['Отправлено'], '5')
  assert.equal(map['Ошибок доставки'], '1')

  const flat = reportSummaryRows({ total: 100, sent: 90, failed: 5, duration_seconds: 3900 })
  const flatMap = Object.fromEntries(flat)
  assert.equal(flatMap['Всего получателей'], '100')
  assert.equal(flatMap['Отправлено'], '90')
  assert.equal(flatMap['Длительность'], '1 ч 5 мин')
})

test('reportSummaryRows: мусор и пустой отчёт', () => {
  assert.deepEqual(reportSummaryRows(null), [])
  assert.deepEqual(reportSummaryRows(undefined), [])
  assert.deepEqual(reportSummaryRows('текст'), [])
  assert.deepEqual(reportSummaryRows([]), [])
  assert.deepEqual(reportSummaryRows({}), [])
})

test('campaignErrorMessage: 404/403/0 и обычные ошибки', () => {
  assert.match(campaignErrorMessage({ status: 404 }), /серверная часть/)
  assert.match(campaignErrorMessage({ status: 403 }), /Недостаточно прав/)
  assert.match(campaignErrorMessage({ status: 401 }), /Сессия истекла/)
  assert.match(campaignErrorMessage({ status: 413 }), /слишком большой/)
  assert.match(campaignErrorMessage({ status: 0 }), /Сервер не отвечает/)
  assert.equal(campaignErrorMessage({ status: 500, message: 'Внутренняя ошибка' }), 'Внутренняя ошибка')
  assert.equal(campaignErrorMessage(null), 'Не удалось выполнить запрос')
});
test('campaignErrorMessage: 404 на конкретную кампанию - «не найдена»', () => {
  // Регрессия D1 (QA 2.7.0): удалённая кампания показывала «серверная часть ещё
  // не обновлена», что вводит в заблуждение.
  assert.match(campaignErrorMessage({ status: 404 }, { resource: 'campaign' }), /не найдена/)
  assert.match(
    campaignErrorMessage({ status: 404, data: { detail: 'Campaign not found' } }),
    /не найдена/
  )
  // Без контекста 404 - это по-прежнему «нет раздела» (старый backend).
  assert.match(campaignErrorMessage({ status: 404 }), /серверная часть/)
  assert.match(
    campaignErrorMessage({ status: 404, data: { detail: 'Not Found' } }),
    /серверная часть/
  )
})
