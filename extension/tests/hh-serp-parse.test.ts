/**
 * EXT-R1: парсинг hh SERP-карточек на статичной фикстуре (tests/fixtures/hh-serp.html).
 * Запуск: cd extension && npx tsx tests/hh-serp-parse.test.ts
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseHTML } from 'linkedom'

import { parseSerpCardsFromDom } from '../src/dom/selectors.ts'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const htmlPath = path.resolve(__dirname, 'fixtures/hh-serp.html')
const html = fs.readFileSync(htmlPath, 'utf8')
const { document } = parseHTML(html)

// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(globalThis as any).document = document
// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(globalThis as any).location = { href: 'https://hh.ru/search/vacancy?text=python' }

const cards = parseSerpCardsFromDom(document)

assert.equal(cards.length, 2, `ожидалось 2 карточки, получено ${cards.length}`)
assert.equal(cards[0].vacancy_id, '111111')
assert.equal(cards[0].title, 'Backend Python Developer')
assert.equal(cards[0].company, 'ООО Компания Раз')
assert.match(cards[0].salary, /200\s*000.*250\s*000/i)
assert.equal(cards[0].location, 'Санкт-Петербург')
assert.equal(cards[1].vacancy_id, '222222')
assert.equal(cards[1].title, 'Middle Python Developer')

console.log('hh-serp-parse.test.ts OK')
console.log('  cards:', cards.length)
