/**
 * EXT-R1: парсинг Хабр Карьеры (career.habr.com) на статичной фикстуре
 * (tests/fixtures/habr-vacancy.html) — SSR-JSON (primary) + JSON-LD (fallback).
 * Запуск: cd extension && npx tsx tests/habr-vacancy-parse.test.ts
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseHTML } from 'linkedom'

import {
  extractHabrVacancyIdFromUrl,
  habrVacancyExtractor,
  parseHabrVacancyFromDom,
} from '../src/dom/extractors/habr.ts'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const htmlPath = path.resolve(__dirname, 'fixtures/habr-vacancy.html')
const html = fs.readFileSync(htmlPath, 'utf8')
const { document } = parseHTML(html)

// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(globalThis as any).document = document
// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(globalThis as any).location = {
  href: 'https://career.habr.com/vacancies/1000164602',
}

const url = 'https://career.habr.com/vacancies/1000164602'
const parsed = parseHabrVacancyFromDom(url)

assert.equal(extractHabrVacancyIdFromUrl(url), 'habr_1000164602')
assert.equal(parsed.vacancy_id, 'habr_1000164602')
assert.equal(parsed.title, 'Lead AI/ML Engineer (LLM Agents & Classical ML)')
assert.equal(parsed.company, 'Selecty')
assert.equal(parsed.salary, 'от 400 000 ₽')
assert.equal(parsed.qualification, 'Lead')
assert.equal(parsed.salary_currency, 'rur')
assert.ok(Array.isArray(parsed.skills))
assert.ok(parsed.skills!.includes('Python'))
assert.ok(parsed.skills!.includes('LangGraph'))
assert.equal(parsed.work_format, 'удалённо')
assert.equal(parsed.area, 'Москва')
assert.equal(parsed.published_at, '2026-08-08T22:27:10+03:00')
assert.equal(parsed.source, 'habr')
// Описание (HTML) стрипнуто в текст
assert.match(parsed.text, /LangGraph/i)
assert.match(parsed.text, /RAG-пайплайн/i)
assert.match(parsed.text, /Навыки: Python/i)
assert.match(parsed.text, /Квалификация: Lead/i)
assert.ok(parsed.text.length >= 200 && parsed.text.length <= 8000, `text len=${parsed.text.length}`)

// buildScorePayload сохраняет структурированные поля Хабр
const payload = habrVacancyExtractor.buildScorePayload(parsed)
assert.equal(payload.source, 'habr')
assert.equal(payload.vacancy_id, 'habr_1000164602')
assert.equal(payload.qualification, 'Lead')
assert.equal(payload.salary_currency, 'rur')
assert.deepEqual(payload.skills, parsed.skills)

console.log('habr-vacancy-parse.test.ts OK')
console.log('  title:', parsed.title)
console.log('  qualification:', parsed.qualification)
console.log('  salary_currency:', parsed.salary_currency)
console.log('  skills:', parsed.skills?.length)
console.log('  textLen:', parsed.text.length)
