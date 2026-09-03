import { useEffect, useState } from "react"

// P-14: таймер для честного прогресса долгих LLM-генераций (вместо голого спиннера) — тикает,
// пока active, и сбрасывается на новый заход без эффекта-в-эффекте (сравнение с предыдущим
// рендером, идиоматичный React вместо setState внутри useEffect).
export function useElapsedMs(active: boolean): number {
  const [elapsed, setElapsed] = useState(0)
  const [prevActive, setPrevActive] = useState(active)

  if (active !== prevActive) {
    setPrevActive(active)
    setElapsed(0)
  }

  useEffect(() => {
    if (!active) return
    const started = Date.now()
    const id = window.setInterval(() => setElapsed(Date.now() - started), 250)
    return () => window.clearInterval(id)
  }, [active])

  return elapsed
}

export function formatElapsedMs(ms: number): string {
  const totalSec = Math.floor(ms / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return m > 0 ? `${m}:${String(s).padStart(2, "0")}` : `0:${String(s).padStart(2, "0")}`
}
