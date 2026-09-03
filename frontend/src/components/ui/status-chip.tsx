import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

// Единый тон для чипов-статусов (D-04): recommendation, work-format, mastery и родственные
// им бейджи-факты держат один и тот же словарь вместо magic emerald/amber/rose/sky/violet.
// strong — сильный сигнал, good — послабее позитив, warn — осторожно, bad — негатив,
// info — нейтральный факт-тег (не про хорошо/плохо). Смысл см. globals.css.
export type StatusTone = "strong" | "good" | "warn" | "bad" | "info"

const statusChipVariants = cva(
  "inline-flex w-fit shrink-0 items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      tone: {
        strong: "border-status-strong-line bg-status-strong-soft text-status-strong-fg",
        good: "border-status-good-line bg-status-good-soft text-status-good-fg",
        warn: "border-status-warn-line bg-status-warn-soft text-status-warn-fg",
        bad: "border-status-bad-line bg-status-bad-soft text-status-bad-fg",
        info: "border-status-info-line bg-status-info-soft text-status-info-fg",
      } satisfies Record<StatusTone, string>,
    },
    defaultVariants: {
      tone: "info",
    },
  },
)

function StatusChip({
  className,
  tone,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof statusChipVariants>) {
  return (
    <span
      data-slot="status-chip"
      className={cn(statusChipVariants({ tone }), className)}
      {...props}
    />
  )
}

const STATUS_DOT_CLASS: Record<StatusTone, string> = {
  strong: "bg-status-strong-dot",
  good: "bg-status-good-dot",
  warn: "bg-status-warn-dot",
  bad: "bg-status-bad-dot",
  info: "bg-status-info-dot",
}

// Точка-индикатор того же тона (StageChain, mastery-точки в «Прогрессе»/разборе).
function StatusDot({ className, tone }: { className?: string; tone: StatusTone }) {
  return (
    <span
      data-slot="status-dot"
      className={cn("inline-block size-2 shrink-0 rounded-full", STATUS_DOT_CLASS[tone], className)}
    />
  )
}

export { StatusChip, StatusDot, statusChipVariants, STATUS_DOT_CLASS }
