export type PhaseId = "bulletin" | "play" | "inspect" | "lines" | "stamp" | "judge" | "result"

export const PHASE_LABEL: Record<PhaseId, string> = {
  bulletin: "Бюллетень",
  play: "Подача",
  inspect: "Осмотр",
  lines: "Реплики",
  stamp: "Штамп",
  judge: "Суд",
  result: "Итог",
}

/** Подпись текущей фазы для шапки стола (SIGame tableCaption). */
export function phaseCaptionLabel(phase: PhaseId, between: boolean): string {
  if (between) return "Передышка"
  return PHASE_LABEL[phase] ?? phase
}
