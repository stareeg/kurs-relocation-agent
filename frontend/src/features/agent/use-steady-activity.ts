import { useEffect, useRef, useState } from "react"

// Строка «Сейчас» без мигания (PLAN 3.2, паттерн COWORK `useSteadyActivity`): каждое действие
// видно не меньше ACTIVITY_MIN_MS, после конца шага последнее держится ещё ACTIVITY_HOLD_MS.
// Пришло несколько действий за это время — показывается последнее. Дольше паузы нового действия
// нет — строки нет: прошлое действие уже не «сейчас». Другой запуск и законченная работа снимают
// строку сразу.

export const ACTIVITY_MIN_MS = 1_500
export const ACTIVITY_HOLD_MS = 3_000

type RunActivity = { runId: number; text: string }

export function useSteadyActivity(
  activity: string | null,
  working: boolean,
  runId: number,
): string | null {
  const [latest, setLatest] = useState<RunActivity | null>(null)
  const [shown, setShown] = useState<RunActivity | null>(null)
  const shownAt = useRef(0)

  useEffect(() => {
    if (!working) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- внешний сигнал (конец работы) снимает строку
      setLatest(null)
      return
    }
    if (activity) {
      setLatest((prev) =>
        prev?.text === activity && prev.runId === runId ? prev : { runId, text: activity },
      )
      return
    }
    const timer = setTimeout(() => setLatest(null), ACTIVITY_HOLD_MS)
    return () => clearTimeout(timer)
  }, [activity, working, runId])

  useEffect(() => {
    if (latest === shown) return
    const show = () => {
      shownAt.current = Date.now()
      setShown(latest)
    }
    const wait = shownAt.current + ACTIVITY_MIN_MS - Date.now()
    if (latest === null || shown === null || shown.runId !== latest.runId || wait <= 0) {
      show()
      return
    }
    const timer = setTimeout(show, wait)
    return () => clearTimeout(timer)
  }, [latest, shown])

  return working && shown?.runId === runId ? shown.text : null
}
