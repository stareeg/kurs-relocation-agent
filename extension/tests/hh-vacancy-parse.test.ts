/**
 * EXT-R1: парсинг hh vacancy на статичной фикстуре (tests/fixtures/hh-vacancy.html) — регресс
 * на смену вёрстки hh (magritte-хедер меняет data-qa не в первый раз, см. selectors.ts:101-103).
 * Запуск: cd extension && npx tsx tests/hh-vacancy-parse.test.ts
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseHTML } from 'linkedom'

import { parseVacancyFromDom, extractVacancyId, detectLetterRequired } from '../src/dom/selectors.ts'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const htmlPath = path.resolve(__dirname, 'fixtures/hh-vacancy.html')
const html = fs.readFileSync(htmlPath, 'utf8')
const { document } = parseHTML(html)

// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(globalThis as any).document = document
// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(globalThis as any).location = { href: 'https://hh.ru/vacancy/98765432' }

const url = 'https://hh.ru/vacancy/98765432'
const parsed = parseVacancyFromDom(url)

assert.equal(extractVacancyId(url), '98765432')
assert.equal(parsed.vacancy_id, '98765432')
assert.equal(parsed.title, 'Senior Python Developer')
assert.equal(parsed.company, 'ООО Ромашка')
assert.match(parsed.salary, /250\s*000.*300\s*000/i)
assert.equal(parsed.work_format, 'Гибрид')
// адрес не должен тянуть текст станции метро (metro-station вырезается clone-санитайзером)
assert.equal(parsed.address, 'Москва, Тверская улица, 7')
assert.equal(parsed.area, 'Москва')
assert.equal(parsed.letter_required, true)
assert.equal(parsed.total_responses_count, 38)
assert.equal(parsed.competition, 'low')
assert.match(parsed.text, /FastAPI/i)
assert.equal(detectLetterRequired(document), true)
assert.equal(parsed.parse_method, 'default')

console.log('hh-vacancy-parse.test.ts OK')
console.log('  title:', parsed.title)
console.log('  address:', parsed.address)
console.log('  total_responses_count:', parsed.total_responses_count)
