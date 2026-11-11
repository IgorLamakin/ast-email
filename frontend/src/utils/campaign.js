// Чистые функции раздела «Рассылки» (2.7.0).
//
// Почему отдельный модуль: почти все подписи на экранах рассылок считаются из
// чисел бэкенда («осталось ~2 ч 40 мин», «84 %», «1 066 писем»), и ошибка в
// такой формуле не видна до ручной проверки собранного приложения. Функции без
// React и без DOM, поэтому покрыты node-тестами (frontend/tests/campaign-utils.test.js).
//
// Модуль ничего не импортирует из api.js: его тянут только компоненты и тесты.
import { pluralRu } from './plural.js'

// --- Статусы кампании -------------------------------------------------------
// Значения приходят с бэкенда строкой (см. контракт GET /campaigns).
// Русские подписи и цвета бейджей живут здесь, а не в JSX, чтобы список,
// экран прогресса и мастер показывали одно и то же.

// 'completed' — фактическое значение с бэкенда (models.CampaignStatus),
// 'finished' оставлен синонимом: контракт в задаче называл статус так, и
// старые ответы не должны показывать «Неизвестно».
const STATUS_LABELS = {
  draft: 'Черновик',
  running: 'Идёт',
  paused: 'Пауза',
  completed: 'Завершена',
  finished: 'Завершена',
  stopped: 'Остановлена',
}

// Классы для «таблетки» статуса. Палитра проекта: canvas/line/ink/signal/ok/warn.
// Янтарного цвета в tailwind.config.js нет, поэтому для паузы берём точные
// значения из макета (screen1.html) произвольными классами Tailwind.
const STATUS_CLASSES = {
  draft: 'bg-line-200 text-ink-500',
  running: 'bg-signal-100 text-signal-600',
  paused: 'bg-[#FBF0D6] text-[#8A6415]',
  completed: 'bg-ok-100 text-ok-600',
  finished: 'bg-ok-100 text-ok-600',
  stopped: 'bg-warn-100 text-warn-600',
}

// Цвет полосы прогресса в списке кампаний: завершённые — зелёные, пауза —
// янтарная, остановленные — красные, черновики — серые.
const STATUS_BAR_CLASSES = {
  draft: 'bg-[#C6CDD6]',
  running: 'bg-signal-500',
  paused: 'bg-[#C08A1E]',
  completed: 'bg-ok-600',
  finished: 'bg-ok-600',
  stopped: 'bg-warn-600',
}

const TERMINAL_STATUSES = ['completed', 'finished', 'stopped']

/** Подпись статуса кампании. Неизвестное значение не роняет экран. */
export function statusLabel(status) {
  return STATUS_LABELS[status] || 'Неизвестно'
}

/** CSS-классы бейджа статуса (фон + цвет текста). */
export function statusClass(status) {
  return STATUS_CLASSES[status] || STATUS_CLASSES.draft
}

/** CSS-классы полосы прогресса под статус кампании. */
export function progressBarClass(status) {
  return STATUS_BAR_CLASSES[status] || STATUS_BAR_CLASSES.draft
}

/**
 * Терминальный статус (кампания больше не меняется). Нужен, чтобы экран
 * прогресса прекращал опрос раз в 4 секунды после завершения или остановки —
 * иначе приложение «стучалось» бы в бэкенд бесконечно.
 */
export function isTerminalStatus(status) {
  return TERMINAL_STATUSES.includes(status)
}

/** Статусы, при которых имеет смысл пауза (кампания сейчас отправляется). */
export function canPause(status) {
  return status === 'running'
}

/** Статусы, при которых имеет смысл продолжение. */
export function canResume(status) {
  return status === 'paused'
}

/** Статусы, при которых имеет смысл остановка. */
export function canStop(status) {
  return status === 'running' || status === 'paused'
}

// --- Темп отправки ----------------------------------------------------------
// pace приходит с бэкенда как 'careful' | 'safe' | 'fast'. Значения взяты из
// backend/campaign_worker.py (PACE_CONFIG): там темп — это пауза между письмами
// плюс длинная пауза после каждой пачки. Чтобы оценка «осталось ~…» не врала в
// разы, secondsPerEmail считаем как среднее на письмо:
//   careful: 60 с + 900 с / 30 писем = 90 с
//   safe:    20 с + 300 с / 25 писем = 32 с
//   fast:     8 с + 120 с / 50 писем = 10,4 с
// (Сравните с макетами, где темп описан консервативнее — реальный воркер
// работает именно так, и подписи должны совпадать с ним, а не с макетом.)

