import { useEffect, useState } from "react"

/**
 * Видимая высота окна (px), реагирующая на появление виртуальной клавиатуры и мобильных
 * тулбаров через `visualViewport`. Используется разделами, которые обязаны уместиться в
 * один экран без скролла (мультиплеер, редакторы).
 *
 * На десктопе совпадает с `window.innerHeight`; на мобиле — `visualViewport.height`,
 * уменьшается при открытии клавиатуры, чтобы стол/поля ввода не уезжали под неё.
 */
export function useViewportHeight(): number {
  const [height, setHeight] = useState(() => readViewportHeight())

  useEffect(() => {
    const update = () => setHeight(readViewportHeight())
    update()
    window.addEventListener("resize", update)
    window.addEventListener("orientationchange", update)
    const vv = window.visualViewport
    vv?.addEventListener("resize", update)
    vv?.addEventListener("scroll", update)
    return () => {
      window.removeEventListener("resize", update)
      window.removeEventListener("orientationchange", update)
      vv?.removeEventListener("resize", update)
      vv?.removeEventListener("scroll", update)
    }
  }, [])

  return height
}

function readViewportHeight(): number {
  if (typeof window === "undefined") return 0
  const vv = window.visualViewport
  if (vv && vv.height > 0) return vv.height
  return window.innerHeight || 0
}

/**
 * Синхронизирует `--mp-vh` / `--mp-vw` на корне раздела с реальной видимой высотой
 * (учитывая мобильную клавиатуру через `visualViewport`). CSS использует их вместо
 * `100dvh`, чтобы автоматически ужиматься при появлении клавиатуры.
 */
export function syncViewportUnits(
  host: HTMLElement | null,
  height: number,
): void {
  if (!host) return
  if (height > 0) host.style.setProperty("--mp-vh", `${height}px`)
  host.style.setProperty("--mp-vw", `${window.innerWidth || 0}px`)
}
