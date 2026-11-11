import { useEffect, useMemo, useRef, useState } from 'react'
import { filterOptions } from '../utils/search'

// Общий combobox для двух полей экрана «Отправка письма»: истории адресов
// отправителя и быстрого выбора сохранённого контакта.
//
// Почему свой компонент, а не <select>/<datalist>: <select> не даёт искать по
// части строки, а у <datalist> в Electron/PowerShell-окружении непредсказуемая
// подсветка и невозможно искать по обращению. Внешних библиотек в проекте нет,
// поэтому вся логика (фокус, клавиатура, клик вне) - здесь, а сам поиск вынесен
// в utils/search.js, чтобы покрывать его node-тестами без React.
const INPUT_CLASS = 'w-full px-3 py-2 border rounded focus:ring-2 focus:ring-signal-500 outline-none'

function Combobox({
  id,
  value,
  onChange,
  options = [],
  placeholder = '',
  allowFreeText = true,
  emptyText = 'Ничего не найдено',
  maxVisible = 8,
  type = 'text',
  filterFields = ['label', 'meta'],
  autoComplete = 'off',
}) {
  const [query, setQuery] = useState(value ?? '')
  const [open, setOpen] = useState(false)
  // dirty: набирал ли пользователь что-то после открытия. По фокусу список
  // должен показывать историю/контакты целиком (первые maxVisible), а не только
  // варианты, совпадающие с уже подставленным адресом, иначе список из одного
  // пункта выглядит как сломанный.
  const [dirty, setDirty] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  const rootRef = useRef(null)
  const listRef = useRef(null)

  const listId = id ? id + '-listbox' : undefined

  // Внешнее изменение value (загрузка истории, выбор контакта, сброс) обновляет
  // текст в поле. Пока allowFreeText={false} и поле в фокусе, value не меняется
  // при вводе, поэтому набранный поисковый текст не затирается.
  useEffect(() => {
    setQuery(value ?? '')
  }, [value])

  const visible = useMemo(
    () => filterOptions(dirty ? query : '', options, { fields: filterFields, limit: maxVisible }),
    [dirty, query, options, filterFields, maxVisible]
  )

  // Страховка от «висящего» activeIndex, если после фильтрации список стал короче.
  useEffect(() => {
    setActiveIndex(current => (visible.length === 0 ? 0 : Math.min(current, visible.length - 1)))
  }, [visible.length])

  // Активный пункт должен быть виден при прокрутке длинного списка.
  useEffect(() => {
    if (!open) return
    const node = listRef.current && listRef.current.querySelector('[data-combobox-active="true"]')
    if (node && typeof node.scrollIntoView === 'function') node.scrollIntoView({ block: 'nearest' })
  }, [open, activeIndex])

  // Закрытие по клику вне поля. Слушатель живёт только пока список открыт и
  // снимается при закрытии/размонтировании - иначе накапливались бы копии.
  useEffect(() => {
    if (!open) return
    const handlePointerDown = (event) => {
      if (rootRef.current && !rootRef.current.contains(event.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handlePointerDown)
    return () => document.removeEventListener('mousedown', handlePointerDown)
  }, [open])

  const openList = () => {
    setOpen(true)
    setDirty(false)
    setActiveIndex(0)
  }

  const closeList = () => {
    setOpen(false)
    setDirty(false)
  }

  const selectOption = (option) => {
    if (!option) return
    const label = option.label ?? option.value
    // Сначала показываем выбранное значение, затем отдаём его наверх: onChange
    // может обновить value, и тогда эффект синхронизации подтвердит текст.
    setQuery(label === null || label === undefined ? '' : String(label))
    closeList()
    setActiveIndex(0)
    onChange(option.value, option)
  }

  const handleInputChange = (event) => {
    const next = event.target.value
    setQuery(next)
    setOpen(true)
    setDirty(true)
    setActiveIndex(0)
    // Для поля с историей (allowFreeText) любой набранный адрес - валидное
    // значение; для «выбора контакта» произвольный текст наверх не отдаём.
    if (allowFreeText) onChange(next, null)
  }

  const handleKeyDown = (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      if (!open) {
        openList()
        return
      }
      setActiveIndex(current => Math.min(current + 1, Math.max(visible.length - 1, 0)))
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      if (!open) {
        openList()
        return
      }
      setActiveIndex(current => Math.max(current - 1, 0))
      return
    }
    if (event.key === 'Enter') {
      // Enter выбирает подсвеченный пункт; если списка нет - не мешаем (форма
      // отправки запускается только кнопкой).
      if (open && visible[activeIndex]) {
        event.preventDefault()
        selectOption(visible[activeIndex])
        return
      }
      if (open) {
        closeList()
        // Для режима «только выбор» не подтверждённый ввод откатываем к value.
        if (!allowFreeText) setQuery(value ?? '')
      }
      return
    }
    if (event.key === 'Escape') {
      if (open) {
        event.preventDefault()
        closeList()
        if (!allowFreeText) setQuery(value ?? '')
      }
      return
    }
    if (event.key === 'Tab') {
      // Tab не должен «съедаться»: закрываем список и отпускаем фокус дальше.
      closeList()
      if (!allowFreeText) setQuery(value ?? '')
    }
  }

  const handleBlur = () => {
    setOpen(false)
    // Ушли из поля, ничего не выбрав, - показываем реальное значение, а не
    // поисковый запрос (для allowFreeText ввод и есть значение).
    if (!allowFreeText) setQuery(value ?? '')
  }

  return (
    <div ref={rootRef} className="relative">
      <input
        id={id}
        type={type}
        value={query}
        onChange={handleInputChange}
        onFocus={openList}
        onBlur={handleBlur}
        onKeyDown={handleKeyDown}
        // После Escape список закрыт, а поле всё ещё в фокусе - повторный
        // клик не вызовет onFocus, поэтому открываем и здесь (только если
        // список закрыт, чтобы клик по полю не сбрасывал прокрутку фильтра).
        onClick={() => { if (!open) openList() }}
        placeholder={placeholder}
        autoComplete={autoComplete}
        className={INPUT_CLASS}
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        aria-controls={listId}
        aria-haspopup="listbox"
      />
      {open && (
        <div
          ref={listRef}
          id={listId}
          role="listbox"
          className="absolute z-20 mt-1 w-full max-h-64 overflow-auto bg-canvas-0 border rounded shadow-lg"
        >
          {visible.length === 0 ? (
            <div className="px-3 py-2 text-sm text-ink-500">{emptyText}</div>
          ) : (
            visible.map((option, index) => {
              const active = index === activeIndex
              return (
                <button
                  type="button"
                  key={String(option.value) + '-' + index}
                  role="option"
                  aria-selected={active}
                  data-combobox-active={active ? 'true' : undefined}
                  // mousedown preventDefault: клик не уводит фокус из input,
                  // иначе onBlur закрыл бы список раньше, чем сработал click.
                  onMouseDown={event => event.preventDefault()}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => selectOption(option)}
                  className={
                    'w-full text-left px-3 py-2 flex items-baseline justify-between gap-3 text-sm ' +
                    (active ? 'bg-signal-100 text-ink-900' : 'text-ink-900 hover:bg-canvas-50')
                  }
                >
                  <span className="truncate">{option.label}</span>
                  {option.meta ? <span className="text-xs text-ink-500 shrink-0">{option.meta}</span> : null}
                </button>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}

export default Combobox
