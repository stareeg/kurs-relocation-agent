import { useState } from "react"
import { ChevronDown, KeyRound, Loader2, X } from "lucide-react"
import type { AdminDeviceSession, AdminUserDetail, AdminUserRow } from "@/api/admin"
import { Button } from "@/components/ui/button"
import { HelpTip } from "@/components/ui/help-tip"
import { SectionTitle } from "@/components/ui/section-title"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { formatMoment } from "@/features/admin/admin-format"
import { formatDateTime } from "@/lib/format"
import {
  useRevokeAdminKey,
  useRevokeAdminSessions,
  useRevokeAdminUserSession,
} from "@/features/admin/use-admin"
import { KeyIssueForm } from "@/features/admin/components/KeyIssueForm"
import { KeyOriginLabel } from "@/features/admin/components/KeyOriginCell"
import { cn } from "@/lib/utils"

/**
 * Ключ и сессии. Отключение аккаунта — в шапке вкладок дровера.
 */
export function PersonOps({
  user,
  detail,
}: {
  user: AdminUserRow
  detail: AdminUserDetail | undefined
}) {
  const revokeAll = useRevokeAdminSessions()
  const revokeOne = useRevokeAdminUserSession()
  const revokeKey = useRevokeAdminKey()
  const sessions = detail?.session_list ?? []
  const [sessionsOpen, setSessionsOpen] = useState(false)

  const [confirmKeyOff, setConfirmKeyOff] = useState(false)
  const [confirmSessions, setConfirmSessions] = useState(false)

  return (
    <div className="space-y-5">
      <section id="admin-person-key" className="scroll-mt-4 rounded-lg border border-slate-200 p-3">
        <div className="mb-2 flex items-baseline justify-between gap-3">
          <div className="flex min-w-0 items-center gap-1.5">
            <KeyRound className="size-3.5 text-slate-500" strokeWidth={2} />
            <SectionTitle>Ключ OpenRouter</SectionTitle>
            <HelpTip id="admin.key-origin" showIcon />
          </div>
          <span className="shrink-0 text-xs tabular-nums text-slate-400">
            {user.key_updated_at ? formatMoment(user.key_updated_at) : "ещё не меняли"}
          </span>
        </div>
        <div className="mb-2">
          <KeyOriginLabel user={user} />
        </div>
        <KeyIssueForm
          accountId={user.account_id}
          submitLabel={user.key_origin ? "Перевыпустить" : "Выдать"}
          hasStoredKey={Boolean(user.key_origin)}
          existingOrigin={
            user.key_origin === "self" || user.key_origin === "admin" ? user.key_origin : null
          }
          extra={
            user.key_origin ? (
              <Button
                size="sm"
                variant="destructive"
                disabled={revokeKey.isPending}
                onClick={() => setConfirmKeyOff(true)}
              >
                Отозвать ключ
              </Button>
            ) : null
          }
        />
      </section>

      <section className="scroll-mt-4 rounded-lg border border-slate-200 p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-1.5">
            <button
              type="button"
              className="flex min-w-0 items-center gap-1.5 text-left"
              aria-expanded={sessionsOpen}
              onClick={() => setSessionsOpen((value) => !value)}
            >
              <SectionTitle>Сессии</SectionTitle>
              <span className="text-xs tabular-nums text-slate-400">{sessions.length}</span>
              <ChevronDown
                className={cn(
                  "size-3.5 text-slate-400 transition-transform",
                  sessionsOpen && "rotate-180",
                )}
                strokeWidth={2}
              />
            </button>
            <HelpTip id="admin.revoke-sessions" showIcon />
          </div>
          {sessionsOpen && sessions.length > 1 ? (
            <Button
              size="sm"
              variant="destructive"
              onClick={() => setConfirmSessions(true)}
              disabled={revokeAll.isPending}
            >
              Завершить все
            </Button>
          ) : null}
        </div>
        {sessionsOpen ? (
          <>
            <p className="mb-2 mt-2 text-xs text-slate-500">
              Telegram: {user.telegram_chat_id ? "привязан" : "нет чата"}
            </p>
            {sessions.length === 0 ? (
              <p className="text-sm text-slate-400">Нет активных сессий.</p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {sessions.map((session) => (
                  <SessionRow
                    key={session.id}
                    session={session}
                    busy={revokeOne.isPending}
                    onRevoke={() =>
                      revokeOne.mutate({ accountId: user.account_id, sessionId: session.id })
                    }
                  />
                ))}
              </ul>
            )}
          </>
        ) : null}
        {user.status !== "active" && user.disabled_reason ? (
          <p className="mt-3 text-xs text-slate-500">Причина отключения: {user.disabled_reason}</p>
        ) : null}
      </section>

      <ConfirmDialog
        open={confirmSessions}
        onOpenChange={setConfirmSessions}
        title="Завершить все сессии?"
        description="Человека выкинет со всех устройств. Войти снова можно только новым токеном из бота."
        confirmLabel="Завершить"
        onConfirm={() => {
          revokeAll.mutate(user.account_id)
          setConfirmSessions(false)
        }}
      />
      <ConfirmDialog
        open={confirmKeyOff}
        onOpenChange={setConfirmKeyOff}
        title="Отозвать ключ OpenRouter?"
        description="LLM-функции у человека перестанут работать. Сам ключ погасите в кабинете OpenRouter."
        confirmLabel="Отозвать"
        onConfirm={() => {
          revokeKey.mutate(user.account_id)
          setConfirmKeyOff(false)
        }}
      />
    </div>
  )
}

function SessionRow({
  session,
  busy,
  onRevoke,
}: {
  session: AdminDeviceSession
  busy: boolean
  onRevoke: () => void
}) {
  return (
    <li className="flex items-center justify-between gap-3 py-2">
      <div className="min-w-0">
        <p className="text-sm text-slate-800">
          {session.issued_at ? formatDateTime(session.issued_at) : "сессия"}
        </p>
        <p className="mt-0.5 truncate font-mono text-xs text-slate-500">
          {[session.login_ip || "IP неизвестен", browserLabel(session.login_user_agent)]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>
      <Button
        type="button"
        size="sm"
        variant="outline"
        className={cn(
          "shrink-0 border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100 hover:text-rose-800",
        )}
        disabled={busy}
        onClick={onRevoke}
      >
        {busy ? <Loader2 className="size-4 animate-spin" strokeWidth={2} /> : <X className="size-4" strokeWidth={2} />}
        Завершить
      </Button>
    </li>
  )
}

function browserLabel(userAgent: string | null | undefined): string {
  if (!userAgent) return "Браузер"
  const ua = userAgent.toLowerCase()
  if (ua.includes("edg/")) return "Edge"
  if (ua.includes("opr/") || ua.includes("opera")) return "Opera"
  if (ua.includes("firefox/")) return "Firefox"
  if (ua.includes("chrome/")) return "Chrome"
  if (ua.includes("safari/")) return "Safari"
  return "Браузер"
}
