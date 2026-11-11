// Мастер создания рассылки: 4 шага «Шаблон → Получатели → Проверка → Отправка»
// (2.7.0, макеты screen2.html и screen3.html).
//
// Мастер держит общее состояние кампании и согласие 38-ФЗ, а сами шаги вынесены
// в отдельные компоненты (CampaignRecipients / CampaignPreflight / CampaignSend):
// так каждый шаг можно читать и править отдельно, не листая тысячу строк.
//
// Черновик создаётся на шаге 1 (POST /campaigns) и дальше живёт на бэкенде:
// загрузка базы, проверка и запуск работают уже с его id. Если пользователь
// закроет окно между шагами, кампания останется черновиком в списке.
import { useState, useEffect, useRef } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { apiFetch } from '../api'
import {
  formatCount,
  validateEmailLite,
  emailHint,
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
  StatusPill,
} from './CampaignUi.jsx'
import CampaignRecipients from './CampaignRecipients.jsx'
import CampaignPreflight from './CampaignPreflight.jsx'
import CampaignSend from './CampaignSend.jsx'

// Шаги, при входе на которые перечитываем кампанию с сервера: после импорта
// базы и после preflight счётчики и настройки изменились, а ответ POST
// /campaigns их ещё не содержит. Без этого шаг 4 показывал бы «0 писем».
const STEPS_NEED_REFRESH = [3, 4]

const STEPS = [
  { id: 1, title: 'Шаблон', sub: 'письмо и отправитель' },
  { id: 2, title: 'Получатели', sub: 'база и колонки' },
  { id: 3, title: 'Проверка', sub: 'перед запуском' },
  { id: 4, title: 'Отправка', sub: 'темп и лимиты' },
]

function CampaignWizard({ token, user, capabilities }) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  // Черновик можно продолжить по ссылке из списка/экрана кампании:
  // /campaigns/new?draft=42. Тогда шаг 1 сразу заполнен, а мастер открывается
  // на получателях — иначе пользователь создавал бы второй черновик.
  const draftId = searchParams.get('draft')
  const [resuming, setResuming] = useState(Boolean(draftId))
  const [resumeError, setResumeError] = useState('')
  const [step, setStep] = useState(1)
  const [campaign, setCampaign] = useState(null)
  // Результат импорта (колонки, сопоставление, счётчики, превью) живёт в мастере,
  // а не в шаге 2: пользователь может вернуться со шага 3 назад и не должен
  // заново загружать тот же файл.
  const [importData, setImportData] = useState(null)
  // Согласие 38-ФЗ спрашиваем один раз на шаге 3 и передаём в start на шаге 4.
  const [consent, setConsent] = useState(false)
  // Пока идёт такое перечитывание — показываем «Загрузка...», а не шаг с
  // устаревшими числами (иначе кнопка запуска считала бы неотправленные нули).
  const [refreshingCampaign, setRefreshingCampaign] = useState(false)

  useEffect(() => {
    if (!campaign?.id || !STEPS_NEED_REFRESH.includes(step)) return
    let cancelled = false
    setRefreshingCampaign(true)
    apiFetch('/campaigns/' + campaign.id, { token })
      .then(data => {
        // Слияние, а не замена: id/title уже известны, и частичный ответ не
        // должен их обнулить.
        if (!cancelled && data) setCampaign(prev => ({ ...prev, ...data }))
      })
      .catch(() => {
        // Не блокируем мастер: шаги 3 и 4 умеют запрашивать свои данные сами.
      })
      .finally(() => {
        if (!cancelled) setRefreshingCampaign(false)
      })
    return () => { cancelled = true }
  }, [step, campaign?.id, token])

  useEffect(() => {
    if (!draftId) return
    let cancelled = false
    setResuming(true)
    setResumeError('')
    apiFetch('/campaigns/' + draftId, { token })
      .then(data => {
        if (cancelled) return
        if (!data || data.status !== 'draft') {
          setResumeError('Продолжить настройку можно только для черновика — эта кампания уже запускалась.')
          return
        }
        setCampaign(data)
        setStep(2)
      })
      .catch(err => {
        if (!cancelled) setResumeError(campaignErrorMessage(err))
      })
      .finally(() => {
        if (!cancelled) setResuming(false)
      })
    return () => { cancelled = true }
  }, [draftId, token])

  const handleCreated = (draft) => {
    setCampaign(draft)
    setStep(2)
  }

  // Сохранение уже существующего черновика (возврат с шага 2 на шаг 1):
  // PUT, а не второй POST — иначе в списке появлялся бы дубль кампании.
  const handleUpdated = (updated) => {
    setCampaign(prev => ({ ...prev, ...updated }))
    setStep(2)
  }

  const handleLaunched = (id) => {
    // После старта мастер больше не нужен: прогресс и отчёт живут на /campaigns/:id.
    navigate('/campaigns/' + (id || campaign?.id))
  }

  const subtitle = campaign
    ? [campaign.template_title || 'шаблон не выбран', formatCount(campaignTotal(campaign)) + ' в базе'].join(' · ')
    : 'Выберите шаблон письма и отправителя — черновик кампании создастся сразу'

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-4 mb-5">
        <div className="min-w-0">
          <nav className="flex items-center gap-1.5 text-xs text-ink-500 mb-1" aria-label="Хлебные крошки">
            <Link to="/campaigns" className="hover:text-ink-900">Рассылки</Link>
            <span>/</span>
            <span className="text-ink-900 font-medium truncate">Новая рассылка</span>
          </nav>
          <h2 className="text-2xl font-bold truncate">{campaign ? campaign.title : 'Новая рассылка'}</h2>
          <p className="text-sm text-ink-500 mt-1">{subtitle}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <StatusPill status={campaign?.status || 'draft'} />
          <SecondaryButton onClick={() => navigate('/campaigns')}>Выйти к списку</SecondaryButton>
        </div>
      </div>

      {resuming ? (
        <Card className="p-6 text-sm text-ink-500">Загружаем черновик кампании...</Card>
      ) : (
        <>
          {resumeError && !campaign && <ErrorBox>{resumeError}</ErrorBox>}
          <Stepper step={step} campaign={campaign} importData={importData} onSelect={setStep} />

          {step === 1 && (
            <TemplateStep
              token={token}
              user={user}
              capabilities={capabilities}
              initialCampaign={campaign}
              onCreated={handleCreated}
              onUpdated={handleUpdated}
            />
          )}

      {step === 2 && campaign && (
        <CampaignRecipients
          token={token}
          campaign={campaign}
          importData={importData}
          setImportData={setImportData}
          onBack={() => setStep(1)}
          onNext={() => setStep(3)}
        />
      )}

      {(step === 3 || step === 4) && campaign && refreshingCampaign && (
        <Card className="p-6 text-sm text-ink-500">Обновляем данные кампании...</Card>
      )}

      {step === 3 && campaign && !refreshingCampaign && (
        <CampaignPreflight
          token={token}
          campaign={campaign}
          capabilities={capabilities}
          consent={consent}
          setConsent={setConsent}
          onBack={() => setStep(2)}
          onNext={() => setStep(4)}
        />
      )}

      {step === 4 && campaign && !refreshingCampaign && (
        <CampaignSend
          token={token}
          campaign={campaign}
          capabilities={capabilities}
          consent={consent}
          onBack={() => setStep(3)}
          onLaunched={handleLaunched}
        />
      )}
        </>
      )}
    </div>
  )
}

