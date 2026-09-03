/**
 * U-06: разбор балла — shared/score-breakdown + калибровка в shared/criteria.
 */
import assert from 'node:assert/strict'
import { scoreCalibrationAdjustmentsTitle } from '../../shared/criteria.ts'
import {
  scoreBreakdownRows,
  scoreCalibrationDelta,
} from '../../shared/score-breakdown.ts'

const baseScore = {
  overall_score: 61,
  salary: { meets_min: true, value_or_range: '300k', note: 'ok' },
  remote_abroad_compat: { level: 'ideal', reasoning: 'remote ok' },
  grade_match: { level: 'match', reasoning: 'grade ok' },
  role_content_match: { score: 80, reasoning: 'domain ok' },
  burnout_risk: { level: 'low', reasoning: 'hands-on' },
  company_fit: { level: 'ok', reasoning: 'company ok' },
  score_breakdown: {
    salary: 18,
    work_format: 16,
    grade_match: 12,
    role_content: 10,
    management: 8,
    company: 5,
  },
}

const rows = scoreBreakdownRows(baseScore)
assert.ok(rows)
assert.equal(rows.length, 6)
assert.equal(rows[0].key, 'salary')
assert.equal(rows[0].label, 'Зарплата')

assert.equal(scoreCalibrationDelta(61, rows!), -8)

assert.equal(
  scoreCalibrationAdjustmentsTitle([{ delta: -3, reason: 'гейт' }, { delta: -5, reason: 'кап' }]),
  '-3: гейт; -5: кап',
)

assert.equal(scoreBreakdownRows({ ...baseScore, score_breakdown: { salary: 1 } }), null)

console.log('score-breakdown.test.ts: ok')
