import { Loader2, Send } from "lucide-react"
import type { TelegramPushKind } from "@/api/telegram"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { usePushToTelegram, useTelegramStatus } from "./use-settings"

type Props = {
  kind: TelegramPushKind
  vacancyId: string
  className?: string
  size?: "default" | "sm" | "lg" | "icon"
}

/**
 * Кнопка «В Telegram» (TB-6.3): disabled + native title, пока `linked=false`.
 * Toast «Отправлено в Telegram» — в `usePushToTelegram`.
 */
export function TelegramPushButton({ kind, vacancyId, className, size = "sm" }: Props) {
  const { data: status, isLoading: statusLoading } = useTelegramStatus()
  const push = usePushToTelegram()
  const linked = Boolean(status?.linked)
  const blocked = !linked || statusLoading || !vacancyId.trim()

  return (
    <Button
      type="button"
      size={size}
      variant="outline"
      className={cn("gap-1.5", className)}
      disabled={blocked || push.isPending}
      title={linked ? undefined : "Сначала войдите токеном из бота (Аккаунт → Вход)"}
      aria-label="Отправить в Telegram"
      onClick={() => {
        if (blocked) return
        push.mutate({ kind, vacancy_id: vacancyId.trim() })
      }}
    >
      {push.isPending ? (
        <Loader2 className="size-4 animate-spin" strokeWidth={2} />
      ) : (
        <Send className="size-4" strokeWidth={2} />
      )}
      В Telegram
    </Button>
  )
}
