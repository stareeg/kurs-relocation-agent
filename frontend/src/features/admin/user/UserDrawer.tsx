import { Fragment, useMemo, useState } from "react"
import type { AdminUserRow } from "@/api/admin"
import { HelpTip } from "@/components/ui/help-tip"
import { SegmentedControl } from "@/components/ui/segmented-control"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useAdminUser, useSetAdminUserRole } from "@/features/admin/use-admin"
import {
  ADMIN_USER_TAB_LABELS,
  ADMIN_USER_TABS,
  type AdminUserTab,
} from "@/features/admin/admin-filters"
import { atHandle, relativeSeen, statusLabel } from "@/features/admin/admin-format"
import { DEFAULT_LOG_HOURS } from "@/features/admin/user/log-window"
import { AccountPowerButton } from "@/features/admin/user/AccountPowerButton"
import { AutomationTab } from "@/features/admin/user/AutomationTab"
import { LogsTab } from "@/features/admin/user/LogsTab"
import { ProfileTab } from "@/features/admin/user/ProfileTab"
import { SpendTab } from "@/features/admin/user/SpendTab"
import { SupportChat } from "@/features/admin/user/SupportChat"

/**
 * Карточка человека: вкладки сверху, чат поддержки закреплён снизу.
 */
export function UserDrawer({
  accountId,
  onClose,
  people,
  tab,
  onTabChange,
}: {
  accountId: number | null
  onClose: () => void
  people: readonly AdminUserRow[]
  tab: AdminUserTab
  onTabChange: (tab: AdminUserTab) => void
}) {
  const row = useMemo(
    () => people.find((person) => person.account_id === accountId),
    [people, accountId],
  )
  const detail = useAdminUser(accountId)
  const [hours, setHours] = useState(DEFAULT_LOG_HOURS)
  const user = detail.data?.user ?? row

  return (
    <Sheet open={accountId != null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="overflow-hidden">
        <SheetHeader className="shrink-0 p-5 pb-3">
          <div className="min-w-0 pr-8">
            <SheetTitle>{user ? atHandle(user.telegram_username) : "Человек"}</SheetTitle>
            <SheetDescription asChild>
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
                {user ? <PersonMeta user={user} /> : <span> </span>}
                {user ? <RoleToggle user={user} /> : null}
              </div>
            </SheetDescription>
          </div>
        </SheetHeader>
        {user ? (
          <div className="flex min-h-0 flex-1 flex-col">
            <Tabs
              value={tab}
              onValueChange={(value) => onTabChange(value as AdminUserTab)}
              className="flex min-h-0 flex-1 flex-col gap-0 px-5"
            >
              <div className="mb-3 flex shrink-0 items-center justify-between gap-2">
                <TabsList>
                  {ADMIN_USER_TABS.map((id) => (
                    <TabsTrigger key={id} value={id}>
                      {ADMIN_USER_TAB_LABELS[id]}
                    </TabsTrigger>
                  ))}
                </TabsList>
                <AccountPowerButton user={user} />
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto pb-4">
                <TabsContent value="profile">
                  <ProfileTab user={user} detail={detail.data} />
                </TabsContent>
                <TabsContent value="automation">
                  <AutomationTab user={user} />
                </TabsContent>
                <TabsContent value="spend">
                  <SpendTab accountId={user.account_id} />
                </TabsContent>
                <TabsContent value="logs">
                  <LogsTab
                    accountId={user.account_id}
                    detail={detail.data}
                    hours={hours}
                    onHoursChange={setHours}
                  />
                </TabsContent>
              </div>
            </Tabs>
            <SupportChat
              accountId={user.account_id}
              canMessageUser={Boolean(user.telegram_chat_id)}
              recentActions={detail.data?.recent_actions}
            />
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  )
}

function PersonMeta({ user }: { user: AdminUserRow }) {
  const seen = relativeSeen(user.last_seen_at)
  const seenMeta = seen === "не заходил" ? "не заходил" : `Был ${seen}`
  const parts = [statusLabel(user.status), seenMeta]
  return (
    <span className="inline-flex min-w-0 flex-wrap items-center gap-x-1.5">
      {parts.map((part, index) => (
        <Fragment key={part}>
          {index > 0 && <span className="text-slate-300">•</span>}
          <span>{part}</span>
        </Fragment>
      ))}
    </span>
  )
}

function RoleToggle({ user }: { user: AdminUserRow }) {
  const setRole = useSetAdminUserRole()
  return (
    <div className="flex shrink-0 items-center gap-1.5">
      <span className="text-xs text-slate-500">роль</span>
      <HelpTip id="admin.role-last-owner" showIcon />
      <SegmentedControl
        size="sm"
        ariaLabel="Роль"
        value={user.role === "owner" ? "owner" : "member"}
        onChange={(role) => {
          if (role !== user.role) setRole.mutate({ accountId: user.account_id, role })
        }}
        options={[
          { value: "member", label: "участник" },
          { value: "owner", label: "оператор" },
        ]}
      />
    </div>
  )
}