export const PACE_PRESETS = {
  careful: {
    label: 'Осторожный',
    description: 'письмо раз в минуту, пауза 15 мин после каждых 30 — для холодных баз',
    secondsPerEmail: 90,
  },
  safe: {
    label: 'Безопасный',
    description: 'письмо раз в 20 секунд, пауза 5 мин после каждых 25 — рекомендуемый',
    secondsPerEmail: 32,
  },
  fast: {
    label: 'Быстрый',
    description: 'письмо раз в 8 секунд, пауза 2 мин после каждых 50 — только для своих клиентов',
    secondsPerEmail: 10.4,
  },
}

export const PACE_ORDER = ['careful', 'safe', 'fast']
export const DEFAULT_PACE = 'safe'

/** Русская подпись темпа. Неизвестный темп считаем безопасным (дефолт). */
export function paceLabel(pace) {
  const preset = PACE_PRESETS[pace]
  return (preset || PACE_PRESETS[DEFAULT_PACE]).label
}

/** Пояснение под темпом: сколько писем в час и какая пауза между ними. */
export function paceDescription(pace) {
  const preset = PACE_PRESETS[pace]
  return (preset || PACE_PRESETS[DEFAULT_PACE]).description
}

/** Пауза между письмами в секундах. Неизвестный темп — как у безопасного. */
export function paceSeconds(pace) {
  const preset = PACE_PRESETS[pace]
  return (preset || PACE_PRESETS[DEFAULT_PACE]).secondsPerEmail
}

// --- Дневной лимит ----------------------------------------------------------
// Лимит одного ящика — 300 писем в сутки (ограничение Яндекс SMTP, см. макет).
// Значение проверяем и на клиенте: бэкенд вернёт 422, но пользователю нужнее
// понятная подпись рядом с полем, а не техническая ошибка.

export const MIN_DAILY_LIMIT = 1
export const MAX_DAILY_LIMIT = 300
export const DEFAULT_DAILY_LIMIT = 250

/**
 * Приводит ввод дневного лимита к числу в диапазоне 1..300.
 * Пустое/нечисловое значение заменяется дефолтом, а не нулём: ноль означал бы
 * «не отправлять ничего», хотя пользователь просто стёр поле.
 */
export function clampDailyLimit(value, fallback = DEFAULT_DAILY_LIMIT) {
  const fallbackValue = Number.isFinite(Number(fallback)) ? Number(fallback) : DEFAULT_DAILY_LIMIT
  const base = fallbackValue > 0 ? Math.round(fallbackValue) : DEFAULT_DAILY_LIMIT
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return Math.min(MAX_DAILY_LIMIT, Math.max(MIN_DAILY_LIMIT, base))
  return Math.min(MAX_DAILY_LIMIT, Math.max(MIN_DAILY_LIMIT, Math.round(n)))
}

// --- Числа, проценты, длительности -----------------------------------------

// «Неизвестно» и «ноль» — разные вещи: пустое поле/отсутствующее значение
// должно показывать прочерк, а не «0 мин» или «0 Б». Поэтому для длительностей
// и размеров отдельно отсекаем null/undefined/пустую строку (Number(null) === 0
// дал бы ложный «ноль»).
function toFiniteOrNaN(value) {
  if (value === null || value === undefined || value === '') return Number.NaN
  const n = Number(value)
  return Number.isFinite(n) ? n : Number.NaN
}

/** Процент отправленных писем. Деление на 0 и мусор дают 0, не NaN. */
export function progressPercent(sent, total) {
  const s = Number(sent)
  const t = Number(total)
  if (!Number.isFinite(t) || t <= 0) return 0
  if (!Number.isFinite(s) || s <= 0) return 0
  const percent = (s / t) * 100
  if (percent >= 100) return 100
  return Math.round(percent)
}

/**
 * Человеческая длительность по количеству минут: «2 ч 40 мин», «45 мин»,
 * «меньше минуты». Отрицательное/битое значение — «—» (не «0 мин»: так видно,
 * что оценка недоступна, а не что рассылка закончилась).
 */
export function formatRemainingMinutes(minutes) {
  const m = toFiniteOrNaN(minutes)
  if (Number.isNaN(m) || m < 0) return '—'
  if (m < 1) return 'меньше минуты'
  const total = Math.round(m)
  if (total < 60) return total + ' мин'
  const hours = Math.floor(total / 60)
  const rest = total % 60
  return rest === 0 ? hours + ' ч' : hours + ' ч ' + rest + ' мин'
}

/**
 * Оценка «осталось ~…»: сколько писем осталось и пауза между письмами (сек).
 * Ноль писем — «меньше минуты», битый темп — «—».
 */
