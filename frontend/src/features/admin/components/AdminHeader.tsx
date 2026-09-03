import { RotateCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { SegmentedControl, type SegmentOption } from "@/components/ui/segmented-control"
import { StatusDot } from "@/components/ui/status-chip"
import type { AdminVerdict } from "@/features/admin/attention"
import { updatedAtLabel } from "@/features/admin/admin-format"
import { cn } from "@/lib/utils"

/**
 * Шапка раздела: слева навигация, справа ответ на «надо ли мне что-то делать».
 *
 * Раньше здесь висела полоса из шести KPI (130 px над КАЖДОЙ вкладкой, включая Журнал и
 * Систему, где ни одно из чисел не нужно). Числа уехали туда, где применяются: расход — в
 * блок «Деньги», ошибки и ожидание ключа — в «Дела», сбои задач — в «Систему»,
 * размер флота — в подпись таблицы людей. Вместо них одна строка-вердикт.
 */
export function AdminHeader<T extends string>({
  sections,
  section,
  onSection,
  verdict,
  onVerdictClick,
  updatedAt,
  refreshing,
  onRefresh,
}: {
  sections: readonly SegmentOption<T>[]
  section: T
  onSection: (next: T) => void
  /** Пока состояние неизвестно — не рисуем ничего: «Всё живо» до ответа было бы враньём. */
  verdict?: AdminVerdict
  onVerdictClick?: () => void
  updatedAt: number | undefined
  refreshing: boolean
  onRefresh: () => void
}) {
  const verdictBody = verdict && (
    <>
      {verdict.tone === "ok" ? null : <StatusDot tone={verdict.tone} />}
      <span
        className={cn(
          "truncate text-sm font-medium",
          verdict.tone === "bad"
            ? "text-status-bad-fg"
            : verdict.tone === "warn"
              ? "text-status-warn-fg"
              : "text-slate-600",
        )}
      >
        {verdict.text}
      </span>
    </>
  )

  return (
    <div className="flex h-11 shrink-0 items-center gap-3 border-b bg-white px-6">
      <SegmentedControl
        ariaLabel="Раздел админки"
        options={sections}
        value={section}
        onChange={onSection}
      />

      <div className="ml-auto flex min-w-0 items-center gap-3">
        {!verdictBody ? null : onVerdictClick ? (
          <button
            type="button"
            onClick={onVerdictClick}
            className="flex min-w-0 items-center gap-1.5 rounded-md px-1 hover:bg-slate-50"
          >
            {verdictBody}
          </button>
        ) : (
          <div className="flex min-w-0 items-center gap-1.5 px-1">{verdictBody}</div>
        )}

        <span className="hidden shrink-0 text-xs tabular-nums text-slate-400 xl:inline">
          {refreshing ? "обновляется…" : updatedAtLabel(updatedAt)}
        </span>
        <Button
          size="sm"
          variant="ghost"
          onClick={onRefresh}
          disabled={refreshing}
          aria-label="Обновить"
        >
          <RotateCw className={cn("size-4", refreshing && "animate-spin")} strokeWidth={2} />
          Обновить
        </Button>
      </div>
    </div>
  )
}
