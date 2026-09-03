/**
 * FR2-78: SKIP_REASONS расширения ≡ core/domains/opportunities/skip_reasons.json.
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { SKIP_REASONS } from '../src/skip-reasons.ts'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const canonPath = path.join(root, 'core/domains/opportunities/skip_reasons.json')
const canon = JSON.parse(readFileSync(canonPath, 'utf-8')) as {
  self_skip_reasons: string[]
}

assert.deepEqual(
  [...SKIP_REASONS],
  canon.self_skip_reasons,
  'SKIP_REASONS разошёлся с core/domains/opportunities/skip_reasons.json — обнови src/skip-reasons.ts или перегенерируй снапшот',
)
assert.equal(SKIP_REASONS.length, 6, 'ожидаем 6 канонических причин (стек+домен слиты)')

console.log('skip-reasons.test.ts: ok')
