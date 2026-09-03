import { useEffect } from "react"
import { useQuery } from "@tanstack/react-query"
import { fetchJobSources } from "@/api/meta"
import { applyJobSources } from "@/features/jobs/source-registry"

/**
 * 7.4 / D2 / D3: подтянуть канон `ALL_JOB_SOURCES` с бэка при старте приложения.
 *
 * Хук вешается один раз на верхнем уровне (App). После успешного `GET /api/meta/sources`
 * вызывает `applyJobSources` — реестр `source-registry.ts` обновляется, и все последующие
 * `resolveSourceGroup` используют актуальный перечень с бэка (вместо дефолт-хардкода).
 *
 * Деградация: если бэк недоступен, реестр остаётся на дефолте (код не падает, фолбэк
 * по vacancy_id продолжает работать). Ошибку не показываем — это статика, не пользовательская
 * задача; в худшем случае владелец видит неправильную группу для нового источника, пока
 * бэк не поднимется.
 */
export function useInitJobSources(): void {
  const query = useQuery({
    queryKey: ["meta-sources"],
    queryFn: fetchJobSources,
    staleTime: Infinity, // справочник меняется редко, не рефетчим
    retry: false, // не спамим бэк при недоступности
  })

  useEffect(() => {
    if (query.data) {
      applyJobSources(query.data.sources)
    }
  }, [query.data])
}
