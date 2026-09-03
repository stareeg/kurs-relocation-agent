import assert from 'node:assert/strict';
import { normalizeScoreErrorMessage } from '../src/content/score-error.ts';

assert.equal(
  normalizeScoreErrorMessage('Failed to fetch'),
  'Backend недоступен. Проверьте, что сервис запущен.',
);
assert.equal(
  normalizeScoreErrorMessage('NetworkError when attempting to fetch resource.'),
  'Backend недоступен. Проверьте, что сервис запущен.',
);
assert.equal(normalizeScoreErrorMessage('HTTP 503'), 'HTTP 503');
assert.equal(normalizeScoreErrorMessage(''), 'Неизвестная ошибка');

console.log('score-error.test.ts: ok');
