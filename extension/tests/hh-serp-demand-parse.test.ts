/**
 * E-01: показание спроса «Найдено N вакансий» + запрос из URL (tests/fixtures/hh-serp.html).
 * Запуск: cd extension && npx tsx tests/hh-serp-demand-parse.test.ts
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseHTML } from 'linkedom'

import { parseSerpDemandFromDom } from '../src/dom/selectors.ts'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const htmlPath = path.resolve(__dirname, 'fixtures/hh-serp.html')
const html = fs.readFileSync(htmlPath, 'utf8')
const { document } = parseHTML(html)

const demand = parseSerpDemandFromDom(document, 'https://hh.ru/search/vacancy?text=python%20backend')
assert.ok(demand, 'ожидалось показание спроса')
assert.equal(demand.query, 'python backend')
assert.equal(demand.count, 1234)

// Без text= в URL (просто /vacancies) — не самостоятельный поиск, показание не шлём.
const noQuery = parseSerpDemandFromDom(document, 'https://hh.ru/vacancies')
assert.equal(noQuery, null)

console.log('hh-serp-demand-parse.test.ts OK')
console.log('  demand:', demand)
