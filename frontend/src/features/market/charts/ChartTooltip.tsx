import { useLayoutEffect, useRef, useState } from "react"
import { cn } from "@/lib/utils"

export type ChartTooltipRow = {
  key?: string
  /** Подпись ряда — мельче значения (план п. 4.3: «в тултипе значение крупнее подписи»). */
  label?: string
  value: string
  /** Маркер цвета ряда, нужен только когда рядов больше одного. */
  swatchClassName?: string
}

/**
 * Общий тултип для наведения на графиках (V-08, план п. 4.3): один плавающий блок и для одной
 * точки (спарклайн), и для нескольких рядов под общим визиром («один тултип со всеми рядами») —
 * решает, какая часть строки крупнее, один раз, а не в каждом графике заново.
 *
 * Правка 2026-08-08 (жалоба «всплывают непонятно где»): тултип по умолчанию центрировался
 * (`-translate-x-1/2`) — у края контейнера он упирался в границу и обрезался/вылезал за карточку.
 * Теперь измеряет собственную ширину против позиционируемого предка и клиппит `left` внутрь него
 * (`container-clamp`), так что точка у любого края всё равно показывает подсказку целиком.
 */
export function ChartTooltip({
  x,
  y,
  rows,
  heading,
  className,
  containerClamp = true,
}: {
  /** Координаты в системе позиционируемого предка (обычно `left`/`top` внутри `relative`
   *  контейнера) — число (px) или готовая CSS-строка (например, `"42%"` для процентных осей). */
  x: number | string
  y: number | string
  rows: readonly ChartTooltipRow[]
  /** Общая подпись над значениями — одна на весь тултип (например, дата точки). */
  heading?: string
  className?: string
  /** Вписывать тултип в границы контейнера (не давать обрезаться у краёв). */
  containerClamp?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  // Значение `left` после клиппинга — пересчитывается после первого замера ширины.
  const [clampedX, setClampedX] = useState<number | string | null>(null)

  useLayoutEffect(() => {
    if (!containerClamp) return
    const el = ref.current
    if (!el) return
    const parent = el.offsetParent as HTMLElement | null
    const numericX = typeof x === "number" ? x : null
    if (!parent || numericX == null) return
    setClampedX(
      Math.min(parent.clientWidth - el.offsetWidth / 2, Math.max(el.offsetWidth / 2, numericX)),
    )
  }, [x, y, heading, rows, containerClamp])

  const left = containerClamp && clampedX != null ? clampedX : x

  if (rows.length === 0) return null

  return (
    <div
      ref={ref}
      role="status"
      className={cn(
        "pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md border border-border bg-card px-2 py-1 shadow-md",
        className,
      )}
      style={{ left, top: y }}
    >
      {heading ? (
        <div className="text-center text-[10px] leading-tight text-slate-500">{heading}</div>
      ) : null}
      {rows.map((row, i) => (
        <div
          key={row.key ?? i}
          className={cn(
            "flex items-center gap-1.5",
            rows.length > 1 ? "justify-between" : "justify-center",
          )}
        >
          {row.swatchClassName ? (
            <span className={cn("size-1.5 shrink-0 rounded-full", row.swatchClassName)} />
          ) : null}
          {row.label ? (
            <span className="text-[10px] leading-tight text-slate-500">{row.label}</span>
          ) : null}
          <span className="text-sm leading-tight font-semibold tabular-nums text-slate-900">
            {row.value}
          </span>
        </div>
      ))}
    </div>
  )
}
