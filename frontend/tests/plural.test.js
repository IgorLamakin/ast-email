import { test } from 'node:test'
import assert from 'node:assert'
import { pluralRu, usedTimesLabel } from '../src/utils/plural.js'

test('pluralRu: базовые формы', () => {
  assert.equal(pluralRu(1, 'раз', 'раза', 'раз'), 'раз')
  assert.equal(pluralRu(2, 'раз', 'раза', 'раз'), 'раза')
  assert.equal(pluralRu(3, 'раз', 'раза', 'раз'), 'раза')
  assert.equal(pluralRu(4, 'раз', 'раза', 'раз'), 'раза')
  assert.equal(pluralRu(5, 'раз', 'раза', 'раз'), 'раз')
  assert.equal(pluralRu(0, 'раз', 'раза', 'раз'), 'раз')
})

test('pluralRu: вторая сотня и большие числа', () => {
  for (const n of [11, 12, 13, 14, 111, 112, 114]) {
    assert.equal(pluralRu(n, 'раз', 'раза', 'раз'), 'раз', 'n=' + n)
  }
  assert.equal(pluralRu(21, 'раз', 'раза', 'раз'), 'раз')
  assert.equal(pluralRu(22, 'раз', 'раза', 'раз'), 'раза')
  assert.equal(pluralRu(101, 'раз', 'раза', 'раз'), 'раз')
  assert.equal(pluralRu(102, 'раз', 'раза', 'раз'), 'раза')
})

test('pluralRu: мусорные значения не роняют функцию', () => {
  assert.equal(pluralRu(null, 'раз', 'раза', 'раз'), 'раз')
  assert.equal(pluralRu(undefined, 'раз', 'раза', 'раз'), 'раз')
  assert.equal(pluralRu('2', 'раз', 'раза', 'раз'), 'раза')
})

test('usedTimesLabel: подпись истории отправителя', () => {
  assert.equal(usedTimesLabel(1), 'использован 1 раз')
  assert.equal(usedTimesLabel(2), 'использован 2 раза')
  assert.equal(usedTimesLabel(3), 'использован 3 раза')
  assert.equal(usedTimesLabel(5), 'использован 5 раз')
  assert.equal(usedTimesLabel(11), 'использован 11 раз')
  assert.equal(usedTimesLabel(21), 'использован 21 раз')
  assert.equal(usedTimesLabel(22), 'использован 22 раза')
})