// Степпер: пройденные шаги с галочкой и подсветкой, активный — с номером.
// Пройденные шаги кликабельны (вернуться на «Получателей» с шага проверки —
// обычный сценарий), но только когда черновик уже создан.
function Stepper({ step, campaign, importData, onSelect }) {
  const subFor = (id) => {
    if (id === 2 && importData?.counts) {
      return formatCount(importData.counts.valid || 0) + ' к отправке'
    }
    if (id === 1 && campaign?.template_title) {
      const title = String(campaign.template_title)
      return title.length > 28 ? title.slice(0, 27) + '…' : title
    }
    return STEPS.find(s => s.id === id).sub
  }

  return (
    <Card className="px-4 py-3 mb-5">
      <ol className="flex flex-wrap items-center gap-y-2">
        {STEPS.map((item, index) => {
          const state = item.id < step ? 'done' : item.id === step ? 'active' : 'todo'
          const canGoBack = campaign && item.id < step
          return (
            <li key={item.id} className="flex items-center gap-2 flex-1 min-w-[150px]">
              <button
                type="button"
                disabled={!canGoBack}
                onClick={() => canGoBack && onSelect(item.id)}
                className={'flex items-center gap-2.5 text-left ' + (canGoBack ? 'cursor-pointer' : 'cursor-default')}
              >
                <span
                  className={
                    'w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold shrink-0 border ' +
                    (state === 'done'
                      ? 'bg-ok-100 border-ok-600 text-ok-600'
                      : state === 'active'
                        ? 'bg-signal-500 border-signal-500 text-white'
                        : 'bg-canvas-0 border-line-200 text-ink-500')
                  }
                >
                  {state === 'done' ? (
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5">
                      <path d="m5 12 5 5L20 7" />
                    </svg>
                  ) : item.id}
                </span>
                <span className="min-w-0">
                  <span className={'block text-sm leading-tight ' + (state === 'todo' ? 'text-ink-500' : 'text-ink-900 font-medium')}>
                    {item.title}
                  </span>
                  <span className="block text-xs text-ink-500 truncate max-w-[170px]">{subFor(item.id)}</span>
                </span>
              </button>
              {index < STEPS.length - 1 && (
                <span className={'hidden md:block flex-1 h-px ' + (item.id < step ? 'bg-ok-600/40' : 'bg-line-200')} />
              )}
            </li>
          )
        })}
      </ol>
    </Card>
  )
}

