import * as React from "react"

import { cn } from "@/lib/utils"

function supportsFieldSizing(): boolean {
  return typeof CSS !== "undefined" && typeof CSS.supports === "function" && CSS.supports("field-sizing", "content")
}

// Растёт с текстом от компактной высоты до `maxHeight`, дальше - обычный скролл внутри поля.
// Раньше каждый композер держал поле большим и пустым (`min-h-24` и т.п. на каждом вызове) и
// давал ручной уголок растягивания (`resize-y`) - оба убраны на уровне базового компонента, чтобы
// не разводить одну и ту же логику по каждому call-site.
//
// `field-sizing: content` (Chrome 123+) считает высоту без JS. Старый путь — `height: auto` в
// useLayoutEffect — на вкладке «Резюме» схлопывал textarea на кадр и дёргал scrollTop контейнера
// (рваный скролл при вводе и при колёсике, если параллельно шёл ре-рендер формы).
function Textarea({
  className,
  maxHeight = 224,
  style,
  ...props
}: React.ComponentProps<"textarea"> & { maxHeight?: number }) {
  const ref = React.useRef<HTMLTextAreaElement | null>(null)
  const native = supportsFieldSizing()

  React.useLayoutEffect(() => {
    if (native) return
    const el = ref.current
    if (!el) return
    const scroller = el.closest("[data-resume-scroll], .overflow-y-auto")
    const top = scroller instanceof HTMLElement ? scroller.scrollTop : null
    el.style.height = "auto"
    const next = Math.min(el.scrollHeight, maxHeight)
    el.style.height = `${next}px`
    el.style.overflowY = el.scrollHeight > maxHeight ? "auto" : "hidden"
    if (scroller instanceof HTMLElement && top != null) scroller.scrollTop = top
  }, [props.value, maxHeight, native])

  return (
    <textarea
      data-slot="textarea"
      ref={ref}
      style={{
        ...(native
          ? { fieldSizing: "content" as const, maxHeight, overflowY: "auto" as const }
          : { maxHeight }),
        ...style,
      }}
      className={cn(
        "flex min-h-10 w-full resize-none overflow-x-hidden overflow-y-auto rounded-md border border-input bg-transparent px-3 py-2 text-base shadow-xs transition-[color,box-shadow] outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 md:text-sm",
        className,
      )}
      {...props}
    />
  )
}

export { Textarea }
