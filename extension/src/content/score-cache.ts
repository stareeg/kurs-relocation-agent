/** U-19: локальный кэш скоринга `score:{vacancy_id}` — TTL и штамп времени записи. */

export const SCORE_CACHE_PREFIX = 'score:';
export const SCORE_CACHE_TTL_MS = 14 * 24 * 60 * 60 * 1000;

export function scoreCacheKey(vacancyId: string): string {
  return `${SCORE_CACHE_PREFIX}${vacancyId}`;
}

/** Добавляет `_cached_at` — по нему чистим записи старше TTL. */
export function stampScoreCacheRecord<T extends Record<string, unknown>>(record: T): T & { _cached_at: string } {
  return { ...record, _cached_at: new Date().toISOString() };
}

/** Возраст записи в мс; `null` — legacy без штампа (не удаляем по TTL). */
export function scoreCacheAgeMs(record: unknown): number | null {
  if (!record || typeof record !== 'object') return null;
  const at = (record as { _cached_at?: string })._cached_at;
  if (!at) return null;
  const ts = Date.parse(at);
  return Number.isFinite(ts) ? Date.now() - ts : null;
}

export function writeScoreCache(vacancyId: string, record: Record<string, unknown>): Promise<void> {
  return new Promise((resolve) => {
    chrome.storage.local.set({ [scoreCacheKey(vacancyId)]: stampScoreCacheRecord(record) }, () => resolve());
  });
}

/** При старте content-script: удалить `score:*` старше 14 дней. Best-effort, без блокировки UI. */
export function pruneScoreCache(): Promise<number> {
  return new Promise((resolve) => {
    chrome.storage.local.get(null, (all) => {
      if (chrome.runtime.lastError || !all) {
        resolve(0);
        return;
      }
      const stale: string[] = [];
      for (const [key, value] of Object.entries(all)) {
        if (!key.startsWith(SCORE_CACHE_PREFIX)) continue;
        const age = scoreCacheAgeMs(value);
        if (age !== null && age > SCORE_CACHE_TTL_MS) stale.push(key);
      }
      if (!stale.length) {
        resolve(0);
        return;
      }
      chrome.storage.local.remove(stale, () => resolve(stale.length));
    });
  });
}
