import { useEffect, useRef, useState } from "react"
import type { AdminUserRow } from "@/api/admin"
import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { useAdminUser } from "@/features/admin/use-admin"
import { SupportChat } from "@/features/admin/user/SupportChat"

/**
 * Быстрый чат из строки людей: мини-лента рядом с кнопкой (как в дровере).
 */
export function PersonRowActions({ user }: { user: AdminUserRow }) {
  const [open, setOpen] = useState(false)
  const closeTimer = useRef<number | null>(null)
  const detail = useAdminUser(open ? user.account_id : null)

  useEffect(() => {
    return () => {
      if (closeTimer.current != null) window.clearTimeout(closeTimer.current)
    }
  }, [])

  const cancelClose = () => {
    if (closeTimer.current != null) {
      window.clearTimeout(closeTimer.current)
      closeTimer.current = null
    }
  }

  const scheduleClose = () => {
    cancelClose()
    closeTimer.current = window.setTimeout(() => setOpen(false), 180)
  }

  return (
    <div
      className="flex items-center justify-end"
      onMouseEnter={() => {
        if (!user.telegram_chat_id) return
        cancelClose()
        setOpen(true)
      }}
      onMouseLeave={scheduleClose}
    >
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            size="sm"
            variant="ghost"
            disabled={!user.telegram_chat_id}
            onClick={(event) => {
              event.stopPropagation()
              if (!user.telegram_chat_id) return
              cancelClose()
              setOpen((value) => !value)
            }}
          >
            Чат
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="end"
          side="left"
          sideOffset={8}
          className="w-auto border-slate-200 p-0 shadow-xl"
          onOpenAutoFocus={(event) => event.preventDefault()}
          onMouseEnter={cancelClose}
          onMouseLeave={scheduleClose}
          onClick={(event) => event.stopPropagation()}
        >
          <SupportChat
            accountId={user.account_id}
            canMessageUser={Boolean(user.telegram_chat_id)}
            recentActions={detail.data?.recent_actions}
            compact
          />
        </PopoverContent>
      </Popover>
    </div>
  )
}
