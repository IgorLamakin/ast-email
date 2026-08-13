import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { apiFetch, API_BASE } from '../api'

// 'columns' сюда намеренно не входит - колонка не может содержать другую
// колонку (ограничили глубину вложенности одним уровнем, см. пояснение в чате:
// полная произвольная вложенность плохо совместима с версткой email-писем).
const LEAF_BLOCK_TYPES = [
  { type: 'heading', label: 'Заголовок', icon: 'H' },
  { type: 'text', label: 'Текст', icon: 'T' },
  { type: 'image', label: 'Изображение', icon: '🖼' },
  { type: 'list', label: 'Список', icon: '☰' },
  { type: 'button', label: 'Кнопка', icon: '▢' },
  { type: 'stats', label: 'Инфографика', icon: '◈' },
  { type: 'signature', label: 'Подпись', icon: '✎' },
  { type: 'divider', label: 'Разделитель', icon: '—' },
]

const BLOCK_TYPES = [
  ...LEAF_BLOCK_TYPES,
  { type: 'columns', label: 'Колонки (в ряд)', icon: '▥' },
]

const FONT_SIZE_OPTIONS = [
  { value: '', label: 'По умолчанию' },
  { value: '13px', label: 'Мелкий' },
  { value: '16px', label: 'Обычный' },
  { value: '20px', label: 'Крупный' },
  { value: '28px', label: 'Очень крупный' },
]

const SPACING_OPTIONS = [
  { value: '0px', label: 'Без отступа' },
  { value: '8px', label: 'Маленький' },
  { value: '16px', label: 'Средний' },
  { value: '32px', label: 'Большой' },
]

function generateId() {
  return Math.random().toString(36).substr(2, 9)
}

function defaultBlock(type) {
  const base = {
    id: generateId(),
    type,
    styles: {
      backgroundColor: '#ffffff',
      textColor: '#1a2332',
      padding: '20px',
      textAlign: 'left',
      fontSize: '',
      marginBottom: '0px',
      // Прозрачность блока (10-100%). У старых (сохранённых ранее) блоков поля
      // нет - везде используем ?? 100, чтобы ничего не менялось само по себе.
      opacity: 100,
    },
  }
  switch (type) {
    case 'heading':
      return { ...base, content: { text: 'Заголовок', level: 'h2' } }
    case 'text':
      return { ...base, content: { text: 'Введите текст...' } }
    case 'image':
      return { ...base, content: { src: '', alt: 'Изображение', width: '100%' } }
    case 'list':
      return { ...base, content: { items: ['Пункт 1', 'Пункт 2', 'Пункт 3'], ordered: false } }
    case 'button':
      return { ...base, content: { text: 'Нажмите здесь', url: 'https://astkip.ru', align: 'center' } }
    case 'stats':
      return { ...base, content: { items: [{ label: 'Лет опыта', value: '10+' }, { label: 'Проектов', value: '500+' }] } }
    case 'signature':
      return { ...base, content: { useProfile: true, customText: '' } }
    case 'divider':
      return { ...base, content: { style: 'solid', color: '#00a8e8' } }
    case 'columns':
      return { ...base, styles: { ...base.styles, backgroundColor: 'transparent', padding: '8px' }, content: { columnCount: 2, columns: [{ blocks: [] }, { blocks: [] }] } }
    default:
      return base
  }
}

function mapBlocksDeep(blocks, id, updater) {
  return blocks.map(b => {
    if (b.id === id) return updater(b)
    if (b.type === 'columns') {
      return {
        ...b,
        content: {
          ...b.content,
          columns: b.content.columns.map(col => ({ ...col, blocks: mapBlocksDeep(col.blocks, id, updater) })),
        },
      }
    }
    return b
  })
}

// Пересчёт пропорций колонок при перетаскивании разделителя.
// blueDividerIndex - номер колонки, ПОСЛЕ которой стоит перетаскиваемая граница
// (0 = граница между 1-й и 2-й колонкой). leftPct - суммарная доля (в %) всех
// колонок слева от границы. Пропорции внутри каждой группы сохраняются.
function resizeColumns(block, leftDividerIndex, leftPct) {
  const cols = block.content.columns
  const n = cols.length
  if (n < 2 || leftDividerIndex < 0 || leftDividerIndex >= n - 1) return block
  const leftCount = leftDividerIndex + 1
  const rightCount = n - leftCount
  const currentPcts = cols.map(c => (typeof c.widthPct === 'number' ? c.widthPct : 100 / n))
  const leftSlice = currentPcts.slice(0, leftCount)
  const rightSlice = currentPcts.slice(leftCount)
  const leftSum = leftSlice.reduce((a, b) => a + b, 0)
  const rightSum = rightSlice.reduce((a, b) => a + b, 0)
  const scaledLeft = leftSum > 0 ? leftSlice.map(v => (v / leftSum) * leftPct) : Array(leftCount).fill(leftPct / leftCount)
  const scaledRight = rightSum > 0 ? rightSlice.map(v => (v / rightSum) * (100 - leftPct)) : Array(rightCount).fill((100 - leftPct) / rightCount)
  const newPcts = [...scaledLeft, ...scaledRight]
  return {
    ...block,
    content: {
      ...block.content,
      columns: cols.map((c, i) => ({ ...c, widthPct: Math.round(newPcts[i] * 10) / 10 })),
    },
  }
}

function findBlockDeep(blocks, id) {
  for (const b of blocks) {
    if (b.id === id) return b
    if (b.type === 'columns') {
      for (const col of b.content.columns) {
        const found = findBlockDeep(col.blocks, id)
        if (found) return found
      }
    }
  }
  return null
}

