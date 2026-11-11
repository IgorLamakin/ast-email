import test from 'node:test'
import assert from 'node:assert/strict'

import { normalize, tokenize, scoreMatch, filterOptions } from '../src/utils/search.js'

// Поиск вынесен в utils/search.js без React именно ради этих тестов:
// в проекте нет jsdom/RTL, а логика фильтрации комбобоксов важна не меньше
// самого UI (её видят в обоих полях экрана «Отправка письма»).

test('normalize: регистр, лишние пробелы, пустые значения', () => {
  assert.equal(normalize('  Ivan   MAIL.ru  '), 'ivan mail.ru')
  assert.equal(normalize('IVAN@MAIL.RU'), 'ivan@mail.ru')
  assert.equal(normalize(''), '')
  assert.equal(normalize(null), '')
  assert.equal(normalize(undefined), '')
  assert.equal(normalize(42), '42')
})

test('tokenize: запрос разбивается на токены', () => {
  assert.deepEqual(tokenize('  Ivan   Mail '), ['ivan', 'mail'])
  assert.deepEqual(tokenize('иван иванович'), ['иван', 'иванович'])
  assert.deepEqual(tokenize(''), [])
  assert.deepEqual(tokenize('   '), [])
})

test('scoreMatch: находит локальную и доменную часть email', () => {
  // Совпадение по любой части адреса - до и после @.
  assert.notEqual(scoreMatch('ivan', 'ivan@mail.ru'), null)
  assert.notEqual(scoreMatch('iva@', 'ivan@mail.ru'), null)
  // Частичный ввод адреса с @: локальная часть + начало домена.
  assert.notEqual(scoreMatch('ivan@mail', 'ivan@mail.ru'), null)
  assert.equal(scoreMatch('ivan@mail', 'petr@ast.ru'), null)
  assert.notEqual(scoreMatch('mail', 'ivan@mail.ru'), null)
  assert.notEqual(scoreMatch('mail.ru', 'ivan@mail.ru'), null)
  // А вот чужие буквы находить не должен.
  assert.equal(scoreMatch('zzz', 'ivan@mail.ru'), null)
  assert.equal(scoreMatch('ivan', ''), null)
})

test('scoreMatch: приоритеты точное > префикс local > префикс строки > начало слова > подстрока', () => {
  const exact = scoreMatch('ivan@mail.ru', 'ivan@mail.ru')
  const localPrefix = scoreMatch('iva', 'ivan@mail.ru')
  const textPrefix = scoreMatch('ivan@', 'ivan@mail.ru')
  const wordStart = scoreMatch('mail', 'ivan@mail.ru')
  const substring = scoreMatch('mail', 'ivan@xmail.ru')

  assert.equal(exact, 0)
  for (const value of [localPrefix, textPrefix, wordStart, substring]) {
    assert.equal(typeof value, 'number')
  }
  assert.ok(localPrefix < textPrefix, 'префикс локальной части должен быть выше префикса строки')
  assert.ok(textPrefix < wordStart, 'префикс строки должен быть выше начала слова')
  assert.ok(wordStart < substring, 'начало слова должно быть выше подстроки')
})

test('scoreMatch: регистронезависимость', () => {
  assert.equal(scoreMatch('IVAN', 'ivan@mail.ru'), scoreMatch('ivan', 'ivan@mail.ru'))
  assert.notEqual(scoreMatch('ИВАН', 'Иван Иванович'), null)
})

test('scoreMatch: все токены запроса должны найтись', () => {
  assert.notEqual(scoreMatch('ivan mail', 'ivan@mail.ru'), null)
  assert.equal(scoreMatch('ivan petrov', 'ivan@mail.ru'), null)
})

test('filterOptions: пустой запрос - первые варианты в исходном порядке', () => {
  const options = [
    { value: 'a@b.ru', label: 'a@b.ru' },
    { value: 'c@d.ru', label: 'c@d.ru' },
    { value: 'e@f.ru', label: 'e@f.ru' },
  ]
  assert.deepEqual(filterOptions('', options), options)
  assert.deepEqual(filterOptions('   ', options), options)
  assert.deepEqual(filterOptions(undefined, options), options)
  assert.equal(filterOptions('', options, { limit: 2 }).length, 2)
  assert.equal(filterOptions('', options, { limit: 0 }).length, 0)
})

