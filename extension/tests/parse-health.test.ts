/**
 * FR2-71: дедуп reportParseHealth — один раз на (site, page, reason, url).
 */
import assert from 'node:assert/strict'
import {
  _resetParseHealthReportedForTests,
  reportParseHealth,
} from '../src/parse-health.ts'

let sent = 0
;(globalThis as unknown as { chrome: unknown }).chrome = {
  runtime: {
    lastError: undefined,
    sendMessage: (_msg: unknown, cb?: () => void) => {
      sent += 1
      cb?.()
    },
  },
}

_resetParseHealthReportedForTests()
sent = 0

const url = 'https://hh.ru/search/vacancy?text=llm'
reportParseHealth({ site: 'hh', page: 'serp', reason: 'zero_cards', url })
reportParseHealth({ site: 'hh', page: 'serp', reason: 'zero_cards', url })
reportParseHealth({
  site: 'hh',
  page: 'serp',
  reason: 'zero_cards',
  url: `${url}#fragment`,
})

assert.equal(sent, 1, 'повтор с тем же url (и с #) не шлёт второй раз')

reportParseHealth({
  site: 'hh',
  page: 'serp',
  reason: 'zero_cards',
  url: 'https://hh.ru/search/vacancy?text=other',
})
assert.equal(sent, 2, 'другой url — новое событие')

reportParseHealth({
  site: 'hh',
  page: 'vacancy',
  reason: 'vacancy_empty',
  url,
})
assert.equal(sent, 3, 'другая page/reason — новое событие')

_resetParseHealthReportedForTests()
let lastPayload: {
  method?: string
  config_version?: number
  config_origin?: string
} | undefined
;(globalThis as unknown as { chrome: unknown }).chrome = {
  runtime: {
    lastError: undefined,
    sendMessage: (msg: { payload?: typeof lastPayload }, cb?: () => void) => {
      lastPayload = msg.payload
      cb?.()
    },
  },
}

reportParseHealth({
  site: 'hh',
  page: 'vacancy',
  reason: 'vacancy_empty',
  url: 'https://hh.ru/vacancy/1',
  method: 'structural',
  config_version: 2,
  config_origin: 'server',
})
assert.equal(lastPayload?.method, 'structural')
assert.equal(lastPayload?.config_version, 2)
assert.equal(lastPayload?.config_origin, 'server')

console.log('parse-health.test.ts: ok')
