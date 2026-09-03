import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ApiError } from "@/api/client"
import { recomputeSalary } from "@/api/jobs"

// Кнопка «Обновить» у зарплаты (шапка чата вакансии / дровер) — запускает узкий пересчёт вилки
// в обход полного /score. Сам прогресс отображает уже существующий usePendingSalaryRefresh
// (поллит ["jobs"], пока job.score.salary.estimate_pending) — здесь только триггер + инвалидация.
export function useRecomputeSalary() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vacancyId: string) => recomputeSalary(vacancyId),
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: ["jobs"] })
      if (!result.estimate_pending) {
        toast.info(
          result.source === "explicit"
            ? "Зарплата зафиксирована вручную — пересчёт не требуется"
            : "Пересчёт не запущен",
        )
      }
    },
    onError: (e: unknown) =>
      toast.error(e instanceof ApiError ? e.message : "Не удалось запросить пересчёт зарплаты"),
  })
}
