// Единая точка правды для обращений к бэкенду.
//
// Раньше в компонентах вперемешку встречались:
//   - абсолютные адреса вида 'http://localhost:8000/api/...'
//   - относительные адреса вида '/api/...'
// Второй вариант работал только в режиме разработки благодаря прокси Vite
// (см. vite.config.js) и полностью ломался в собранном Electron-приложении,
// которое грузит фронтенд как file://, где проксировать запросы некому.
//
// Теперь весь фронтенд обращается к бэкенду только через apiFetch() из этого файла.
//
// 2.6.0, «автологин»: бэкенд отдаёт пару токенов - access (живёт 12 часов) и
// refresh (180 дней, с ротацией). Access-токен протухает незаметно для
// пользователя, поэтому здесь живёт вся механика «поймали 401 -> тихо
// обновили пару -> повторили запрос». Компоненты об этой механике не знают:
// они по-прежнему вызывают apiFetch(path, { token }) и получают данные или
// ApiError, как раньше.
//
// События для UI (App.jsx):
//   'auth:refreshed'    - { detail: { accessToken } } access-токен обновлён,
//                         надо положить его в состояние, чтобы дочерние
//                         компоненты ходили в API с актуальным токеном;
//   'auth:unauthorized' - обновить сессию не удалось (refresh протух/отозван),
//                         пользователя надо вернуть на экран входа.
// window и localStorage трогаются только внутри функций, не на верхнем уровне
// модуля: так api.js импортируется в Node-тестах (npm test) без jsdom.

import { createAuthStorage } from './utils/authStorage.js'

export const API_BASE = 'http://localhost:8000/api'

class ApiError extends Error {
  constructor(message, status, data) {
    super(message)
    this.status = status
    this.data = data
  }
}

// Пути, на которых 401 - это нормальный ответ, а не «сессия протухла»:
// неверный пароль при входе/регистрации и отказ в refresh-токене. Для них
// нельзя запускать автообновление (рекурсия на /auth/refresh) и нельзя
// рассылать 'auth:unauthorized' (пользователь и так на экране входа).
const AUTH_FLOW_PATHS = ['/auth/login', '/auth/register', '/auth/refresh']

function isAuthFlowPath(path) {
  const clean = String(path || '').split('?')[0]
  return AUTH_FLOW_PATHS.some((p) => clean === p || clean.endsWith(p))
}

// --- Текущая сессия (модульное состояние) ---
// Держим пару в памяти, чтобы при каждом 401 не перечитывать localStorage и
// чтобы все параллельные запросы видели один и тот же refresh-токен (это
// важно для single-flight обновления: ротация refresh-токена одноразовая).

let authStorage = null
let currentSession = null
let initialized = false

function defaultStorage() {
  try {
    return globalThis.localStorage || null
  } catch {
    return null
  }
}

/**
 * Инициализирует модуль сессии из storage (по умолчанию localStorage).
 * Вызывается лениво при первом обращении, но App.jsx может вызвать и явно.
 * Возвращает { accessToken, refreshToken } или null.
 */
export function initSession(storage = defaultStorage()) {
  authStorage = createAuthStorage(storage)
  currentSession = authStorage.load()
  initialized = true
  return currentSession ? { ...currentSession } : null
}

function ensureInit() {
  if (!initialized) initSession()
  return currentSession
}

/** Текущая сессия (копия, чтобы снаружи не мутировали модульное состояние). */
export function getSession() {
  ensureInit()
  return currentSession ? { ...currentSession } : null
}

/** Текущий access-токен или '' (пустая строка = заголовок Authorization не ставим). */
export function getAccessToken() {
  ensureInit()
  return (currentSession && currentSession.accessToken) || ''
}

/**
 * Принимает ответ бэкенда на /auth/login, /auth/register, /auth/refresh
 * ({"access_token","refresh_token",...}) и делает его текущей сессией:
 * обновляет и модульное состояние, и localStorage.
 * Возвращает сохранённую сессию либо текущую, если в ответе нет токена.
 */
export function setSessionFromResponse(data) {
  ensureInit()
  if (!data) return getSession()
  const accessToken = data.access_token || data.accessToken || ''
  if (!accessToken) return getSession()
  // При ротации бэкенд обязан прислать новый refresh-токен, но если по какой-то
  // причине не прислал - оставляем прежний, иначе «тихо» потеряем автологин.
  const refreshToken =
    data.refresh_token ?? data.refreshToken ?? (currentSession && currentSession.refreshToken) ?? null
  currentSession = { accessToken, refreshToken: refreshToken || null }
  if (authStorage) authStorage.save(currentSession)
  return { ...currentSession }
}

// Стирает сессию из памяти и localStorage (по 401, по кнопке «Выйти»).
function forgetSession() {
  ensureInit()
  currentSession = null
  if (authStorage) authStorage.clear()
}

function dispatchAuthEvent(name, detail) {
  let target = null
  try {
    target = globalThis.window
  } catch {
    target = null
  }
  if (!target || typeof target.dispatchEvent !== 'function') return
  let event
  if (typeof CustomEvent === 'function') {
    event = new CustomEvent(name, { detail })
  } else {
    // На случай экзотического окружения без CustomEvent - подписчикам важен
    // только type/detail, поэтому простой объект тоже подходит.
    event = { type: name, detail }
  }
  try {
    target.dispatchEvent(event)
  } catch {
    // Ошибка в подписчике не должна ломать сетевой запрос.
  }
}

// --- Один сетевой запрос без всякой магии ---

