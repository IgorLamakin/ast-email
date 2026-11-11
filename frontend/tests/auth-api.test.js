// Тесты прозрачного обновления токенов в frontend/src/api.js.
//
// JSX node не умеет, поэтому проверяем именно чистую часть: apiFetch с
// подменёнными fetch / localStorage / window. api.js не обращается к window
// и localStorage на верхнем уровне модуля - иначе этот файл упал бы уже на
// статическом import (в Node их нет).
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  API_BASE,
  ApiError,
  apiFetch,
  initSession,
  getSession,
  getAccessToken,
  setSessionFromResponse,
  refreshSession,
  logoutSession,
} from '../src/api.js'

function createMemoryStorage(initial = {}) {
  const map = new Map(Object.entries(initial))
  return {
    getItem(key) {
      return map.has(key) ? map.get(key) : null
    },
    setItem(key, value) {
      map.set(key, String(value))
    },
    removeItem(key) {
      map.delete(key)
    },
    keys() {
      return [...map.keys()]
    },
  }
}

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: {
      get(name) {
        return String(name).toLowerCase() === 'content-type' ? 'application/json' : null
      },
    },
    async json() {
      return body
    },
  }
}

// Поднимает «браузерное» окружение: fetch-заглушка, localStorage с уже
// сохранённой парой, window.dispatchEvent, собирающий события.
// handler(call) получает { url, options, urlPath, authorization }.
function setupEnv(t, handler, initial = null) {
  const storage = createMemoryStorage(
    initial ?? {
      auth: JSON.stringify({ accessToken: 'old-access', refreshToken: 'old-refresh' }),
      token: 'old-access',
    },
  )
  const calls = []
  const events = []

  globalThis.fetch = async (url, options = {}) => {
    const headers = options.headers || {}
    const call = {
      url,
      options,
      urlPath: String(url).startsWith(API_BASE) ? String(url).slice(API_BASE.length) : String(url),
      authorization: headers.Authorization || headers.authorization || null,
    }
    calls.push(call)
    return handler(call)
  }
  globalThis.localStorage = storage
  globalThis.window = {
    dispatchEvent(event) {
      events.push(event)
    },
  }

  // Сбрасываем модульное состояние api.js на нашу заглушку хранилища.
  initSession(storage)

  t.after(() => {
    delete globalThis.fetch
    delete globalThis.localStorage
    delete globalThis.window
  })

  return { storage, calls, events }
}

function eventTypes(events) {
  return events.map((e) => e.type)
}

test('401 -> refresh -> исходный запрос повторяется с новым токеном', async (t) => {
  const env = setupEnv(t, (call) => {
    if (call.urlPath === '/auth/refresh') {
      return jsonResponse(200, {
        access_token: 'new-access',
        token_type: 'bearer',
        refresh_token: 'new-refresh',
        expires_in: 43200,
      })
    }
    if (call.authorization === 'Bearer old-access') {
      return jsonResponse(401, { detail: 'Not authenticated' })
    }
    if (call.authorization === 'Bearer new-access') {
      return jsonResponse(200, { items: [1, 2] })
    }
    return jsonResponse(500, { detail: 'unexpected token' })
  })

  const data = await apiFetch('/contacts', { token: 'old-access' })

  assert.deepEqual(data, { items: [1, 2] })
  assert.equal(env.calls.length, 3)
  assert.equal(env.calls[0].urlPath, '/contacts')
  assert.equal(env.calls[0].authorization, 'Bearer old-access')
  assert.equal(env.calls[1].urlPath, '/auth/refresh')
  assert.equal(env.calls[1].options.method, 'POST')
  // В refresh уходит именно refresh-токен из хранилища, а не access.
  assert.deepEqual(JSON.parse(env.calls[1].options.body), { refresh_token: 'old-refresh' })
  assert.equal(env.calls[2].urlPath, '/contacts')
  assert.equal(env.calls[2].authorization, 'Bearer new-access')

  // localStorage: сохранена новая пара + продублирован legacy 'token'.
  const stored = JSON.parse(env.storage.getItem('auth'))
  assert.deepEqual(stored, { accessToken: 'new-access', refreshToken: 'new-refresh' })
  assert.equal(env.storage.getItem('token'), 'new-access')

  // Событие для App.jsx и актуальный токен в модуле.
  assert.deepEqual(eventTypes(env.events), ['auth:refreshed'])
  assert.equal(env.events[0].detail.accessToken, 'new-access')
  assert.equal(getAccessToken(), 'new-access')
})

