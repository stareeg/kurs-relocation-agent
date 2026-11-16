import { useCallback, useSyncExternalStore } from "react"

/**
 * Совпадает ли медиазапрос сейчас (живое значение, без эффекта и setState).
 * Нет `matchMedia` (jsdom, старый браузер) — `fallback`.
 */
export function useMediaQuery(query: string, fallback = false): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {}
      const mq = window.matchMedia(query)
      mq.addEventListener("change", onChange)
      return () => mq.removeEventListener("change", onChange)
    },
    [query],
  )
  return useSyncExternalStore(subscribe, () =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(query).matches
      : fallback,
  )
}
