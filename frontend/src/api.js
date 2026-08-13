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

export const API_BASE = 'http://localhost:8000/api'

class ApiError extends Error {
  constructor(message, status, data) {
    super(message)
    this.status = status
    this.data = data
  }
}

/**
 * Обёртка над fetch(): подставляет базовый адрес API, добавляет заголовок
 * авторизации (если передан токен), сама разбирает JSON и кидает ApiError
 * с понятным сообщением на нестандартных ответах.
 *
 * При 401 (просроченный/невалидный токен) рассылает глобальное событие
 * 'auth:unauthorized', на которое подписан App.jsx, чтобы разлогинить
 * пользователя и вернуть его на экран входа - раньше протухший токен просто
 * приводил к тихим ошибкам во всех разделах без какого-либо объяснения.
 */
export async function apiFetch(path, { token, ...options } = {}) {
  const headers = { ...(options.headers || {}) }
  if (token) headers.Authorization = `Bearer ${token}`

  let res
  try {
    res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  } catch (e) {
    throw new ApiError('Сервер не отвечает. Проверьте, что backend запущен.', 0, null)
  }

  if (res.status === 401) {
    window.dispatchEvent(new CustomEvent('auth:unauthorized'))
  }

  const contentType = res.headers.get('content-type') || ''
  const data = contentType.includes('application/json') ? await res.json().catch(() => null) : null

  if (!res.ok) {
    const message = (data && (data.detail || data.message)) || `Ошибка запроса (${res.status})`
    throw new ApiError(message, res.status, data)
  }

  return data
}

export { ApiError }
