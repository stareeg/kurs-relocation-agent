import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { Check, Copy, ExternalLink, Loader2, Send } from "lucide-react"
import { toast } from "sonner"
import { useQueryClient } from "@tanstack/react-query"
import type { AuthStatus } from "@/api/auth"
import { ApiError } from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { HelpTip } from "@/components/ui/help-tip"
import { Input } from "@/components/ui/input"
import { copyText } from "@/lib/clipboard"
import { cn } from "@/lib/utils"
import { looksLikeBotAuthToken } from "@/lib/web-auth-token"
import { useAuth } from "@/features/auth/auth-context"
import { AUTH_STATUS_KEY } from "@/features/auth/use-auth-status"
import { LAST_TOKEN_STORAGE_KEY, readLastAuthToken, writeLastAuthToken } from "./last-auth-token"

// AUTH-1: вход по токену из официального Telegram-бота — первая карточка «Параметров».
// Пользователи не создают своих ботов: ссылка t.me/… ведёт на нашего бота всегда
// (бэкенд отдаёт username из кэша getMe или из TELEGRAM_BOT_USERNAME).
// Токен нужного вида (~32 символа urlsafe) логинится сам при вставке — как ключ OpenRouter.

const dangerBtnClass =
  "border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100 hover:text-rose-800"

function StepMarker({ n }: { n: number }) {
  return (
    <span className="grid size-5 shrink-0 translate-y-px place-items-center rounded-full bg-slate-100 text-[11px] font-semibold text-slate-600">
      {n}
    </span>
  )
}

