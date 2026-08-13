import { useState } from 'react'
import { apiFetch } from '../api'

function Login({ onLogin }) {
  const [isRegister, setIsRegister] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const data = isRegister
        ? await apiFetch('/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password, full_name: fullName }),
          })
        : await apiFetch('/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ username: email, password }),
          })

      if (isRegister) {
        setIsRegister(false)
        setError('Регистрация успешна! Войдите.')
      } else {
        onLogin(data.access_token)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-line-200">
      <div className="bg-canvas-0 p-8 rounded-lg shadow-md w-full max-w-md">
        <h1 className="text-2xl font-bold text-center mb-2">Email Templates</h1>
        <p className="text-ink-500 text-center mb-6">{isRegister ? 'Регистрация' : 'Вход в систему'}</p>

        {error && (
          <div className={`mb-4 p-3 rounded text-sm ${error.includes('успешна') ? 'bg-ok-100 text-ok-600' : 'bg-warn-100 text-warn-600'}`}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          {isRegister && (
            <div>
              <label className="block text-sm font-medium text-ink-900 mb-1">Имя</label>
              <input type="text" value={fullName} onChange={e => setFullName(e.target.value)}
                className="w-full px-3 py-2 border rounded focus:outline-none focus:ring-2 focus:ring-signal-500" />
            </div>
          )}
          <div>
            <label className="block text-sm font-medium text-ink-900 mb-1">Email</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} required
              className="w-full px-3 py-2 border rounded focus:outline-none focus:ring-2 focus:ring-signal-500" />
          </div>
          <div>
            <label className="block text-sm font-medium text-ink-900 mb-1">Пароль</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} required
              className="w-full px-3 py-2 border rounded focus:outline-none focus:ring-2 focus:ring-signal-500" />
          </div>
          <button type="submit" disabled={loading}
            className="w-full bg-signal-500 hover:bg-signal-600 text-white py-2 rounded font-medium transition disabled:opacity-50">
            {loading ? 'Загрузка...' : isRegister ? 'Зарегистрироваться' : 'Войти'}
          </button>
        </form>

        <p className="mt-4 text-center text-sm text-ink-500">
          {isRegister ? 'Уже есть аккаунт?' : 'Нет аккаунта?'}{' '}
          <button onClick={() => { setIsRegister(!isRegister); setError('') }}
            className="text-signal-600 hover:underline">
            {isRegister ? 'Войти' : 'Зарегистрироваться'}
          </button>
        </p>
      </div>
    </div>
  )
}

export default Login
