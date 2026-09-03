import { memo, useState } from "react"
import { cn } from "@/lib/utils"
import { TAG_SHORT } from "@/features/multiplayer/wolves/tags"

export type ExperienceTag =
  | "ownership"
  | "scale"
  | "incident"
  | "soft"
  | "stack"
  | "bluff"
  | "batna"
  | "second_job"

/** Размер карты опыта: чем меньше, тем меньше текста помещается — вплоть до одного ярлыка. */
export type CardSize = "sm" | "md" | "lg"

const TAG_TINT: Record<ExperienceTag, string> = {
  ownership: "#166534",
  scale: "#1d4ed8",
  incident: "#b42318",
  soft: "#854d0e",
  stack: "#0f766e",
  bluff: "#6b21a8",
  batna: "#9a3412",
  second_job: "#334155",
}

/** Человеческий ярлык тега — служебное слово (`ownership:`) вслух не показываем (Э19.0). */
const TAG_LABEL = TAG_SHORT

const SIZE_BOX: Record<CardSize, string> = {
  sm: "h-16 w-12",
  md: "h-24 w-20",
  lg: "h-36 w-28",
}

type CardFaceProps = {
  tag: ExperienceTag
  title: string
  /** Габарит + кегль. `sm` показывает только ярлык тега, полный текст — в `title`. */
  size?: CardSize
  className?: string
}

export const CardFace = memo(function CardFace({
  tag,
  title,
  size = "lg",
  className,
}: CardFaceProps) {
  const tint = TAG_TINT[tag]
  const label = TAG_LABEL[tag]

  // Маленькая карта физически не вмещает название — показываем ярлык тега, текст уходит в tooltip.
  if (size === "sm") {
    return (
      <div
        title={title}
        className={cn(
          "flex h-16 w-12 flex-col items-center justify-center gap-0.5 overflow-hidden rounded-md border-2 bg-[color:var(--mp-paper)] px-1 text-center shadow-md",
          className,
        )}
        style={{ borderColor: tint }}
      >
        <span
          className="mp-mono text-[9px] font-semibold uppercase leading-tight tracking-wide sm:text-[length:var(--mp-text-xs)]"
          style={{ color: tint }}
        >
          {label}
        </span>
      </div>
    )
  }

  const isMd = size === "md"
  return (
    <div
      title={title}
      className={cn("flex flex-col overflow-hidden rounded-md border-2 bg-[color:var(--mp-paper)] shadow-md", SIZE_BOX[size], className)}
      style={{ borderColor: tint }}
    >
      <div
        className={cn(
          "mp-mono font-semibold uppercase tracking-wider text-[color:var(--mp-paper)]",
          isMd ? "px-1.5 py-0.5 text-[8px]" : "px-2 py-1 text-[9px]",
        )}
        style={{ backgroundColor: tint }}
      >
        {label}
      </div>
      <div className={cn("flex flex-1 items-center", isMd ? "px-1.5 py-1" : "px-2 py-2")}>
        <p
          className={cn(
            "mp-mono leading-snug text-[color:var(--mp-ink)]",
            isMd ? "line-clamp-3 text-[9px]" : "line-clamp-4 text-[11px]",
          )}
        >
          {title}
        </p>
      </div>
    </div>
  )
})

type CardBackProps = { className?: string }

export const CardBack = memo(function CardBack({ className }: CardBackProps) {
  // Инлайн-SVG, не <img src>: внешний файл был единственным звеном, которое отваливалось
  // «крашнутой картинкой», и он же лишний сетевой запрос на каждую рубашку.
  return (
    <svg
      viewBox="0 0 80 112"
      className={cn(
        "h-36 w-28 rounded-md border border-[color:var(--mp-felt-line)] shadow-md",
        className,
      )}
      aria-hidden
    >
      <rect width="80" height="112" rx="6" fill="var(--mp-felt)" />
      <rect
        x="4"
        y="4"
        width="72"
        height="104"
        rx="4"
        fill="none"
        stroke="var(--mp-paper)"
        strokeWidth="2"
        opacity="0.85"
      />
      <path
        d="M28 40h24M28 52h24M28 64h16"
        stroke="var(--mp-paper)"
        strokeWidth="2"
        strokeLinecap="round"
        opacity="0.5"
      />
      <circle cx="40" cy="84" r="6" fill="none" stroke="var(--mp-paper)" strokeWidth="1.5" opacity="0.7" />
    </svg>
  )
})

type FlippableCardProps = {
  tag: ExperienceTag
  title: string
  className?: string
  /** Начальная сторона: false = рубашка */
  startFaceUp?: boolean
}

/** Кликни — карта переворачивается (3D flip). */
export function FlippableCard({
  tag,
  title,
  className,
  startFaceUp = false,
}: FlippableCardProps) {
  const [faceUp, setFaceUp] = useState(startFaceUp)
  return (
    <button
      type="button"
      aria-label={faceUp ? `Карта: ${title}` : "Карта рубашкой вверх"}
      onClick={() => setFaceUp((v) => !v)}
      className={cn("mp-card-flip-scene relative h-36 w-28", className)}
    >
      <div
        className={cn("mp-card-flip-inner relative size-full", faceUp && "mp-card-flip-inner--face")}
      >
        <div className="mp-card-face absolute inset-0">
          <CardBack className="size-full" />
        </div>
        <div
          className="mp-card-face absolute inset-0"
          style={{ transform: "rotateY(180deg)" }}
        >
          <CardFace tag={tag} title={title} className="size-full" />
        </div>
      </div>
    </button>
  )
}
