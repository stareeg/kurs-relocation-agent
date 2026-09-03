import * as React from "react"
import { Tooltip as TooltipPrimitive } from "radix-ui"

import { cn } from "@/lib/utils"

const DEFAULT_AUTO_HIDE_MS = 5000

function TooltipProvider({
  delayDuration = 300,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Provider>) {
  return (
    <TooltipPrimitive.Provider
      data-slot="tooltip-provider"
      delayDuration={delayDuration}
      {...props}
    />
  )
}

function Tooltip(props: React.ComponentProps<typeof TooltipPrimitive.Root>) {
  return <TooltipPrimitive.Root data-slot="tooltip" {...props} />
}

function TooltipTrigger(props: React.ComponentProps<typeof TooltipPrimitive.Trigger>) {
  return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />
}

function TooltipContent({
  className,
  sideOffset,
  collisionPadding,
  variant = "default",
  children,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Content> & {
  /** `help` - крупная карточка подсказки (шаг 38); `dark` - белый текст на тёмном фоне
   *  (вместо нативного title браузера) для коротких hover-подсказок над словом/иконкой;
   *  `default` - системный тултип. */
  variant?: "default" | "help" | "dark"
}) {
  const isHelp = variant === "help"
  const isDark = variant === "dark"
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        data-slot="tooltip-content"
        data-variant={variant}
        sideOffset={sideOffset ?? (isHelp ? 10 : 6)}
        collisionPadding={collisionPadding ?? (isHelp ? 16 : 8)}
        className={cn(
          isHelp &&
            "z-50 max-w-md rounded-xl border border-sky-200/90 bg-card px-4 py-3 text-base leading-relaxed text-foreground shadow-lg outline-none pointer-events-none",
          isDark &&
            "z-50 max-w-xs rounded-lg bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-white shadow-lg outline-none pointer-events-none",
          !isHelp &&
            !isDark &&
            "z-50 max-w-xs rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground shadow-md outline-none pointer-events-none",
          "animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95",
          className,
        )}
        {...props}
      >
        {children}
        <TooltipPrimitive.Arrow
          className={
            isHelp
              ? "fill-card [&>polygon]:stroke-sky-200 [&>polygon]:stroke-[1]"
              : isDark
                ? "fill-slate-900"
                : "fill-card [&>polygon]:stroke-border [&>polygon]:stroke-[1]"
          }
        />
      </TooltipPrimitive.Content>
    </TooltipPrimitive.Portal>
  )
}

type OnboardingHintProps = {
  /** Родитель: подсказка ещё не отклонена (`shouldShow(id)`). */
  open: boolean
  /**
   * Вызывается при первом показе и при явном закрытии — родитель пишет в память,
   * чтобы подсказка не вернулась при следующем заходе на экран.
   */
  onDismiss: () => void
  content: React.ReactNode
  side?: React.ComponentProps<typeof TooltipPrimitive.Content>["side"]
  align?: React.ComponentProps<typeof TooltipPrimitive.Content>["align"]
  autoHideMs?: number
  className?: string
  children: React.ReactElement
}

/**
 * Одноразовая обучающая подсказка: не hover, а «показать один раз».
 * Появляется при первом попадании якоря в viewport или при фокусе; исчезает по таймеру
 * или при любом взаимодействии. Как только показалась — сразу помечается увиденной
 * (уход со страницы / ремаунт не вернёт её снова).
 */
function OnboardingHint({
  open,
  onDismiss,
  content,
  side = "bottom",
  align = "center",
  autoHideMs = DEFAULT_AUTO_HIDE_MS,
  className,
  children,
}: OnboardingHintProps) {
  const triggerRef = React.useRef<HTMLSpanElement>(null)
  const dismissedRef = React.useRef(false)
  const seenPersistedRef = React.useRef(false)
  const revealedRef = React.useRef(false)
  const onDismissRef = React.useRef(onDismiss)
  const timerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null)
  const [revealed, setRevealed] = React.useState(false)
  const [visible, setVisible] = React.useState(false)

  React.useEffect(() => {
    onDismissRef.current = onDismiss
  }, [onDismiss])

  const clearTimer = React.useCallback(() => {
    if (timerRef.current != null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const persistSeen = React.useCallback(() => {
    if (seenPersistedRef.current) return
    seenPersistedRef.current = true
    onDismissRef.current()
  }, [])

  const dismiss = React.useCallback(() => {
    if (dismissedRef.current) return
    dismissedRef.current = true
    clearTimer()
    setVisible(false)
    persistSeen()
  }, [clearTimer, persistSeen])

  // Родитель закрыл open до показа — сброс. После reveal open=false (из-за persistSeen)
  // не должен убивать текущий показ: таймер / interact сами закроют.
  React.useEffect(() => {
    if (open || revealedRef.current || dismissedRef.current) return
    setVisible(false)
    clearTimer()
  }, [open, clearTimer])

  React.useEffect(() => {
    if (!open || revealedRef.current || dismissedRef.current) return

    const el = triggerRef.current
    if (!el) return

    let armed = false

    const reveal = () => {
      if (armed || dismissedRef.current) return
      armed = true
      revealedRef.current = true
      setRevealed(true)
      setVisible(true)
      // Сразу в память: уход со страницы до таймера больше не вернёт ту же подсказку.
      persistSeen()
      timerRef.current = setTimeout(() => {
        dismiss()
      }, autoHideMs)
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          reveal()
          observer.disconnect()
        }
      },
      { threshold: 0.25 },
    )
    observer.observe(el)

    const onFocusIn = (event: FocusEvent) => {
      if (el.contains(event.target as Node)) reveal()
    }
    el.addEventListener("focusin", onFocusIn)

    return () => {
      observer.disconnect()
      el.removeEventListener("focusin", onFocusIn)
    }
  }, [open, autoHideMs, dismiss, persistSeen])

  React.useEffect(() => {
    if (!visible) return

    let active = false
    const armTimer = window.setTimeout(() => {
      active = true
    }, 120)

    const onInteract = () => {
      if (!active) return
      dismiss()
    }

    window.addEventListener("pointerdown", onInteract, { capture: true })
    window.addEventListener("keydown", onInteract, { capture: true })
    window.addEventListener("scroll", onInteract, { capture: true })
    window.addEventListener("touchstart", onInteract, { capture: true })

    return () => {
      window.clearTimeout(armTimer)
      window.removeEventListener("pointerdown", onInteract, { capture: true })
      window.removeEventListener("keydown", onInteract, { capture: true })
      window.removeEventListener("scroll", onInteract, { capture: true })
      window.removeEventListener("touchstart", onInteract, { capture: true })
    }
  }, [visible, dismiss])

  // Unmount insurance: если успели показать — в памяти уже должно быть, но на всякий.
  React.useEffect(() => {
    return () => {
      if (revealedRef.current) persistSeen()
      clearTimer()
    }
  }, [persistSeen, clearTimer])

  if (!open && !revealed) return children

  return (
    <TooltipProvider delayDuration={0} skipDelayDuration={0}>
      <Tooltip
        open={visible}
        onOpenChange={() => {
          /* Управляем видимостью сами — не реагируем на hover Radix. */
        }}
        disableHoverableContent
      >
        <TooltipTrigger asChild>
          <span ref={triggerRef} className="contents">
            {children}
          </span>
        </TooltipTrigger>
        <TooltipContent
          side={side}
          align={align}
          className={cn("border-border bg-muted text-foreground shadow-lg", className)}
        >
          {content}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

export {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
  OnboardingHint,
  DEFAULT_AUTO_HIDE_MS,
}
