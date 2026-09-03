/**
 * EXT-R1: парсинг «Ваши отклики» career.habr.com из перехваченного JSON
 * `/api/frontend/responses` (S13). Источник — не DOM, а JSON-объект (см. habr-xhr-interceptor.ts).
 * Запуск: cd extension && npx tsx tests/habr-responses-parse.test.ts
 */
import assert from 'node:assert/strict'

import {
  habrResponsesList,
  normalizeHabrStatus,
  parseHabrResponsesFromJson,
} from '../src/dom/selectors-habr-applications.ts'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(globalThis as any).location = { href: 'https://career.habr.com/profile/responses' }

// ── Форма payload из 0x55AAh/habr_career: { list: Response[], meta } ──
const payload = {
  list: [
    {
      id: 101,
      publishedAt: '2026-08-01T10:00:00+03:00',
      message: 'Привет, скиньте резюме',
      messageHtml: '<p>Привет, скиньте резюме</p>',
      author: { id: 'u1', title: 'Анна', href: '/users/u1' },
      favorite: false,
      archived: false,
      vacancy: {
        id: 1000164602,
        title: 'Lead AI/ML Engineer',
        href: 'https://career.habr.com/vacancies/1000164602',
        company: { title: 'Selecty', href: '/companies/selecty' },
      },
    },
    {
      id: 102,
      publishedAt: '2026-08-10T12:00:00+03:00',
      message: '',
      messageHtml: '',
      author: { id: 'u2', title: 'Бот', href: '/users/u2' },
      favorite: false,
      archived: true,
      vacancy: {
        id: 777,
        title: 'Python Dev',
        href: 'https://career.habr.com/vacancies/777',
        company: { title: 'Acme' },
      },
    },
  ],
  meta: { totalResults: 2, perPage: 20, currentPage: 1, totalPages: 1 },
}

assert.equal(habrResponsesList(payload).length, 2)
assert.deepEqual(habrResponsesList(payload.list), payload.list)

const parsed = parseHabrResponsesFromJson(payload)
assert.equal(parsed.length, 2)

const first = parsed.find((p) => p.vacancy_id === 'habr_1000164602')!
assert.ok(first)
assert.equal(first.title, 'Lead AI/ML Engineer')
assert.equal(first.company, 'Selecty')
assert.equal(first.url, 'https://career.habr.com/vacancies/1000164602')
assert.equal(first.habr_status, 'unknown')
assert.equal(first.is_archived, false)
assert.equal(first.funnel_status_preview, 'Отклик')
assert.equal(first.applied_at, '2026-08-01 10:00')

const archived = parsed.find((p) => p.vacancy_id === 'habr_777')!
assert.ok(archived)
assert.equal(archived.habr_status, 'archived')
assert.equal(archived.is_archived, true)
assert.equal(archived.skip_stage_update, true)
assert.equal(archived.funnel_status_preview, 'Отклик') // архив ≠ отказ, воронку не трогаем

// ── Нормализация статусов ──
assert.equal(normalizeHabrStatus('отказ', false), 'rejected')
assert.equal(normalizeHabrStatus('Приглашение', false), 'invitation')
assert.equal(normalizeHabrStatus('просмотрен', false), 'viewed')
assert.equal(normalizeHabrStatus('', true), 'archived')
assert.equal(normalizeHabrStatus('', false), 'unknown')

// ── Пустой/битый payload не падает ──
assert.deepEqual(parseHabrResponsesFromJson(null), [])
assert.deepEqual(parseHabrResponsesFromJson({}), [])
assert.deepEqual(parseHabrResponsesFromJson({ list: [{ no: 'vacancy' }] }), [])

console.log('habr-responses-parse.test.ts OK')
console.log('  items:', parsed.length)
