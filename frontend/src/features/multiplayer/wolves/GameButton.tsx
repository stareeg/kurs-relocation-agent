import { cn } from "@/lib/utils"

type GameButtonVariant = "standard" | "primary" | "accept" | "reject" | "glass"

type GameButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: GameButtonVariant
  /** Пульсация «нажми сейчас» (SIGame demoSlowBlink). */
  pulse?: boolean
}

/** Игровая кнопка в стиле SIGame — градиент, text-shadow, белый flash на :active. */
export function GameButton({
  variant = "standard",
  pulse = false,
  className,
  children,
  ...props
}: GameButtonProps) {
  const variantClass: Record<GameButtonVariant, string> = {
    standard: "mp-btn-standard",
    primary: "mp-btn-primary",
    accept: "mp-btn-accept",
    reject: "mp-btn-reject",
    glass: "mp-btn-glass",
  }

  return (
    <button
      type="button"
      className={cn(
        "mp-btn",
        variantClass[variant],
        pulse && "mp-demo-blink",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}
