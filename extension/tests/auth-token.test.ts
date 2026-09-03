/**
 * EX-10/EX-17: чистые функции модуля авторизации расширения — без DOM/browser.
 * looksLikeBotAuthToken (оба формата токена + мусор), buildAuthHeaders (X-Auth-Token — единственный
 * заголовок после удаления X-API-Key), isAuthActive (эквивалент active = authed &&
 * auth_token_configured на фронте), deriveApiBaseUrl (адрес API из адреса сайта, EX-17).
 */
import assert from 'node:assert/strict'
import { buildAuthHeaders, type AuthStatus } from '../src/auth/api.ts'
import { isAuthActive } from '../src/auth/render.ts'
import { looksLikeBotAuthToken } from '../src/auth/token.ts'
import { deriveApiBaseUrl } from '../src/config.ts'

// --- looksLikeBotAuthToken ---

assert.ok(looksLikeBotAuthToken('a'.repeat(32)), 'обычный токен владельца (32 символа)')
assert.ok(looksLikeBotAuthToken('A-Za-z0-9_-'.padEnd(28, 'x')), 'обычный токен ровно на нижней границе')
assert.ok(
  looksLikeBotAuthToken(`cc.${'a'.repeat(10)}.${'b'.repeat(20)}`),
  'переносимый гостевой токен cc.<аккаунт>.<секрет>',
)
assert.ok(looksLikeBotAuthToken(`  ${'a'.repeat(32)}  `), 'внешние пробелы обрезаются перед проверкой')

assert.ok(!looksLikeBotAuthToken(''), 'пустая строка — не токен')
assert.ok(!looksLikeBotAuthToken('short'), 'слишком короткая строка — не токен')
assert.ok(!looksLikeBotAuthToken('a'.repeat(27)), 'на один символ короче нижней границы — не токен')
assert.ok(!looksLikeBotAuthToken('has spaces inside string here'), 'пробелы внутри — не токен')
assert.ok(!looksLikeBotAuthToken('cc.short'), 'cc.-префикс без секрета нужной длины — не токен')
assert.ok(!looksLikeBotAuthToken('привет мир, это не токен'), 'явный мусор — не токен')

// --- buildAuthHeaders ---

assert.deepEqual(
  buildAuthHeaders('token123'),
  { 'X-Auth-Token': 'token123' },
  'токен задан — X-Auth-Token',
)
assert.deepEqual(buildAuthHeaders(''), {}, 'токена нет — пустой объект заголовков')

// --- deriveApiBaseUrl ---

assert.equal(
  deriveApiBaseUrl('http://localhost:5173'),
  'http://localhost:8000',
  'localhost — порт веба меняется на порт API (нет reverse-proxy)',
)
assert.equal(
  deriveApiBaseUrl('http://127.0.0.1:5173'),
  'http://127.0.0.1:8000',
  '127.0.0.1 — та же дев-конвенция, что и localhost',
)
assert.equal(
  deriveApiBaseUrl('https://copilot.example.com'),
  'https://copilot.example.com',
  'прод-домен — тот же origin (один Caddy на API и веб)',
)
assert.equal(
  deriveApiBaseUrl('not a url'),
  'http://localhost:8000',
  'некорректный ввод — дефолт, не падение',
)

// --- isAuthActive ---

function status(overrides: Partial<AuthStatus>): AuthStatus {
  return {
    authed: false,
    auth_token_configured: false,
    openrouter_key_configured: false,
    extension_confirmed: false,
    bot_configured: false,
    bot_username: null,
    account_username: null,
    ...overrides,
  }
}

assert.equal(
  isAuthActive(status({ authed: true, auth_token_configured: true })),
  true,
  'authed + токен настроен — вход активен',
)
assert.equal(
  isAuthActive(status({ authed: true, auth_token_configured: false })),
  false,
  'authed без настроенного токена (не должно случаться, но не должно и ронять UI) — не активен',
)
assert.equal(
  isAuthActive(status({ authed: false, auth_token_configured: true })),
  false,
  'токен настроен на инсталляции, но этот запрос не авторизован — не активен',
)
assert.equal(
  isAuthActive(status({ authed: false, auth_token_configured: false })),
  false,
  'ничего не настроено — не активен',
)

console.log('auth-token.test.ts: ok')
