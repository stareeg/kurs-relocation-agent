import { cn } from "@/lib/utils"

type PaperSheetProps = {
  children?: React.ReactNode
  className?: string
  title?: string
  /** Относительный контейнер для штампов / маркеров поверх листа */
  overlay?: React.ReactNode
}

/** Лист бумаги кабинки: зерно, тень, клип для отпечатков. */
export function PaperSheet({ children, className, title, overlay }: PaperSheetProps) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-sm border border-[color:var(--mp-paper-edge)] bg-[color:var(--mp-paper)] shadow-[2px_3px_0_rgba(30,41,59,0.18)]",
        className,
      )}
      style={{
        backgroundImage: "url(/multiplayer/paper-grain.svg)",
        backgroundSize: "120px 120px",
      }}
    >
      {title ? (
        <div className="mp-mono border-b border-[color:var(--mp-paper-edge)] px-3 py-1.5 text-[10px] uppercase tracking-wider text-[color:var(--mp-ink)]/70">
          {title}
        </div>
      ) : null}
      <div className="relative px-3 py-3 text-sm leading-relaxed text-[color:var(--mp-ink)]">
        {children}
        {overlay}
      </div>
    </div>
  )
}
