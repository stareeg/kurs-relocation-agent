import { useQuery } from "@tanstack/react-query"
import { fetchScoreRevisions } from "@/api/score-revisions"

// История ревизий скоринга по вакансии (JS-8.1). Тянем только когда есть vacancy_id; ревизии
// стабильны — не перезапрашиваем при каждом фокусе (авто-пересчёт инвалидирует через ["jobs"]).
export function useScoreRevisions(vacancyId: string | null) {
  return useQuery({
    queryKey: ["score-revisions", vacancyId],
    queryFn: () => fetchScoreRevisions(vacancyId!),
    enabled: !!vacancyId,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  })
}
