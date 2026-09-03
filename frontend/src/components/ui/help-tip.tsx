import * as React from "react"
import { Info } from "lucide-react"
import { useInRouterContext, useLocation } from "react-router-dom"

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { getHelpText, type HelpTextId } from "@/lib/help-texts"
import { HELP_TIP_COOLDOWN_MS, markTipShown, wasTipShownRecently } from "@/lib/tip-memory"
import { cn } from "@/lib/utils"

const DELAY_MS = 280
/** Даже при удержании курсора тултип не должен вечно перекрывать соседние кнопки. */
const AUTO_HIDE_MS = 3500

type HelpTipProps = {
  /** Ключ из `HELP_TEXTS`. Не нужен, если передан свободный `text`. */
  id?: HelpTextId
  /** Свободный текст подсказки (динамические причины LLM и т.п.). */
  text?: string
  /**
   * Якорь: существующий контрол/подпись. Без children подсказка не рисуется —
   * голые Info у каждой кнопки убраны; помощь — «Что делать?» и редкий `showIcon`.
   */
  children?: React.ReactElement
  /** Явная Info-иконка (админка / редкие опасные действия). По умолчанию выкл. */
  showIcon?: boolean
  side?: React.ComponentProps<typeof TooltipContent>["side"]
  align?: React.ComponentProps<typeof TooltipContent>["align"]
  className?: string
  contentClassName?: string
}

function tipMemoryKey(id: HelpTextId | undefined, text: string): string {
  if (id) return `help.${id}`
  // Свободный текст без id — стабильный ключ по содержимому, чтобы кулдаун работал.
  let h = 0
  for (let i = 0; i < text.length; i += 1) h = (h * 31 + text.charCodeAt(i)) | 0
  return `help.free.${h}`
}

/**
 * Тихий hover-tooltip на важном контроле.
 * Не режим «подсказки», не пунктир, не sticky-клик, не точка-маркер.
 * Icon-only без `showIcon` → null (не засоряем UI).
 * Контекстная помощь — в «Что делать?»; здесь только короткие пояснения контролов.
 *
 * Механика «по-человечески»: после показа тот же ключ молчит ~12 минут —
 * случайный повторный наезд курсора не всплывает тем же текстом снова.
 * Явный клик по Info (`showIcon`) всегда открывает.
 */
function HelpTip(props: HelpTipProps) {
  const inRouter = useInRouterContext()
  if (!inRouter) return <HelpTipView {...props} pathname="" />
  return <HelpTipInRouter {...props} />
}

function HelpTipInRouter(props: HelpTipProps) {
  const pathname = useLocation().pathname
  return <HelpTipView {...props} pathname={pathname} />
}

function HelpTipView({
  id,
  text: textProp,
  children,
  showIcon = false,
  side = "top",
  align,
  className,
  contentClassName,
  pathname,
}: HelpTipProps & { pathname: string }) {
  const text = (textProp?.trim() || (id ? getHelpText(id) : "")).trim()
  const memoryKey = tipMemoryKey(id, text)
  const resolvedAlign = align ?? (side === "right" ? "center" : "start")
  const sideOffset = side === "right" ? 14 : 8
  const [open, setOpen] = React.useState(false)
  const openRef = React.useRef(false)

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- sync к смене маршрута
    setOpen(false)
    openRef.current = false
  }, [pathname])

  React.useEffect(() => {
    if (!open) return
    markTipShown(memoryKey)
    const t = window.setTimeout(() => {
      setOpen(false)
      openRef.current = false
    }, AUTO_HIDE_MS)
    return () => window.clearTimeout(t)
  }, [open, memoryKey])

  const onOpenChange = React.useCallback(
    (next: boolean) => {
      if (next) {
        // Повторный hover сразу после показа — не открываем (назойливо).
        // showIcon: пользователь кликнул Info намеренно — пропускаем кулдаун.
        if (!showIcon && wasTipShownRecently(memoryKey, HELP_TIP_COOLDOWN_MS)) {
          return
        }
      }
      openRef.current = next
      setOpen(next)
    },
    [memoryKey, showIcon],
  )

  if (!text) return children ?? null
  if (!children && !showIcon) return null

  const trigger = children ? (
    children
  ) : (
    <button
      type="button"
      className={cn(
        "inline-flex size-4 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors",
        "hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
      aria-label="Подсказка"
    >
      <Info className="size-3.5" strokeWidth={1.5} aria-hidden />
    </button>
  )

  return (
    <TooltipProvider delayDuration={DELAY_MS} skipDelayDuration={0}>
      <Tooltip open={open} onOpenChange={onOpenChange} disableHoverableContent>
        <TooltipTrigger asChild>{trigger}</TooltipTrigger>
        <TooltipContent
          variant="default"
          side={side}
          align={resolvedAlign}
          sideOffset={sideOffset}
          collisionPadding={12}
          className={contentClassName}
        >
          {text}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

export { HelpTip }
