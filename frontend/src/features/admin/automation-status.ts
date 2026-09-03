/**
 * Статус авто-процессов пользователя — чистые функции без React (тестируются напрямую).
 *
 * Одно место для правила «что значит это состояние площадки» — иначе оно жило бы в таблице
 * «Люди» и в дровере в двух разных видах (было именно так: `PlatformAutomationDots` красил
 * глифы своим набором `ring-*`, а `AutomationTab` — своим набором `StatusChip`).
 */
import type { StatusTone } from "@/components/ui/status-chip"

export const AUTOMATION_PLATFORMS = ["hh", "getmatch", "habr"] as const

/** Состояние сессии автопросмотра площадки → подпись + тон чипа (дровер). */
export function discoveryStateChip(state: string): { label: string; tone: StatusTone } {
  if (state === "running") return { label: "работает", tone: "strong" }
  if (state === "paused_daily_cap") return { label: "дневной лимит", tone: "warn" }
  if (state === "paused_pages_exhausted") return { label: "выдача просмотрена", tone: "warn" }
  if (state === "paused_suspected_block") return { label: "похоже на блок", tone: "bad" }
  if (state.startsWith("paused_")) return { label: "на паузе", tone: "warn" }
  return { label: "выключен", tone: "info" }
}

/** Автоотклик площадки → подпись + тон. `dryRun` = «Тест»/подтверждение (реальных откликов нет). */
export function applyStateChip(
  enabled: boolean,
  dryRun: boolean,
): { label: string; tone: StatusTone } {
  if (!enabled) return { label: "выключен", tone: "info" }
  if (dryRun) return { label: "проверка", tone: "warn" }
  return { label: "включён", tone: "strong" }
}

/** Брифовое состояние площадки из таблицы «Люди» ('off'|'running'|'paused'|'idle') → тон точки. */
export function briefDiscoveryTone(state: string | undefined): StatusTone {
  if (state === "running") return "strong"
  if (state === "paused") return "warn"
  return "info"
}

/** Брифовое состояние автоотклика ('off'|'live'|'stale') → тон точки. */
export function briefApplyTone(state: string | undefined): StatusTone {
  if (state === "live") return "strong"
  if (state === "stale") return "warn"
  return "info"
}

/** Сколько площадок в «активном» состоянии из трёх (для сводки «работает на 2 из 3»). */
export function countActive(
  map: Record<string, string> | undefined,
  active: (state: string) => boolean,
): number {
  let n = 0
  for (const p of AUTOMATION_PLATFORMS) if (active(map?.[p] ?? "")) n += 1
  return n
}

/** Раннер молчит дольше трёх тиков → service worker расширения, скорее всего, усыплён. */
export function runnerAsleep(
  lastTickIso: string | null | undefined,
  tickSeconds: number,
  now: number = Date.now(),
): boolean {
  if (!lastTickIso) return false
  const at = new Date(lastTickIso).getTime()
  if (Number.isNaN(at)) return false
  return now - at > Math.max(60, tickSeconds) * 1000 * 3
}

/** «45 / 200» — сколько из суточного потолка выбрано; для мини-прогресса. */
export function capPct(current: number, cap: number): number {
  if (cap <= 0) return 0
  return Math.min(100, Math.round((current / cap) * 100))
}
