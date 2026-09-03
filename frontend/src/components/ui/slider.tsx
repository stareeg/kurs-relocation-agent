import * as React from "react"
import { Slider as SliderPrimitive } from "radix-ui"

import { cn } from "@/lib/utils"

// Ползунок (shadcn/radix, токены дизайн-системы). Один бегунок (число) или диапазон (массив) — бегунки
// рендерим по количеству значений. Замена select-фильтрам с порогами (скор, вилка, сроки). UI-0.
function Slider({
  className,
  value,
  defaultValue,
  ...props
}: React.ComponentProps<typeof SliderPrimitive.Root>) {
  const thumbs = Array.isArray(value) ? value : Array.isArray(defaultValue) ? defaultValue : [0]
  return (
    <SliderPrimitive.Root
      data-slot="slider"
      value={value}
      defaultValue={defaultValue}
      className={cn("relative flex w-full touch-none select-none items-center", className)}
      {...props}
    >
      <SliderPrimitive.Track className="relative h-1.5 w-full grow overflow-hidden rounded-full bg-muted">
        <SliderPrimitive.Range className="absolute h-full bg-primary" />
      </SliderPrimitive.Track>
      {thumbs.map((_, i) => (
        <SliderPrimitive.Thumb
          key={i}
          className="block size-4 rounded-full border border-input bg-card shadow-sm outline-none transition-colors hover:border-ring focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
        />
      ))}
    </SliderPrimitive.Root>
  )
}

export { Slider }
