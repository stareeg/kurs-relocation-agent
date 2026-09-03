import { useCallback, useState } from "react"
import { cn } from "@/lib/utils"

export type StampKind = "approve" | "reject" | "probe" | "offer"

const STAMP_LABEL: Record<StampKind, string> = {
  approve: "На собес",
  reject: "Отказ",
  probe: "Проверка",
  offer: "Оффер",
}

/** SIGame accept/reject/standard mapping для штампов. */
const STAMP_VARIANT: Record<StampKind, string> = {
  approve: "mp-btn-accept",
  reject: "mp-btn-reject",
  probe: "mp-btn-standard",
  offer: "mp-btn-primary",
}

type StampButtonProps = {
  kind?: StampKind
  label?: string
  disabled?: boolean
  highlight?: boolean
  className?: string
  onStamp?: (kind: StampKind) => void
}

/** Штамп — градиентная кнопка SIGame с slam-анимацией на нажатии. */
export function StampButton({
  kind = "approve",
  label,
  disabled,
  highlight = false,
  className,
  onStamp,
}: StampButtonProps) {
  const [slam, setSlam] = useState(false)
  const text = label ?? STAMP_LABEL[kind]

  const handleClick = useCallback(() => {
    if (disabled) return
    setSlam(false)
    requestAnimationFrame(() => setSlam(true))
    onStamp?.(kind)
  }, [disabled, kind, onStamp])

  return (
    <button
      type="button"
      disabled={disabled}
      aria-label={`Штамп: ${text}`}
      onClick={handleClick}
      onAnimationEnd={() => setSlam(false)}
      className={cn(
        "mp-btn inline-flex h-10 w-full items-center justify-center gap-1.5 uppercase tracking-wide",
        STAMP_VARIANT[kind],
        !disabled && highlight && "mp-demo-blink",
        slam && "mp-stamp-slam",
        className,
      )}
    >
      <svg viewBox="0 0 24 24" aria-hidden className="size-3.5 shrink-0" fill="currentColor">
        <path d="M9 2h6a2 2 0 0 1 2 2v3a3 3 0 0 1-3 3h-4a3 3 0 0 1-3-3V4a2 2 0 0 1 2-2Z" opacity="0.55" />
        <rect x="4" y="15" width="16" height="3.5" rx="1.2" />
        <rect x="7" y="11" width="10" height="4" rx="1" opacity="0.8" />
      </svg>
      {text}
    </button>
  )
}
