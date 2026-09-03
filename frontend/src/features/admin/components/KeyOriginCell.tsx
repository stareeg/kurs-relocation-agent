import type { AdminUserRow } from "@/api/admin"
import { StatusChip } from "@/components/ui/status-chip"
import { remainingLabel, remainingTone, type KeyRemainingProbe } from "@/features/admin/admin-format"
import { cn } from "@/lib/utils"

/**
 * Происхождение ключа OpenRouter: «свой» / «выдан вами» / «нет» плюс хвост `…15fb`.
 *
 * Жило во вкладке «Ключи», которая с Этапа 3 растворилась: отдельный экран ради одной колонки
 * заставлял сличать одних и тех же людей по двум таблицам.
 */
export function KeyOriginLabel({ user }: { user: AdminUserRow }) {
  if (!user.key_origin) return <span className="text-xs text-slate-400">нет</span>
  const managed = user.key_origin === "admin"
  return (
    <span className="inline-flex min-w-0 items-baseline gap-1.5">
      <span
        className={cn(
          "inline-flex shrink-0 items-center rounded px-1.5 py-0.5 text-xs font-medium",
          managed ? "bg-slate-200 text-slate-700" : "bg-slate-100 text-slate-600",
        )}
      >
        {managed ? "выдан вами" : "свой"}
      </span>
      {user.key_hint && (
        <span className="shrink-0 font-mono text-xs text-slate-500">{user.key_hint}</span>
      )}
      {user.key_label && <span className="truncate text-xs text-slate-400">{user.key_label}</span>}
    </span>
  )
}

/**
 * Ячейка «Ключ» в таблице людей: происхождение, остаток после «Обновить остатки» и тихая
 * подпись, если этот же ключ стоит у кого-то ещё.
 *
 * Остаток красится только когда он ненормален (§2.5): «$12.50 осталось» — обычный факт, а не
 * повод для цветной плашки; «мёртв» и «нет ответа» — повод.
 */
export function KeyOriginCell({
  user,
  probe,
  sharedWith,
}: {
  user: AdminUserRow
  /** Ответ пробы OpenRouter; приезжает только после «Обновить остатки». */
  probe?: KeyRemainingProbe
  /** Готовая подпись «тот же ключ, что у @lil_hate» — считает `sharedKeyNotes`. */
  sharedWith?: string
}) {
  const tone = remainingTone(probe)
  const label = remainingLabel(probe)
  const alarming = tone === "warn" || tone === "bad"
  return (
    <div className="min-w-0">
      <div className="flex min-w-0 items-baseline gap-1.5">
        <KeyOriginLabel user={user} />
        {user.key_origin === "admin" && label !== "—" ? (
          alarming ? (
            <StatusChip tone={tone} className="tabular-nums">
              {label}
            </StatusChip>
          ) : (
            <span className="shrink-0 tabular-nums text-xs text-slate-500">{label}</span>
          )
        ) : null}
      </div>
      {sharedWith && <div className="truncate text-xs text-slate-400">{sharedWith}</div>}
    </div>
  )
}
