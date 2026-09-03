/**
 * EXT-R1: парсинг каталога getmatch на статичной фикстуре (tests/fixtures/getmatch-catalog.html).
 * Запуск: cd extension && npx tsx tests/getmatch-catalog-parse.test.ts
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseHTML } from 'linkedom'

import { parseGetmatchCatalogCardsFromDom } from '../src/dom/selectors-getmatch-catalog.ts'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const htmlPath = path.resolve(__dirname, 'fixtures/getmatch-catalog.html')
const html = fs.readFileSync(htmlPath, 'utf8')
const { document } = parseHTML(html)

const cards = parseGetmatchCatalogCardsFromDom(document)

assert.equal(cards.length, 2, `ожидалось 2 карточки, получено ${cards.length}`)
assert.equal(cards[0].vacancy_id, 'gm_34716')
assert.match(cards[0].title, /Senior Data Scientist/i)
assert.equal(cards[1].vacancy_id, 'gm_40021')
assert.match(cards[1].title, /Middle Python Developer/i)

console.log('getmatch-catalog-parse.test.ts OK')
console.log('  cards:', cards.length)
