/**
 * Парсинг карточки отклика getmatch (реальная разметка 2026-07).
 * Запуск: node --experimental-vm-modules tests/getmatch-applications-parse.test.js
 * (или через esbuild bundle + jsdom — здесь минимальный smoke без DOM: regex/id).
 */
import assert from 'node:assert/strict'

const SAMPLE_HREF = '/vacancies/34716-senior-data-scientist-mws-data-copilot?s=my-applications-v'

function extractGetmatchVacancyIdFromUrl(url) {
  const m = String(url || '').match(/\/vacancies\/(\d+)-/)
  return m ? `gm_${m[1]}` : null
}

function normalizeGetmatchAppliedAt(raw) {
  if (!raw || !String(raw).trim()) return null
  const s = String(raw)
    .trim()
    .replace(/\u00a0/g, ' ')
    .replace(/\s*г\.?\s*$/i, '')
    .trim()
  const ru = s.match(/(\d{1,2})\s+([а-яёa-z]+)(?:\s+(\d{4}))?/i)
  if (ru) {
    const prefixes = [
      ['янв', 0],
      ['фев', 1],
      ['мар', 2],
      ['апр', 3],
      ['мая', 4],
      ['май', 4],
      ['июн', 5],
      ['июл', 6],
      ['авг', 7],
      ['сен', 8],
      ['окт', 9],
      ['ноя', 10],
      ['дек', 11],
    ]
    const day = Number(ru[1])
    const monTxt = ru[2].toLowerCase()
    const year = Number(ru[3] || new Date().getFullYear())
    for (const [prefix, m] of prefixes) {
      if (monTxt.startsWith(prefix)) {
        const d = new Date(year, m, day, 12, 0)
        const pad = (n) => String(n).padStart(2, '0')
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} 12:00`
      }
    }
  }
  return null
}

assert.equal(extractGetmatchVacancyIdFromUrl(SAMPLE_HREF), 'gm_34716')
assert.equal(normalizeGetmatchAppliedAt('6 июля 2026 г.'), '2026-07-06 12:00')
console.log('getmatch-applications-parse.test.js OK')
