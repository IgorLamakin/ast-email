// Чистая логика поиска для полей экрана «Отправка письма» (история адресов
// отправителя и быстрый выбор контакта).
//
// Вынесена из компонентов в отдельный ESM-модуль без React, потому что в
// проекте нет jsdom/react-testing-library: проверять поиск проще всего
// обычными node-тестами (npm test из frontend).
//
// Термины:
//   query - то, что набрал пользователь;
//   text  - строка, по которой ищем (email, обращение и т.п.).

/** Приводит строку к виду, в котором регистр и лишние пробелы не мешают поиску. */
export function normalize(value) {
  return String(value ?? '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
}

/** Разбивает запрос на токены: «Ivan  Mail» -> ['ivan', 'mail']. */
export function tokenize(query) {
  const normalized = normalize(query)
  if (!normalized) return []
  return normalized.split(' ').filter(Boolean)
}

// Категории совпадения: чем меньше число, тем выше вариант в списке.
// Порядок ровно из задачи: точное совпадение -> префикс локальной части email
// -> префикс строки -> начало слова -> подстрока.
const SCORE_EXACT = 0
const SCORE_LOCAL_PREFIX = 1
const SCORE_TEXT_PREFIX = 2
const SCORE_WORD_START = 3
const SCORE_SUBSTRING = 4
// Категории разносим на разряд, чтобы позиция совпадения внутри категории
// (используется как тай-брейк) не могла перебить более важную категорию.
const SCORE_STEP = 1000

// Граница слова: любой не-алфавитно-цифровой символ (пробел, @, точка, дефис).
// Этого достаточно и для латиницы (email), и для кириллицы (обращение).
function isLetterOrDigit(char) {
  return /[0-9a-zа-яё]/.test(char)
}

// Запрос с «@» - пользователь набирает адрес целиком («iva@», «ivan@mail»).
// Такое совпадение не обязано быть подстрокой: «iva@» не встречается в
// «ivan@mail.ru» как подстрока, но означает «локальная часть начинается на iva,
// дальше @» - и должно находить адрес. Поэтому сверяем структуру адреса:
// то, что до @, - начало локальной части, то, что после, - начало домена.
// Для text берём первое слово: при поиске по нескольким полям (email + meta)
// адрес всегда идёт первым, а приветствие в разбор @ попадать не должно.
function scoreEmailToken(token, text) {
  const emailText = text.split(' ')[0]
  const textAt = emailText.indexOf('@')
  if (textAt === -1) return null
  const queryAt = token.indexOf('@')
  const queryLocal = token.slice(0, queryAt)
  const queryDomain = token.slice(queryAt + 1)
  if (!queryLocal && !queryDomain) return null
  // «ivan@» и «ivan@mail» - буквальный префикс строки, это самый точный
  // вариант после полного совпадения.
  if (text.startsWith(token)) return SCORE_TEXT_PREFIX * SCORE_STEP
  const textLocal = emailText.slice(0, textAt)
  const textDomain = emailText.slice(textAt + 1)
  if (queryLocal && !textLocal.startsWith(queryLocal)) return null
  if (queryDomain && !textDomain.startsWith(queryDomain)) return null
  return SCORE_LOCAL_PREFIX * SCORE_STEP + Math.max(textLocal.indexOf(queryLocal), 0)
}

function scoreToken(token, text) {
  if (text === token) return SCORE_EXACT
  if (token.indexOf('@') !== -1) return scoreEmailToken(token, text)
  const index = text.indexOf(token)
  if (index === -1) return null
  // Локальная часть email (всё до @) - самый точный признак: «iva» должно
  // находить «ivan@mail.ru» раньше, чем «...iva...» где-то в домене.
  const localPart = text.split('@')[0]
  if (localPart.startsWith(token)) return SCORE_LOCAL_PREFIX * SCORE_STEP + index
  if (text.startsWith(token)) return SCORE_TEXT_PREFIX * SCORE_STEP + index
  if (index === 0 || !isLetterOrDigit(text[index - 1])) {
    return SCORE_WORD_START * SCORE_STEP + index
  }
  return SCORE_SUBSTRING * SCORE_STEP + index
}

/**
 * Оценивает, насколько текст похож на запрос.
 * Возвращает число (меньше = лучше) или null, если запрос не найден.
 * Запрос разбивается на токены, и КАЖДЫЙ токен должен найтись в тексте.
 */
export function scoreMatch(query, text) {
  const tokens = tokenize(query)
  const haystack = normalize(text)
  // Пустой запрос - «пользователь ещё ничего не ввёл»; ограничение выдачи
  // делает filterOptions, здесь это просто валидное совпадение.
  if (tokens.length === 0) return 0
  if (!haystack) return null
  let total = 0
  for (const token of tokens) {
    const tokenScore = scoreToken(token, haystack)
    if (tokenScore === null) return null
    total += tokenScore
  }
  return total
}

// Поля опций можно задавать строкой (имя свойства) или функцией-аксессором -
// так filterOptions не зависит от конкретной формы объектов (контакты с
// greeting, история с use_count и т.п.).
function optionText(option, fields) {
  if (!option || typeof option !== 'object') return ''
  const parts = []
  for (const field of fields) {
    const raw = typeof field === 'function' ? field(option) : option[field]
    if (raw !== null && raw !== undefined && raw !== '') parts.push(String(raw))
  }
  return parts.join(' ')
}

/**
 * Фильтрует и сортирует варианты выпадающего списка.
 *
 * @param {string} query - запрос пользователя.
 * @param {Array<object>} options - варианты {value, label, meta, ...}.
 * @param {{fields?: Array<string|Function>, limit?: number}} [settings]
 *   fields - по каким полям искать (по умолчанию label);
 *   limit  - сколько вариантов вернуть (по умолчанию 8).
 * @returns {Array<object>} подходящие варианты, лучшие первыми.
 */
export function filterOptions(query, options, { fields = ['label'], limit = 8 } = {}) {
  const list = Array.isArray(options) ? options : []
  const max = Number.isFinite(limit) ? Math.max(0, Math.floor(limit)) : 8
  // Пустой запрос - показываем первые варианты в исходном порядке (история
  // приходит с бэкенда уже отсортированной по последнему использованию).
  if (tokenize(query).length === 0) return list.slice(0, max)
  const matches = []
  list.forEach((option, index) => {
    const score = scoreMatch(query, optionText(option, fields))
    if (score !== null) matches.push({ option, score, index })
  })
  // При равной оценке сохраняем исходный порядок - он осмысленный (свежесть).
  matches.sort((a, b) => a.score - b.score || a.index - b.index)
  return matches.slice(0, max).map(match => match.option)
}
