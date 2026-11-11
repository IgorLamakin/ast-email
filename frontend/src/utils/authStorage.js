// Хранилище пары токенов (access + refresh) в localStorage.
//
// Зачем отдельный модуль, а не пара строк в App.jsx:
//   - Логика «прочитать сессию / записать / стереть» нужна минимум в трёх местах
//     (App.jsx при старте и входе, api.js при обновлении токена по 401, экран
//     выхода). Раньше это был один ключ 'token', размазанный по компонентам, и
//     любая опечатка в имени ключа давала «пользователь внезапно разлогинен».
//   - Модуль чистый и не трогает window на верхнем уровне, поэтому его можно
//     покрыть юнит-тестами в Node (npm test) без jsdom/браузера.
//
// Ключи:
//   'auth'  — новая (2.6.0) пара {"accessToken","refreshToken"}.
//   'token' — легаси-ключ со «старым» одиночным access-токеном. Его продолжаем
//             писать и читать, чтобы обновление приложения не разлогинило тех,
//             у кого уже установлена предыдущая версия (и чтобы electron/
//             wizard.html, который пишет 'token', оставался совместимым).
//
// Сам localStorage передаётся аргументом (createAuthStorage) — в тестах вместо
// него подставляется простая заглушка в памяти. Обёртки loadSession/saveSession/
// clearSession берут globalThis.localStorage ЛЕНИВО, в момент вызова: на верхнем
// уровне модуля обращаться к нему нельзя (в Node его нет, а в браузере при
// запрете сторонних cookies обращение к localStorage вообще бросает исключение).

export const AUTH_STORAGE_KEY = 'auth'
export const LEGACY_TOKEN_KEY = 'token'

// Возвращает безопасный storage или null, если хранилище недоступно.
function safeStorage() {
  try {
    return globalThis.localStorage || null
  } catch {
    // Приватный режим / запрет cookies: приложение должно работать без
    // сохранения сессии, а не падать на старте.
    return null
  }
}

function readRaw(store, key) {
  if (!store || typeof store.getItem !== 'function') return null
  try {
    return store.getItem(key)
  } catch {
    return null
  }
}

/**
 * Создаёт обёртку над переданным storage (обычно localStorage).
 * Возвращает объект {load, save, clear}.
 *
 * @param {Storage|null|undefined} storage
 */
export function createAuthStorage(storage) {
  const store = storage && typeof storage.getItem === 'function' ? storage : null

  return {
    /**
     * Читает сессию. Возвращает {accessToken, refreshToken} или null.
     *
     * Порядок важен: если ключ 'auth' вообще существует, доверяем только ему.
     * Битый JSON в нём — это не «нет сессии», а испорченное хранилище: отдаём
     * null и НЕ проваливаемся в легаси 'token', иначе после неудачной записи
     * можно было бы «воскресить» давно просроченный токен.
     */
    load() {
      const raw = readRaw(store, AUTH_STORAGE_KEY)
      if (raw !== null && raw !== undefined) {
        try {
          const parsed = JSON.parse(raw)
          const accessToken = parsed && (parsed.accessToken || parsed.access_token)
          if (!accessToken || typeof accessToken !== 'string') return null
          const refreshToken = parsed.refreshToken ?? parsed.refresh_token ?? null
          return { accessToken, refreshToken: refreshToken || null }
        } catch {
          return null
        }
      }

      // Миграция со старых версий: был только 'token', refresh-токена нет.
      // При первом же 401 такой пользователь один раз увидит экран входа,
      // а после входа получит полноценную пару.
      const legacy = readRaw(store, LEGACY_TOKEN_KEY)
      if (legacy && typeof legacy === 'string') {
        return { accessToken: legacy, refreshToken: null }
      }
      return null
    },

    /**
     * Сохраняет сессию. Пара пишется в 'auth', access-токен дублируется в
     * 'token' для обратной совместимости (его читают старые сборки фронтенда
     * и electron/wizard.html).
     */
    save(session) {
      if (!store) return null
      const accessToken = session && (session.accessToken || session.access_token)
      if (!accessToken || typeof accessToken !== 'string') return null
      const refreshToken = session.refreshToken ?? session.refresh_token ?? null
      const payload = { accessToken, refreshToken: refreshToken || null }
      try {
        store.setItem(AUTH_STORAGE_KEY, JSON.stringify(payload))
        store.setItem(LEGACY_TOKEN_KEY, accessToken)
      } catch {
        // Квота/запрет записи: сессия проживёт до перезапуска приложения,
        // но запросы работать не перестанут.
        return null
      }
      return payload
    },

    /** Полностью забывает сессию (и легаси-ключ, иначе load() вернёт старый токен). */
    clear() {
      if (!store) return
      try {
        store.removeItem(AUTH_STORAGE_KEY)
        store.removeItem(LEGACY_TOKEN_KEY)
      } catch {
        // см. комментарий в save()
      }
    },
  }
}

// --- Обёртки над «тем самым» localStorage приложения ---
// Обращаемся к globalThis.localStorage только внутри функций (см. комментарий
// в заголовке файла).

export function loadSession() {
  return createAuthStorage(safeStorage()).load()
}

export function saveSession(session) {
  return createAuthStorage(safeStorage()).save(session)
}

export function clearSession() {
  createAuthStorage(safeStorage()).clear()
}
