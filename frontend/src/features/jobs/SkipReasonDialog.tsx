import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { DODGY_COMPANY_REASON, SELF_REJECT_REASONS } from "./reject-reasons"
import type { SkipReasonItem } from "@/api/jobs"

/**
 * Диалог выбора причины пропуска вакансии (веб-дровер).
 *
 * Показывает LLM-сгенерированные чипы (если есть) либо статичный канон (фолбэк).
 * «Избегать компанию» — отдельная кнопка внизу, не в общем потоке чипов: она
 * добавляет компанию в список «Избегать» резюме (через backend POST /skip с
 * канонической причиной «Избегать компанию»).
 *
 * Под капотом backend сам канонизирует причину (canonical_skip_reason), так что
 * передаём как есть — LLM-текст или статичный лейбл.
 *
 * Этап 1.4 плана `plans/ui_slop_cleanup_2026_08_25.md`: причина обязательна. Раньше «Пропустить»
 * жала и без выбора, а именно эти причины питают секцию «Причины в пропуске» на «Рынке» —
 * график выглядел фактом, а собирался из добровольного ввода, который проще всего пропустить.
 * Заодно убрано обещание «отменить кнопкой «Вернуть»» без указания, где эта кнопка: пропущенные
 * скрыты фильтром доски, и найти их, не зная про фильтр, нельзя.
 */
export function SkipReasonDialog({
  open,
  onOpenChange,
  reasons,
  selected,
  onSelect,
  skipPending,
  onConfirm,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  reasons: SkipReasonItem[]
  selected: string | undefined
  onSelect: (reason: string | undefined) => void
  skipPending: boolean
  onConfirm: () => void
}) {
  // LLM-чипы есть — показываем их; нет — статичный фолбэк (без «Избегать компанию»).
  const chips: SkipReasonItem[] =
    reasons.length > 0
      ? reasons
      : SELF_REJECT_REASONS.filter((r) => r !== DODGY_COMPANY_REASON).map((r) => ({
          text: r,
          canonical: r,
        }))

  return (
    <AlertDialog open={open} onOpenChange={(o) => !o && onOpenChange(o)}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Пропустить вакансию?</AlertDialogTitle>
          <AlertDialogDescription>
            Вакансия уйдёт из активной воронки. Вернуть её можно на доске — включите фильтр
            «Пропущено». Выберите причину: из этих ответов собирается блок «Причины в пропуске» на
            «Рынке».
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="flex flex-wrap gap-2 py-2">
          {chips.map((chip) => {
            const isSelected = selected === chip.canonical
            return (
              <button
                key={chip.canonical}
                type="button"
                onClick={() => onSelect(isSelected ? undefined : chip.canonical)}
                className={
                  "rounded-md border px-3 py-1.5 text-sm transition-colors " +
                  (isSelected
                    ? "border-rose-400 bg-rose-100 text-rose-800"
                    : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50")
                }
                title={`Канон: ${chip.canonical}`}
              >
                {chip.text}
              </button>
            )
          })}
        </div>

        {/* «Избегать компанию» — отдельная статичная кнопка: добавляет компанию
            в список «Избегать» резюме (через backend POST /skip с этой причиной). */}
        <div className="pt-1">
          <button
            type="button"
            onClick={() =>
              onSelect(selected === DODGY_COMPANY_REASON ? undefined : DODGY_COMPANY_REASON)
            }
            className={
              "rounded-md border px-3 py-1.5 text-sm transition-colors " +
              (selected === DODGY_COMPANY_REASON
                ? "border-amber-400 bg-amber-100 text-amber-800"
                : "border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100")
            }
          >
            {DODGY_COMPANY_REASON} (в список «Избегать»)
          </button>
        </div>

        {/* Причина обязательна, поэтому у выключенной кнопки обязана быть видимая причина
            блокировки: выключенный элемент без объяснения — то же самое, что тупик. Отдельной
            строкой над футером, а не внутри него: в узком диалоге текст ужимал кнопки. */}
        {!selected && (
          <p className="pt-1 text-sm text-muted-foreground">Сначала выберите причину</p>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={skipPending}>Отмена</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            disabled={skipPending || !selected}
            title={selected ? undefined : "Выберите причину пропуска — она нужна для «Рынка»"}
          >
            {skipPending ? "Сохраняем…" : "Пропустить"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
