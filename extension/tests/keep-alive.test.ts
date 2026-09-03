/**
 * `keepAliveSleep` — сон, переживающий усыпление MV3 service worker'а (см. keep-alive.ts).
 * Проверяем то, ради чего он заведён: длинный сон пингует chrome-API (сброс idle-таймера),
 * короткий — нет, и в обоих случаях сон честно досыпает.
 * Запуск: cd extension && npx tsx tests/keep-alive.test.ts
 */
import assert from 'node:assert/strict'

let pings = 0
;(globalThis as unknown as { chrome: unknown }).chrome = {
  runtime: {
    lastError: undefined,
    getPlatformInfo: (cb: () => void) => {
      pings++
      cb()
    },
  },
}

const { keepAliveSleep, _PING_INTERVAL_MS_FOR_TESTS, _PING_THRESHOLD_MS_FOR_TESTS } = await import(
  '../src/background/keep-alive.ts'
)

assert.ok(
  _PING_INTERVAL_MS_FOR_TESTS < 30_000,
  'пинг должен быть заметно чаще 30-секундного idle-таймера MV3',
)
assert.ok(_PING_THRESHOLD_MS_FOR_TESTS < 30_000, 'порог пинга ниже idle-таймера')

// Короткий сон — без пингов, воркер и так не успеет уснуть.
pings = 0
let t0 = Date.now()
await keepAliveSleep(30)
assert.equal(pings, 0, 'короткий сон не должен пинговать')
assert.ok(Date.now() - t0 >= 25, 'короткий сон должен реально спать')

// Нулевой/отрицательный сон резолвится сразу и ничего не планирует.
pings = 0
await keepAliveSleep(0)
await keepAliveSleep(-5)
assert.equal(pings, 0, 'нулевой сон не пингует')

// Длинный сон: пинги идут, пока спим. Ускоряем время подменой таймеров — реальные 20с в тесте
// ждать нельзя, а важен сам факт «во время сна воркер дёргают».
const realSetInterval = globalThis.setInterval
const realSetTimeout = globalThis.setTimeout
const intervals: (() => void)[] = []
;(globalThis as unknown as { setInterval: unknown }).setInterval = (fn: () => void) => {
  intervals.push(fn)
  return 1 as unknown as NodeJS.Timeout
}
;(globalThis as unknown as { setTimeout: unknown }).setTimeout = (fn: () => void) => {
  // Сон «истекает» сразу, но сначала прогоняем накопленные пинги — как если бы прошло время.
  intervals.forEach((tick) => tick())
  fn()
  return 1 as unknown as NodeJS.Timeout
}
pings = 0
await keepAliveSleep(120_000)
globalThis.setInterval = realSetInterval
globalThis.setTimeout = realSetTimeout
assert.ok(pings > 0, 'длинный сон обязан пинговать service worker, иначе MV3 его усыпит')

// Ошибка chrome-API не должна ронять сон.
;(globalThis as unknown as { chrome: unknown }).chrome = {
  runtime: {
    getPlatformInfo: () => {
      throw new Error('worker is shutting down')
    },
  },
}
t0 = Date.now()
await keepAliveSleep(30)
assert.ok(Date.now() - t0 >= 25, 'сон досыпает даже когда пинг падает')

console.log('keep-alive.test.ts — ок')
