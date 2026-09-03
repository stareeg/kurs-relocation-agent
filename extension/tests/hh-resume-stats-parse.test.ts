/**
 * EXT-R1: парсинг статистики резюме hh на статичной фикстуре (tests/fixtures/hh-resume-stats.html).
 * Вёрстка кабинета соискателя нестабильна (см. комментарий в selectors.ts перед AF-2) — держим на
 * текстовых якорях, фикстура ловит регресс на смену их формата.
 * Запуск: cd extension && npx tsx tests/hh-resume-stats-parse.test.ts
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseHTML } from 'linkedom'

import { parseResumeStatsFromDom } from '../src/dom/selectors.ts'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const htmlPath = path.resolve(__dirname, 'fixtures/hh-resume-stats.html')
const html = fs.readFileSync(htmlPath, 'utf8')
const { document } = parseHTML(html)

// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(globalThis as any).location = { href: 'https://hh.ru/applicant/resumes' }

const stats = parseResumeStatsFromDom(document)

assert.ok(stats, 'ожидался ненулевой результат парсинга')
assert.equal(stats!.resume_id, 'abc123def456')
assert.equal(stats!.impressions, 2917)
assert.equal(stats!.views, 41)
assert.equal(stats!.views_delta, 4)
assert.equal(stats!.invitations, 1)
assert.equal(stats!.invitations_delta, 1)
assert.equal(stats!.recommended_vacancies, 12)

console.log('hh-resume-stats-parse.test.ts OK')
console.log('  stats:', JSON.stringify(stats))
