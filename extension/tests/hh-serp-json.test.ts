/**
 * Шаг 4: embedded JSON выдачи hh — тот же контракт, что tests/test_hh_serp_discovery.py.
 * Без сетевого запроса; цепочка JSON → DOM-конфиг → DOM-дефолты; устаревший JSON отбрасывается.
 */
import assert from 'node:assert/strict'
import { parseHTML } from 'linkedom'

import {
  extractSerpVacanciesFromHtml,
  parseSerpListingFromDom,
} from '../src/dom/serp-json.ts'
import { getSelectors } from '../src/dom/selectors-config.ts'

function sampleVacancy(vacancyId = 111, extra: Record<string, unknown> = {}) {
  return {
    vacancyId,
    name: 'Backend Developer',
    company: { name: 'Acme', id: 55 },
    area: { name: 'Москва' },
    compensation: { from: 300000, to: 400000, currencyCode: 'RUR' },
    workFormats: [{ workFormatsElement: ['REMOTE'] }],
    '@responseLetterRequired': false,
    totalResponsesCount: 42,
    links: { desktop: `https://hh.ru/vacancy/${vacancyId}` },
    ...extra,
  }
}

function encodeSerpPayload(vacancies: unknown[]): string {
  return JSON.stringify({ vacancies }).replace(/"/g, '&#34;')
}

function wrapPage(body: string): string {
  return `<html><body><div data-params="${body}"></div></body></html>`
}

const encoded = wrapPage(encodeSerpPayload([sampleVacancy(111)]))
const fromEncoded = extractSerpVacanciesFromHtml(encoded)
assert.equal(fromEncoded.length, 1, 'HTML-entity encoded vacancies')
assert.equal(fromEncoded[0].vacancy_id, '111')
assert.equal(fromEncoded[0].title, 'Backend Developer')
assert.equal(fromEncoded[0].company, 'Acme')
assert.equal(fromEncoded[0].total_responses_count, 42)
assert.equal(fromEncoded[0].letter_required, false)
assert.match(fromEncoded[0].salary, /300000/)
assert.equal(fromEncoded[0].source, 'serp_json')

const legacy = `<html><body><script>window.__STATE__ = ${JSON.stringify({ vacancies: [sampleVacancy(222)] })}</script></body></html>`
const fromLegacy = extractSerpVacanciesFromHtml(legacy)
assert.equal(fromLegacy.length, 1)
assert.equal(fromLegacy[0].vacancy_id, '222')
assert.equal(fromLegacy[0].total_responses_count, 42)

const good = sampleVacancy(333, { totalResponsesCount: 7 })
const broken = sampleVacancy(444, {
  totalResponsesCount: 9,
  mapData: JSON.stringify({ points: { lng: 1, lat: 2 } }),
})
const encodedCorrect = encodeSerpPayload([good, broken])
const encodedBuggy = encodedCorrect.replace(/\\&#34;/g, '\\\\&#34;')
const fromBuggy = extractSerpVacanciesFromHtml(wrapPage(encodedBuggy))
const byId = Object.fromEntries(fromBuggy.map((v) => [v.vacancy_id, v]))
assert.equal(byId['333'].total_responses_count, 7)
assert.equal(byId['444'].total_responses_count, 9)

const noMarker = extractSerpVacanciesFromHtml(
  '<html><body><a href="/vacancy/999888">карточка</a></body></html>',
)
assert.equal(noMarker.length, 0, 'без маркера JSON не выдумываем id regex-ом — это DOM-слой')

const { document: jsonOnlyDoc } = parseHTML(wrapPage(encodeSerpPayload([sampleVacancy(555)])))
;(globalThis as unknown as { document: typeof jsonOnlyDoc }).document = jsonOnlyDoc
const jsonOnly = parseSerpListingFromDom(jsonOnlyDoc)
assert.equal(jsonOnly.method, 'serp_json')
assert.equal(jsonOnly.items.length, 1)
assert.equal(jsonOnly.items[0].vacancy_id, '555')

const staleHtml = `<html><body>
  <div data-params="${encodeSerpPayload([sampleVacancy(111)])}"></div>
  <div data-qa="vacancy-serp__vacancy">
    <div data-qa="serp-item__title"><a href="/vacancy/999001">DOM карточка</a></div>
    <a data-qa="vacancy-serp__vacancy-employer" href="/employer/1">Фирма</a>
  </div>
</body></html>`
const { document: staleDoc } = parseHTML(staleHtml)
const stale = parseSerpListingFromDom(staleDoc, getSelectors())
assert.equal(stale.method, 'default', 'disjoint JSON vs DOM → JSON устарел, берём карточки')
assert.equal(stale.items.length, 1)
assert.equal(stale.items[0].vacancy_id, '999001')

const overlapHtml = `<html><body>
  <div data-params="${encodeSerpPayload([sampleVacancy(111111)])}"></div>
  <div data-qa="vacancy-serp__vacancy">
    <div data-qa="serp-item__title"><a href="/vacancy/111111">Backend Python Developer</a></div>
    <a data-qa="vacancy-serp__vacancy-employer" href="/employer/2222">ООО Компания Раз</a>
  </div>
</body></html>`
const { document: overlapDoc } = parseHTML(overlapHtml)
const overlap = parseSerpListingFromDom(overlapDoc)
assert.equal(overlap.method, 'serp_json')
assert.equal(overlap.items[0].vacancy_id, '111111')
assert.ok(overlap.items[0].el, 'при живом DOM красим карточку, даже если список взяли из JSON')

console.log('hh-serp-json.test.ts OK')
console.log('  encoded:', fromEncoded[0].vacancy_id)
console.log('  stale→dom:', stale.items[0].vacancy_id)
console.log('  overlap method:', overlap.method)
