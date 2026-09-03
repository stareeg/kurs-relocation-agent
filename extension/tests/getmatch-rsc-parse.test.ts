/**
 * GM-5: парсинг вакансии getmatch из RSC Flight Stream (primary) + JSON-LD (fallback).
 * Фикстуры — полные SSR-снимки страниц вакансий (tests/fixtures/getmatch/), содержащие
 * `self.__next_f.push([1,"..."])` с `initialVacancy` и `<script type="application/ld+json">`.
 * Запуск: cd extension && npx tsx tests/getmatch-rsc-parse.test.ts
 *
 * См. plans/getmatch_refactoring_plan.md — Шаг 2 и 8.1.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  extractFlightStream,
  extractInitialVacancy,
  mapRscToParsedVacancy,
  parseGetmatchVacancyFromRscHtml,
} from '../src/dom/selectors-getmatch-rsc.ts'
import {
  extractJsonLdJobPosting,
  mapJsonLdToParsedVacancy,
  parseGetmatchVacancyFromJsonLdHtml,
} from '../src/dom/selectors-getmatch-jsonld.ts'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Полные снимки лежат в tests/fixtures/getmatch/ (общие для backend/extension, см. план Шаг 1).
const fixture = (name: string) =>
  fs.readFileSync(path.resolve(__dirname, '../../tests/fixtures/getmatch', name), 'utf8')

const FULL_HTML = fixture('vacancy_full.html')
const HIDDEN_HTML = fixture('vacancy_hidden_company.html')
const FULL_URL = 'https://getmatch.ru/vacancies/35788-data-scientist'
const HIDDEN_URL = 'https://getmatch.ru/vacancies/34714-senior-ai-ml-engineer-llm-agents'

// ── RSC: полная вакансия ──

const full = parseGetmatchVacancyFromRscHtml(FULL_HTML, FULL_URL)
assert.ok(full, 'RSC должен извлечь полную вакансию')
assert.equal(full.vacancy_id, 'gm_35788')
assert.equal(full.title, 'Data Scientist')
assert.equal(full.company, 'Selecty')
assert.match(full.salary, /220\s*000.*310\s*000/)
assert.equal(full.work_format, 'remote')
assert.equal(full.area, 'Россия')
assert.equal(full.employer_id, 'yoQjKXl7-selecty')
assert.equal(full.published_at, '2026-08-14T16:01:17.126665')
assert.equal(full.source, 'getmatch')
assert.equal(full.is_archived, false)
assert.equal(full.parse_method, 'rsc', 'RSC-парсер должен выставить parse_method=rsc')
// Новые поля (skills/specialization/seniority)
assert.ok(Array.isArray(full.skills))
assert.ok(full.skills!.includes('Python'), `skills=${full.skills}`)
assert.ok(full.skills!.includes('Spark'))
assert.equal(full.specialization, 'Data Scientist & Machine Learning')
assert.equal(full.seniority, 'senior')
// Текст для LLM содержит навыки и специализацию
assert.match(full.text, /Навыки: .*Python/s)
assert.match(full.text, /Специализация: Data Scientist & Machine Learning/)
assert.match(full.text, /Грейд: senior/)
assert.ok(full.text.length >= 200 && full.text.length <= 8000, `text len=${full.text.length}`)

// ── RSC: скрытая компания + зарплата без вилки ──

const hidden = parseGetmatchVacancyFromRscHtml(HIDDEN_HTML, HIDDEN_URL)
assert.ok(hidden, 'RSC должен извлечь вакансию со скрытой компанией')
assert.equal(hidden.vacancy_id, 'gm_34714')
assert.equal(hidden.title, 'Senior AI/ML Engineer (LLM Agents & Classical ML)')
assert.equal(hidden.company, 'Конфиденциально')
assert.match(hidden.salary, /от\s*383\s*000/)
assert.equal(hidden.employer_id, null, 'у скрытой компании нет company.url')
assert.equal(hidden.specialization, 'Data Scientist & Machine Learning')
assert.equal(hidden.seniority, 'senior')
assert.ok(Array.isArray(hidden.skills))
assert.ok(hidden.skills!.includes('PySpark'), `skills=${hidden.skills}`)
assert.ok(hidden.skills!.includes('Kubernetes'))
// Мультилокация: Россия (remote) + Москва (hybrid) и ещё города
assert.match(hidden.area, /Россия/)
assert.match(hidden.area, /Москва/)
assert.match(hidden.work_format, /remote/)
assert.match(hidden.work_format, /hybrid/)

// ── Низкоуровневые примитивы ──

const flight = extractFlightStream(FULL_HTML)
assert.ok(flight.length > 0, 'Flight Stream должен извлекаться')
const initial = extractInitialVacancy(flight) as Record<string, unknown> | null
assert.ok(initial, 'initialVacancy должен парситься из Flight Stream')
assert.equal(initial.id, 35788)
assert.equal(initial.position, 'Data Scientist')

// ── JSON-LD: fallback (по тому же снимку, где есть <script ld+json>) ──

const jsonLd = extractJsonLdJobPosting(FULL_HTML)
assert.ok(jsonLd, 'JobPosting должен извлекаться из JSON-LD')
const ldVac = mapJsonLdToParsedVacancy(jsonLd, FULL_URL, 'gm_35788')
assert.equal(ldVac.vacancy_id, 'gm_35788')
assert.equal(ldVac.title, 'Data Scientist')
assert.equal(ldVac.company, 'Selecty')
assert.match(ldVac.salary, /220\s*000.*310\s*000/)
assert.equal(ldVac.work_format, 'remote', 'jobLocationType TELECOMMUTE → remote')
assert.equal(ldVac.parse_method, 'jsonld', 'JSON-LD-парсер должен ставить parse_method=jsonld')

// JSON-LD через HTML-обёртку (без RSC в строке — не зависит от Flight Stream)
const jsonLdOnlyHtml = `<html><head><script type="application/ld+json">
{"@type":"JobPosting","title":"Data Scientist","hiringOrganization":{"name":"Selecty"},"baseSalary":{"currency":"RUB","value":{"minValue":220000,"maxValue":310000}},"datePosted":"2026-08-14T16:01:17.126665","jobLocationType":"TELECOMMUTE"}
</script></head><body></body></html>`
const ldParsed = parseGetmatchVacancyFromJsonLdHtml(jsonLdOnlyHtml, FULL_URL, 'gm_35788')
assert.ok(ldParsed, 'JSON-LD должен парситься из чистого HTML')
assert.equal(ldParsed.title, 'Data Scientist')
assert.equal(ldParsed.company, 'Selecty')
assert.equal(ldParsed.work_format, 'remote')
assert.equal(ldParsed.parse_method, 'jsonld', 'JSON-LD-парсер должен ставить parse_method=jsonld')

// ── Отсутствие RSC/JSON-LD → null (вызывающий код уходит на DOM) ──

assert.equal(parseGetmatchVacancyFromRscHtml('<html><body>нет RSC</body></html>', FULL_URL), null)
assert.equal(parseGetmatchVacancyFromJsonLdHtml('<html><body>нет JSON-LD</body></html>', FULL_URL), null)

// mapRscToParsedVacancy — прямой вызов с минимальным объектом (архивная вакансия)
const archived = mapRscToParsedVacancy(
  {
    id: 123,
    position: 'Архивная вакансия',
    is_active: false,
    company: { name: 'Selecty' },
    salary_description: '220 000 — 310 000 ₽/мес на руки',
    location_items: [{ label: 'Россия', format: 'remote' }],
    skills_objects: [{ name: 'Python' }, { name: 'SQL' }],
    specialization: 'Data Science',
    seniorities: ['senior'],
    cover_letter_required: true,
  },
  FULL_URL,
)
assert.equal(archived.vacancy_id, 'gm_123')
assert.equal(archived.is_archived, true)
assert.equal(archived.letter_required, true)
assert.deepEqual(archived.skills, ['Python', 'SQL'])
assert.match(archived.text, /ВАКАНСИЯ СНЯТА/)

console.log('getmatch-rsc-parse.test.ts OK')
console.log('  full:', full.title, '|', full.company, '|', full.salary)
console.log('  skills:', full.skills?.length, '| spec:', full.specialization, '| seniority:', full.seniority)
console.log('  hidden:', hidden.company, '|', hidden.salary)
console.log('  jsonld:', ldVac.title, '|', ldVac.company, '|', ldVac.work_format)
