import * as React from "react"

/** Любая координата с горизонтальной позицией — общий домен для «ближайшей точки». */
export type NearestCoord = { cx: number }

/** Индекс координаты, чей `cx` ближе всего к позиции курсора (визир «липнет», план п. 4.3). */
export function nearestIndex(coords: readonly NearestCoord[], pointerX: number): number {
  let best = 0
  let bestDist = Infinity
  for (let i = 0; i < coords.length; i++) {
    const dist = Math.abs(coords[i]!.cx - pointerX)
    if (dist < bestDist) {
      bestDist = dist
      best = i
    }
  }
  return best
}

/** Линейная интерполяция числа между `a` и `b` по доле `t` (0..1). */
export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

export type InterpolatedPosition = {
  /** Индекс точки слева от позиции курсора. */
  index: number
  /** Индекс точки справа — обычно `index + 1`; равен `index`, когда позиция ровно на точке
   * (в т.ч. единственная точка в ряду) — тогда `lerp` на одинаковых `a`/`b` даёт саму точку
   * независимо от `t`. */
  nextIndex: number
  /** Доля пути от `index` к `nextIndex`, 0..1. */
  t: number
}

/**
 * Позиция курсора МЕЖДУ соседними точками — не снэп к ближайшей (план 2026-08-11 п.6:
 * «хотелось бы смотреть статистику в произвольные моменты», курсор должен плавно скользить
 * вдоль линии, а значение между реальными снимками — линейная аппроксимация отрезка, который
 * и так нарисован на графике, а не скачок к ближайшему снимку). `null`, если точек нет.
 */
export function interpolatedPosition(
  coords: readonly NearestCoord[],
  pointerX: number,
): InterpolatedPosition | null {
  if (coords.length === 0) return null
  if (coords.length === 1) return { index: 0, nextIndex: 0, t: 0 }
  const first = coords[0]!.cx
  const last = coords[coords.length - 1]!.cx
  const clamped = Math.min(last, Math.max(first, pointerX))
  for (let i = 0; i < coords.length - 1; i++) {
    const a = coords[i]!.cx
    const b = coords[i + 1]!.cx
    if (clamped >= a && clamped <= b) {
      const t = b > a ? (clamped - a) / (b - a) : 0
      return { index: i, nextIndex: i + 1, t }
    }
  }
  // Кламп уже держит `clamped` внутри [first, last] — сюда доходим только на границах
  // плавающей точки; берём последний сегмент, ровно на его конце.
  return { index: coords.length - 2, nextIndex: coords.length - 1, t: 1 }
}

export type UseNearestResult<E extends Element> = {
  containerRef: React.RefObject<E | null>
  activeIndex: number | null
  setActiveIndex: React.Dispatch<React.SetStateAction<number | null>>
  handlers: {
    onPointerMove: (e: { clientX: number }) => void
    onPointerLeave: () => void
    onFocus: () => void
    onBlur: () => void
    onClick: (e: { clientX: number }) => void
    onKeyDown: (e: { key: string; preventDefault: () => void }) => void
  }
}

/**
 * Общий слой наведения для линейных графиков (V-08, план п. 4.3): визир липнет к ближайшей
 * координате под курсором/пальцем, стрелки двигают его с клавиатуры, фокус ставит на последнюю
 * точку, Enter/Space выбирают — то же самое, что раньше жило внутри `Sparkline` (V-07), теперь
 * доступно любому графику с координатами вдоль оси X (например, оси денег с наведением «в любую
 * точку», план п. 3.1). Одна и та же логика на pointer и на клавиатуру не даёт им разойтись.
 */
