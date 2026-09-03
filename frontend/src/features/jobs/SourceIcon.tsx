import { Send } from "lucide-react"
import { cn } from "@/lib/utils"
import { SOURCE_GROUP_LABEL, type SourceGroup } from "./source"

/** 16×16 (или size=20 для колонки списка): иконка источника с tooltip и aria-label (GM-6). */
export function SourceIcon({
  group,
  size = 16,
  className,
}: {
  group: SourceGroup
  size?: 16 | 20
  className?: string
}) {
  const label = SOURCE_GROUP_LABEL[group]
  const box = size === 20 ? "size-5" : "size-4"
  const aria = `Источник: ${label}`

  if (group === "hh") {
    return (
      <span
        className={cn(
          "inline-flex shrink-0 items-center justify-center rounded-[3px] bg-[#d6001c] font-bold leading-none text-white",
          box,
          size === 20 ? "text-[9px]" : "text-[8px]",
          className,
        )}
        title={label}
        aria-label={aria}
        role="img"
      >
        hh
      </span>
    )
  }

  if (group === "getmatch") {
    // D8: text-[9px]/text-[8px] выровнен с hh — ранее был меньше (8/7) без причины.
    // Вне шкалы D-07: буквы логотипа внутри значка box, а не читаемый текст.
    return (
      <span
        className={cn(
          "inline-flex shrink-0 items-center justify-center rounded-[3px] bg-amber-400 font-bold leading-none text-slate-900",
          box,
          size === 20 ? "text-[9px]" : "text-[8px]",
          className,
        )}
        title={label}
        aria-label={aria}
        role="img"
      >
        gm
      </span>
    )
  }

  if (group === "habr") {
    return (
      <span
        className={cn(
          "inline-flex shrink-0 items-center justify-center rounded-[3px] bg-[#77b55b] font-bold leading-none text-white",
          box,
          size === 20 ? "text-[9px]" : "text-[8px]",
          className,
        )}
        title={label}
        aria-label={aria}
        role="img"
      >
        hr
      </span>
    )
  }

  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-[3px] bg-sky-100 text-sky-600",
        box,
        className,
      )}
      title={label}
      aria-label={aria}
      role="img"
    >
      <Send className={size === 20 ? "size-3" : "size-2.5"} strokeWidth={2} />
    </span>
  )
}
