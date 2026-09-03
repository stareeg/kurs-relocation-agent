/**
 * U-05: карточки фактов — общая логика зарплаты/формата (панель ↔ дровер).
 */
import assert from 'node:assert/strict'
import {
  formatConflictOf,
  formatSalaryCardText,
  gradeFactCard,
  resolveSalaryForCard,
  salaryCardCaption,
  salaryCardValueTone,
  workFormatChip,
} from '../../shared/fact-cards.ts'
import { scoreBreakdownTone } from '../../shared/criteria.ts'

assert.deepEqual(workFormatChip('удалённо'), { label: 'Удалёнка', tone: 'strong' })
assert.deepEqual(workFormatChip('гибрид'), { label: 'Гибрид', tone: 'warn' })

const explicit = resolveSalaryForCard({
  salary_text: '300 000 — 350 000 ₽',
  score: { salary: { meets_min: true, source: 'explicit' } },
})
assert.equal(explicit.text, '300 000 — 350 000 ₽')
assert.equal(explicit.isEstimate, false)
assert.equal(salaryCardCaption(explicit), 'выше цели')
assert.equal(salaryCardValueTone(explicit), 'good')

const pending = resolveSalaryForCard({
  score: { salary: { estimate_pending: true, source: 'none' } },
})
assert.equal(pending.text, 'оценка…')
assert.equal(salaryCardCaption(pending), 'оценка')
assert.equal(salaryCardValueTone(pending), 'muted')

const estimate = resolveSalaryForCard({
  score: {
    salary: {
      estimated_range: '250 000 — 300 000 ₽',
      meets_min: false,
      source: 'llm',
      confidence: 'medium',
    },
  },
})
assert.match(formatSalaryCardText(estimate), /250к.*300к/)
assert.equal(salaryCardCaption(estimate), 'ниже цели')

const conflict = formatConflictOf(
  { label: 'Удалёнка', tone: 'strong' },
  { verdict: 'unlikely', signals: [{ text: 'офис 3/2', polarity: 'contra' }] },
)
assert.ok(conflict)
assert.equal(conflict.caption, 'Скорее Офис')
assert.equal(conflict.tone, 'bad')

const polished = formatSalaryCardText({
  text: '350 000 — 400 000 ₽/мес',
  isEstimate: false,
  meetsMin: true,
  estimateSuffix: null,
  source: 'explicit',
})
assert.equal(polished, 'от 350к до 400к')
assert.equal(salaryCardValueTone({
  text: 'от 350к до 400к',
  isEstimate: true,
  meetsMin: null,
  estimateSuffix: 'оценка',
  source: 'llm',
}), 'neutral')

// Этап 1 §1.3: off_profile — две разные ситуации. «Другая специальность» остаётся дилбрейкером,
// «сдвиг руками↔управление» внутри своей профессии — нет, и в UI не должен читаться как
// «не по профилю».
const otherProfession = gradeFactCard({
  grade_match: { level: 'off_profile', reasoning: '', off_profile_kind: 'other_profession' },
  burnout_risk: { level: 'medium' },
})
assert.equal(otherProfession.value, 'Не по профилю')
assert.equal(otherProfession.tone, 'bad')

const roleShift = gradeFactCard({
  grade_match: { level: 'off_profile', reasoning: '', off_profile_kind: 'role_shift' },
  burnout_risk: { level: 'medium' },
})
assert.equal(roleShift.value, 'Сдвиг роли')
assert.equal(roleShift.tone, 'mid')

// Старый jsonb без off_profile_kind ведёт себя как раньше.
const legacyOffProfile = gradeFactCard({
  grade_match: { level: 'off_profile', reasoning: '' },
  burnout_risk: { level: 'medium' },
})
assert.equal(legacyOffProfile.tone, 'bad')

const breakdownInput = {
  salary: { meets_min: true, value_or_range: '500000' },
  remote_abroad_compat: { level: 'ok' },
  grade_match: { level: 'off_profile', off_profile_kind: 'role_shift' },
  role_content_match: { score: 80 },
  burnout_risk: { level: 'low' },
  company_fit: { level: 'ok' },
}
assert.equal(scoreBreakdownTone('grade_match', breakdownInput), 'mid')

console.log('fact-cards.test.ts: ok')
