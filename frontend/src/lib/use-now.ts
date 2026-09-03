import { useEffect, useState } from "react"

/**
 * Живой `Date.now()`, обновляется раз в `intervalMs` — для отсчётов «через N мин», которые
 * должны тикать без рефетча данных. Возвращает миллисекунды.
 */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    const onVisible = () => setNow(Date.now())
    document.addEventListener("visibilitychange", onVisible)
    return () => {
      clearInterval(id)
      document.removeEventListener("visibilitychange", onVisible)
    }
  }, [intervalMs])
  return now
}