export function estimateRemaining(remaining, paceSecondsValue) {
  const r = toFiniteOrNaN(remaining)
  const s = toFiniteOrNaN(paceSecondsValue)
  if (Number.isNaN(r) || r < 0) return '—'
  if (Number.isNaN(s) || s <= 0) return '—'
  return formatRemainingMinutes(Math.ceil((r * s) / 60))
}

// --- Форматирование ---------------------------------------------------------

/** Русское число с пробелами между разрядами: 1066 -> «1 066». */
export function formatNumber(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '0'
  const rounded = Math.round(n)
  const sign = rounded < 0 ? '-' : ''
  const digits = String(Math.abs(rounded))
  return sign + digits.replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
}

/**
 * Число для подписи, где отсутствие данных должно показывать «—», а не «0»:
 * остаток лимита, счётчики из ещё не заполненного ответа. Number(null) === 0,
 * поэтому без отдельной проверки пустое значение выглядело бы как реальный ноль.
 */
export function formatMaybeNumber(value) {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  return Number.isFinite(n) ? formatNumber(n) : '—'
}

/** Слово «письмо/письма/писем» для числа. */
export function countWord(count) {
  const n = Number(count)
  if (!Number.isFinite(n)) return 'писем'
  return pluralRu(n, 'письмо', 'письма', 'писем')
}

/** «1 письмо», «2 письма», «1 066 писем» — для подписей под счётчиками. */
export function formatCount(count) {
  const n = Number(count)
  if (!Number.isFinite(n)) return '0 писем'
  return formatNumber(n) + ' ' + countWord(n)
}

// Десятичный разделитель в русской локали — запятая. Отдельная функция, чтобы
// formatBytes не тянул Intl (в Electron и в node-тестах он может вести себя
// по-разному из-за разных ICU).
function formatDecimalRu(value) {
  const rounded = Math.round(value * 10) / 10
  return String(rounded).replace('.', ',')
}

/** Размер файла для подписи под загруженным Excel: «37,5 КБ». */
export function formatBytes(bytes) {
  const b = toFiniteOrNaN(bytes)
  if (Number.isNaN(b) || b < 0) return '—'
  if (b < 1024) return Math.round(b) + ' Б'
  const kb = b / 1024
  if (kb < 1024) return formatDecimalRu(kb) + ' КБ'
  const mb = kb / 1024
  if (mb < 1024) return formatDecimalRu(mb) + ' МБ'
  return formatDecimalRu(mb / 1024) + ' ГБ'
}

// --- Счётчики кампании ------------------------------------------------------
// Бэкенд отдаёт счётчики в списке как *_count (total_count/sent_count), а в
// карточке кампании по контракту ещё и короткими именами (total/sent/failed/
// skipped). Читаем оба варианта: расхождение в именах не должно превращать
// прогресс кампании в NaN.

function readCount(campaign, shortKey, longKey) {
  if (!campaign) return 0
  // Короткое имя приоритетнее: если бэкенд его прислал (даже нулём), значит
  // это актуальное значение, а *_count — устаревший дубль из списка.
  const hasShort = campaign[shortKey] !== undefined && campaign[shortKey] !== null
  const value = hasShort ? campaign[shortKey] : campaign[longKey]
  const n = Number(value)
  return Number.isFinite(n) && n > 0 ? n : 0
}

export function campaignTotal(campaign) { return readCount(campaign, 'total', 'total_count') }
export function campaignSent(campaign) { return readCount(campaign, 'sent', 'sent_count') }
export function campaignFailed(campaign) { return readCount(campaign, 'failed', 'failed_count') }
export function campaignSkipped(campaign) { return readCount(campaign, 'skipped', 'skipped_count') }
export function campaignUnsubscribed(campaign) { return readCount(campaign, 'unsubscribed', 'unsubscribed_count') }

// --- Даты -------------------------------------------------------------------
// Бэкенд отдаёт ISO-строки. Специально разбираем их по компонентам, а не через
// new Date('2026-11-11'), который трактует дату без времени как UTC и в
// западных часовых поясах сдвигает день назад. Отображение должно быть
// предсказуемым и в тестах, и на машине пользователя.

const ISO_PARTS_RE = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/

