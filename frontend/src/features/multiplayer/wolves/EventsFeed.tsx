import type { WolvesWsPublicState } from "./wolves-ws"

type EventsFeedProps = {
  pub: WolvesWsPublicState | undefined
  eventLabel?: string | null
  slotTicker?: string | null
}

/** Лента игровых событий — правая колонка: событие, тикер, контекст слота. */
export function EventsFeed({ pub, eventLabel, slotTicker }: EventsFeedProps) {
  const eventType = pub?.event?.kind ?? null

  const hasContent = Boolean(eventType || eventLabel || slotTicker)

  if (!hasContent) return null

  return (
    <div className="mp-glass-panel flex flex-col gap-2 rounded-lg p-3">
      <span className="mp-mono text-[length:var(--mp-text-xs)] uppercase tracking-wider text-white/45">
        События
      </span>
      {eventLabel ? (
        <div className="rounded-md bg-white/10 px-2 py-1.5">
          <span className="mp-display text-[length:var(--mp-text-sm)] font-semibold text-white">
            {eventLabel}
          </span>
        </div>
      ) : null}
      {slotTicker ? (
        <p className="mp-mono text-[length:var(--mp-text-xs)] leading-snug text-white/70">
          {slotTicker}
        </p>
      ) : null}
      {eventType ? (
        <div className="flex flex-col gap-1 border-t border-white/10 pt-2">
          <span className="mp-mono text-[length:var(--mp-text-2xs)] uppercase tracking-wide text-white/40">
            Тип
          </span>
          <span className="mp-display text-[length:var(--mp-text-xs)] text-white/80">
            {eventType}
          </span>
        </div>
      ) : null}
    </div>
  )
}
