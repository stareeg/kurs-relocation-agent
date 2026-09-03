import { useEffect, useState } from "react"

/** Пауза поверх сцены — как `#table .pauseLogo` в SIGame, без сдвига layout. */
export function PauseOverlay({
  by,
  resumingAt,
}: {
  by?: string
  resumingAt?: number | null
}) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (resumingAt == null) return
    const id = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(id)
  }, [resumingAt])

  const secLeft = resumingAt != null ? Math.max(0, Math.ceil((resumingAt - now) / 1000)) : null

  return (
    <div
      className="mp-pause-overlay mp-enter absolute inset-0 z-30 flex items-center justify-center bg-black/55 px-4 backdrop-blur-[2px]"
      role="status"
      aria-live="polite"
    >
      <div className="mp-glass-panel max-w-md px-6 py-5 text-center shadow-xl">
        <p className="mp-display mp-stage-text text-[length:var(--mp-text-xl)] font-bold text-white">
          ⏸ Пауза
        </p>
        <p className="mp-display mt-2 text-[length:var(--mp-text-base)] leading-snug text-white/85">
          {secLeft != null
            ? `Продолжаем через ${secLeft}с…`
            : by
              ? `Поставил ${by} · «▶» вверху жмёт любой`
              : "«▶» вверху жмёт любой"}
        </p>
      </div>
    </div>
  )
}
