import { useState } from "react"
import { ChevronDown, ChevronUp, Loader2, X } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import { useAuth } from "@/features/auth/auth-context"
import { useRevokeSession, useSessionsQuery } from "./use-devices"

// Блок «Устройства» (Part C): список активных сессий входа. Токен из бота больше не
// единственный на аккаунт — каждое устройство/браузер держит свою сессию, перевыпуск в боте
// не выкидывает остальные. Подпись строки — Telegram-аккаунт, выпустивший токен, и краткая
// подпись браузера из User-Agent (без выдумывания «iPhone 14 Pro»).

const dangerBtnClass =
  "border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100 hover:text-rose-800"

/** Краткая подпись браузера из User-Agent — «Chrome», «Firefox», «Safari», «Edge» или «Браузер». */
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

export function DevicesSection() {
  const { data: sessions, isLoading } = useSessionsQuery()
  const revoke = useRevokeSession()
  const { logout, logoutEverywhere } = useAuth()
  const [open, setOpen] = useState(false)
  const [loggingOutAll, setLoggingOutAll] = useState(false)
  const [revokingId, setRevokingId] = useState<number | null>(null)

  async function handleRevoke(id: number, isCurrent: boolean) {
    if (isCurrent) {
      // Отзыв текущей сессии — то же самое, что «Выйти»: полноценный клиентский сброс,
      // не просто пункт списка (иначе останется «залогинен», но без рабочей cookie).
      await logout()
      return
    }
    setRevokingId(id)
    try {
      await revoke.mutateAsync(id)
    } finally {
      setRevokingId(null)
    }
  }

  async function handleLogoutEverywhere() {
    setLoggingOutAll(true)
    try {
      await logoutEverywhere()
    } catch {
      toast.error("Не удалось выйти на всех устройствах")
    } finally {
      setLoggingOutAll(false)
    }
  }

  return (
    <section className="rounded-xl border bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-4 text-left"
      >
        <h2 className="text-sm font-semibold text-slate-900">Устройства</h2>
        {open ? (
          <ChevronUp className="size-4 shrink-0 text-slate-500" strokeWidth={2} />
        ) : (
          <ChevronDown className="size-4 shrink-0 text-slate-500" strokeWidth={2} />
        )}
      </button>

      {open && (
        <div className="space-y-3 border-t px-4 pb-4 pt-3">
          {sessions && sessions.length > 1 && (
            <div className="flex justify-end">
              <Button
                type="button"
                size="sm"
                variant="outline"
                className={cn("shrink-0", dangerBtnClass)}
                disabled={loggingOutAll}
                onClick={() => void handleLogoutEverywhere()}
              >
                {loggingOutAll ? <Loader2 className="size-4 animate-spin" strokeWidth={2} /> : null}
                Выйти на всех устройствах
              </Button>
            </div>
          )}

          {isLoading && <p className="text-sm text-slate-500">Загрузка…</p>}

          {!isLoading && sessions && sessions.length === 0 && (
            <p className="text-sm text-slate-500">Нет активных сессий.</p>
          )}

          {!isLoading && sessions && sessions.length > 0 && (
            <ul className="divide-y divide-slate-100">
              {sessions.map((session) => (
                <li key={session.id} className="flex items-center justify-between gap-3 py-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm text-slate-800">
                        {formatDateTime(session.issued_at)}
                      </span>
                      {session.is_current && (
                        <Badge
                          variant="outline"
                          className="border-emerald-200 bg-emerald-50/50 text-emerald-700"
                        >
                          Это устройство
                        </Badge>
                      )}
                    </div>
                    <p className="mt-0.5 truncate text-xs text-slate-500">
                      {[
                        session.telegram_username && `Telegram — @${session.telegram_username}`,
                        `Браузер — ${browserLabel(session.login_user_agent)}`,
                      ]
                        .filter(Boolean)
                        .join(" · ") || "—"}
                    </p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className={cn("shrink-0", dangerBtnClass)}
                    disabled={revokingId === session.id}
                    onClick={() => void handleRevoke(session.id, session.is_current)}
                  >
                    {revokingId === session.id ? (
                      <Loader2 className="size-4 animate-spin" strokeWidth={2} />
                    ) : (
                      <X className="size-4" strokeWidth={2} />
                    )}
                    Завершить
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}