test('refresh не удался -> auth:unauthorized, сессия очищена, ошибка исходного запроса', async (t) => {
  const env = setupEnv(t, (call) => {
    if (call.urlPath === '/auth/refresh') {
      return jsonResponse(401, { detail: 'Invalid refresh token' })
    }
    return jsonResponse(401, { detail: 'Not authenticated' })
  })

  await assert.rejects(
    () => apiFetch('/contacts', { token: 'old-access' }),
    (err) => {
      assert.ok(err instanceof ApiError)
      assert.equal(err.status, 401)
      // Текст ошибки прежний - протухший токен, а не «ошибка обновления».
      assert.equal(err.message, 'Not authenticated')
      return true
    },
  )

  assert.equal(env.calls.filter((c) => c.urlPath === '/auth/refresh').length, 1)
  assert.equal(env.calls.filter((c) => c.urlPath === '/contacts').length, 1)
  assert.equal(env.storage.getItem('auth'), null)
  assert.equal(env.storage.getItem('token'), null)
  assert.deepEqual(env.storage.keys(), [])
  assert.deepEqual(eventTypes(env.events), ['auth:unauthorized'])
  assert.equal(getSession(), null)
})

test('два параллельных 401 -> только ОДИН запрос /auth/refresh (single-flight)', async (t) => {
  let refreshCount = 0
  const env = setupEnv(t, async (call) => {
    if (call.urlPath === '/auth/refresh') {
      refreshCount += 1
      // Задержка: оба исходных запроса должны получить 401 ДО завершения
      // refresh, иначе тест перестанет проверять single-flight.
      await new Promise((resolve) => setTimeout(resolve, 25))
      return jsonResponse(200, { access_token: 'new-access', refresh_token: 'new-refresh' })
    }
    if (call.authorization === 'Bearer old-access') {
      return jsonResponse(401, { detail: 'Not authenticated' })
    }
    return jsonResponse(200, { ok: true })
  })

  const [first, second] = await Promise.all([
    apiFetch('/templates', { token: 'old-access' }),
    apiFetch('/workspace', { token: 'old-access' }),
  ])

  assert.deepEqual(first, { ok: true })
  assert.deepEqual(second, { ok: true })
  assert.equal(refreshCount, 1)
  assert.equal(env.calls.filter((c) => c.urlPath === '/auth/refresh').length, 1)
  // Повторные запросы оба ушли уже с новым токеном.
  const retries = env.calls.filter((c) => c.authorization === 'Bearer new-access')
  assert.equal(retries.length, 2)
  assert.deepEqual(eventTypes(env.events), ['auth:refreshed'])
})

test('повторный 401 после успешного refresh -> auth:unauthorized и очистка', async (t) => {
  const env = setupEnv(t, (call) => {
    if (call.urlPath === '/auth/refresh') {
      return jsonResponse(200, { access_token: 'new-access', refresh_token: 'new-refresh' })
    }
    // Защищённый эндпоинт не принимает вообще никакой токен (например,
    // пользователя удалили или он заблокирован).
    return jsonResponse(401, { detail: 'Not authenticated' })
  })

  await assert.rejects(() => apiFetch('/contacts', { token: 'old-access' }), (err) => {
    assert.equal(err.status, 401)
    return true
  })

  assert.deepEqual(
    env.calls.map((c) => c.urlPath),
    ['/contacts', '/auth/refresh', '/contacts'],
  )
  // Сначала refresh всё-таки удался ('auth:refreshed'), но повторный запрос
  // с новым токеном снова получил 401 - только тогда разлогиниваем.
  assert.deepEqual(eventTypes(env.events), ['auth:refreshed', 'auth:unauthorized'])
  assert.equal(env.storage.getItem('auth'), null)
  assert.equal(getSession(), null)
})

test('401 на /auth/login не запускает refresh и не разлогинивает', async (t) => {
  const env = setupEnv(t, () =>
    jsonResponse(401, { detail: 'Incorrect username or password' }),
  )

  await assert.rejects(
    () =>
      apiFetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'username=user%40example.com&password=wrong',
      }),
    (err) => {
      assert.ok(err instanceof ApiError)
      assert.equal(err.status, 401)
      assert.equal(err.message, 'Incorrect username or password')
      return true
    },
  )

  // Ровно один запрос (сам логин), ни refresh, ни события авторизации.
  assert.deepEqual(env.calls.map((c) => c.urlPath), ['/auth/login'])
  assert.deepEqual(eventTypes(env.events), [])
  // Существующая сессия не тронута: 401 на логине - это «неверный пароль»,
  // а не «сессия истекла».
  assert.equal(getAccessToken(), 'old-access')
  assert.equal(JSON.parse(env.storage.getItem('auth')).accessToken, 'old-access')
})

