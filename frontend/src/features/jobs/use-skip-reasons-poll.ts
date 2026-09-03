import { useEffect, useRef, useState } from "react"
import { fetchSkipReasons, type SkipReasonItem } from "@/api/jobs"

const EMPTY: SkipReasonItem[] = []

/**
 * Полл LLM-причин пропуска под вакансию (GET /vacancies/{id}/skip-reasons).
 *
 * Возвращает массив чипов ({text, canonical}). Пока фон генерирует (task_running)
 * или причин ещё нет — поллим каждые 2с до 10 попыток. Если причин нет и задача
 * не активна — возвращаем пустой массив (UI падает на статичные SELF_REJECT_REASONS).
 *
 * Не используем react-query тут: данные не кэшируются глобально (каждый дровер
 * опрашивает свой vacancy_id, и нам важен именно поллинг, а не stale-while-revalidate).
 */
export function useSkipReasonsPoll(vacancyId: string | null): SkipReasonItem[] {
  // Ранний возврат без эффекта, если vacancyId нет — eslint не ругается на
  // setState-в-эффекте, т.к. хук завершается до useEffect.
  const [reasons, setReasons] = useState<SkipReasonItem[]>(EMPTY)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!vacancyId) return

    let cancelled = false
    let attempt = 0
    const MAX_ATTEMPTS = 10
    const INTERVAL_MS = 2000

    const poll = async () => {
      while (attempt < MAX_ATTEMPTS && !cancelled) {
        attempt += 1
        try {
          const data = await fetchSkipReasons(vacancyId)
          if (cancelled) return
          if (data.reasons && data.reasons.length > 0) {
            setReasons(data.reasons)
            return
          }
          if (!data.task_running) return
        } catch {
          // сеть/ошибка — продолжаем поллить
        }
        await new Promise((r) => {
          timerRef.current = setTimeout(r, INTERVAL_MS)
        })
      }
    }

    void poll()

    return () => {
      cancelled = true
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [vacancyId])

  // Когда vacancyId сменяется/пропадает, возвращаем пустой массив — через
  // производное значение, а не setState-в-эффекте (react-hooks/set-state-in-effect).
  return vacancyId ? reasons : EMPTY
}