function parseDate(value) {
  if (!value) return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  const raw = String(value)
  const match = raw.match(ISO_PARTS_RE)
  if (match) {
    const date = new Date(
      Number(match[1]),
      Number(match[2]) - 1,
      Number(match[3]),
      match[4] ? Number(match[4]) : 0,
      match[5] ? Number(match[5]) : 0,
    )
    return Number.isNaN(date.getTime()) ? null : date
  }
  const parsed = new Date(raw)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function pad2(n) {
  return String(n).padStart(2, '0')
}

/** «11.11.2026» или «—». */
export function formatDate(value) {
  const date = parseDate(value)
  if (!date) return '—'
  return pad2(date.getDate()) + '.' + pad2(date.getMonth() + 1) + '.' + date.getFullYear()
}

/** «09:40» или «». */
export function formatTime(value) {
  const date = parseDate(value)
  if (!date) return ''
  return pad2(date.getHours()) + ':' + pad2(date.getMinutes())
}

/** Пара для двухстрочной ячейки даты в таблице: { date, time }. */
export function formatDateTime(value) {
  return { date: formatDate(value), time: formatTime(value) }
}

// --- Email и статусы получателей -------------------------------------------

// Намеренно мягкая проверка: окончательное решение всё равно за бэкендом
// (там нормализация, список отписок и стоп-лист). Но в мастере нельзя дать
// человеку отправить заведомо битый адрес.
const EMAIL_RE = /^[^\s@]+@[^\s@.]+(\.[^\s@.]+)+$/

/** true, если строка похожа на email (для ручного добавления получателя). */
export function validateEmailLite(value) {
  const email = String(value == null ? '' : value).trim()
  if (!email || email.length > 254) return false
  return EMAIL_RE.test(email)
}

/**
 * Понятная подпись к полю email: пустая строка = ошибки нет.
 * Разбираем типичные опечатки по отдельности, чтобы человек видел причину.
 */
export function emailHint(value) {
  const email = String(value == null ? '' : value).trim()
  if (!email) return 'Введите адрес вида name@company.ru'
  if (/\s/.test(email)) return 'Адрес не должен содержать пробелов'
  const atCount = (email.match(/@/g) || []).length
  if (atCount === 0) return 'В адресе нет «@»'
  if (atCount > 1) return 'В адресе должна быть одна «@»'
  const domain = email.slice(email.indexOf('@') + 1)
  if (!domain) return 'После «@» нужен домен'
  if (!domain.includes('.')) return 'В домене нужна хотя бы одна точка'
  if (!validateEmailLite(email)) return 'Похоже, это не email — пример: name@company.ru'
  return ''
}

// Статусы получателей: значения бэкенда (pending/sending/sent/failed/unknown/
// skipped) плюс статусы строк файла при импорте (ok/duplicate/invalid/
// unsubscribed) — превью на шаге 2 приходит именно с ними.
const RECIPIENT_STATUS_LABELS = {
  ok: 'OK',
  valid: 'Валидный',
  pending: 'Ожидает',
  sending: 'Отправляется',
  sent: 'Отправлено',
  failed: 'Ошибка',
  unknown: 'Неизвестно',
  skipped: 'Пропущено',
  duplicate: 'Дубль',
  invalid: 'Ошибка',
  unsubscribed: 'Отписался',
}

const RECIPIENT_STATUS_CLASSES = {
  ok: 'bg-ok-100 text-ok-600',
  valid: 'bg-ok-100 text-ok-600',
  pending: 'bg-line-200 text-ink-500',
  sending: 'bg-signal-100 text-signal-600',
  sent: 'bg-ok-100 text-ok-600',
  failed: 'bg-warn-100 text-warn-600',
  unknown: 'bg-[#FBF0D6] text-[#8A6415]',
  skipped: 'bg-line-200 text-ink-500',
  duplicate: 'bg-[#FBF0D6] text-[#8A6415]',
  invalid: 'bg-warn-100 text-warn-600',
  unsubscribed: 'bg-line-200 text-ink-500',
}

/** Подпись статуса получателя (в превью импорта и таблице последних отправок). */
export function recipientStatusLabel(status) {
  return RECIPIENT_STATUS_LABELS[status] || ''
}

/** CSS-классы бейджа статуса получателя. */
export function recipientStatusClass(status) {
  return RECIPIENT_STATUS_CLASSES[status] || 'bg-line-200 text-ink-500'
}

// --- Отчёт по кампании ------------------------------------------------------
// Реальная схема GET /campaigns/{id}/report (2.7.0):
//   {campaign, counts, by_status, errors, skipped, remaining_today}
// counts = {total, pending, sent, failed, skipped, unknown}.
// Формируем пары «подпись — значение» здесь, а не в JSX: так их можно проверить
// node-тестами, не поднимая браузер (схема отчёта менялась не раз).

export const REPORT_COUNT_LABELS = {
  total: 'Всего получателей',
  pending: 'Ожидает отправки',
  sending: 'Отправляется сейчас',
  sent: 'Отправлено',
  failed: 'Ошибок доставки',
  skipped: 'Пропущено (отписки/стоп-лист)',
  unknown: 'Неизвестно',
  delivered: 'Доставлено',
  unsubscribed: 'Отписались',
  opened: 'Открыли',
  clicked: 'Перешли по ссылке',
}

const FLAT_REPORT_LABELS = {
  total: 'Всего получателей',
  recipients: 'Всего получателей',
  sent: 'Отправлено',
  delivered: 'Доставлено',
  failed: 'Ошибок доставки',
  skipped: 'Пропущено',
  unsubscribed: 'Отписались',
}

/**
 * Сводка отчёта: массив пар [подпись, готовое значение].
 * Понимает три вида ответа: реальный (campaign + counts), только counts и
 * «плоский» (total/sent/... из контракта). Незнакомый ответ даёт пустой массив —
 * экран покажет JSON, а не выдуманные нули.
 */
export function reportSummaryRows(report) {
  if (!report || typeof report !== 'object' || Array.isArray(report)) return []
  const rows = []
  const campaign = report.campaign && typeof report.campaign === 'object' ? report.campaign : null
  const counts = report.counts && typeof report.counts === 'object' ? report.counts : null

  if (campaign) {
    const total = campaignTotal(campaign)
    const sent = campaignSent(campaign)
    const failed = campaignFailed(campaign)
    const skipped = campaignSkipped(campaign)
    rows.push(['Всего получателей', formatNumber(total)])
    rows.push(['Отправлено', formatNumber(sent)])
    rows.push(['Ошибок доставки', formatNumber(failed)])
    rows.push(['Пропущено (отписки/стоп-лист)', formatNumber(skipped)])
    rows.push(['Осталось в очереди', formatNumber(Math.max(0, total - sent - failed - skipped))])
  } else if (counts) {
    for (const [key, label] of Object.entries(REPORT_COUNT_LABELS)) {
      if (counts[key] !== undefined && counts[key] !== null) {
        rows.push([label, formatNumber(counts[key])])
      }
    }
  } else {
    for (const [key, label] of Object.entries(FLAT_REPORT_LABELS)) {
      if (report[key] !== undefined && report[key] !== null) {
        rows.push([label, formatNumber(report[key])])
      }
    }
  }

  if (report.started_at !== undefined && report.started_at !== null) {
    const when = formatDateTime(report.started_at)
    rows.push(['Начало', (when.date + ' ' + when.time).trim()])
  }
  if (report.finished_at !== undefined && report.finished_at !== null) {
    const when = formatDateTime(report.finished_at)
    rows.push(['Завершение', (when.date + ' ' + when.time).trim()])
  }
  if (report.duration_seconds !== undefined && report.duration_seconds !== null) {
    rows.push(['Длительность', formatRemainingMinutes(Number(report.duration_seconds) / 60)])
  }
  if (report.remaining_today !== undefined && report.remaining_today !== null) {
    rows.push(['Остаток лимита на сегодня', formatMaybeNumber(report.remaining_today)])
  }
  return rows
}

// --- Ошибки API -------------------------------------------------------------

/**
 * Понятное сообщение вместо технического «Ошибка запроса (404)».
 * 404 на /campaigns значит, что установлен старый backend без раздела рассылок
 * (эндпоинты добавляются параллельно), 403 — что массовые рассылки запрещены
 * администратором. Ронять экран из-за этого нельзя.
 */
export function campaignErrorMessage(error, options = {}) {
  const status = error && error.status
  const detail = (error && error.data && (error.data.detail || error.data.message)) || ''
  const resource = (options && options.resource) || ''
  if (status === 404) {
    // 404 бывает двух разных природ: «эндпоинта нет вовсе» (старый backend без
    // раздела рассылок) и «такой кампании нет» (удалена/неверный id). Раньше оба
    // показывали «серверная часть ещё не обновлена», что на несуществующую
    // кампанию — просто неверная подсказка.
    if (resource === 'campaign' || /campaign|кампани/i.test(String(detail))) {
      return 'Кампания не найдена или удалена'
    }
    return 'Раздел «Рассылки» недоступен: серверная часть ещё не обновлена'
  }
  if (status === 403) return 'Недостаточно прав: массовые рассылки ограничены администратором'
  if (status === 401) return 'Сессия истекла. Войдите заново'
  if (status === 413) return 'Файл слишком большой — уменьшите количество строк'
  if (status === 0) return 'Сервер не отвечает. Проверьте, что backend запущен'
  return (error && error.message) || 'Не удалось выполнить запрос'
}
