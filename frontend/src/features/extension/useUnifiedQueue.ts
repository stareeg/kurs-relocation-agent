import { useAutoApplyPreview } from "@/features/settings/use-settings"
import type { AutoApplyPlatform, AutoApplyPreviewItem, AutoApplySchedule } from "@/api/auto-apply"

export type QueueEntry = AutoApplyPreviewItem & { platform: AutoApplyPlatform }

export function useUnifiedQueue(enabled: boolean = true): {
  auto: QueueEntry[]
  manual: QueueEntry[]
  applied: QueueEntry[]
  schedules: Partial<Record<AutoApplyPlatform, AutoApplySchedule>>
  platformCounts: Partial<Record<AutoApplyPlatform, { auto: number; manual: number; applied: number }>>
  isLoading: boolean
} {
  const hh = useAutoApplyPreview("hh", enabled)
  const getmatch = useAutoApplyPreview("getmatch", enabled)
  const habr = useAutoApplyPreview("habr", enabled)
  const byPlatform = [
    { platform: "hh" as const, query: hh },
    { platform: "getmatch" as const, query: getmatch },
    { platform: "habr" as const, query: habr },
  ]
  const auto: QueueEntry[] = []
  const manual: QueueEntry[] = []
  const applied: QueueEntry[] = []
  const schedules: Partial<Record<AutoApplyPlatform, AutoApplySchedule>> = {}
  const platformCounts: Partial<Record<AutoApplyPlatform, { auto: number; manual: number; applied: number }>> = {}
  for (const { platform, query } of byPlatform) {
    const a = query.data?.auto ?? []
    const m = query.data?.manual_review ?? []
    const ap = query.data?.applied ?? []
    for (const item of a) auto.push({ ...item, platform })
    for (const item of m) manual.push({ ...item, platform })
    for (const item of ap) applied.push({ ...item, platform })
    if (query.data?.schedule) schedules[platform] = query.data.schedule
    platformCounts[platform] = { auto: a.length, manual: m.length, applied: ap.length }
  }
  return {
    auto,
    manual,
    applied,
    schedules,
    platformCounts,
    isLoading: byPlatform.some(({ query }) => query.isLoading),
  }
}
