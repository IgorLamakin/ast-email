// Тесты хранилища сессии (frontend/src/utils/authStorage.js).
//
// Модуль чистый (без window/React), поэтому проверяется обычным node:test
// с заглушкой localStorage в памяти - без jsdom.
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createAuthStorage,
  loadSession,
  saveSession,
  clearSession,
  AUTH_STORAGE_KEY,
} from '../src/utils/authStorage.js'

// Минимальная заглушка Storage API. Отдельный объект на каждый тест, чтобы
// тесты не влияли друг на друга.
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

test('save/load: пара токенов сохраняется и читается, access дублируется в legacy token', () => {
  const storage = createMemoryStorage()
  const auth = createAuthStorage(storage)

  assert.equal(auth.load(), null)

  auth.save({ accessToken: 'access-1', refreshToken: 'refresh-1' })

  const raw = JSON.parse(storage.getItem(AUTH_STORAGE_KEY))
  assert.deepEqual(raw, { accessToken: 'access-1', refreshToken: 'refresh-1' })
  // Обратная совместимость: старые места читают одиночный 'token'.
  assert.equal(storage.getItem('token'), 'access-1')

  assert.deepEqual(auth.load(), { accessToken: 'access-1', refreshToken: 'refresh-1' })
})

test('load: миграция со старого ключа token (refresh-токена ещё нет)', () => {
  const storage = createMemoryStorage({ token: 'legacy-access' })
  const auth = createAuthStorage(storage)

  assert.deepEqual(auth.load(), { accessToken: 'legacy-access', refreshToken: null })
})

test('load: битый JSON в auth -> null, легаси-токен НЕ воскрешаем', () => {
  const storage = createMemoryStorage({
    auth: '{"accessToken": "broken"',
    token: 'legacy-access',
  })
  const auth = createAuthStorage(storage)

  assert.equal(auth.load(), null)
})

test('load: auth без accessToken (кривой формат) -> null', () => {
  const storage = createMemoryStorage({ auth: JSON.stringify({ refreshToken: 'refresh-1' }) })
  assert.equal(createAuthStorage(storage).load(), null)
})

test('clear: удаляет и auth, и legacy token', () => {
  const storage = createMemoryStorage()
  const auth = createAuthStorage(storage)
  auth.save({ accessToken: 'access-1', refreshToken: 'refresh-1' })

  auth.clear()

  assert.equal(auth.load(), null)
  assert.equal(storage.getItem(AUTH_STORAGE_KEY), null)
  assert.equal(storage.getItem('token'), null)
  assert.deepEqual(storage.keys(), [])
})

test('save: пустой/битый вход не пишет мусор и не бросает', () => {
  const storage = createMemoryStorage()
  const auth = createAuthStorage(storage)

  assert.equal(auth.save(null), null)
  assert.equal(auth.save({}), null)
  assert.equal(auth.save({ refreshToken: 'refresh-only' }), null)
  assert.deepEqual(storage.keys(), [])
})

test('без storage (Node/localStorage недоступен) все операции безопасны', () => {
  for (const auth of [createAuthStorage(null), createAuthStorage(undefined), createAuthStorage()]) {
    assert.equal(auth.load(), null)
    assert.equal(auth.save({ accessToken: 'a', refreshToken: 'r' }), null)
    assert.doesNotThrow(() => auth.clear())
  }
})

test('обёртки loadSession/saveSession/clearSession берут globalThis.localStorage лениво', (t) => {
  const storage = createMemoryStorage()
  const prev = globalThis.localStorage
  globalThis.localStorage = storage
  t.after(() => {
    if (prev === undefined) delete globalThis.localStorage
    else globalThis.localStorage = prev
  })

  assert.equal(loadSession(), null)
  saveSession({ accessToken: 'access-2', refreshToken: 'refresh-2' })
  assert.equal(storage.getItem('token'), 'access-2')
  assert.deepEqual(loadSession(), { accessToken: 'access-2', refreshToken: 'refresh-2' })

  clearSession()
  assert.equal(loadSession(), null)
})

test('обёртки не падают, если localStorage недоступен', (t) => {
  const prev = globalThis.localStorage
  delete globalThis.localStorage
  t.after(() => {
    if (prev !== undefined) globalThis.localStorage = prev
  })

  assert.equal(loadSession(), null)
  assert.equal(saveSession({ accessToken: 'a', refreshToken: 'r' }), null)
  assert.doesNotThrow(() => clearSession())
})
