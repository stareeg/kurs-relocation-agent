import { cn } from "@/lib/utils"

type BoothFrameProps = {
  children?: React.ReactNode
  className?: string
  footer?: React.ReactNode
}

/** Рамка кабинки хрюши (левая половина стола). */
export function BoothFrame({ children, className, footer }: BoothFrameProps) {
  return (
    <section
      className={cn(
        "flex flex-col overflow-hidden rounded-lg border-2 border-[color:var(--mp-plastic-deep)] bg-[color:var(--mp-plastic)]/40 shadow-[inset_0_1px_0_rgba(255,255,255,0.35)]",
        className,
      )}
    >
      <header className="mp-display flex items-center justify-between border-b border-[color:var(--mp-plastic-deep)] bg-[color:var(--mp-plastic)] px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-[color:var(--mp-ink)]">
        <span>Кабинка хрюши</span>
        <span className="mp-mono text-[10px] font-normal opacity-60">окно / бумага / штамп</span>
      </header>
      <div className="flex-1 space-y-3 bg-[color:var(--mp-paper)]/30 p-3">{children}</div>
      {footer ? (
        <footer className="border-t border-[color:var(--mp-plastic-deep)] bg-[color:var(--mp-plastic)] px-3 py-2">
          {footer}
        </footer>
      ) : null}
    </section>
  )
}