export function useNearest<E extends Element = Element>(
  coords: readonly NearestCoord[],
  width: number,
  onSelect?: (index: number) => void,
): UseNearestResult<E> {
  const containerRef = React.useRef<E>(null)
  const [activeIndex, setActiveIndex] = React.useState<number | null>(null)
  const lastIndex = coords.length - 1

  const indexFromClientX = React.useCallback(
    (clientX: number): number | null => {
      const el = containerRef.current
      if (!el || coords.length === 0) return null
      const rect = el.getBoundingClientRect()
      const scaleX = rect.width > 0 ? width / rect.width : 1
      const pointerX = (clientX - rect.left) * scaleX
      return nearestIndex(coords, pointerX)
    },
    [coords, width],
  )

  const moveActive = React.useCallback(
    (delta: number) => {
      if (lastIndex < 0) return
      setActiveIndex((prev) => {
        const base = prev ?? lastIndex
        return Math.min(lastIndex, Math.max(0, base + delta))
      })
    },
    [lastIndex],
  )

  const handlers = React.useMemo(
    () => ({
      onPointerMove: (e: { clientX: number }) => {
        const idx = indexFromClientX(e.clientX)
        if (idx != null) setActiveIndex(idx)
      },
      onPointerLeave: () => setActiveIndex(null),
      onFocus: () => setActiveIndex((prev) => prev ?? (lastIndex >= 0 ? lastIndex : null)),
      onBlur: () => setActiveIndex(null),
      onClick: (e: { clientX: number }) => {
        const idx = indexFromClientX(e.clientX)
        if (idx == null) return
        setActiveIndex(idx)
        onSelect?.(idx)
      },
      onKeyDown: (e: { key: string; preventDefault: () => void }) => {
        if (e.key === "ArrowLeft") {
          e.preventDefault()
          moveActive(-1)
        } else if (e.key === "ArrowRight") {
          e.preventDefault()
          moveActive(1)
        } else if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          setActiveIndex((prev) => {
            if (prev != null) onSelect?.(prev)
            return prev
          })
        }
      },
    }),
    [indexFromClientX, lastIndex, moveActive, onSelect],
  )

  return { containerRef, activeIndex, setActiveIndex, handlers }
}

export type UseInterpolatedHoverResult<E extends Element> = {
  containerRef: React.RefObject<E | null>
  position: InterpolatedPosition | null
  setPosition: React.Dispatch<React.SetStateAction<InterpolatedPosition | null>>
  handlers: {
    onPointerMove: (e: { clientX: number }) => void
    onPointerLeave: () => void
    onFocus: () => void
    onBlur: () => void
    onClick: (e: { clientX: number }) => void
    onKeyDown: (e: { key: string; preventDefault: () => void }) => void
  }
}

/**
 * Слой наведения с линейной интерполяцией между точками (план 2026-08-11 п.6, `LineChart`):
 * в отличие от `useNearest` (визир липнет к ближайшей реальной точке), здесь позиция курсора —
 * доля пути между двумя соседними точками, курсор скользит по нарисованному отрезку плавно, а
 * не скачками. Клавиатура (стрелки/фокус/Enter) по-прежнему шагает по реальным точкам —
 * непрерывная интерполяция имеет смысл только для позиции указателя.
 */
export function useInterpolatedHover<E extends Element = Element>(
  coords: readonly NearestCoord[],
  width: number,
  onSelect?: (position: InterpolatedPosition) => void,
): UseInterpolatedHoverResult<E> {
  const containerRef = React.useRef<E>(null)
  const [position, setPosition] = React.useState<InterpolatedPosition | null>(null)
  const lastIndex = coords.length - 1

  const positionFromClientX = React.useCallback(
    (clientX: number): InterpolatedPosition | null => {
      const el = containerRef.current
      if (!el || coords.length === 0) return null
      const rect = el.getBoundingClientRect()
      const scaleX = rect.width > 0 ? width / rect.width : 1
      const pointerX = (clientX - rect.left) * scaleX
      return interpolatedPosition(coords, pointerX)
    },
    [coords, width],
  )

  const moveDiscrete = React.useCallback(
    (delta: number) => {
      if (lastIndex < 0) return
      setPosition((prev) => {
        const current = prev ? Math.round(prev.index + prev.t) : lastIndex
        const next = Math.min(lastIndex, Math.max(0, current + delta))
        return { index: next, nextIndex: next, t: 0 }
      })
    },
    [lastIndex],
  )

  const handlers = React.useMemo(
    () => ({
      onPointerMove: (e: { clientX: number }) => {
        const pos = positionFromClientX(e.clientX)
        if (pos != null) setPosition(pos)
      },
      onPointerLeave: () => setPosition(null),
      onFocus: () =>
        setPosition(
          (prev) =>
            prev ?? (lastIndex >= 0 ? { index: lastIndex, nextIndex: lastIndex, t: 0 } : null),
        ),
      onBlur: () => setPosition(null),
      onClick: (e: { clientX: number }) => {
        const pos = positionFromClientX(e.clientX)
        if (pos == null) return
        setPosition(pos)
        onSelect?.(pos)
      },
      onKeyDown: (e: { key: string; preventDefault: () => void }) => {
        if (e.key === "ArrowLeft") {
          e.preventDefault()
          moveDiscrete(-1)
        } else if (e.key === "ArrowRight") {
          e.preventDefault()
          moveDiscrete(1)
        } else if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          setPosition((prev) => {
            if (prev != null) onSelect?.(prev)
            return prev
          })
        }
      },
    }),
    [positionFromClientX, lastIndex, moveDiscrete, onSelect],
  )

  return { containerRef, position, setPosition, handlers }
}