async function requestOnce(path, options, token) {
  const headers = { ...((options && options.headers) || {}) }
  if (token) headers.Authorization = `Bearer ${token}`
  try {
    return await fetch(`${API_BASE}${path}`, { ...options, headers })
  } catch (e) {
    throw new ApiError('Сервер не отвечает. Проверьте, что backend запущен.', 0, null)
  }
}

async function readJsonBody(res) {
  if (!res) return null
  let contentType = ''
  try {
    contentType = (res.headers && res.headers.get && res.headers.get('content-type')) || ''
  } catch {
    contentType = ''
  }
  if (!contentType.includes('application/json')) return null
  try {
    return await res.json()
  } catch {
    return null
  }
}

// --- Обновление пары токенов ---

// Single-flight: все параллельные 401 ждут ОДИН запрос /auth/refresh.
// Без этого, например, EmailRender при открытии раздела делает два запроса
// одновременно, оба получают 401, оба идут ротировать refresh-токен - и второй
// приходит с уже недействительным токеном, выкидывая пользователя на логин.
let refreshPromise = null

async function performRefresh(refreshToken) {
  let res
  try {
    res = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
  } catch (e) {
    throw new ApiError('Сервер не отвечает. Проверьте, что backend запущен.', 0, null)
  }

  const data = await readJsonBody(res)
  if (!res.ok || !data || !data.access_token) {
    const message = (data && (data.detail || data.message)) || `Не удалось обновить сессию (${res.status})`
    throw new ApiError(message, res.status, data)
  }

  setSessionFromResponse(data)
  dispatchAuthEvent('auth:refreshed', { accessToken: getAccessToken() })
  return getSession()
}

function requestRefresh(refreshToken) {
  if (!refreshPromise) {
    refreshPromise = performRefresh(refreshToken).finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

/**
 * Принудительно обновляет пару токенов по refresh-токену из хранилища.
 * Бросает ApiError, если refresh-токена нет или бэкенд его не принял.
 * Для UI обычно не нужна (всё происходит прозрачно внутри apiFetch), но
 * полезна, чтобы «разбудить» сессию при старте приложения.
 */
export async function refreshSession() {
  ensureInit()
  const refreshToken = currentSession && currentSession.refreshToken
  if (!refreshToken) {
    throw new ApiError('Сессия истекла. Войдите заново.', 401, null)
  }
  return requestRefresh(refreshToken)
}

/**
 * Выход: best-effort отзываем refresh-токен на бэкенде, затем в любом случае
 * чистим локальную сессию. Ошибки наружу не пробрасываем - если сервер
 * недоступен, пользователь всё равно должен выйти из приложения.
 * Намеренно не используем apiFetch: он при 401 сам полез бы обновлять токен.
 */
export async function logoutSession() {
  ensureInit()
  const refreshToken = currentSession && currentSession.refreshToken
  if (refreshToken) {
    try {
      await fetch(`${API_BASE}/auth/logout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      })
    } catch (e) {
      // нет сети / сервер упал - выходим локально, это не ошибка для пользователя
    }
  }
  forgetSession()
  return true
}

/**
 * Пытается довести access-токен до актуального после 401.
 * tokenUsed - токен, с которым упал исходный запрос.
 * true  -> можно повторить запрос (в сессии уже свежий access-токен);
 * false -> сессию не спасти, вызывающий разлогинивает пользователя.
 */
async function ensureFreshAccessToken(tokenUsed) {
  const current = getAccessToken()
  // Пока наш запрос летел, параллельный запрос уже обновил пару: повторно
  // ротировать refresh-токен нельзя (он одноразовый), просто повторим запрос
  // с токеном, который уже лежит в сессии.
  if (current && tokenUsed && current !== tokenUsed) return true

  if (!(currentSession && currentSession.refreshToken)) return false

  try {
    await requestRefresh(currentSession.refreshToken)
    return true
  } catch (e) {
    return false
  }
}

/**
 * Обёртка над fetch(): подставляет базовый адрес API, добавляет заголовок
 * авторизации (если передан токен), сама разбирает JSON и кидает ApiError
 * с понятным сообщением на нестандартных ответах.
 *
 * 2.6.0: при 401 (просроченный access-токен) пара токенов обновляется
 * прозрачно, исходный запрос повторяется ОДИН раз с новым access-токеном.
 * Если обновить не удалось - сессия стирается и рассылается глобальное
 * событие 'auth:unauthorized', на которое подписан App.jsx: пользователь
 * возвращается на экран входа (раньше протухший токен приводил к тихим
 * ошибкам во всех разделах без какого-либо объяснения).
 *
 * Сигнатура сохранена: apiFetch(path, { token, ...fetchOptions }).
 */
export async function apiFetch(path, { token, ...options } = {}) {
  ensureInit()

  // Если токен не передали явно - берём из сессии (удобно для новых вызовов,
  // старые компоненты продолжают передавать token пропсом, как раньше).
  const firstToken = token || getAccessToken()
  let res = await requestOnce(path, options, firstToken)

  if (res.status === 401 && !isAuthFlowPath(path)) {
    const renewed = await ensureFreshAccessToken(firstToken)
    if (renewed) {
      res = await requestOnce(path, options, getAccessToken())
    }

    if (res.status === 401) {
      // Повторный 401 (или refresh не удался): сессию не спасти - выходим.
      forgetSession()
      dispatchAuthEvent('auth:unauthorized')
    }
  }

  const data = await readJsonBody(res)

  if (!res.ok) {
    const message = (data && (data.detail || data.message)) || `Ошибка запроса (${res.status})`
    throw new ApiError(message, res.status, data)
  }

  return data
}

export { ApiError }
