import { cn } from "@/lib/utils"

type TableFeltProps = {
  children?: React.ReactNode
  className?: string
}

/** Сукно стола кандидатов (SI-style). */
export function TableFelt({ children, className }: TableFeltProps) {
  return (
    <div
      className={cn(
        "relative min-h-40 overflow-hidden rounded-lg border border-[color:var(--mp-felt-line)] bg-[color:var(--mp-felt)] p-4 shadow-inner",
        className,
      )}
      style={{
        backgroundImage: "url(/multiplayer/felt-noise.svg)",
        backgroundSize: "80px 80px",
      }}
    >
      {children}
    </div>
  )
}
