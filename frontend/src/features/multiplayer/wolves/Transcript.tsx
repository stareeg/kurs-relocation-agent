import { seatName } from "./seatName"
import type { WolvesWsPublicState } from "./wolves-ws"

type TranscriptProps = {
  pub: WolvesWsPublicState
}

/**
 * Стенограмма реплик слота — только чтение, скроллится внутри себя.
 * Раньше жила внутри `LinesPanel`; вынесена, чтобы органы ответа уехали в нижнюю панель
 * действий, а лог остался в правой колонке.
 */
export function Transcript({ pub }: TranscriptProps) {
  const answers = pub.answers ?? {}
  const live = pub.live_lines ?? {}
  const question = pub.question_chip
  const hasAny = Object.keys(answers).length > 0 || Object.keys(live).length > 0

  if (!question && !hasAny) return null

  return (
    <div className="flex min-h-0 flex-col rounded-lg border border-slate-200 bg-white/90 p-3">
      <p className="mp-mono mb-1.5 shrink-0 text-[10px] uppercase tracking-wide text-slate-400">
        Стенограмма
      </p>
      <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto overscroll-contain pr-1">
        {Object.entries(answers).map(([seatId, text]) => (
          <li key={seatId} className="mp-mono text-[11px] leading-snug text-slate-700">
            <span className="font-semibold text-slate-500">{seatName(pub, seatId)}: </span>
            {text}
          </li>
        ))}
        {/* Реплика, которая печатается прямо сейчас: кадры `line_delta` со стрима модели. */}
        {Object.entries(live).map(([seatId, text]) => (
          <li key={`live-${seatId}`} className="mp-mono text-[11px] leading-snug text-slate-500">
            <span className="font-semibold text-slate-400">{seatName(pub, seatId)}: </span>
            {text}
            <span className="mp-caret" aria-hidden="true">
              ▌
            </span>
          </li>
        ))}
        {!hasAny ? (
          <li className="mp-mono text-[11px] text-slate-400">Пока тихо — ждём ответы.</li>
        ) : null}
      </ul>
    </div>
  )
}
