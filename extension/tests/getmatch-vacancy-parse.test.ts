/**
 * EXT-R1: парсинг getmatch vacancy на статичной фикстуре — фрагмент реальной вёрстки
 * (b-vacancy-header/b-location/b-specs/b-vacancy-stack/b-vacancy-description/b-notification),
 * вынесенный из живого снимка `plans/MWS.html` (MWS / gm_34716), см. tests/fixtures/README.md.
 * Запуск: cd extension && npx tsx tests/getmatch-vacancy-parse.test.ts
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseHTML } from 'linkedom'

import {
  detectGetmatchAlreadyApplied,
  extractGetmatchVacancyIdFromUrl,
  parseGetmatchVacancyFromDom,
} from '../src/dom/selectors-getmatch.ts'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const htmlPath = path.resolve(__dirname, 'fixtures/getmatch-vacancy.html')
const html = fs.readFileSync(htmlPath, 'utf8')
const { document } = parseHTML(html)

// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(globalThis as any).document = document
// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(globalThis as any).location = {
  href: 'https://getmatch.ru/vacancies/34716-senior-data-scientist-mws-data-copilot',
}

const url = 'https://getmatch.ru/vacancies/34716-senior-data-scientist-mws-data-copilot'
const parsed = parseGetmatchVacancyFromDom(url)

assert.equal(extractGetmatchVacancyIdFromUrl(url), 'gm_34716')
assert.equal(parsed.vacancy_id, 'gm_34716')
assert.equal(parsed.company, 'MTS Web Services')
assert.match(parsed.title, /Senior Data Scientist.*MWS Data Copilot/i)
assert.match(parsed.salary, /300\s*000.*350\s*000/i)
assert.match(parsed.work_format || '', /Гибрид/i)
assert.match(parsed.text, /Text-to-SQL|Text2SQL|MWS Data Copilot/i)
assert.match(parsed.text, /LangGraph|LangChain/i)
assert.ok(parsed.text.length >= 400 && parsed.text.length <= 8000, `text len=${parsed.text.length}`)
assert.equal(detectGetmatchAlreadyApplied(document), true)
assert.equal(parsed.published_at, '05.07.2026')

console.log('getmatch-vacancy-parse.test.ts OK')
console.log('  title:', parsed.title)
console.log('  salary:', parsed.salary)
console.log('  textLen:', parsed.text.length)
