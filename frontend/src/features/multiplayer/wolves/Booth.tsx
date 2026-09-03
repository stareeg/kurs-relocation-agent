import { CardFace, EnergyPips, type ExperienceTag } from "@/features/multiplayer/wolves/gfx"
import { cn } from "@/lib/utils"
import { PAPER_FIELDS, paperFieldById } from "./papers"
import { seatLabelFor } from "./seatName"
import { tagRu } from "./tags"
import type { WolvesWsPublicState, WolvesWsSeat } from "./wolves-ws"
import { useCallback, useRef, useState } from "react"

type BoothProps = {
  pub: WolvesWsPublicState
  isHr: boolean
  /** Хрюша может кликать строки-несостыковки прямо сейчас (фаза «Осмотр», иск не подан). */
  canInspect: boolean
  /** Выбранные несостыковки (id строк) — 0..2, состояние живёт в `WolvesTable`. */
  marks: string[]
  onToggleMark: (id: string) => void
  /** Кандидат, чьи бумаги открыты (фокус хрюши). */
  focusSeat: WolvesWsSeat | null
  /** Стряска кабинки при штампе (Э21.3). */
  shaking?: boolean
  onShakeEnd?: () => void
}

/**
 * Кабинка хрюши: сводка кабинета + одна таблица-сличение «требование ↔ факт в резюме».
 *
 * Раньше бумаги рисовались двумя списками (JD и резюме отдельно), и обе копии вешали клик на
 * один и тот же маркер — интерфейс учил ходу, который движок запрещает (Э31.1). Теперь строка
 * целиком = одна несостыковка, «выбери две» становится буквальным действием.
 */
export function Booth({ pub, isHr, canInspect, marks, onToggleMark, focusSeat, shaking = false, onShakeEnd }: BoothProps) {
  const energyMax = pub.hr_energy_max ?? 5
  const energy = pub.hr_energy ?? energyMax
  const citations = pub.citations ?? 0
  const citationsLimit = pub.citations_limit ?? 3
  const citedField = pub.judge_marker ? paperFieldById(pub.judge_marker) : undefined
  const bulletin = pub.bulletin
  const requiredTagRu = bulletin?.required_tag ? tagRu(bulletin.required_tag) : null

  return (
    <section
      className={cn(
        "flex min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border-2 border-[color:var(--mp-plastic-deep)] bg-[color:var(--mp-plastic)]/40 h-full",
        shaking && "mp-booth-shake",
      )}
      onAnimationEnd={onShakeEnd}
    >
      <header className="mp-display flex shrink-0 items-center justify-between border-b border-[color:var(--mp-plastic-deep)] bg-[color:var(--mp-plastic)] px-3 py-2 text-[length:var(--mp-text-sm)] font-semibold uppercase tracking-wide text-[color:var(--mp-ink)]">
        <span>Кабинка хрюши</span>
        <span className="mp-mono text-[length:var(--mp-text-xs)] font-normal opacity-70">
          Выговоры {citations}/{citationsLimit}
          {pub.pending_judge ? " · иск на суде" : ""}
        </span>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-hidden bg-[color:var(--mp-paper)]/30 p-3">
        {isHr ? (
          <div className="flex shrink-0 items-center gap-2">
            <EnergyPips max={energyMax} value={energy} low={energy <= 1} />
          </div>
        ) : null}

        {pub.judge_line ? (
          <div className="mp-enter shrink-0 rounded border border-[color:var(--mp-paper-edge)] bg-[color:var(--mp-paper)]/90 px-3 py-2.5">
            <p className="mp-display text-[length:var(--mp-text-base)] font-semibold leading-snug text-[color:var(--mp-ink)]">
              {pub.judge_line}
            </p>
            {citedField ? (
              <p className="mp-mono mt-1.5 text-[length:var(--mp-text-xs)] text-[color:var(--mp-ink)]/55">
                {citedField.label}: {citedField.resumeText}
              </p>
            ) : null}
          </div>
        ) : null}

        {pub.slot_brief ? (
          <p className="mp-enter mp-display shrink-0 text-[length:var(--mp-text-lg)] font-medium leading-snug text-[color:var(--mp-ink)]/85">
            {pub.slot_brief}
          </p>
        ) : null}

        {bulletin ? (
          <aside className="shrink-0 rounded-sm border border-[color:var(--mp-bulletin-edge)] bg-[color:var(--mp-bulletin)] p-3">
            <div className="mp-display text-[length:var(--mp-text-sm)] font-semibold uppercase tracking-wide text-[color:var(--mp-ink)]">
              Бюллетень · {bulletin.day_label}
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {bulletin.gates.map((label, i) => (
                <span
                  key={`g${i}`}
                  className="mp-mono rounded-sm bg-[color:var(--mp-ink)]/10 px-2 py-0.5 text-[length:var(--mp-text-xs)] leading-snug text-[color:var(--mp-ink)]"
                >
                  {label}
                </span>
              ))}
              {requiredTagRu ? (
                <span className="mp-mono rounded-sm bg-[color:var(--mp-stamp)]/15 px-2 py-0.5 text-[length:var(--mp-text-xs)] font-semibold text-[color:var(--mp-stamp)]">
                  обязательно: {requiredTagRu} — иначе отказ без разговора
                </span>
              ) : null}
              {bulletin.offer_allowed === false ? (
                <span className="mp-mono rounded-sm bg-[color:var(--mp-stamp)]/15 px-2 py-0.5 text-[length:var(--mp-text-xs)] font-semibold text-[color:var(--mp-stamp)]">
                  штамп ОФФЕР закрыт этот слот
                </span>
              ) : null}
            </div>
          </aside>
        ) : null}

        <ComparisonSheet
          focusSeat={focusSeat}
          canInspect={canInspect}
          marks={marks}
          onToggleMark={onToggleMark}
        />

        {focusSeat ? <PlayedStrip seat={focusSeat} /> : null}
      </div>
    </section>
  )
}

