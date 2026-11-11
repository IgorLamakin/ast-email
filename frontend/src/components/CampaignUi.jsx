// Мелкие визуальные элементы раздела «Рассылки» (2.7.0).
//
// Почему отдельный файл, а не копия в каждом экране: бейджи статусов, полоса
// прогресса и сообщения об ошибке выглядят одинаково в списке, мастере и на
// экране прогресса. Один источник — меньше шансов, что «Идёт» на одном экране
// оранжевое, а на другом серое.
import {
  statusLabel,
  statusClass,
  recipientStatusLabel,
  recipientStatusClass,
  progressBarClass,
} from '../utils/campaign.js'

/** Бейдж статуса кампании: Черновик / Идёт / Пауза / Завершена / Остановлена. */
export function StatusPill({ status }) {
  return (
    <span className={'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium whitespace-nowrap ' + statusClass(status)}>
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {statusLabel(status)}
    </span>
  )
}

/** Бейдж статуса получателя: дубль / ошибка / отписался / валидный и т.п. */
export function RecipientBadge({ status }) {
  const label = recipientStatusLabel(status)
  if (!label) return null
  return (
    <span className={'inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-semibold whitespace-nowrap ' + recipientStatusClass(status)}>
      {label}
    </span>
  )
}

/**
 * Полоса прогресса кампании. percent уже посчитан (progressPercent), tone —
 * статус кампании: от него зависит цвет (сделано/пауза/остановлено/черновик).
 */
export function CampaignProgressBar({ percent, status, height = 'h-1.5' }) {
  const width = Math.max(0, Math.min(100, Number(percent) || 0))
  return (
    <div className={'w-full rounded bg-line-200 overflow-hidden ' + height}>
      <div className={'h-full rounded transition-all ' + progressBarClass(status)} style={{ width: width + '%' }} />
    </div>
  )
}

/** Карточка в стиле остальных экранов проекта. */
export function Card({ children, className = '' }) {
  return <div className={'bg-canvas-0 border border-line-200 rounded-xl ' + className}>{children}</div>
}

/** Сообщение об ошибке загрузки/действия. */
export function ErrorBox({ children, onRetry, retryLabel = 'Повторить' }) {
  if (!children) return null
  return (
    <div className="flex items-start justify-between gap-4 bg-warn-100 text-warn-600 px-4 py-3 rounded-lg text-sm mb-4">
      <span>{children}</span>
      {onRetry && (
        <button type="button" onClick={onRetry} className="font-medium underline underline-offset-2 whitespace-nowrap">
          {retryLabel}
        </button>
      )}
    </div>
  )
}

/** Нейтральное пояснение под блоком (не ошибка). */
export function Note({ children, className = '' }) {
  return <p className={'text-xs text-ink-500 leading-relaxed ' + className}>{children}</p>
}

/** Подпись поля формы с необязательным пояснением справа. */
export function FieldLabel({ children, note }) {
  return (
    <span className="flex items-center justify-between gap-2 text-sm font-medium text-ink-900 mb-1.5">
      <span>{children}</span>
      {note && <span className="text-xs font-normal text-ink-500">{note}</span>}
    </span>
  )
}

/** Текстовое поле в стиле проектных экранов. */
export function TextInput(props) {
  return (
    <input
      {...props}
      className={'w-full rounded-lg border border-line-200 px-3 py-2 text-sm focus:border-signal-500 ' + (props.className || '')}
    />
  )
}

/** Выпадающий список в стиле проектных экранов. */
export function Select(props) {
  return (
    <select
      {...props}
      className={'w-full rounded-lg border border-line-200 px-3 py-2 text-sm bg-canvas-0 focus:border-signal-500 ' + (props.className || '')}
    />
  )
}

/** Кнопка «главное действие» (акцент проекта). */
export function PrimaryButton({ children, className = '', ...props }) {
  return (
    <button
      {...props}
      className={'inline-flex items-center justify-center gap-2 px-5 py-2 rounded-lg bg-signal-500 hover:bg-signal-600 text-white text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ' + className}
    >
      {children}
    </button>
  )
}

/** Кнопка второго плана (белая с рамкой). */
export function SecondaryButton({ children, className = '', ...props }) {
  return (
    <button
      {...props}
      className={'inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg border border-line-200 bg-canvas-0 text-ink-900 hover:border-signal-500 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ' + className}
    >
      {children}
    </button>
  )
}

/** Кнопка-иконка для строк таблицы. */
export function IconButton({ children, className = '', ...props }) {
  return (
    <button
      {...props}
      className={'w-7 h-7 inline-flex items-center justify-center rounded-md text-ink-500 hover:bg-canvas-50 hover:text-ink-900 transition-colors ' + className}
    >
      {children}
    </button>
  )
}
