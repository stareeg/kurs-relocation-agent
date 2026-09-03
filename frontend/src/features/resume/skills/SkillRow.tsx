import { ArrowLeftRight, Check, EyeOff, Loader2, RotateCcw } from "lucide-react"
import type { SkillSuggestionRow } from "@/api/resume"
import { Button } from "@/components/ui/button"
import { StatusChip, type StatusTone } from "@/components/ui/status-chip"
import { SIGN, skillRowLabel } from "./select"

const TONE: Partial<Record<SkillSuggestionRow["state"], StatusTone>> = {
  add: "good",
  drop: "warn",
  rename: "info",
}

// U-05: применённое действие ещё не пересчитано в снимке (state остаётся add/drop/rename до
// следующей пересборки — E-02), но для владельца оно уже сделано, поэтому строка ведёт себя
// как «держу»: нейтральный знак, без кнопок.
function isDone(row: SkillSuggestionRow): boolean {
  return row.state === "have" || row.user_state === "accepted"
}

const APPLY_TITLE: Record<SkillSuggestionRow["state"], string> = {
  have: "",
  add: "Добавить в мои навыки",
  drop: "Убрать из моих навыков",
  rename: "Переименовать навык",
}

export function SkillRow({
  row,
  onHide,
  onShow,
  swapDrop,
  onSwap,
  swapPending,
  onApply,
  applyPending,
}: {
  row: SkillSuggestionRow
  onHide: (skill: string) => void
  onShow: (skill: string) => void
  /** U-04: пара «слабейший drop» для этой add-строки при 30/30 — `undefined`, если строка
   * не входит в режим обмена (не add, есть свободный слот, или пара уже разобрана). */
  swapDrop?: SkillSuggestionRow
  onSwap?: (add: string, drop: string) => void
  swapPending?: boolean
  /** U-05 / Решение 8: применить одиночное действие (add/drop/rename) сразу в key_skills.
   * Для add-строки с `swapDrop` кнопка выполняет обмен вместо простого добавления. */
  onApply?: (row: SkillSuggestionRow) => void
  applyPending?: boolean
}) {
  const done = isDone(row)
  const tone = done ? undefined : TONE[row.state]
  const sign = done ? SIGN.have : SIGN[row.state]

  return (
    <div className="border-b border-border/60 last:border-b-0">
      <div className="flex items-center gap-2 py-1.5">
        {tone ? (
          <StatusChip tone={tone} className="w-5 shrink-0 justify-center px-0 py-0">
            {sign}
          </StatusChip>
        ) : (
          <span className="w-5 shrink-0 text-center text-muted-foreground" aria-hidden>
            {sign}
          </span>
        )}
        <span className="min-w-0 flex-1 truncate text-sm" title={skillRowLabel(row)}>
          {skillRowLabel(row)}
        </span>
        <span
          className="shrink-0 text-xs tabular-nums text-muted-foreground"
          title={`спрос: ${row.demand_count} из ${row.demand_total} вакансий`}
        >
          {row.demand_count}/{row.demand_total}
        </span>
        {!done && (
          <div className="flex shrink-0 items-center gap-0.5">
            {onApply && (row.state !== "add" || !swapDrop) && (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                disabled={applyPending}
                onClick={() => onApply(row)}
                title={APPLY_TITLE[row.state]}
                aria-label={APPLY_TITLE[row.state]}
                className="size-7"
              >
                {applyPending ? (
                  <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
                ) : (
                  <Check className="size-3.5" strokeWidth={2} />
                )}
              </Button>
            )}
            {swapDrop && onSwap && (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                disabled={swapPending}
                onClick={() => onSwap(row.skill, swapDrop.skill)}
                title={`Обменять: добавить ${row.skill}, убрать ${swapDrop.skill}`}
                aria-label={`Обменять на ${swapDrop.skill}`}
                className="size-7"
              >
                {swapPending ? (
                  <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
                ) : (
                  <ArrowLeftRight className="size-3.5" strokeWidth={2} />
                )}
              </Button>
            )}
            {row.user_state === "hidden" ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => onShow(row.skill)}
                title="Вернуть в предложенные"
                aria-label="Вернуть в предложенные"
                className="size-7"
              >
                <RotateCcw className="size-3.5" strokeWidth={2} />
              </Button>
            ) : (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => onHide(row.skill)}
                title="Скрыть из предложенных"
                aria-label="Скрыть из предложенных"
                className="size-7"
              >
                <EyeOff className="size-3.5" strokeWidth={2} />
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