function ComparisonSheet({
  focusSeat,
  canInspect,
  marks,
  onToggleMark,
}: {
  focusSeat: WolvesWsSeat | null
  canInspect: boolean
  marks: string[]
  onToggleMark: (id: string) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null)
  const [markCenters, setMarkCenters] = useState<Record<string, { x: number; y: number }>>({})

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (marks.length !== 1) {
      setCursor(null)
      return
    }
    const container = containerRef.current
    if (!container) return
    const rect = container.getBoundingClientRect()
    setCursor({ x: e.clientX - rect.left, y: e.clientY - rect.top })
  }, [marks.length])

  const handlePointerLeave = useCallback(() => setCursor(null), [])

  const getMarkCenter = useCallback(
    (markId: string, el: HTMLElement | null): void => {
      const container = containerRef.current
      if (!el || !container) return
      const containerRect = container.getBoundingClientRect()
      const btnRect = el.getBoundingClientRect()
      const center = {
        x: btnRect.left - containerRect.left + btnRect.width / 2,
        y: btnRect.top - containerRect.top + btnRect.height / 2,
      }
      setMarkCenters((prev) => {
        if (prev[markId]?.x === center.x && prev[markId]?.y === center.y) return prev
        return { ...prev, [markId]: center }
      })
    },
    [],
  )

  return (
    <div
      ref={containerRef}
      className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-sm border border-[color:var(--mp-paper-edge)] bg-[color:var(--mp-paper)] shadow-[2px_3px_0_rgba(30,41,59,0.18)]"
      style={{ backgroundImage: "url(/multiplayer/paper-grain.svg)", backgroundSize: "120px 120px" }}
      onPointerMove={handlePointerMove}
      onPointerLeave={handlePointerLeave}
    >
      <div className="mp-mono flex shrink-0 items-center justify-between border-b border-[color:var(--mp-paper-edge)] px-3 py-2 text-[length:var(--mp-text-xs)] uppercase tracking-wider text-[color:var(--mp-ink)]/70">
        <span>
           Бумаги{focusSeat ? ` · ${seatLabelFor(focusSeat)}` : ""}
        </span>
        <span>требование ↔ резюме</span>
      </div>

      {!focusSeat ? (
        <div className="flex min-h-[6rem] flex-1 flex-col items-center justify-center gap-2 px-3 py-6">
          <p className="mp-display text-center text-[length:var(--mp-text-base)] text-[color:var(--mp-ink)]/45">
            Выбери кандидата на столе внизу
          </p>
          <span className="mp-mono text-[length:var(--mp-text-xs)] text-[color:var(--mp-ink)]/30" aria-hidden>
            ↓
          </span>
        </div>
      ) : (
        <ul className="min-h-0 flex-1 divide-y divide-[color:var(--mp-paper-edge)]/60 overflow-y-auto overscroll-contain">
          {PAPER_FIELDS.map((f) => {
            const selected = marks.includes(f.id)
            return (
              <li key={f.id}>
                <button
                  type="button"
                  data-mark-id={f.id}
                  disabled={!canInspect}
                  onClick={() => onToggleMark(f.id)}
                  ref={(el) => getMarkCenter(f.id, el)}
                  className={cn(
                    "grid w-full grid-cols-[4.5rem_1fr] gap-x-2 gap-y-0.5 px-3 py-2.5 text-left transition-all duration-300 sm:grid-cols-[5rem_1fr_1fr]",
                    selected && "bg-[color:var(--mp-stamp)]/15 ring-1 ring-inset ring-[color:var(--mp-stamp)]",
                    !selected && canInspect && "cursor-pointer hover:bg-[color:var(--mp-ink)]/5 hover:scale-[1.01]",
                    !canInspect && "cursor-default",
                  )}
                >
                  <span className="mp-mono self-center text-[length:var(--mp-text-xs)] uppercase tracking-wide text-[color:var(--mp-ink)]/60">
                    {f.label}
                  </span>
                  <span className="mp-mono text-[length:var(--mp-text-sm)] leading-snug text-[color:var(--mp-ink)]/80">
                    {f.jdText}
                  </span>
                  <span className="mp-mono col-start-2 text-[length:var(--mp-text-sm)] leading-snug text-[color:var(--mp-ink)] sm:col-start-3 sm:row-start-1">
                    {f.resumeText}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {marks.length === 0 || !canInspect ? null : (
        <ThreadOverlay marks={marks} cursor={cursor} centers={markCenters} />
      )}
    </div>
  )
}

function ThreadOverlay({
  marks,
  cursor,
  centers,
}: {
  marks: string[]
  cursor: { x: number; y: number } | null
  centers: Record<string, { x: number; y: number }>
}) {
  if (marks.length === 1 && cursor) {
    const start = centers[marks[0]]
    if (!start) return null
    return (
      <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
        <line
          x1={start.x}
          y1={start.y}
          x2={cursor.x}
          y2={cursor.y}
          stroke="var(--mp-stamp)"
          strokeWidth="2"
          strokeDasharray="6 4"
          className="mp-thread-line"
        />
        <circle cx={start.x} cy={start.y} r="4" fill="var(--mp-stamp)" />
      </svg>
    )
  }

  if (marks.length === 2) {
    const start = centers[marks[0]]
    const end = centers[marks[1]]
    if (!start || !end) return null
    return (
      <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
        <line
          x1={start.x}
          y1={start.y}
          x2={end.x}
          y2={end.y}
          stroke="var(--mp-stamp)"
          strokeWidth="2.5"
          className="mp-thread-fixed"
        />
        <circle cx={start.x} cy={start.y} r="4" fill="var(--mp-stamp)" />
        <circle cx={end.x} cy={end.y} r="4" fill="var(--mp-stamp)" />
      </svg>
    )
  }

  return null
}

function PlayedStrip({ seat }: { seat: WolvesWsSeat }) {
  const played = seat.played ?? []
  if (!played.length) return null
  return (
    <div className="flex shrink-0 flex-wrap gap-2">
      {played.map((c) =>
        c.tag === "hidden" ? (
          <span
            key={c.id}
            className="mp-mono rounded border border-[color:var(--mp-paper-edge)] px-2 py-1 text-[10px]"
          >
            •••
          </span>
        ) : (
          <CardFace key={c.id} tag={(c.tag as ExperienceTag) || "soft"} title={c.title} size="md" />
        ),
      )}
    </div>
  )
}
