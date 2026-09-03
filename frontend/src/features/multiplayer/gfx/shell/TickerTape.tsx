import { cn } from "@/lib/utils"

type TickerTapeProps = {
  text: string
  className?: string
}

/** Газета-итог слота — одна строка; remount по text → вход + скан. */
export function TickerTape({ text, className }: TickerTapeProps) {
  return (
    <div
      key={text}
      className={cn(
        "mp-ticker overflow-hidden border-y border-[color:var(--mp-ink)] bg-[color:var(--mp-paper)] px-2 py-0.5",
        className,
      )}
    >
      <p className="mp-display text-[length:var(--mp-text-xs)] font-semibold leading-snug text-[color:var(--mp-ink)]">
        ★ {text}
      </p>
    </div>
  )
}
