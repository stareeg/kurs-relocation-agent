import { useCallback, useId, useRef, useState } from "react"
import type { StampKind } from "./StampButton"

const STAMP_LABEL: Record<StampKind, string> = {
  approve: "НА СОБЕС",
  reject: "ОТКАЗ",
  probe: "ПРОВЕРКА",
  offer: "ОФФЕР",
}

type Imprint = { id: number; x: number; y: number; rot: number; kind: StampKind }

/** Контроллер отпечатков на PaperSheet (React-state для витрины/кабинки). */
export function useStampImprints() {
  const [imprints, setImprints] = useState<Imprint[]>([])
  const seq = useRef(0)
  const layerId = useId()

  const addImprint = useCallback((kind: StampKind) => {
    seq.current += 1
    setImprints((prev) => [
      ...prev,
      {
        id: seq.current,
        kind,
        x: 12 + Math.random() * 55,
        y: 20 + Math.random() * 45,
        rot: -14 + Math.random() * 28,
      },
    ])
  }, [])

  const clear = useCallback(() => setImprints([]), [])

  const overlay = (
    <div id={layerId} className="pointer-events-none absolute inset-0 overflow-hidden">
      {imprints.map((m) => (
        <span
          key={m.id}
          className="mp-imprint absolute border-2 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide"
          style={{
            left: `${m.x}%`,
            top: `${m.y}%`,
            ["--mp-rot" as string]: `${m.rot}deg`,
            borderColor:
              m.kind === "reject"
                ? "var(--mp-stamp)"
                : m.kind === "offer"
                  ? "var(--mp-chip-offer)"
                  : m.kind === "probe"
                    ? "var(--mp-chip-wait)"
                    : "var(--mp-chip-ok)",
            color:
              m.kind === "reject"
                ? "var(--mp-stamp)"
                : m.kind === "offer"
                  ? "var(--mp-chip-offer)"
                  : m.kind === "probe"
                    ? "var(--mp-chip-wait)"
                    : "var(--mp-chip-ok)",
            fontFamily: "var(--mp-font-display)",
          }}
        >
          {STAMP_LABEL[m.kind]}
        </span>
      ))}
    </div>
  )

  return { imprints, addImprint, clear, overlay }
}
