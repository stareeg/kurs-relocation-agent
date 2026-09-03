import { useEffect, useState } from "react"
import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Живой (не мемоизированный) читатель системной настройки — только для точечных JS-веток
 * (WAAPI, таймеры), где CSS-эквивалента `@media (prefers-reduced-motion)` нет. */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches
}

/** Токены появления из globals.css (шаг 46). */
export const MOTION_RISE = "motion-rise"
export const MOTION_FADE = "motion-fade"
export const MOTION_POP = "motion-pop"

/** Каскад только у первых N элементов списка (шаг 47). */
export const MOTION_STAGGER_LIMIT = 8

const MOTION_STAGGER = [
  "motion-stagger-0",
  "motion-stagger-1",
  "motion-stagger-2",
  "motion-stagger-3",
  "motion-stagger-4",
  "motion-stagger-5",
  "motion-stagger-6",
  "motion-stagger-7",
] as const

/** Задержка каскада по индексу; ≥8 — без задержки. */
export function motionStaggerClass(index: number): string {
  if (index < 0 || index >= MOTION_STAGGER_LIMIT) return ""
  return MOTION_STAGGER[index] ?? ""
}

/** Первый показ списка — rise+stagger; смена состава (фильтры) — fade без каскада. */
export function motionListItemClass(index: number, mode: "rise" | "fade" = "rise"): string {
  if (mode === "fade") return MOTION_FADE
  return cn(MOTION_RISE, motionStaggerClass(index))
}

/**
 * Режим появления списка по сигнатуре состава (обычно отсортированные id).
 * Первый непустой состав — rise; дальнейшие смены сигнатуры — fade + bump appearKey
 * (чтобы CSS-анимация перезапустилась на тех же ключах React).
 */
export function useListAppearMotion(listSignature: string): {
  mode: "rise" | "fade"
  appearKey: number
  itemClass: (index: number) => string
} {
  const [mode, setMode] = useState<"rise" | "fade">("rise")
  const [appearKey, setAppearKey] = useState(0)
  const [prevSig, setPrevSig] = useState<string | null>(null)
  const [primed, setPrimed] = useState(false)

  if (listSignature !== prevSig) {
    const hadPrev = prevSig !== null
    setPrevSig(listSignature)
    if (hadPrev && primed) {
      setMode("fade")
      setAppearKey((k) => k + 1)
    }
  }
  if (listSignature.length > 0 && !primed) {
    setPrimed(true)
  }

  return {
    mode,
    appearKey,
    itemClass: (index: number) => motionListItemClass(index, mode),
  }
}

/**
 * Разовый motion-pop на конкретном элементе (например карточка, только что перетащенная в другую
 * колонку доски) — правило «правки состояния конкретного элемента — pop» (D-14). Раньше каждый
 * потребитель заводил свой `useState`/`useEffect`/`setTimeout`; здесь — один хук на всех.
 */
export function usePopMotion(ms = 160): {
  trigger: (id: string) => void
  classFor: (id: string, fallbackClass?: string) => string
} {
  const [popId, setPopId] = useState<string | null>(null)

  useEffect(() => {
    if (popId == null) return
    const t = window.setTimeout(() => setPopId(null), ms)
    return () => window.clearTimeout(t)
  }, [popId, ms])

  return {
    trigger: (id: string) => setPopId(id),
    classFor: (id: string, fallbackClass = "") => (id === popId ? MOTION_POP : fallbackClass),
  }
}

/**
 * id-шники, впервые появившиеся в списке после первой отрисовки — план §6.3, «появление
 * сообщения с картинкой в ленте». Первая отрисовка (история чата целиком) ничего не помечает
 * новым, иначе при открытии диалога проигралась бы анимация по всей ленте разом; помечаются
 * только те id, что пришли уже после неё (новое сообщение, довставка через SSE).
 */
export function useNewIds(currentIds: number[]): Set<number> {
  const signature = currentIds.join(",")
  const [state, setState] = useState<{
    signature: string | null
    seen: Set<number>
    fresh: Set<number>
  }>({ signature: null, seen: new Set(), fresh: new Set() })

  // Правка состояния прямо при рендере (как в `useListAppearMotion` выше) — не setState в
  // эффекте: `fresh` должен быть готов к тому же коммиту, что и новый `signature`.
  if (signature !== state.signature) {
    const fresh =
      state.signature == null
        ? new Set<number>()
        : new Set(currentIds.filter((id) => !state.seen.has(id)))
    setState({ signature, seen: new Set(currentIds), fresh })
  }

  return state.fresh
}
