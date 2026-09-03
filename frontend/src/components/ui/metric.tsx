import { cn } from "@/lib/utils"

/**
 * Числовой показатель: крупное число, следом подпись, слева вертикальный разделитель.
 *
 * Идиома продукта — так метрики стоят в шапках блоков «Рынка» (`MarketPage`, «1 240 вак. ·
 * 380 000 медиана»). Заведена как примитив на Этапе 0 редизайна админки: там показатели
 * рисовались наоборот — КАПС-подпись сверху, число под ней, без разделителя, — из-за чего
 * шапка раздела читалась как чужая. Метрики «Рынка» пока собраны инлайн и на этот примитив
 * не переведены: их значения разношёрстные (пара «число + вторая величина»), это отдельная
 * уборка.
 *
 * Ставить прямыми детьми flex-контейнера — разделитель снимается у первой метрики через
 * `first:`.
 */
export function Metric({
  label,
  value,
  note,
  tone = "normal",
  onClick,
  title,
  className,
}: {
  label: string
  value: string | number
  /** Из чего сложилось число: «в т.ч. 19 без аккаунта». */
  note?: string
  /** `bad` — число само по себе плохая новость. «Нормально» цвета не имеет (§2.5). */
  tone?: "normal" | "bad"
  onClick?: () => void
  title?: string
  className?: string
}) {
  const body = (
    <>
      <span
        className={cn(
          "text-lg leading-none font-semibold tabular-nums tracking-tight",
          tone === "bad" ? "text-status-bad-fg" : "text-slate-900",
        )}
      >
        {value}
      </span>
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="text-xs leading-none text-slate-500">{label}</span>
        {note ? <span className="text-xs leading-none text-slate-400">{note}</span> : null}
      </span>
    </>
  )

  const shell = cn(
    "flex min-w-0 items-baseline gap-2 border-l border-slate-200 pl-3 first:border-l-0 first:pl-0",
    className,
  )

  if (!onClick) {
    return (
      <div className={shell} title={title}>
        {body}
      </div>
    )
  }
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={cn(shell, "rounded-md text-left hover:opacity-80")}
    >
      {body}
    </button>
  )
}
