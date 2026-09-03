import { useState } from "react"
import type { AdminUserRow } from "@/api/admin"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { useDisableAdminUser, useEnableAdminUser } from "@/features/admin/use-admin"

/**
 * Отключить / Включить — справа от вкладок карточки человека.
 */
export function AccountPowerButton({ user }: { user: AdminUserRow }) {
  const disable = useDisableAdminUser()
  const enable = useEnableAdminUser()
  const [confirmOff, setConfirmOff] = useState(false)
  const isOwner = user.role === "owner"

  if (user.status === "active" && isOwner) return null

  if (user.status !== "active") {
    return (
      <Button
        size="sm"
        variant="outline"
        className="shrink-0"
        onClick={() => enable.mutate(user.account_id)}
        disabled={enable.isPending}
      >
        Включить
      </Button>
    )
  }

  return (
    <>
      <Button
        size="sm"
        variant="destructive"
        className="shrink-0"
        onClick={() => setConfirmOff(true)}
      >
        Отключить
      </Button>
      <ConfirmDialog
        open={confirmOff}
        onOpenChange={setConfirmOff}
        title="Отключить?"
        description="Сессии сгорят, войти снова можно только новым токеном из бота."
        confirmLabel="Отключить"
        onConfirm={() => {
          disable.mutate({ accountId: user.account_id, reason: "" })
          setConfirmOff(false)
        }}
      />
    </>
  )
}
