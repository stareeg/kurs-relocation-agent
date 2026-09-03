import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/** U-15: подпись кнопки письма не должна «скакать» после генерации. */
const mainTs = readFileSync(
  path.join(path.dirname(fileURLToPath(import.meta.url)), '../src/content/main.ts'),
  'utf8',
);

assert.match(mainTs, /const COVER_LETTER_LABEL = 'Сопроводительное'/);
assert.match(mainTs, /btn\.innerHTML = COVER_LETTER_HTML;/);
assert.doesNotMatch(mainTs, /Сопровод\./);
assert.doesNotMatch(mainTs, /Черновик письма/);
assert.doesNotMatch(mainTs, /const COVER_LETTER_LABEL = 'Письмо'/);

console.log('cover-letter-label.test.ts: ok');
