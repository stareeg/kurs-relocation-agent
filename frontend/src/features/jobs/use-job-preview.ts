import { useQuery, type Query } from "@tanstack/react-query"
import { fetchJobByVacancyId } from "@/api/jobs"
import type { Job } from "@/api/jobs"

// Ленивая подгрузка полного Job по vacancy_id для ховер-превью в очередях «Расширения» (Фаза A
// редизайна) — тот же ключ/паттерн, что у deep-link лукапа в JobsWorkspace.tsx (общий кэш,
// `staleTime: Infinity` — карточка неизменна в рамках сессии просмотра, свежие данные подтянутся
// обычной инвалидацией `["jobs", ...]` при следующем маунте). `enabled` — запрос только когда
// попап реально открыт, не на каждый рендер строки очереди.
export function useJobPreview(
  vacancyId: string | null | undefined,
  enabled: boolean,
  options?: {
    /** Правка 2026-08-20: попап сопроводительного письма (`CoverLetterIcon`) держит его
     * включённым, пока письмо готовится фоновой пре-генерацией (`preview_with_pregen` на бэке) —
     * `staleTime: Infinity` иначе не подхватил бы результат без ручного закрытия/переоткрытия
     * попапа. `false`/не задано — обычное поведение (ни разу не рефетчит после первой загрузки). */
    refetchInterval?: number | false | ((query: Query<Job>) => number | false)
  },
) {
  return useQuery({
    queryKey: ["jobs", "by-vacancy", vacancyId],
    queryFn: () => fetchJobByVacancyId(vacancyId as string),
    enabled: enabled && Boolean(vacancyId),
    retry: false,
    staleTime: Infinity,
    refetchInterval: options?.refetchInterval ?? false,
  })
}
