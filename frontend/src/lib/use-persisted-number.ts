import { useCallback, useState } from "react"

/** Числовой аналог usePersistedBoolean (например ширина резиновой панели, решение #12). */
export function usePersistedNumber(key: string, defaultValue: number) {
  const [value, setValue] = useState(() => {
    try {
      const raw = localStorage.getItem(key)
      if (raw != null) {
        const parsed = Number(raw)
        if (Number.isFinite(parsed)) return parsed
      }
    } catch {
      /* ignore */
    }
    return defaultValue
  })

  const set = useCallback(
    (next: number | ((prev: number) => number)) => {
      setValue((prev) => {
        const v = typeof next === "function" ? next(prev) : next
        try {
          localStorage.setItem(key, String(v))
        } catch {
          /* ignore */
        }
        return v
      })
    },
    [key],
  )

  return [value, set] as const
}
