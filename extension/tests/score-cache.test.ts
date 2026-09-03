import assert from 'node:assert/strict';
import {
  scoreCacheAgeMs,
  scoreCacheKey,
  SCORE_CACHE_TTL_MS,
  stampScoreCacheRecord,
} from '../src/content/score-cache.ts';

assert.equal(scoreCacheKey('123'), 'score:123');

{
  const rec = stampScoreCacheRecord({ vacancy_id: '1', title: 'Dev' });
  assert.ok(rec._cached_at);
  const age = scoreCacheAgeMs(rec);
  assert.ok(age !== null && age >= 0 && age < 5000);
}

{
  const old = stampScoreCacheRecord({ vacancy_id: '2' });
  old._cached_at = new Date(Date.now() - SCORE_CACHE_TTL_MS - 1000).toISOString();
  const age = scoreCacheAgeMs(old);
  assert.ok(age !== null && age > SCORE_CACHE_TTL_MS);
}

assert.equal(scoreCacheAgeMs({ vacancy_id: 'legacy' }), null);

console.log('score-cache.test.ts: ok');
