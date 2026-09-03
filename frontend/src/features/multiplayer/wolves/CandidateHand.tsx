import { useCallback, useRef, useState } from "react"
import { CardFace, type ExperienceTag } from "@/features/multiplayer/wolves/gfx"
import { cn } from "@/lib/utils"
import { GameButton } from "./GameButton"

type HandCard = { id: string; tag: string; title: string }

type CandidateHandProps = {
  hand: HandCard[]
  cardsToPlay: number
  alreadyPlayed: boolean
  canPlay: boolean
  submitting?: boolean
  errorText?: string | null
  onPlay: (cardIds: string[]) => void
  vertical?: boolean
}

/** Рука кандидата — карты + одна кнопка «Выложить». */
export function CandidateHand({
  hand,
  cardsToPlay,
  alreadyPlayed,
  canPlay,
  submitting = false,
  errorText = null,
  onPlay,
  vertical = false,
}: CandidateHandProps) {
  const [selected, setSelected] = useState<string[]>([])
  const active = canPlay && !alreadyPlayed && !submitting

  const toggle = (id: string) => {
    if (!active) return
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id)
      if (prev.length >= cardsToPlay) return [...prev.slice(1), id]
      return [...prev, id]
    })
  }

  const submit = () => {
    if (!active || selected.length !== cardsToPlay) return
    onPlay(selected)
    setSelected([])
  }

  if (!hand.length && !alreadyPlayed && !submitting) return null

  return (
    <div className={vertical ? "space-y-2" : "shrink-0 p-3"}>
      {canPlay && !alreadyPlayed ? (
        <GameButton
          variant="primary"
          pulse={selected.length === cardsToPlay}
          disabled={!active || selected.length !== cardsToPlay}
          className="w-full"
          onClick={submit}
        >
          {submitting ? "…" : `Выложить · ${selected.length}/${cardsToPlay}`}
        </GameButton>
      ) : alreadyPlayed ? (
        <p className="mp-mono text-center text-[length:var(--mp-text-xs)] text-white/45">✓</p>
      ) : null}

      {errorText ? (
        <p className="mp-mono text-[length:var(--mp-text-xs)] text-[color:var(--mp-stamp)]">{errorText}</p>
      ) : null}

       <div className={`flex gap-2 ${vertical ? "flex-col items-center" : "flex-wrap justify-center"}`}>
        {hand.map((c) => {
          const on = selected.includes(c.id)
          return (
            <TiltCard key={c.id} active={active} title={c.title} selected={on} onToggle={() => toggle(c.id)}>
              <CardFace
                tag={asTag(c.tag)}
                title={c.title}
                size="lg"
                className={cn("shadow-lg", on && "ring-2 ring-[color:var(--mp-bulletin)] ring-offset-2 ring-offset-transparent")}
              />
            </TiltCard>
          )
        })}
      </div>
    </div>
  )
}

function TiltCard({
  active,
  selected,
  onToggle,
  title,
  children,
}: {
  active: boolean
  selected: boolean
  onToggle: () => void
  title: string
  children: React.ReactNode
}) {
  const ref = useRef<HTMLButtonElement>(null)
  const [tilt, setTilt] = useState({ rx: 0, ry: 0 })

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLButtonElement>) => {
      if (!active || !ref.current) return
      const rect = ref.current.getBoundingClientRect()
      const cx = rect.left + rect.width / 2
      const cy = rect.top + rect.height / 2
      const dx = (e.clientX - cx) / (rect.width / 2)
      const dy = (e.clientY - cy) / (rect.height / 2)
      setTilt({ rx: Math.max(-1, Math.min(1, -dy)) * 12, ry: Math.max(-1, Math.min(1, dx)) * 12 })
    },
    [active],
  )

  const resetTilt = useCallback(() => setTilt({ rx: 0, ry: 0 }), [])

  return (
    <button
      ref={ref}
      type="button"
      disabled={!active}
      title={title}
      onClick={onToggle}
      onPointerMove={handlePointerMove}
      onPointerLeave={resetTilt}
      className={cn(
        "origin-bottom rounded-md transition-transform duration-200",
        active && "cursor-pointer hover:z-10 hover:scale-105",
        selected && "z-10 -translate-y-2 scale-105",
        !active && "cursor-default opacity-50",
      )}
      style={{
        transform: active
          ? `perspective(700px) rotateX(${tilt.rx}deg) rotateY(${tilt.ry}deg) ${selected ? "translateY(-0.5rem) scale(1.05)" : ""}`
          : undefined,
      }}
    >
      {children}
    </button>
  )
}

function asTag(tag: string): ExperienceTag {
  const ok: ExperienceTag[] = [
    "ownership",
    "scale",
    "incident",
    "soft",
    "stack",
    "bluff",
    "batna",
    "second_job",
  ]
  return (ok.includes(tag as ExperienceTag) ? tag : "soft") as ExperienceTag
}
