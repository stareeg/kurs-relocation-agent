import { useLayoutEffect, useRef, useState } from "react"

/**
 * Ширина контейнера в пикселях через ResizeObserver — чтобы SVG-графики «Рынка» заполняли
 * свою ячейку целиком, а не торчали фиксированной шириной с пустотой справа (F-07).
 * `fallback` — стартовая ширина до первого замера (и значение под SSR/тесты без ResizeObserver).
 */
export function useContainerWidth<T extends HTMLElement = HTMLDivElement>(
  fallback = 520,
): { ref: React.RefObject<T | null>; width: number } {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(fallback)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const update = () => setWidth(el.clientWidth || fallback)
    update()
    if (typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [fallback])

  return { ref, width }
}
