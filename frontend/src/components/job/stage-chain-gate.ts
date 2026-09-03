import type { FunnelStage } from "@/features/jobs/funnel"

// Этапы имеет смысл добавлять только начиная со «Скрининга» — раньше (Просмотр/Отклик) и в
// терминальном «Отказе» это был тупиковый путь: можно было накрутить цепочку собесов вакансии,
// которая по факту ещё не сдвинулась дальше отклика (или уже закрыта). Сначала — сдвинуть статус
// воронки, потом — вести этапы. Тот же список статусов, что и `_STAGES_AFTER_SCREENING`
// (`core/domains/preparation/events.py`) плюс сам «Скрининг».
const STAGE_ADDABLE_FUNNEL: ReadonlySet<FunnelStage> = new Set([
  "Скрининг",
  "Техничка",
  "Финал",
  "Оффер",
])

/** Можно ли добавить этап цепочки при данном статусе воронки. `funnelStatus == null` (гейт не
 * подключён вызывающей стороной, напр. Технички — там и так только Техничка/Финал) → всегда true. */
export function canAddInterviewStage(
  funnelStatus: FunnelStage | null | undefined,
  skipped = false,
): boolean {
  if (funnelStatus == null) return true
  return STAGE_ADDABLE_FUNNEL.has(funnelStatus) && !skipped
}

/**
 * Почему цепочку вести нельзя — и лечится ли это переводом на «Скрининг».
 *
 * `null` — единственный случай, из которого есть выход кнопкой: этап просто слишком ранний
 * (Просмотр/Отклик). Строка — случай, который переводом не чинится, её и показываем вместо
 * кнопки. Раньше все три причины отдавали одну бледную надпись «Сначала переместите на этап
 * «Скрининг»», хотя пропущенную вакансию надо сперва вернуть в воронку, а после отказа цепочка
 * не нужна вовсе (Этап 1.2 плана `plans/ui_slop_cleanup_2026_08_25.md`).
 */
export function stageChainBlockedReason(
  funnelStatus: FunnelStage | null | undefined,
  skipped = false,
): string | null {
  if (skipped) {
    return "Вакансия в пропущенных. Верните её в воронку — тогда можно вести цепочку собесов."
  }
  if (funnelStatus === "Отказ") {
    return "По вакансии зафиксирован отказ — цепочку собесов уже не ведём."
  }
  return null
}
