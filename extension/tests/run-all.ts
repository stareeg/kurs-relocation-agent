/**
 * EXT-R1: запускает все *.test.ts/*.test.js в tests/ (кроме fixtures/) последовательно,
 * каждый — самостоятельный assert-скрипт (падает через process.exit при первом assert.fail).
 * Запуск: cd extension && npx tsx tests/run-all.ts
 */
import { readdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const files = readdirSync(__dirname)
  .filter((f) => /\.test\.(ts|js)$/.test(f))
  .sort()

let failed = 0
for (const file of files) {
  const full = path.join(__dirname, file)
  try {
    execFileSync(process.execPath, ['--import', 'tsx', full], { stdio: 'inherit' })
  } catch {
    failed++
    console.error(`[FAIL] ${file}`)
  }
}

console.log(`\n${files.length - failed}/${files.length} тестов прошли`)
if (failed > 0) process.exit(1)
