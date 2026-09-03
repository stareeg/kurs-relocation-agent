/**
 * Память показа подсказок: не повторять то, что пользователь уже недавно видел.
 * Без сервера — localStorage + sessionStorage. Сбой storage = «как будто не видели».
 */

const SHOWN_PREFIX = "copilot.tip.shown."
const LAST_ANY_AT_KEY = "copilot.tip.lastAt"

/** Онбординг: раз показали — больше не показываем (постоянно). */
export const ONBOARDING_SEEN_MS = Number.POSITIVE_INFINITY

/** Hover HelpTip: не всплывать снова по тому же ключу несколько минут. */
export const HELP_TIP_COOLDOWN_MS = 12 * 60 * 1000

/**
 * Пауза между разными онбординг-подсказками: не устраивать «тур» при быстром
 * переключении разделов.
 */
export const ONBOARDING_GLOBAL_GAP_MS = 45_000

function storageGet(store: Storage, key: string): string | null {
  try {
    return store.getItem(key)
  } catch {
    return null
  }
}

function storageSet(store: Storage, key: string, value: string) {
  try {
    store.setItem(key, value)
  } catch {
    /* private mode / quota — игнор */
  }
}

function readShownAt(key: string): number | null {
  const raw =
    storageGet(localStorage, SHOWN_PREFIX + key) ?? storageGet(sessionStorage, SHOWN_PREFIX + key)
  if (raw == null || raw === "") return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}

function writeShownAt(key: string, at: number) {
  const value = String(at)
  storageSet(localStorage, SHOWN_PREFIX + key, value)
  storageSet(sessionStorage, SHOWN_PREFIX + key, value)
}

function readLastAnyAt(): number {
  const raw =
    storageGet(localStorage, LAST_ANY_AT_KEY) ?? storageGet(sessionStorage, LAST_ANY_AT_KEY)
  const n = Number(raw ?? 0)
  return Number.isFinite(n) ? n : 0
}

function writeLastAnyAt(at: number) {
  const value = String(at)
  storageSet(localStorage, LAST_ANY_AT_KEY, value)
  storageSet(sessionStorage, LAST_ANY_AT_KEY, value)
}

/** Уже показывали этот ключ и кулдаун ещё не вышел. */
export function wasTipShownRecently(
  key: string,
  cooldownMs: number,
  now: number = Date.now(),
): boolean {
  if (!key) return false
  const shownAt = readShownAt(key)
  if (shownAt == null) return false
  if (!Number.isFinite(cooldownMs) || cooldownMs === Number.POSITIVE_INFINITY) return true
  return now - shownAt < cooldownMs
}

/** Другая онбординг-подсказка была недавно — подождать, не спамить. */
export function isOnboardingGapActive(
  gapMs: number = ONBOARDING_GLOBAL_GAP_MS,
  now: number = Date.now(),
): boolean {
  const last = readLastAnyAt()
  if (!last) return false
  return now - last < gapMs
}

/** Зафиксировать показ (и обновить глобальный «последний раз»). */
export function markTipShown(key: string, now: number = Date.now()) {
  if (!key) return
  writeShownAt(key, now)
  writeLastAnyAt(now)
}

/** Тесты / сброс. */
export function clearTipMemoryForTests() {
  try {
    const stores: Storage[] = [localStorage, sessionStorage]
    for (const store of stores) {
      const keys: string[] = []
      for (let i = 0; i < store.length; i += 1) {
        const k = store.key(i)
        if (k && (k.startsWith(SHOWN_PREFIX) || k === LAST_ANY_AT_KEY)) keys.push(k)
      }
      for (const k of keys) store.removeItem(k)
    }
  } catch {
    /* ignore */
  }
}
