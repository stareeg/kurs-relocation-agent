/**
 * Шаг 3: структурный фолбэк hh — фикстура без data-qa.
 * CSS-селекторы и зашитый `h1` (первый узел пустой) промахиваются; семантика DOM жива.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseHTML } from 'linkedom'

import { parseVacancyFromDom } from '../src/dom/selectors.ts'
import { parseVacancyStructural } from '../src/dom/selectors-structural.ts'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const htmlPath = path.resolve(__dirname, 'fixtures/hh-vacancy-structural.html')
const html = fs.readFileSync(htmlPath, 'utf8')
const { document } = parseHTML(html)

;(globalThis as unknown as { document: typeof document }).document = document
;(globalThis as unknown as { location: { href: string } }).location = {
  href: 'https://hh.ru/vacancy/98765432',
}

const url = 'https://hh.ru/vacancy/98765432'

const structural = parseVacancyStructural(document)
assert.ok(structural, 'без h1 с текстом structural должен вернуть null, здесь заголовок есть')
assert.equal(structural.title, 'Senior Python Developer')
assert.equal(structural.company, 'ООО Ромашка')
assert.match(structural.salary, /250\s*000.*300\s*000/i)
assert.match(structural.description, /FastAPI/i)
assert.doesNotMatch(structural.description, /Другой работодатель/)

const parsed = parseVacancyFromDom(url)
assert.equal(parsed.parse_method, 'structural')
assert.equal(parsed.title, 'Senior Python Developer')
assert.equal(parsed.company, 'ООО Ромашка')
assert.match(parsed.salary, /250\s*000.*300\s*000/i)
assert.match(parsed.description || '', /FastAPI/i)
assert.match(parsed.text, /FastAPI/i)
assert.equal(parsed.vacancy_id, '98765432')
assert.equal(parsed.work_format, '', 'структурный слой не выдумывает формат работы')

const noHeading = parseHTML(
  '<!doctype html><html><body><p>просто текст без вакансии</p></body></html>',
).document
assert.equal(parseVacancyStructural(noHeading), null)

console.log('hh-vacancy-structural.test.ts OK')
console.log('  title:', parsed.title)
console.log('  method:', parsed.parse_method)
console.log('  salary:', parsed.salary)