test('filterOptions: limit применяется и к результатам поиска', () => {
  const options = [
    { value: 'ivan1@mail.ru', label: 'ivan1@mail.ru' },
    { value: 'ivan2@mail.ru', label: 'ivan2@mail.ru' },
    { value: 'ivan3@mail.ru', label: 'ivan3@mail.ru' },
  ]
  const found = filterOptions('ivan', options, { limit: 2 })
  assert.equal(found.length, 2)
  // При равной оценке порядок исходный - так сохраняется «свежесть» истории.
  assert.equal(found[0].label, 'ivan1@mail.ru')
  assert.equal(found[1].label, 'ivan2@mail.ru')
  assert.equal(filterOptions('ivan', options).length, 3)
})

test('filterOptions: точное совпадение выше префикса, префикс - выше подстроки', () => {
  const options = [
    { value: 'xivan@mail.ru', label: 'xivan@mail.ru' },
    { value: 'ivan@mail.ru', label: 'ivan@mail.ru' },
    { value: 'ivan', label: 'ivan' },
    { value: 'ivan-petrov@mail.ru', label: 'ivan-petrov@mail.ru' },
  ]
  const labels = filterOptions('ivan', options).map(option => option.label)
  assert.deepEqual(labels, ['ivan', 'ivan@mail.ru', 'ivan-petrov@mail.ru', 'xivan@mail.ru'])
})

test('filterOptions: нет совпадений - пустой список', () => {
  const options = [
    { value: 'ivan@mail.ru', label: 'ivan@mail.ru' },
    { value: 'olga@ast.ru', label: 'olga@ast.ru' },
  ]
  assert.deepEqual(filterOptions('zzz', options), [])
})

test('filterOptions: совпадение по домену и регистру', () => {
  const options = [
    { value: 'ivan@mail.ru', label: 'ivan@mail.ru' },
    { value: 'olga@ast.ru', label: 'olga@ast.ru' },
    { value: 'petr@ivanov.ru', label: 'petr@ivanov.ru' },
  ]
  assert.deepEqual(filterOptions('MAIL', options).map(option => option.label), ['ivan@mail.ru'])
  assert.deepEqual(filterOptions('ast.ru', options).map(option => option.label), ['olga@ast.ru'])
  assert.deepEqual(filterOptions('iva@', options).map(option => option.label), ['ivan@mail.ru'])
})

test('filterOptions: поиск по обращению через fields', () => {
  const contacts = [
    { value: 'ivan@mail.ru', label: 'ivan@mail.ru', meta: 'Иван Иванович' },
    { value: 'petrov@mail.ru', label: 'petrov@mail.ru', meta: 'Пётр Сергеевич' },
  ]
  // По умолчанию ищем только по label - обращения не мешают поиску по email.
  assert.deepEqual(filterOptions('иван', contacts), [])
  // С явными fields по обращению находится контакт, хотя в email этих букв нет.
  assert.deepEqual(
    filterOptions('иван', contacts, { fields: ['label', 'meta'] }).map(option => option.label),
    ['ivan@mail.ru']
  )
  // Обращение через функцию-аксессор - на случай будущих форм опций.
  assert.deepEqual(
    filterOptions('пётр', contacts, { fields: [option => option.meta] }).map(option => option.label),
    ['petrov@mail.ru']
  )
  // Несколько токенов могут найтись в разных полях одной опции.
  assert.deepEqual(
    filterOptions('ivan иван', contacts, { fields: ['label', 'meta'] }).map(option => option.label),
    ['ivan@mail.ru']
  )
  assert.deepEqual(filterOptions('ivan пётр', contacts, { fields: ['label', 'meta'] }), [])
})

test('filterOptions: поля истории отправителя (label + meta) ищутся раздельно', () => {
  // Эхо истории: meta = «использован N раз», а искать по ней в поле отправителя
  // не нужно - поэтому EmailRender передаёт fields: ['label'].
  const senderOptions = [
    { value: 'ivan@mail.ru', label: 'ivan@mail.ru', meta: 'использован 5 раз' },
    { value: 'petr@ast.ru', label: 'petr@ast.ru', meta: 'использован 1 раз' },
  ]
  assert.deepEqual(
    filterOptions('5', senderOptions, { fields: ['label', 'meta'] }).map(option => option.label),
    ['ivan@mail.ru']
  )
  assert.deepEqual(filterOptions('5', senderOptions, { fields: ['label'] }), [])
})

test('filterOptions: устойчивость к некорректным входам', () => {
  assert.deepEqual(filterOptions('ivan', null), [])
  assert.deepEqual(filterOptions('ivan', undefined), [])
  assert.deepEqual(filterOptions('ivan', [{ label: 'ivan@mail.ru' }], { limit: 0 }), [])
})
