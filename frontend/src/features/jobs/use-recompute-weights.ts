import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ApiError } from "@/api/client"
import { fetchCurrentWeightsVersion, recomputeWeights } from "@/api/jobs"

// Версия рубрики скоринга ПРЯМО СЕЙЧАС (Этап 5 §5.3) — карточка сравнивает её со своим
// job.score_weights_version. staleTime как у useAppSettings (60с): рубрика меняется только
// правкой резюме, гонять запрос на каждый рендер дровера незачем.
export function useCurrentWeightsVersion() {
  return useQuery({
    queryKey: ["scoring", "weights-version"],
    queryFn: fetchCurrentWeightsVersion,
    staleTime: 60_000,
  })
}

// Кнопка «Пересчитать» на карточке — узкий пересчёт по текущей рубрике в обход полного /score
// (без LLM). Инвалидация ["jobs"] обновляет карточку/доску тем же путём, что и useRecomputeSalary.
export function useRecomputeWeights() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vacancyId: string) => recomputeWeights(vacancyId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["jobs"] })
    },
    onError: (e: unknown) =>
      toast.error(e instanceof ApiError ? e.message : "Не удалось пересчитать рубрику"),
  })
}
