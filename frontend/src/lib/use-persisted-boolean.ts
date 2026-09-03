import { useCallback, useState } from "react"

export function usePersistedBoolean(key: string, defaultValue = false) {
  const [value, setValue] = useState(() => {
    try {
      const raw = localStorage.getItem(key)
      if (raw != null) return raw === "1"
    } catch {
      /* ignore */
    }
    return defaultValue
  })

  const set = useCallback(
    (next: boolean | ((prev: boolean) => boolean)) => {
      setValue((prev) => {
        const v = typeof next === "function" ? next(prev) : next
        try {
          localStorage.setItem(key, v ? "1" : "0")
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

/** Строковый аналог `usePersistedBoolean` — для UI-состояния с более чем двумя значениями
 * (например переключатель режима панели), которое должно пережить перезагрузку страницы, но
 * никогда не должно само по себе триггерить сетевые мутации. */
export function usePersistedString<T extends string>(key: string, defaultValue: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key)
      if (raw != null) return raw as T
    } catch {
      /* ignore */
    }
    return defaultValue
  })

  const set = useCallback(
    (next: T) => {
      setValue(next)
      try {
        localStorage.setItem(key, next)
      } catch {
        /* ignore */
      }
    },
    [key],
  )

  return [value, set] as const
}
