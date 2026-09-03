import { useQuery } from "@tanstack/react-query"
import { fetchVacancyTextFormat } from "@/api/vacancy-text-format"

// Форматированный текст вакансии (абзацы + **выделения**): тянем лениво, только когда вкладка
// «Вакансия» реально открыта (TabVacancy монтируется по клику) и текст есть. Текст вакансии не
// меняется — staleTime Infinity, повторный визит на ту же карточку не бьёт в сеть заново (бэкенд
// и так кэширует сам LLM-вызов, но нет смысла даже слать лишний HTTP).
export function useVacancyTextFormat(vacancyId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["vacancy-text-format", vacancyId],
    queryFn: () => fetchVacancyTextFormat(vacancyId!),
    enabled: enabled && !!vacancyId,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
}
