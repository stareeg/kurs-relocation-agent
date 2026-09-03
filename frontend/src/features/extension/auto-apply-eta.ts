import type { components } from "@/api/schema"

export type AutoApplySchedule = components["schemas"]["AutoApplySchedule"]

/**
 * Оценка момента (ms), когда раннер дойдёт до автоотклика на позиции `indexInPlatform` в очереди
 * СВОЕЙ площадки. Раннер идёт по каждой площадке отдельной очередью, за тик берёт не больше
 * `real_per_tick` реальных откликов, между ними спит минимум `min_gap_seconds`.
 *
 * Это грубая прикидка, а не гарантия — в UI подписывается «≈».
 */
export function computeQueueEtaMs(
  schedule: AutoApplySchedule,
  indexInPlatform: number,
  nowMs: number,
): number {
  const tickMs = Math.max(60, schedule.tick_seconds) * 1000
  const perTick = Math.max(1, schedule.real_per_tick)
  const gapMs = Math.max(schedule.gap_seconds, schedule.min_gap_seconds) * 1000

  const lastTick = schedule.runner_last_tick_at
    ? new Date(schedule.runner_last_tick_at).getTime()
    : NaN
  // Следующий тик: от последнего heartbeat + период, но не в прошлом. Нет heartbeat — считаем,
  // что первый тик будет не позже чем через период.
  const nextTick = Number.isNaN(lastTick)
    ? nowMs + tickMs
    : Math.max(nowMs, lastTick + tickMs)

  const i = Math.max(0, indexInPlatform)
  const tickOffset = Math.floor(i / perTick)
  const withinTick = i % perTick
  return nextTick + tickOffset * tickMs + withinTick * gapMs
}

/** «≈ сейчас» / «≈ через 4 мин» / «≈ через 1 ч 10 мин». */
export function formatEtaShort(etaMs: number, nowMs: number): string {
  const deltaMin = Math.round((etaMs - nowMs) / 60_000)
  if (deltaMin <= 0) return "≈ сейчас"
  if (deltaMin < 60) return `≈ через ${deltaMin} мин`
  const h = Math.floor(deltaMin / 60)
  const m = deltaMin % 60
  return m > 0 ? `≈ через ${h} ч ${m} мин` : `≈ через ${h} ч`
}

/** Раннер молчит дольше трёх периодов — service worker расширения, скорее всего, усыплён. */
export function runnerLooksAsleep(schedule: AutoApplySchedule, nowMs: number): boolean {
  if (!schedule.runner_last_tick_at) return false
  const last = new Date(schedule.runner_last_tick_at).getTime()
  if (Number.isNaN(last)) return false
  return nowMs - last > Math.max(60, schedule.tick_seconds) * 1000 * 3
}

/** «5 мин» / «2 ч» — как давно был последний тик (для предупреждения «раннер молчит»). */
export function formatSinceShort(iso: string | null | undefined, nowMs: number): string {
  if (!iso) return "ни разу"
  const at = new Date(iso).getTime()
  if (Number.isNaN(at)) return "ни разу"
  const min = Math.max(0, Math.round((nowMs - at) / 60_000))
  if (min < 60) return `${min} мин`
  const h = Math.floor(min / 60)
  return `${h} ч`
}
