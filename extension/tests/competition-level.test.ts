/**
 * U-03: competitionLevel — общие пороги 100/500 для конкуренции по откликам (панель ↔ веб).
 */
import assert from 'node:assert/strict'
import {
  competitionLevel,
  COMPETITION_HIGH_THRESHOLD,
  COMPETITION_MEDIUM_THRESHOLD,
  COMPETITION_LEVEL_SUFFIX,
} from '../../shared/criteria.ts'

assert.equal(COMPETITION_MEDIUM_THRESHOLD, 100)
assert.equal(COMPETITION_HIGH_THRESHOLD, 500)

assert.equal(competitionLevel(null), null)
assert.equal(competitionLevel(undefined), null)
assert.equal(competitionLevel(0), 'low')
assert.equal(competitionLevel(100), 'low')
assert.equal(competitionLevel(101), 'medium')
assert.equal(competitionLevel(500), 'medium')
assert.equal(competitionLevel(501), 'high')

assert.equal(COMPETITION_LEVEL_SUFFIX.low, '')
assert.equal(COMPETITION_LEVEL_SUFFIX.medium, 'средняя конкуренция')
assert.equal(COMPETITION_LEVEL_SUFFIX.high, 'высокая конкуренция')

console.log('competition-level.test.ts: ok')
