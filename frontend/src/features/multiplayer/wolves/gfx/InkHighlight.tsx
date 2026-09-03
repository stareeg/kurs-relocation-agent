import { cn } from "@/lib/utils"

type InkHighlightProps = {
  active?: boolean
  selected?: boolean
  children: React.ReactNode
  className?: string
  onToggle?: () => void
}

/** Маркер несостыковки: клик выделяет улику (до двух слотов снаружи). */
export function InkHighlight({
  active = true,
  selected = false,
  children,
  className,
  onToggle,
}: InkHighlightProps) {
  return (
    <button
      type="button"
      disabled={!active}
      onClick={onToggle}
      className={cn(
        "mp-mono rounded-sm px-1 py-0.5 text-left text-sm transition-colors",
        selected
          ? "bg-[color:var(--mp-stamp)]/20 ring-2 ring-[color:var(--mp-stamp)] ring-offset-1"
          : active
            ? // Э35.2: активная улика читается как кликабельная — пунктир тоном бюллетеня.
              "cursor-pointer border-b border-dashed border-[color:var(--mp-bulletin-edge)] hover:bg-[color:var(--mp-ink)]/10"
            : "hover:bg-[color:var(--mp-ink)]/5",
        !active && "cursor-default opacity-70",
        className,
      )}
    >
      {children}
    </button>
  )
}