test('401 без refresh-токена (легаси-сессия) -> сразу auth:unauthorized', async (t) => {
  // Пользователь обновился с 2.5.x: в localStorage только старый 'token'.
  const env = setupEnv(t, () => jsonResponse(401, { detail: 'Not authenticated' }), {
    token: 'legacy-access',
  })

  await assert.rejects(() => apiFetch('/contacts', { token: 'legacy-access' }), (err) => {
    assert.equal(err.status, 401)
    return true
  })

  assert.deepEqual(env.calls.map((c) => c.urlPath), ['/contacts'])
  assert.deepEqual(eventTypes(env.events), ['auth:unauthorized'])
  assert.equal(env.storage.getItem('token'), null)
  assert.equal(getSession(), null)
})

test('сетевой сбой: ApiError(status=0), текст ошибки не изменился', async (t) => {
  const env = setupEnv(t, () => {
    throw new Error('ECONNREFUSED')
  })

  await assert.rejects(() => apiFetch('/contacts', { token: 'old-access' }), (err) => {
    assert.ok(err instanceof ApiError)
    assert.equal(err.status, 0)
    assert.equal(err.message, 'Сервер не отвечает. Проверьте, что backend запущен.')
    return true
  })

  assert.equal(env.calls.length, 1)
  assert.deepEqual(eventTypes(env.events), [])
})

test('setSessionFromResponse сохраняет пару ответа бэкенда и не теряет refresh при ротации', (t) => {
  const env = setupEnv(t, () => jsonResponse(200, {}), {})

  const saved = setSessionFromResponse({
    access_token: 'access-login',
    token_type: 'bearer',
    refresh_token: 'refresh-login',
    expires_in: 43200,
  })

  assert.deepEqual(saved, { accessToken: 'access-login', refreshToken: 'refresh-login' })
  assert.deepEqual(getSession(), { accessToken: 'access-login', refreshToken: 'refresh-login' })
  assert.deepEqual(JSON.parse(env.storage.getItem('auth')), {
    accessToken: 'access-login',
    refreshToken: 'refresh-login',
  })
  assert.equal(env.storage.getItem('token'), 'access-login')

  // Ответ без refresh_token (например, кривой бэкенд) не должен «обнулить»
  // автологин - оставляем прежний refresh-токен.
  const rotated = setSessionFromResponse({ access_token: 'access-2' })
  assert.deepEqual(rotated, { accessToken: 'access-2', refreshToken: 'refresh-login' })
})

test('refreshSession бросает ApiError, если refresh-токена нет', async (t) => {
  setupEnv(t, () => jsonResponse(200, {}), {})

  await assert.rejects(() => refreshSession(), (err) => {
    assert.ok(err instanceof ApiError)
    assert.equal(err.status, 401)
    return true
  })
})

test('logoutSession отзывает refresh-токен и очищает сессию', async (t) => {
  const env = setupEnv(t, (call) => {
    if (call.urlPath === '/auth/logout') return jsonResponse(200, { message: 'Logged out' })
    return jsonResponse(404, { detail: 'Not found' })
  })

  const result = await logoutSession()

  assert.equal(result, true)
  assert.deepEqual(env.calls.map((c) => c.urlPath), ['/auth/logout'])
  assert.deepEqual(JSON.parse(env.calls[0].options.body), { refresh_token: 'old-refresh' })
  assert.equal(env.storage.getItem('auth'), null)
  assert.equal(env.storage.getItem('token'), null)
  assert.equal(getSession(), null)
  // Выход по кнопке не рассылает 'auth:unauthorized' - состояние уже
  // сбрасывает сам App.jsx.
  assert.deepEqual(eventTypes(env.events), [])
})

test('logoutSession не пробрасывает ошибки сети наружу', async (t) => {
  const env = setupEnv(t, () => {
    throw new Error('ECONNREFUSED')
  })

  await assert.doesNotReject(() => logoutSession())
  assert.equal(env.storage.getItem('auth'), null)
  assert.equal(getSession(), null)
})