// --- Шаг 1: шаблон и отправитель -------------------------------------------
// Отдельный компонент, а не часть мастера: у него своя загрузка справочников
// (шаблоны, история адресов) и своя форма, которая отправляется один раз.
function TemplateStep({ token, user, capabilities, initialCampaign, onCreated, onUpdated }) {
  const isUpdate = Boolean(initialCampaign && initialCampaign.id)
  const [templates, setTemplates] = useState([])
  const [senders, setSenders] = useState([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  // Возврат с шага 2 на шаг 1 не должен спрашивать всё заново: подставляем то,
  // что уже сохранено в черновике (initialCampaign).
  const [title, setTitle] = useState(() => (initialCampaign && initialCampaign.title) || '')
  const [templateId, setTemplateId] = useState(() => {
    const id = initialCampaign && initialCampaign.template_id
    return id === null || id === undefined ? '' : String(id)
  })
  const [senderEmail, setSenderEmail] = useState(() => (initialCampaign && initialCampaign.sender_email) || '')
  const [greeting, setGreeting] = useState(() => (initialCampaign && initialCampaign.greeting) || '')
  // Если название уже есть в черновике, автоподстановка из шаблона его не трогает.
  const titleTouchedRef = useRef(Boolean(initialCampaign && initialCampaign.title))

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      // Promise.allSettled: история адресов отправителя необязательна (404 от
      // старого backend не должен мешать выбрать шаблон), шаблоны обязательны.
      const [templatesResult, sendersResult] = await Promise.allSettled([
        apiFetch('/templates', { token }),
        apiFetch('/sender-emails', { token }),
      ])
      if (cancelled) return
      if (templatesResult.status === 'fulfilled' && Array.isArray(templatesResult.value)) {
        setTemplates(templatesResult.value)
      } else if (templatesResult.status === 'rejected') {
        setError(campaignErrorMessage(templatesResult.reason))
      }
      if (sendersResult.status === 'fulfilled' && Array.isArray(sendersResult.value)) {
        setSenders(sendersResult.value)
      }
      setLoading(false)
    })()
    return () => { cancelled = true }
  }, [token])

  // Адрес по умолчанию: самый свежий из истории, иначе адрес из профиля.
  // Ровно как на экране «Отправка», чтобы пользователь не вводил его заново.
  useEffect(() => {
    setSenderEmail(prev => prev || senders[0]?.email || user?.sender_email || '')
  }, [senders, user])

  // Адрес из редактируемого черновика обязательно попадает в список: иначе
  // <select> показал бы первый вариант, и сохранение молча подменило бы
  // отправителя кампании.
  const senderOptions = Array.from(new Set(
    [
      ...senders.map(item => item && item.email),
      user?.sender_email,
      initialCampaign?.sender_email,
    ].filter(Boolean)
  ))

  const selectedTemplate = templates.find(t => String(t.id) === String(templateId))
  const templateAttachPdf = Boolean(selectedTemplate && selectedTemplate.attach_pdf)

  const handleTitleChange = (value) => {
    titleTouchedRef.current = true
    setTitle(value)
    setError('')
  }

  const handleTemplateChange = (value) => {
    setTemplateId(value)
    setError('')
    // Название кампании удобно получить из шаблона, но только если пользователь
    // не ввёл своё — иначе молча затрём введённый текст.
    if (!titleTouchedRef.current) {
      const template = templates.find(t => String(t.id) === String(value))
      setTitle(template ? template.title : '')
    }
  }

  const handleCreate = async (event) => {
    event.preventDefault()
    if (!title.trim()) { setError('Введите название кампании'); return }
    if (!templateId) { setError('Выберите шаблон письма'); return }
    if (!validateEmailLite(senderEmail)) { setError(emailHint(senderEmail) || 'Укажите корректный email отправителя'); return }
    setCreating(true)
    setError('')
    try {
      const body = {
        title: title.trim(),
        template_id: Number(templateId),
        sender_email: senderEmail.trim(),
      }
      // Обращение по умолчанию передаём только если оно заполнено: пустая
      // строка сбросила бы подстановку на стороне бэкенда.
      if (greeting.trim()) body.greeting = greeting.trim()
      const saved = await apiFetch(isUpdate ? '/campaigns/' + initialCampaign.id : '/campaigns', {
        method: isUpdate ? 'PUT' : 'POST',
        token,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!saved || saved.id === undefined || saved.id === null) {
        setError('Сервер не вернул кампанию — изменения не сохранены')
        return
      }
      if (isUpdate) onUpdated(saved)
      else onCreated(saved)
    } catch (err) {
      setError(campaignErrorMessage(err))
    } finally {
      setCreating(false)
    }
  }

  if (loading) return <Card className="p-6 text-sm text-ink-500">Загрузка шаблонов...</Card>

  return (
    <Card className="p-6">
      <div className="mb-5">
        <h3 className="font-semibold">Шаблон и отправитель</h3>
        <p className="text-sm text-ink-500 mt-1">Из чего собирается письмо и от чьего имени оно уйдёт</p>
      </div>

      <ErrorBox>{error}</ErrorBox>

      <form onSubmit={handleCreate} className="space-y-4">
        <label className="block">
          <FieldLabel note="видно только внутри приложения">Название кампании *</FieldLabel>
          <TextInput
            type="text"
            value={title}
            onChange={e => handleTitleChange(e.target.value)}
            placeholder="Например: КП — поставка КИПиА, ноябрь"
            maxLength={200}
          />
        </label>

        <label className="block">
          <FieldLabel note={templates.length ? 'мои и общие шаблоны' : 'шаблонов пока нет'}>Шаблон письма *</FieldLabel>
          <Select value={templateId} onChange={e => handleTemplateChange(e.target.value)}>
            <option value="">— Выберите шаблон —</option>
            {templates.map(t => (
              <option key={t.id} value={t.id}>
                {t.title}{t.attach_pdf ? ' (с PDF)' : ''}
              </option>
            ))}
          </Select>
          {templates.length === 0 && (
            <Note className="mt-1.5">
              Шаблонов нет. Сначала <Link to="/templates/new" className="text-signal-600">создайте шаблон</Link> в разделе «Шаблоны».
            </Note>
          )}
        </label>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="block">
            <FieldLabel note={senderOptions.length ? 'история и профиль' : 'адрес из профиля'}>Отправитель *</FieldLabel>
            {senderOptions.length > 0 ? (
              <Select value={senderEmail} onChange={e => { setSenderEmail(e.target.value); setError('') }}>
                {senderOptions.map(email => (
                  <option key={email} value={email}>{email}</option>
                ))}
              </Select>
            ) : (
              <TextInput
                type="email"
                value={senderEmail}
                onChange={e => { setSenderEmail(e.target.value); setError('') }}
                placeholder="sales@company.ru"
              />
            )}
            <Note className="mt-1.5">Должен совпадать с ящиком в настройках SMTP, иначе письма уйдут в спам.</Note>
          </label>

          <label className="block">
            <FieldLabel note="необязательно">Обращение по умолчанию</FieldLabel>
            <TextInput
              type="text"
              value={greeting}
              onChange={e => setGreeting(e.target.value)}
              placeholder="Например: Уважаемый(ая) {{ greeting }}"
            />
            <Note className="mt-1.5">
              Подставится, если в базе нет колонки с обращением. В письме доступна переменная {'{{ greeting }}'}.
            </Note>
          </label>
        </div>

        {templateAttachPdf && (
          <div className="flex items-start gap-3 rounded-lg bg-signal-100 text-signal-600 px-4 py-3 text-sm">
            <span className="shrink-0 mt-0.5">📎</span>
            <div>
              <p className="font-medium">В шаблоне включено вложение PDF</p>
              <p className="text-xs mt-0.5">
                Для массовых писем вложение снижает доставляемость и увеличивает размер письма.
                Прикладывание можно отключить на шаге 4.
              </p>
            </div>
          </div>
        )}

        {Number(capabilities?.daily_limit) > 0 && (
          <Note>
            Дневной лимит ящика: {Number(capabilities.daily_limit)} писем. Остаток на сегодня —{' '}
            {Number.isFinite(Number(capabilities.remaining_today)) ? Number(capabilities.remaining_today) : '—'}.
          </Note>
        )}

        <div className="flex flex-wrap items-center gap-3 pt-2">
          <PrimaryButton type="submit" disabled={creating || (templates.length === 0 && !isUpdate)}>
            {creating
              ? (isUpdate ? 'Сохранение...' : 'Создание черновика...')
              : (isUpdate ? 'Сохранить и продолжить' : 'Далее: получатели')}
          </PrimaryButton>
          <Link to="/campaigns" className="text-sm text-ink-500 hover:text-ink-900">Отмена</Link>
        </div>

        <Note>
          Согласие получателей (38-ФЗ) подтверждается на шаге проверки — до этого рассылка не запускается.
        </Note>
      </form>
    </Card>
  )
}

export default CampaignWizard