function removeBlockDeep(blocks, id) {
  return blocks
    .filter(b => b.id !== id)
    .map(b => {
      if (b.type === 'columns') {
        return {
          ...b,
          content: { ...b.content, columns: b.content.columns.map(col => ({ ...col, blocks: removeBlockDeep(col.blocks, id) })) },
        }
      }
      return b
    })
}

function normalizeImageUrl(url) {
  // Уже сохранённые шаблоны (созданные до этого исправления) могут содержать
  // относительный путь вида "/uploads/имя.png" - он не грузится в собранном
  // Electron-приложении. Чиним "на лету" при загрузке, не заставляя
  // пользователя заново перезагружать картинки в старых шаблонах.
  if (url && url.startsWith('/uploads/')) {
    return `${API_BASE}${url}`
  }
  return url
}

function normalizeBlocksImages(blocks) {
  return blocks.map(b => {
    if (b.type === 'image' && b.content.src) {
      return { ...b, content: { ...b.content, src: normalizeImageUrl(b.content.src) } }
    }
    if (b.type === 'columns') {
      return { ...b, content: { ...b.content, columns: b.content.columns.map(col => ({ ...col, blocks: normalizeBlocksImages(col.blocks) })) } }
    }
    return b
  })
}

function BlockEditor({ token }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const isEdit = Boolean(id)
  const [title, setTitle] = useState('')
  const [blocks, setBlocks] = useState([])
  const [background, setBackground] = useState({ color: '#f5f6f8', image: '' })
  const [attachPdf, setAttachPdf] = useState(false)
  const [noBlockData, setNoBlockData] = useState(false)
  const [selectedBlockId, setSelectedBlockId] = useState(null)
  const [showTemplateSettings, setShowTemplateSettings] = useState(false)
  const [insertMenuKey, setInsertMenuKey] = useState(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [dragIndex, setDragIndex] = useState(null)

  useEffect(() => {
    if (isEdit) fetchTemplate()
  }, [id])

  const fetchTemplate = async () => {
    setLoading(true)
    try {
      const data = await apiFetch(`/templates/${id}`, { token })
      setTitle(data.title)
      let parsedBlocks = []
      let parsedBackground = { color: '#f5f6f8', image: '' }
      if (data.blocks) {
        try {
          const parsed = JSON.parse(data.blocks)
          if (Array.isArray(parsed)) {
            parsedBlocks = parsed
          } else if (parsed && typeof parsed === 'object') {
            parsedBlocks = parsed.items || []
            parsedBackground = parsed.background || parsedBackground
          }
        } catch {
          parsedBlocks = []
        }
      }
      setBlocks(normalizeBlocksImages(parsedBlocks))
      setBackground({ ...parsedBackground, image: normalizeImageUrl(parsedBackground.image) })
      setAttachPdf(!!data.attach_pdf)
      setNoBlockData(parsedBlocks.length === 0 && !!data.html_content)
    } catch {
      alert('Не удалось загрузить шаблон')
    } finally {
      setLoading(false)
    }
  }

  const addBlock = (type) => {
    setBlocks([...blocks, defaultBlock(type)])
  }

  const insertBlockAt = (type, index) => {
    setBlocks(bs => {
      const copy = [...bs]
      copy.splice(index, 0, defaultBlock(type))
      return copy
    })
    setInsertMenuKey(null)
  }

  const addBlockToColumn = (columnsBlockId, columnIndex, type) => {
    setBlocks(bs => mapBlocksDeep(bs, columnsBlockId, b => {
      const newColumns = b.content.columns.map((col, i) =>
        i === columnIndex ? { ...col, blocks: [...col.blocks, defaultBlock(type)] } : col
      )
      return { ...b, content: { ...b.content, columns: newColumns } }
    }))
    setInsertMenuKey(null)
  }

  const setColumnCount = (columnsBlockId, count) => {
    setBlocks(bs => mapBlocksDeep(bs, columnsBlockId, b => {
      const current = b.content.columns
      let columns
      if (count > current.length) {
        columns = [...current, ...Array.from({ length: count - current.length }, () => ({ blocks: [] }))]
      } else {
        columns = current.slice(0, count)
      }
      // При смене количества колонок сбрасываем пропорции на равные - иначе
      // после 2->3 старые проценты (например 30/70) в сумме с новой колонкой
      // разъедутся за 100% и таблица письма вылезет за ширину.
      columns = columns.map(c => ({ ...c, widthPct: 100 / count }))
      return { ...b, content: { ...b.content, columnCount: count, columns } }
    }))
  }

  const updateBlockContent = (blockId, contentUpdates) => {
    setBlocks(bs => mapBlocksDeep(bs, blockId, b => ({ ...b, content: { ...b.content, ...contentUpdates } })))
  }

  const updateBlockStyles = (blockId, styleUpdates) => {
    setBlocks(bs => mapBlocksDeep(bs, blockId, b => ({ ...b, styles: { ...b.styles, ...styleUpdates } })))
  }

  // Перетаскивание границы между колонками. leftDividerIndex - колонка, ПОСЛЕ
  // которой находится перетаскиваемая граница. Работает через document-level
  // mousemove/mouseup (не на самом элементе), чтобы не было «залипания» курсора
  // и утечек слушателей при быстрых движениях.
  const startColumnResize = (columnsBlockId, leftDividerIndex, e) => {
    e.preventDefault()
    e.stopPropagation()
    const container = e.currentTarget.closest('[data-columns-container]')
    if (!container) return
    const rect = container.getBoundingClientRect()
    if (rect.width <= 0) return
    const onMove = (ev) => {
      let pct = ((ev.clientX - rect.left) / rect.width) * 100
      pct = Math.min(95, Math.max(5, pct))
      setBlocks(bs => mapBlocksDeep(bs, columnsBlockId, b => resizeColumns(b, leftDividerIndex, pct)))
    }
    const onUp = () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      document.body.style.cursor = ''
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
    document.body.style.cursor = 'col-resize'
  }

  const removeBlock = (blockId) => {
    setBlocks(bs => removeBlockDeep(bs, blockId))
    if (selectedBlockId === blockId) setSelectedBlockId(null)
  }

  const moveBlock = (fromIndex, toIndex) => {
    const newBlocks = [...blocks]
    const [moved] = newBlocks.splice(fromIndex, 1)
    newBlocks.splice(toIndex, 0, moved)
    setBlocks(newBlocks)
  }

  const handleDragStart = (e, index) => {
    setDragIndex(index)
    e.dataTransfer.effectAllowed = 'move'
  }

  const handleDragOver = (e, index) => {
    e.preventDefault()
    if (dragIndex === null || dragIndex === index) return
    moveBlock(dragIndex, index)
    setDragIndex(index)
  }

  const handleDragEnd = () => {
    setDragIndex(null)
  }

  const handleFileUpload = async (e, blockId) => {
    const file = e.target.files[0]
    if (!file) return
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await fetch(`${API_BASE}/upload`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData
      })
      if (!res.ok) throw new Error('Ошибка загрузки файла')
      const data = await res.json()
      if (data.url) {
        // Бэкенд отдаёт относительный путь ("/uploads/имя.png") - в браузере при
        // разработке это могло случайно сработать, но в собранном Electron-
        // приложении (грузится как file://) относительный путь ведёт в никуда.
        // Превращаем в полный адрес сразу при получении.
        updateBlockContent(blockId, { src: `${API_BASE}${data.url}` })
      }
    } catch {
      alert('Ошибка загрузки файла')
    }
  }

  const handleBackgroundUpload = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await fetch(`${API_BASE}/upload`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData
      })
      if (!res.ok) throw new Error('Ошибка загрузки файла')
      const data = await res.json()
      if (data.url) setBackground(bg => ({ ...bg, image: `${API_BASE}${data.url}` }))
    } catch {
      alert('Ошибка загрузки фона')
    }
  }

  const renderBlockPreview = (block) => {
    switch (block.type) {
      case 'heading': {
        const Tag = block.content.level || 'h2'
        return <Tag style={{ margin: 0, color: block.styles.textColor, fontSize: block.styles.fontSize || undefined }}>{block.content.text}</Tag>
      }
      case 'text':
        return <p style={{ margin: 0, lineHeight: 1.6, whiteSpace: 'pre-wrap', fontSize: block.styles.fontSize || undefined }}>{block.content.text}</p>
      case 'image':
        return block.content.src
          ? <ResizableImage
              src={block.content.src}
              alt={block.content.alt}
              width={block.content.width}
              onChange={(w) => updateBlockContent(block.id, { width: w })}
            />
          : <div style={{ padding: '40px', textAlign: 'center', background: '#f0f0f0', color: '#999' }}>🖼 Нажмите, чтобы загрузить изображение</div>
      case 'list': {
        const ListTag = block.content.ordered ? 'ol' : 'ul'
        return <ListTag style={{ margin: 0, paddingLeft: '20px', fontSize: block.styles.fontSize || undefined }}>{block.content.items.map((item, i) => <li key={i}>{item}</li>)}</ListTag>
      }
      case 'button':
        return (
          <div style={{ textAlign: block.content.align || 'center' }}>
            <a href={block.content.url} onClick={e => e.preventDefault()} style={{
              display: 'inline-block', padding: '12px 32px', backgroundColor: '#00a8e8',
              color: '#fff', textDecoration: 'none', borderRadius: '4px', fontWeight: 'bold'
            }}>{block.content.text}</a>
          </div>
        )
      case 'stats':
        return (
          <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', justifyContent: 'center' }}>
            {block.content.items.map((item, i) => (
              <div key={i} style={{ textAlign: 'center', padding: '10px' }}>
                <div style={{ fontSize: '32px', fontWeight: 'bold', color: '#00a8e8' }}>{item.value}</div>
                <div style={{ fontSize: '14px', color: block.styles.textColor }}>{item.label}</div>
              </div>
            ))}
          </div>
        )
      case 'signature':
        return (
          <div style={{ fontSize: '14px', lineHeight: 1.6 }}>
            <p style={{ margin: '0 0 8px 0' }}>С уважением,</p>
            <p style={{ margin: 0, fontWeight: 'bold' }}>{block.content.customText || '{{ full_name }}'}</p>
            <p style={{ margin: 0, color: '#666' }}>{'{{ position }}'}</p>
            <p style={{ margin: 0, color: '#666' }}>{'{{ company }}'}</p>
            <p style={{ margin: 0, color: '#666' }}>тел.: {'{{ phone }}'}</p>
            <p style={{ margin: 0, color: '#666' }}>email: {'{{ sender_email }}'}</p>
            <p style={{ margin: 0, color: '#666' }}>сайт: {'{{ website }}'}</p>
          </div>
        )
      case 'divider':
        return <hr style={{ border: 'none', borderTop: `2px ${block.content.style} ${block.content.color}`, margin: 0 }} />
      case 'columns': {
        const colCount = block.content.columns.length || 1
        return (
          <div data-columns-container style={{ display: 'flex', position: 'relative', alignItems: 'stretch' }}>
            {block.content.columns.map((col, colIndex) => {
              const isLast = colIndex === colCount - 1
              const widthPct = typeof col.widthPct === 'number' ? col.widthPct : (100 / colCount)
              return (
                <div key={colIndex} style={{ flex: `0 0 ${widthPct}%`, minWidth: 0, boxSizing: 'border-box' }}>
                  <div style={{ height: '100%', border: '1px dashed #cbd5e0', borderRadius: '4px', padding: '8px' }}>
                    <BlockList
                      blockArray={col.blocks}
                      containerLabel={`Колонка ${colIndex + 1}`}
                      onSelect={setSelectedBlockId}
                      selectedBlockId={selectedBlockId}
                      renderBlockPreview={renderBlockPreview}
                      insertMenuKey={insertMenuKey}
                      setInsertMenuKey={setInsertMenuKey}
                      insertMenuNamespace={`${block.id}:${colIndex}`}
                      onInsertLeaf={(type) => addBlockToColumn(block.id, colIndex, type)}
                      allowInsertBetween={false}
                    />
                  </div>
                  {!isLast && (
                    <div
                      onMouseDown={(e) => startColumnResize(block.id, colIndex, e)}
                      title="Потяните, чтобы изменить ширину колонок"
                      style={{ position: 'absolute', top: '8px', bottom: '8px', left: `${widthPct}%`, width: '12px', marginLeft: '-6px', cursor: 'col-resize', zIndex: 10, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                    >
                      <div style={{ width: '4px', height: '100%', backgroundColor: '#00a8e8', borderRadius: '2px', opacity: 0.5 }} />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )
      }
      default:
        return null
    }
  }

  const selectedBlock = findBlockDeep(blocks, selectedBlockId)

  const saveTemplate = async () => {
    setSaving(true)
    try {
      const payload = {
        title,
        html_content: renderBlocksToHtml(blocks, background),
        blocks: JSON.stringify({ background, items: blocks }),
        attach_pdf: attachPdf,
      }
      const path = isEdit ? `/templates/${id}` : '/templates'
      const method = isEdit ? 'PUT' : 'POST'
      await apiFetch(path, {
        method,
        token,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      alert('Шаблон сохранён!')
      if (!isEdit) navigate('/templates')
    } catch {
      alert('Не удалось сохранить шаблон')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="p-8 text-center">Загрузка...</div>

  return (
    <div className="flex h-screen">
      <div className="w-64 bg-canvas-50 border-r p-4 overflow-y-auto">
        <h2 className="font-bold text-lg mb-4">Блоки</h2>
        <div className="space-y-2">
          {BLOCK_TYPES.map(bt => (
            <button
              key={bt.type}
              onClick={() => addBlock(bt.type)}
              className="w-full flex items-center gap-3 px-3 py-2 bg-canvas-0 border rounded hover:bg-signal-100/40 hover:border-signal-500 transition text-left"
            >
              <span className="w-8 h-8 flex items-center justify-center bg-signal-100 text-signal-600 rounded font-bold text-sm">{bt.icon}</span>
              <span className="text-sm">{bt.label}</span>
            </button>
          ))}
        </div>
        <p className="text-xs text-ink-500 mt-3">
          Совет: наведите на промежуток между блоками на холсте — там появится
          «+» для вставки нового блока именно в этом месте.
        </p>
      </div>

      <div className="flex-1 bg-line-200 overflow-y-auto p-8">
        <div className="max-w-2xl mx-auto flex items-center gap-2 mb-2">
          <button
            onClick={() => { setShowTemplateSettings(v => !v); setSelectedBlockId(null) }}
            className={`text-xs px-3 py-1.5 rounded-full border transition ${showTemplateSettings ? 'border-signal-500 text-signal-600 bg-signal-100/50' : 'border-line-200 text-ink-500 hover:border-signal-500'}`}
          >
            ⚙ Настройки письма
          </button>
        </div>
        <div
          className="max-w-2xl mx-auto shadow-lg min-h-[600px]"
          style={{
            backgroundColor: background.color || '#f5f6f8',
            backgroundImage: background.image ? `url(${background.image})` : undefined,
            backgroundSize: 'cover',
          }}
        >
          <div className="p-4 border-b bg-canvas-0/90">
            <input
              type="text"
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="Название шаблона"
              className="w-full text-xl font-bold border-none outline-none bg-transparent"
            />
          </div>
          <div className="p-4 space-y-0">
            {noBlockData && (
              <div className="bg-signal-100/60 border border-signal-500/30 text-ink-900 text-sm rounded-lg px-4 py-3 mb-2">
                <strong>Этот шаблон создан не через блочный конструктор</strong> (например,
                один из 5 стандартных шаблонов АСТ) — данных о блоках для него нет, поэтому
                холст ниже пустой. Само письмо при этом никуда не делось и продолжит
                работать как обычно. Если вы соберёте блоки здесь и нажмёте «Сохранить» —
                оригинальное содержимое будет <strong>заменено</strong> тем, что вы
                составите из блоков. Если не хотите этого — просто закройте редактор, не
                сохраняя.
              </div>
            )}
            {blocks.length === 0 && (
              <div className="text-center text-ink-500 py-20">
                Нажмите блок слева, чтобы добавить его в шаблон
              </div>
            )}
            <BlockList
              blockArray={blocks}
              onSelect={setSelectedBlockId}
              selectedBlockId={selectedBlockId}
              renderBlockPreview={renderBlockPreview}
              insertMenuKey={insertMenuKey}
              setInsertMenuKey={setInsertMenuKey}
              insertMenuNamespace="root"
              onInsertLeaf={(type, index) => insertBlockAt(type, index)}
              allowInsertBetween={true}
              draggable={true}
              onDragStart={handleDragStart}
              onDragOver={handleDragOver}
              onDragEnd={handleDragEnd}
            />
          </div>
        </div>
        <div className="max-w-2xl mx-auto mt-4 flex gap-3">
          <button onClick={saveTemplate} disabled={saving}
            className="bg-signal-500 hover:bg-signal-600 text-white px-6 py-2 rounded font-medium transition disabled:opacity-50">
            {saving ? 'Сохранение...' : 'Сохранить шаблон'}
          </button>
          <button onClick={() => navigate('/templates')}
            className="bg-line-200 hover:bg-steel-300/40 text-ink-900 px-6 py-2 rounded font-medium transition">
            Отмена
          </button>
        </div>
      </div>

      {showTemplateSettings && (
        <div className="w-80 bg-canvas-0 border-l p-4 overflow-y-auto">
          <h3 className="font-bold mb-4">Настройки письма</h3>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">Фон письма (цвет)</label>
              <input type="color" value={background.color}
                onChange={e => setBackground(bg => ({ ...bg, color: e.target.value }))}
                className="w-full h-10 border rounded" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Фон письма (картинка, необязательно)</label>
              {background.image && <img src={background.image} alt="" className="w-full h-24 object-cover rounded mb-2" />}
              <input type="file" accept="image/*" onChange={handleBackgroundUpload} className="w-full text-sm" />
              {background.image && (
                <button onClick={() => setBackground(bg => ({ ...bg, image: '' }))} className="text-xs text-warn-600 hover:opacity-70 mt-1">
                  Убрать картинку фона
                </button>
              )}
            </div>
            <div className="pt-3 border-t">
              <label className="flex items-center gap-2 text-sm font-medium">
                <input type="checkbox" checked={attachPdf} onChange={e => setAttachPdf(e.target.checked)} />
                Прикладывать PDF-версию письма при отправке
              </label>
              <p className="text-xs text-ink-500 mt-1">
                Получатель дополнительно получит файл-вложение с содержимым письма
                в формате PDF (без кнопок — в статичном документе они всё равно не
                нажимаются).
              </p>
            </div>
          </div>
        </div>
      )}

      {!showTemplateSettings && selectedBlock && (
        <div className="w-80 bg-canvas-0 border-l p-4 overflow-y-auto">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-bold">Редактирование блока</h3>
            <button onClick={() => removeBlock(selectedBlock.id)} className="text-warn-600 hover:opacity-70 text-sm">Удалить</button>
          </div>

          <div className="space-y-4">
            {selectedBlock.type === 'heading' && (
              <>
                <div>
                  <label className="block text-sm font-medium mb-1">Текст</label>
                  <input type="text" value={selectedBlock.content.text}
                    onChange={e => updateBlockContent(selectedBlock.id, { text: e.target.value })}
                    className="w-full px-3 py-2 border rounded" />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Размер</label>
                  <select value={selectedBlock.content.level}
                    onChange={e => updateBlockContent(selectedBlock.id, { level: e.target.value })}
                    className="w-full px-3 py-2 border rounded">
                    <option value="h1">H1 — Очень крупный</option>
                    <option value="h2">H2 — Крупный</option>
                    <option value="h3">H3 — Средний</option>
                  </select>
                </div>
              </>
            )}

            {selectedBlock.type === 'text' && (
              <div>
                <label className="block text-sm font-medium mb-1">Текст</label>
                <textarea value={selectedBlock.content.text}
                  onChange={e => updateBlockContent(selectedBlock.id, { text: e.target.value })}
                  rows={6} className="w-full px-3 py-2 border rounded" />
              </div>
            )}

            {selectedBlock.type === 'image' && (
              <>
                <div>
                  <label className="block text-sm font-medium mb-1">Изображение</label>
                  {selectedBlock.content.src && (
                    <img src={selectedBlock.content.src} alt="" className="w-full h-32 object-cover rounded mb-2" />
                  )}
                  <input type="file" accept="image/*"
                    onChange={e => handleFileUpload(e, selectedBlock.id)}
                    className="w-full text-sm" />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Подпись (alt)</label>
                  <input type="text" value={selectedBlock.content.alt}
                    onChange={e => updateBlockContent(selectedBlock.id, { alt: e.target.value })}
                    className="w-full px-3 py-2 border rounded" />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Ширина</label>
                  <select value={selectedBlock.content.width}
                    onChange={e => updateBlockContent(selectedBlock.id, { width: e.target.value })}
                    className="w-full px-3 py-2 border rounded">
                    <option value="100%">100%</option>
                    <option value="75%">75%</option>
                    <option value="50%">50%</option>
                    <option value="25%">25%</option>
                  </select>
                </div>
              </>
            )}

            {selectedBlock.type === 'list' && (
              <>
                <div>
                  <label className="block text-sm font-medium mb-1">Тип списка</label>
                  <select value={selectedBlock.content.ordered ? 'ordered' : 'unordered'}
                    onChange={e => updateBlockContent(selectedBlock.id, { ordered: e.target.value === 'ordered' })}
                    className="w-full px-3 py-2 border rounded">
                    <option value="unordered">Маркированный</option>
                    <option value="ordered">Нумерованный</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Пункты (по одному на строку)</label>
                  <textarea value={selectedBlock.content.items.join('\n')}
                    onChange={e => updateBlockContent(selectedBlock.id, { items: e.target.value.split('\n').filter(i => i.trim()) })}
                    rows={6} className="w-full px-3 py-2 border rounded" />
                </div>
              </>
            )}

            {selectedBlock.type === 'button' && (
              <>
                <div>
                  <label className="block text-sm font-medium mb-1">Текст кнопки</label>
                  <input type="text" value={selectedBlock.content.text}
                    onChange={e => updateBlockContent(selectedBlock.id, { text: e.target.value })}
                    className="w-full px-3 py-2 border rounded" />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Ссылка</label>
                  <input type="text" value={selectedBlock.content.url}
                    onChange={e => updateBlockContent(selectedBlock.id, { url: e.target.value })}
                    className="w-full px-3 py-2 border rounded" />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Выравнивание</label>
                  <select value={selectedBlock.content.align}
                    onChange={e => updateBlockContent(selectedBlock.id, { align: e.target.value })}
                    className="w-full px-3 py-2 border rounded">
                    <option value="left">По левому краю</option>
                    <option value="center">По центру</option>
                    <option value="right">По правому краю</option>
                  </select>
                </div>
              </>
            )}

            {selectedBlock.type === 'stats' && (
              <div>
                <label className="block text-sm font-medium mb-1">Данные (формат: Значение|Подпись)</label>
                <textarea
                  value={selectedBlock.content.items.map(i => `${i.value}|${i.label}`).join('\n')}
                  onChange={e => {
                    const items = e.target.value.split('\n').filter(l => l.trim()).map(line => {
                      const [value, label] = line.split('|')
                      return { value: value?.trim() || '', label: label?.trim() || '' }
                    })
                    updateBlockContent(selectedBlock.id, { items })
                  }}
                  rows={6} className="w-full px-3 py-2 border rounded" />
              </div>
            )}

            {selectedBlock.type === 'signature' && (
              <div>
                <label className="block text-sm font-medium mb-1">Дополнительный текст (необязательно)</label>
                <textarea value={selectedBlock.content.customText}
                  onChange={e => updateBlockContent(selectedBlock.id, { customText: e.target.value })}
                  rows={3} className="w-full px-3 py-2 border rounded" placeholder="Будет подставлено вместо {{ full_name }}" />
                <p className="text-xs text-ink-500 mt-1">Если оставить пустым, подставится из профиля</p>
              </div>
            )}

            {selectedBlock.type === 'divider' && (
              <>
                <div>
                  <label className="block text-sm font-medium mb-1">Стиль</label>
                  <select value={selectedBlock.content.style}
                    onChange={e => updateBlockContent(selectedBlock.id, { style: e.target.value })}
                    className="w-full px-3 py-2 border rounded">
                    <option value="solid">Сплошная</option>
                    <option value="dashed">Пунктирная</option>
                    <option value="dotted">Точечная</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Цвет</label>
                  <input type="color" value={selectedBlock.content.color}
                    onChange={e => updateBlockContent(selectedBlock.id, { color: e.target.value })}
                    className="w-full h-10 border rounded" />
                </div>
              </>
            )}

            {selectedBlock.type === 'columns' && (
              <div>
                <label className="block text-sm font-medium mb-1">Количество колонок</label>
                <select value={selectedBlock.content.columnCount}
                  onChange={e => setColumnCount(selectedBlock.id, parseInt(e.target.value))}
                  className="w-full px-3 py-2 border rounded">
                  <option value={2}>2 колонки</option>
                  <option value={3}>3 колонки</option>
                </select>
                <p className="text-xs text-ink-500 mt-1">
                  Добавляйте блоки внутрь каждой колонки прямо на холсте — под
                  каждой колонкой есть своя кнопка «+ Добавить».
                </p>
              </div>
            )}
          </div>

          {selectedBlock.type !== 'columns' && (
            <div className="mt-6 pt-4 border-t">
              <h4 className="font-medium mb-3">Стили блока</h4>
              <div className="space-y-3">
                <div>
                  <label className="block text-sm font-medium mb-1">Цвет фона</label>
                  <input type="color" value={selectedBlock.styles.backgroundColor}
                    onChange={e => updateBlockStyles(selectedBlock.id, { backgroundColor: e.target.value })}
                    className="w-full h-10 border rounded" />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Цвет текста</label>
                  <input type="color" value={selectedBlock.styles.textColor}
                    onChange={e => updateBlockStyles(selectedBlock.id, { textColor: e.target.value })}
                    className="w-full h-10 border rounded" />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Прозрачность ({selectedBlock.styles.opacity ?? 100}%)</label>
                  <input type="range" min="10" max="100" step="10" value={selectedBlock.styles.opacity ?? 100}
                    onChange={e => updateBlockStyles(selectedBlock.id, { opacity: parseInt(e.target.value, 10) })}
                    className="w-full" />
                  <p className="text-xs text-ink-500 mt-1">От 10% (почти прозрачный) до 100% (непрозрачный)</p>
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Отступы (padding)</label>
                  <select value={selectedBlock.styles.padding}
                    onChange={e => updateBlockStyles(selectedBlock.id, { padding: e.target.value })}
                    className="w-full px-3 py-2 border rounded">
                    <option value="10px">Маленькие (10px)</option>
                    <option value="20px">Средние (20px)</option>
                    <option value="40px">Большие (40px)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Выравнивание текста</label>
                  <select value={selectedBlock.styles.textAlign}
                    onChange={e => updateBlockStyles(selectedBlock.id, { textAlign: e.target.value })}
                    className="w-full px-3 py-2 border rounded">
                    <option value="left">По левому краю</option>
                    <option value="center">По центру</option>
                    <option value="right">По правому краю</option>
                    <option value="justify">По ширине</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Размер шрифта</label>
                  <select value={selectedBlock.styles.fontSize || ''}
                    onChange={e => updateBlockStyles(selectedBlock.id, { fontSize: e.target.value })}
                    className="w-full px-3 py-2 border rounded">
                    {FONT_SIZE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Отступ снизу (до следующего блока)</label>
                  <select value={selectedBlock.styles.marginBottom || '0px'}
                    onChange={e => updateBlockStyles(selectedBlock.id, { marginBottom: e.target.value })}
                    className="w-full px-3 py-2 border rounded">
                    {SPACING_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function InsertMenu({ isOpen, onToggle, onPick }) {
  return (
    <div className="relative flex justify-center" style={{ height: isOpen ? 'auto' : '10px' }}>
      <button
        onClick={onToggle}
        className={`z-10 w-6 h-6 rounded-full bg-signal-500 text-white text-sm leading-none flex items-center justify-center transition-opacity
          ${isOpen ? 'opacity-100' : 'opacity-0 hover:opacity-100'}`}
        style={{ marginTop: '-11px', marginBottom: '-11px' }}
        title="Вставить блок здесь"
      >
        +
      </button>
      {isOpen && (
        <div className="absolute top-4 z-20 bg-canvas-0 border border-line-200 rounded-lg shadow-lg p-2 flex flex-wrap gap-1 max-w-xs">
          {LEAF_BLOCK_TYPES.map(bt => (
            <button key={bt.type} onClick={() => onPick(bt.type)}
              className="w-8 h-8 flex items-center justify-center bg-canvas-50 hover:bg-signal-100 border border-line-200 rounded text-sm"
              title={bt.label}>
              {bt.icon}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function BlockList({
  blockArray, onSelect, selectedBlockId, renderBlockPreview,
  insertMenuKey, setInsertMenuKey, insertMenuNamespace, onInsertLeaf,
  allowInsertBetween, draggable, onDragStart, onDragOver, onDragEnd, containerLabel,
}) {
  const gapKey = (index) => `${insertMenuNamespace}:gap:${index}`

  return (
    <div>
      {containerLabel && <p className="text-[11px] uppercase tracking-wide text-ink-500 mb-1">{containerLabel}</p>}

      {allowInsertBetween && (
        <InsertMenu
          isOpen={insertMenuKey === gapKey(0)}
          onToggle={() => setInsertMenuKey(insertMenuKey === gapKey(0) ? null : gapKey(0))}
          onPick={(type) => onInsertLeaf(type, 0)}
        />
      )}

      {blockArray.map((block, index) => (
        <div key={block.id}>
          <div
            draggable={draggable}
            onDragStart={draggable ? (e => onDragStart(e, index)) : undefined}
            onDragOver={draggable ? (e => onDragOver(e, index)) : undefined}
            onDragEnd={draggable ? onDragEnd : undefined}
            onClick={e => { e.preventDefault(); onSelect(block.id) }}
            style={{ cursor: draggable ? 'grab' : 'pointer' }}
          >
            <div style={{
              backgroundColor: block.styles.backgroundColor,
              color: block.styles.textColor,
              padding: block.styles.padding,
              textAlign: block.styles.textAlign,
              marginBottom: block.styles.marginBottom || '0px',
              opacity: block.styles.opacity != null ? block.styles.opacity / 100 : 1,
              border: selectedBlockId === block.id ? '2px solid #00a8e8' : '2px solid transparent',
              borderRadius: '4px',
            }}>
              {renderBlockPreview(block)}
            </div>
          </div>
          {allowInsertBetween && (
            <InsertMenu
              isOpen={insertMenuKey === gapKey(index + 1)}
              onToggle={() => setInsertMenuKey(insertMenuKey === gapKey(index + 1) ? null : gapKey(index + 1))}
              onPick={(type) => onInsertLeaf(type, index + 1)}
            />
          )}
        </div>
      ))}

      {!allowInsertBetween && (
        <InsertMenuInline onPick={(type) => onInsertLeaf(type)} />
      )}
    </div>
  )
}

function InsertMenuInline({ onPick }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-2">
      <button onClick={() => setOpen(v => !v)}
        className="text-xs px-2 py-1 rounded border border-dashed border-line-200 text-ink-500 hover:border-signal-500 hover:text-signal-600 w-full">
        + Добавить блок
      </button>
      {open && (
        <div className="mt-1 bg-canvas-0 border border-line-200 rounded-lg shadow p-2 flex flex-wrap gap-1">
          {LEAF_BLOCK_TYPES.map(bt => (
            <button key={bt.type} onClick={() => { onPick(bt.type); setOpen(false) }}
              className="w-8 h-8 flex items-center justify-center bg-canvas-50 hover:bg-signal-100 border border-line-200 rounded text-sm"
              title={bt.label}>
              {bt.icon}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// Картинка в превью с угловым «хандлом» ресайза. Ширина привязывается к шагу 25%
// (25/50/75/100%). Слушатели mousemove/mouseup вешаются на документ и снимаются
// в onUp / при размонтировании - без утечек и без «залипания» при быстрых движениях.
function ResizableImage({ src, alt, width, onChange }) {
  const containerRef = useRef(null)
  // onChange каждый рендер создаётся заново (стрелка в renderBlockPreview), поэтому
  // храним его в ref и держим эффект зависимым только от dragging - иначе слушатели
  // пересоздавались бы на каждый mousemove.
  const onChangeRef = useRef(onChange)
  const [dragging, setDragging] = useState(false)

  useEffect(() => { onChangeRef.current = onChange })

  useEffect(() => {
    if (!dragging) return
    const onMove = (e) => {
      const el = containerRef.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      if (rect.width <= 0) return
      let pct = ((e.clientX - rect.left) / rect.width) * 100
      pct = Math.min(100, Math.max(10, Math.round(pct)))
      const steps = [25, 50, 75, 100]
      const snap = steps.reduce((best, s) => (Math.abs(s - pct) < Math.abs(best - pct) ? s : best), steps[0])
      onChangeRef.current(`${snap}%`)
    }
    const onUp = () => setDragging(false)
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
    return () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
  }, [dragging])

  const label = width || '100%'

  return (
    <div ref={containerRef} style={{ position: 'relative' }} onClick={(e) => e.stopPropagation()}>
      <img src={src} alt={alt} style={{ maxWidth: width || '100%', display: 'block', margin: '0 auto' }} />
      <div
        onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); setDragging(true) }}
        title="Потяните за угол, чтобы изменить ширину (шаг 25%)"
        style={{ position: 'absolute', right: 0, bottom: 0, width: 14, height: 14, cursor: 'nwse-resize', background: '#00a8e8', borderRadius: '3px', border: '2px solid #fff', boxShadow: '0 0 0 1px #00a8e8', zIndex: 3 }}
      />
      <div style={{ position: 'absolute', top: 0, left: 0, background: 'rgba(0,168,232,0.85)', color: '#fff', fontSize: 11, padding: '1px 6px', borderRadius: '0 0 4px 0', zIndex: 3 }}>
        {label}
      </div>
    </div>
  )
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderBlocksBody(blocks) {
  return blocks.map(block => {
    const s = block.styles
    const fontSizeCss = s.fontSize ? `font-size:${s.fontSize};` : ''
    const marginCss = s.marginBottom ? `margin-bottom:${s.marginBottom};` : ''
    const opacityCss = s.opacity != null ? `opacity:${s.opacity / 100};` : ''
    const wrapperStyle = `background-color:${s.backgroundColor};color:${s.textColor};padding:${s.padding};text-align:${s.textAlign};${opacityCss}${fontSizeCss}${marginCss}`
    switch (block.type) {
      case 'heading': {
        const H = block.content.level || 'h2'
        return `<div style="${wrapperStyle}"><${H} style="margin:0;color:${s.textColor}">${escapeHtml(block.content.text)}</${H}></div>`
      }
      case 'text':
        return `<div style="${wrapperStyle}"><p style="margin:0;line-height:1.6">${escapeHtml(block.content.text).replace(/\n/g, '<br>')}</p></div>`
      case 'image':
        return `<div style="${wrapperStyle}"><img src="${escapeHtml(block.content.src)}" alt="${escapeHtml(block.content.alt)}" style="max-width:${block.content.width || '100%'};display:block;margin:0 auto" /></div>`
      case 'list': {
        const tag = block.content.ordered ? 'ol' : 'ul'
        const items = block.content.items.map(i => `<li>${escapeHtml(i)}</li>`).join('')
        return `<div style="${wrapperStyle}"><${tag} style="margin:0;padding-left:20px">${items}</${tag}></div>`
      }
      case 'button':
        return `<div data-pdf-exclude="true" style="${wrapperStyle}text-align:${block.content.align || 'center'}"><a href="${escapeHtml(block.content.url)}" style="display:inline-block;padding:12px 32px;background-color:#00a8e8;color:#fff;text-decoration:none;border-radius:4px;font-weight:bold">${escapeHtml(block.content.text)}</a></div>`
      case 'stats': {
        const statsItems = block.content.items.map(i => `
          <div style="text-align:center;padding:10px">
            <div style="font-size:32px;font-weight:bold;color:#00a8e8">${escapeHtml(i.value)}</div>
            <div style="font-size:14px;color:${s.textColor}">${escapeHtml(i.label)}</div>
          </div>
        `).join('')
        return `<div style="${wrapperStyle}"><div style="display:flex;gap:20px;flex-wrap:wrap;justify-content:center">${statsItems}</div></div>`
      }
      case 'signature':
        return `<div style="${wrapperStyle}font-size:14px;line-height:1.6">
          <p style="margin:0 0 8px 0">С уважением,</p>
          <p style="margin:0;font-weight:bold">${block.content.customText ? escapeHtml(block.content.customText) : '{{ full_name }}'}</p>
          <p style="margin:0;color:#666">{{ position }}</p>
          <p style="margin:0;color:#666">{{ company }}</p>
          <p style="margin:0;color:#666">тел.: {{ phone }}</p>
          <p style="margin:0;color:#666">email: {{ sender_email }}</p>
          <p style="margin:0;color:#666">сайт: {{ website }}</p>
        </div>`
      case 'divider':
        return `<div style="${wrapperStyle}"><hr style="border:none;border-top:2px ${block.content.style} ${block.content.color};margin:0" /></div>`
      case 'columns': {
        const colCount = block.content.columns.length || 1
        const cells = block.content.columns.map(col =>
          `<td valign="top" width="${typeof col.widthPct === 'number' ? col.widthPct : (100 / colCount)}%" style="padding:8px">${renderBlocksBody(col.blocks)}</td>`
        ).join('')
        return `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="${marginCss}"><tr>${cells}</tr></table>`
      }
      default:
        return ''
    }
  }).join('')
}

function renderBlocksToHtml(blocks, background) {
  const bg = background || { color: '#f5f6f8', image: '' }
  const bodyBg = bg.image
    ? `background-image:url('${bg.image}');background-size:cover;background-color:${bg.color || '#f5f6f8'};`
    : `background-color:${bg.color || '#f5f6f8'};`
  const body = renderBlocksBody(blocks)

  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>body{margin:0;font-family:Arial,sans-serif}</style>
</head>
<body style="${bodyBg}">
<div style="max-width:640px;margin:0 auto;">
${body}
</div>
</body>
</html>`
}

export default BlockEditor
