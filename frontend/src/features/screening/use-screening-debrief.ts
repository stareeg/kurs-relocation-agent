import type { DebriefResult } from "@/api/debrief"
import { useDebriefHistory } from "@/features/tech/use-debrief"

// HR-скрининг хранит расшифровку в общем сторе разборов (`core.domains.preparation.debrief`)
// под ключом stage="screening" — тем же, что и остальные форматы Техичек, просто своим
// значением. Общий хук: раньше фильтр жил только в HrScreeningPrepView (Техички), теперь его же
// зовут QuestionsChatPanel (Скрининги, режим «Расшифровка») и TechPage (вставленная здесь
// расшифровка — та же строка в БД, поэтому синхронизация между разделами не требует отдельного
// кода).
export const HR_DEBRIEF_STAGE = "screening"

export function useScreeningDebrief(vacancyId: string | null) {
  const { data, isLoading } = useDebriefHistory(vacancyId)
  const debrief: DebriefResult | undefined = data?.items?.find((d) => d.stage === HR_DEBRIEF_STAGE)
  return { debrief, isLoading }
}
