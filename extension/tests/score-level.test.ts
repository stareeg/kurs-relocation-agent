/**
 * U-02: scoreLevel — общие пороги 80/60 для цвета overall_score (панель ↔ веб).
 */
import assert from 'node:assert/strict'
import { scoreLevel } from '../../shared/criteria.ts'

assert.equal(scoreLevel(null), 'none')
assert.equal(scoreLevel(undefined), 'none')
assert.equal(scoreLevel(80), 'good')
assert.equal(scoreLevel(100), 'good')
assert.equal(scoreLevel(79), 'mid')
assert.equal(scoreLevel(60), 'mid')
assert.equal(scoreLevel(59), 'low')
assert.equal(scoreLevel(0), 'low')

console.log('score-level.test.ts: ok')
