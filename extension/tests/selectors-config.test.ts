/**
 * Шаг 0: контракт parseSelectorsConfig — allowlist, поштучный отброс, https-only.
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseHTML } from 'linkedom'

import {
  DEFAULT_HH_SELECTORS_CONFIG,
  HH_SELECTORS_STORAGE_KEY,
  MAX_ARRAY_LEN,
  MAX_SELECTOR_LEN,
  SELECTOR_VALUE_KIND,
  _resetSelectorsForTests,
  dumpSelectorsConfigJson,
  fetchSelectorsFromApi,
  getSelectors,
  initSelectors,
  isConfigFetchAllowed,
  loadSelectors,
  parseSelectorsConfig,
} from '../src/dom/selectors-config.ts'
import { parseVacancyFromDom } from '../src/dom/selectors.ts'

const { document } = parseHTML('<!DOCTYPE html><html></html>')
;(globalThis as unknown as { document: typeof document }).document = document

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const jsonPath = path.join(
  root,
  'core/domains/opportunities/sources/hh_selectors.json',
)
const repoJson = JSON.parse(readFileSync(jsonPath, 'utf-8')) as typeof DEFAULT_HH_SELECTORS_CONFIG

assert.deepEqual(
  DEFAULT_HH_SELECTORS_CONFIG,
  repoJson,
  'DEFAULT_HH_SELECTORS_CONFIG разошёлся с hh_selectors.json',
)

for (const [group, kind] of Object.entries(SELECTOR_VALUE_KIND)) {
  const payload = repoJson.selectors[group]
  assert.ok(payload !== undefined, `в JSON нет группы ${group}`)
  if (kind === 'list') {
    assert.ok(Array.isArray(payload), group)
    continue
  }
  assert.deepEqual(
    Object.keys(payload as object).sort(),
    Object.keys(kind).sort(),
    `allowlist TS разошёлся с JSON в группе ${group}`,
  )
}

const clean = parseSelectorsConfig(repoJson)
assert.equal(clean.schemaValid, true)
assert.equal(clean.issues.length, 0)
assert.equal(clean.version, 1)

// неизвестный ключ отброшен, остальное применилось
const withUnknown = parseSelectorsConfig({
  version: 2,
  selectors: {
    vacancy: {
      salary: '[data-qa="vacancy-salary-v2"]',
      passport: '[data-qa="passport"]',
      cardNumber: 'input[name=card]',
    },
  },
  archived_text_re: '/secret/i',
})
assert.equal(withUnknown.schemaValid, true)
assert.equal(withUnknown.version, 2)
const vacancy = withUnknown.selectors.vacancy as Record<string, string>
assert.equal(vacancy.salary, '[data-qa="vacancy-salary-v2"]')
assert.equal(vacancy.passport, undefined)
assert.equal(vacancy.cardNumber, undefined)
assert.equal(vacancy.title, '[data-qa="vacancy-title"]')
const unknownDetails = new Set(withUnknown.issues.map((i) => i.detail))
assert.ok(unknownDetails.has('selectors.vacancy.passport'))
assert.ok(unknownDetails.has('selectors.vacancy.cardNumber'))
assert.ok(unknownDetails.has('archived_text_re'))
assert.ok(withUnknown.issues.every((i) => i.reason !== 'config_schema_invalid'))

// синтаксически битый селектор отброшен поштучно
const withBroken = parseSelectorsConfig({
  version: 3,
  selectors: {
    vacancy: {
      title: '[[[',
      company: '[data-qa="vacancy-company-name"]',
      salary: '/foo/i',
    },
  },
})
const brokenVacancy = withBroken.selectors.vacancy as Record<string, string>
assert.equal(brokenVacancy.title, '[data-qa="vacancy-title"]')
assert.equal(brokenVacancy.company, '[data-qa="vacancy-company-name"]')
assert.equal(brokenVacancy.salary, '[data-qa="vacancy-salary"]')
const invalidPaths = new Set(
  withBroken.issues.filter((i) => i.reason === 'invalid_selector').map((i) => i.detail),
)
assert.ok(invalidPaths.has('selectors.vacancy.title'))
assert.ok(invalidPaths.has('selectors.vacancy.salary'))

// регекс в паттерне не проходит enum
const withRegexPattern = parseSelectorsConfig({
  version: 1,
  patterns: { appliedText: '/отклик/i' },
})
assert.equal(withRegexPattern.patterns.appliedText, 'hh_applied')
assert.ok(withRegexPattern.issues.some((i) => i.detail === 'patterns.appliedText'))

// битая схема целиком → дефолты
for (const raw of [null, 'nope', [], { version: 0 }, { version: 1.5 }]) {
  const rolled = parseSelectorsConfig(raw)
  assert.equal(rolled.schemaValid, false, `schema ${JSON.stringify(raw)}`)
  assert.equal(rolled.usedDefaults, true)
  assert.equal(rolled.issues[0]?.reason, 'config_schema_invalid')
  assert.deepEqual(rolled.selectors, repoJson.selectors)
}

// битый JSON как из chrome.storage.local
const fromStorage = parseSelectorsConfig(JSON.parse('"not-an-object"'))
assert.equal(fromStorage.usedDefaults, true)
assert.equal(fromStorage.schemaValid, false)

const tooLong = `div${'a'.repeat(MAX_SELECTOR_LEN)}`
const capped = parseSelectorsConfig({
  version: 1,
  selectors: {
    vacancy: { title: tooLong },
    fallbacks: { title: Array.from({ length: MAX_ARRAY_LEN + 3 }, (_, i) => `h${i}`) },
  },
})
assert.equal(
  (capped.selectors.vacancy as Record<string, string>).title,
  '[data-qa="vacancy-title"]',
)
assert.deepEqual(
  (capped.selectors.fallbacks as Record<string, string[]>).title,
  Array.from({ length: MAX_ARRAY_LEN }, (_, i) => `h${i}`),
)

assert.equal(isConfigFetchAllowed('https://copilot.example.com'), true)
assert.equal(isConfigFetchAllowed('http://localhost:8000'), true)
assert.equal(isConfigFetchAllowed('http://127.0.0.1:8000'), true)
assert.equal(isConfigFetchAllowed('HTTP://LOCALHOST'), true)
assert.equal(isConfigFetchAllowed('http://evil.example'), false)
assert.equal(isConfigFetchAllowed('http://192.168.0.1'), false)
assert.equal(isConfigFetchAllowed('http://localhost.evil.com'), false)
assert.equal(isConfigFetchAllowed('ftp://localhost'), false)
assert.equal(isConfigFetchAllowed(''), false)

const dump = JSON.parse(dumpSelectorsConfigJson(clean))
assert.equal(dump.version, 1)
assert.ok(dump.selectors.vacancy.title)

// ── Шаг 2: загрузка конфига (storage / сеть / фолбэк на дефолты) ─────────────

type ChromeStore = Record<string, unknown>
const chromeStore: ChromeStore = {}
let fetchCalls: Array<{ url: string; ifNoneMatch: string | null }> = []
let fetchImpl: (url: string, init?: RequestInit) => Promise<Response> = async () => {
  throw new Error('network down')
}

function installChromeMock(): void {
  ;(globalThis as unknown as { chrome: unknown }).chrome = {
    runtime: {
      lastError: undefined,
      sendMessage: (_msg: unknown, cb?: () => void) => {
        cb?.()
      },
    },
    storage: {
      local: {
        get: async (keys: string[] | string) => {
          const list = Array.isArray(keys) ? keys : [keys]
          const out: Record<string, unknown> = {}
          for (const k of list) out[k] = chromeStore[k]
          return out
        },
        set: async (obj: Record<string, unknown>) => {
          Object.assign(chromeStore, obj)
        },
      },
      onChanged: { addListener() {} },
    },
  }
}

function jsonResponse(body: unknown, status = 200, etag = '"hh-2"'): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ETag: etag, 'Content-Type': 'application/json' },
  })
}

installChromeMock()
const originalFetch = globalThis.fetch
globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input)
  const headers = new Headers(init?.headers)
  fetchCalls.push({ url, ifNoneMatch: headers.get('If-None-Match') })
  return fetchImpl(url, init)
}) as typeof fetch

function resetRuntime(): void {
  _resetSelectorsForTests()
  for (const key of Object.keys(chromeStore)) delete chromeStore[key]
  fetchCalls = []
  fetchImpl = async () => {
    throw new Error('network down')
  }
}

const fixtureHtml = readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures/hh-vacancy.html'), 'utf8')
const { document: vacancyDoc } = parseHTML(fixtureHtml)
;(globalThis as unknown as { document: typeof vacancyDoc }).document = vacancyDoc
;(globalThis as unknown as { location: { href: string } }).location = {
  href: 'https://hh.ru/vacancy/98765432',
}

function assertParseAlive(): void {
  const parsed = parseVacancyFromDom('https://hh.ru/vacancy/98765432')
  assert.equal(parsed.title, 'Senior Python Developer')
  assert.equal(parsed.company, 'ООО Ромашка')
}

// сервер недоступен → дефолты, парсинг живой
resetRuntime()
chromeStore.authToken = 'tok'
chromeStore.webBaseUrl = 'http://localhost:5173'
await loadSelectors()
assert.equal(getSelectors().origin, 'builtin')
assert.equal(getSelectors().vacancy.title, '[data-qa="vacancy-title"]')
assert.ok(fetchCalls.length >= 1)
assertParseAlive()

// неизвестный ключ отброшен, остальное применилось
resetRuntime()
chromeStore.authToken = 'tok'
chromeStore.webBaseUrl = 'http://localhost:5173'
fetchImpl = async () =>
  jsonResponse({
    version: 2,
    updated_at: '2026-08-25T10:00:00Z',
    origin: 'repo',
    selectors: {
      vacancy: {
        salary: '[data-qa="vacancy-salary-v2"]',
        passport: '[data-qa="passport"]',
      },
    },
  })
await fetchSelectorsFromApi()
assert.equal(getSelectors().origin, 'server')
assert.equal(getSelectors().version, 2)
assert.equal(getSelectors().vacancy.salary, '[data-qa="vacancy-salary-v2"]')
assert.equal(getSelectors().vacancy.title, '[data-qa="vacancy-title"]')
assert.equal(getSelectors().vacancy.passport, undefined)
assertParseAlive()

// синтаксически битый селектор отброшен поштучно
resetRuntime()
chromeStore.authToken = 'tok'
chromeStore.webBaseUrl = 'http://localhost:5173'
fetchImpl = async () =>
  jsonResponse({
    version: 3,
    updated_at: '2026-08-25T10:00:00Z',
    origin: 'repo',
    selectors: {
      vacancy: {
        title: '[[[',
        company: '[data-qa="vacancy-company-name-v2"]',
      },
    },
  })
await fetchSelectorsFromApi()
assert.equal(getSelectors().vacancy.title, '[data-qa="vacancy-title"]')
assert.equal(getSelectors().vacancy.company, '[data-qa="vacancy-company-name-v2"]')
assertParseAlive()

// битый JSON в chrome.storage.local → дефолты, не падение
resetRuntime()
chromeStore[HH_SELECTORS_STORAGE_KEY] = { version: 0, selectors: 'nope' }
await initSelectors()
assert.equal(getSelectors().origin, 'builtin')
assert.equal(getSelectors().vacancy.title, '[data-qa="vacancy-title"]')
assertParseAlive()

resetRuntime()
chromeStore[HH_SELECTORS_STORAGE_KEY] = 'not-an-object'
await initSelectors()
assert.equal(getSelectors().origin, 'builtin')
assertParseAlive()

// apiBaseUrl на http:// не-localhost → сетевой запрос не делается вовсе
resetRuntime()
chromeStore.authToken = 'tok'
chromeStore.webBaseUrl = 'http://evil.example'
await loadSelectors()
assert.equal(fetchCalls.length, 0)
assert.equal(getSelectors().origin, 'builtin')
assertParseAlive()

globalThis.fetch = originalFetch

console.log('selectors-config.test.ts: ok')