export function AuthTokenSection({ status }: { status: AuthStatus }) {
  const { login, logout } = useAuth()
  const qc = useQueryClient()
  const [token, setToken] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const [lastToken, setLastToken] = useState<string | null>(readLastAuthToken)
  const [copied, setCopied] = useState(false)
  // Неудавшийся токен не пробуем повторно, пока пользователь его не поменял.
  const lastTried = useRef("")

  const active = status.authed && status.auth_token_configured
  const botName = status.bot_username ? `@${status.bot_username}` : null
  const botLink = status.bot_username ? `https://t.me/${status.bot_username}` : null
  const accountName = status.account_username ? `@${status.account_username}` : null

  const submitToken = useCallback(
    async (raw: string) => {
      const trimmed = raw.trim()
      if (!trimmed) return
      lastTried.current = trimmed
      setPending(true)
      setError(null)
      try {
        await login(trimmed)
        writeLastAuthToken(trimmed)
        setLastToken(trimmed)
        setToken("")
        void qc.invalidateQueries({ queryKey: AUTH_STATUS_KEY })
        toast.success("Вход выполнен")
      } catch (err) {
        setError(
          err instanceof ApiError && err.status === 401
            ? err.message
            : "Не удалось войти — проверьте, что сервер запущен",
        )
      } finally {
        setPending(false)
      }
    },
    [login, qc],
  )

  // Автовход при вставке токена нужного вида — кнопку жать не обязательно.
  useEffect(() => {
    const trimmed = token.trim()
    if (!looksLikeBotAuthToken(trimmed)) return
    if (trimmed === lastTried.current) return
    if (pending) return
    const timer = window.setTimeout(() => void submitToken(trimmed), 500)
    return () => window.clearTimeout(timer)
  }, [token, pending, submitToken])

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (pending) return
    lastTried.current = ""
    void submitToken(token)
  }

  async function handleLogout() {
    setLoggingOut(true)
    try {
      await logout()
      try {
        localStorage.removeItem(LAST_TOKEN_STORAGE_KEY)
      } catch {
        /* приватный режим/квота — не критично */
      }
      setLastToken(null)
      toast.success("Вы вышли")
    } catch {
      toast.error("Не удалось выйти")
    } finally {
      setLoggingOut(false)
    }
  }

  async function handleCopyToken() {
    if (!lastToken) return
    const ok = await copyText(lastToken)
    if (!ok) {
      toast.error("Не удалось скопировать")
      return
    }
    setCopied(true)
    toast.success("Токен скопирован — вставьте его в расширение")
    window.setTimeout(() => setCopied(false), 1800)
  }

  const badge = active ? (
    <Badge variant="outline" className="border-emerald-200 bg-emerald-50/50 text-emerald-700">
      <Check strokeWidth={2.5} />
      Вход активен
    </Badge>
  ) : (
    <Badge variant="outline" className="border-sky-200 bg-sky-50 text-sky-700">
      Ждёт токен
    </Badge>
  )

  return (
    <section
      className={cn(
        "rounded-xl border bg-white p-4 transition-shadow duration-300",
        !active && "border-sky-300 shadow-[0_0_0_3px_rgba(56,189,248,0.25)]",
      )}
    >
      <div className={cn("flex items-center justify-between gap-3", !active && "mb-3")}>
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="text-sm font-semibold text-slate-900">Токен авторизации</h2>
          {botLink && (
            <a
              href={botLink}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-sm font-medium text-sky-700 underline-offset-2 hover:underline"
            >
              Открыть бота
              <ExternalLink className="size-3.5" strokeWidth={2} />
            </a>
          )}
        </div>
        {badge}
      </div>

      {active && (
        <div className="motion-pop mt-4 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <span className="grid size-10 shrink-0 place-items-center rounded-full bg-emerald-50 ring-1 ring-emerald-200">
              <Check className="size-5 text-emerald-600" strokeWidth={2.5} />
            </span>
            <div className="min-w-0">
              <p className="text-sm font-medium text-slate-900">
                {accountName ? <>Вы вошли как {accountName}</> : "Вы вошли"}
              </p>
              <p className="mt-0.5 text-sm text-slate-500">
                Для нового устройства — новый токен в боте.
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {lastToken && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => void handleCopyToken()}
              >
                {copied ? (
                  <Check className="size-4 text-emerald-600" strokeWidth={2.5} />
                ) : (
                  <Copy className="size-4" strokeWidth={2} />
                )}
                {copied ? "Скопировано" : "Копировать токен"}
              </Button>
            )}
            <HelpTip id="settings.logout">
              <Button
                type="button"
                size="sm"
                variant="outline"
                className={dangerBtnClass}
                disabled={loggingOut}
                onClick={() => void handleLogout()}
              >
                {loggingOut ? <Loader2 className="size-4 animate-spin" strokeWidth={2} /> : null}
                Выйти
              </Button>
            </HelpTip>
          </div>
        </div>
      )}

      {!active && (
        <div className="space-y-4">
          <ol className="space-y-2.5 text-sm text-slate-600">
            <li className="flex items-start gap-2.5">
              <StepMarker n={1} />
              <span>
                Откройте бота{" "}
                {botLink ? (
                  <a
                    href={botLink}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 font-medium text-sky-700 underline-offset-2 hover:underline"
                  >
                    {botName}
                    <ExternalLink className="size-3.5" strokeWidth={2} />
                  </a>
                ) : (
                  <span>в Telegram</span>
                )}{" "}
                и нажмите <span className="font-mono text-slate-800">/start</span>
              </span>
            </li>
            <li className="flex items-start gap-2.5">
              <StepMarker n={2} />
              <span>
                Нажмите кнопку{" "}
                <strong className="font-medium text-slate-800">«Токен авторизации»</strong> — бот
                пришлёт токен
              </span>
            </li>
            <li className="flex items-start gap-2.5">
              <StepMarker n={3} />
              <span>Вставьте токен в поле ниже — вход выполнится сам</span>
            </li>
          </ol>

          {!status.bot_configured && (
            <p className="rounded-lg bg-amber-50/70 px-3 py-2 text-xs text-amber-800">
              На этом сервере бот не запущен (пустой TELEGRAM_BOT_TOKEN в .env установки) — кнопка в
              боте не ответит, пока установка не починена.
            </p>
          )}

          <form onSubmit={onSubmit} className="flex flex-col gap-3 sm:flex-row sm:items-start">
            {botLink && (
              <a
                href={botLink}
                target="_blank"
                rel="noopener noreferrer"
                className={cn(
                  "inline-flex h-9 shrink-0 items-center justify-center gap-2 rounded-md bg-primary px-3.5 text-sm font-medium text-primary-foreground",
                  "transition-colors hover:bg-primary/90",
                )}
              >
                <Send className="size-4" strokeWidth={2} />
                Открыть бота
              </a>
            )}
            <div className="min-w-0 flex-1 space-y-1.5">
              <Input
                type="password"
                autoComplete="off"
                placeholder="Токен из бота"
                aria-label="Токен из бота"
                value={token}
                onChange={(e) => {
                  setToken(e.target.value)
                  setError(null)
                }}
                className="border-sky-400 bg-sky-50/40 ring-2 ring-sky-300/80 ring-offset-2 placeholder:text-sky-600/50 focus-visible:ring-sky-400"
              />
              {pending && (
                <p className="inline-flex items-center gap-1.5 text-xs text-slate-500">
                  <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
                  Проверяю токен…
                </p>
              )}
              {!pending && error && <p className="text-xs text-amber-700">{error}</p>}
            </div>
            <Button type="submit" size="sm" className="h-9" disabled={pending || !token.trim()}>
              Войти
            </Button>
          </form>
        </div>
      )}
    </section>
  )
}
