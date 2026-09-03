import { useQuery } from "@tanstack/react-query"
import { fetchVacancyEvents } from "@/api/jobs"

export function useVacancyEvents(vacancyId: string | null) {
  return useQuery({
    queryKey: ["vacancy-events", vacancyId],
    queryFn: () => fetchVacancyEvents(vacancyId!),
    enabled: !!vacancyId,
    staleTime: 20_000,
    refetchOnWindowFocus: false,
  })
}
