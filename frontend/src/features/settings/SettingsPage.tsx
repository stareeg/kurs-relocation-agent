import { useEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate } from "react-router-dom"
import {
  Check,
  ChevronDown,
  ChevronUp,
  KeyRound,
  Loader2,
  Settings,
} from "lucide-react"
import type { AppSettings } from "@/api/settings"
import type { AuthStatus } from "@/api/auth"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ErrorState } from "@/components/ui/empty-state"
import { HelpTip } from "@/components/ui/help-tip"
import { Input } from "@/components/ui/input"
import { SkeletonCard } from "@/components/ui/skeleton"
import { OnboardingHint } from "@/components/ui/tooltip"
import { looksLikeOpenRouterKey } from "@/lib/openrouter-key"
import { formatDateTime } from "@/lib/format"
import { ONBOARDING_HINT_IDS, useOnboardingHints } from "@/lib/use-onboarding-hints"
import { cn } from "@/lib/utils"
import { useAuth } from "@/features/auth/auth-context"
import { AUTH_STATUS_KEY, useAuthStatusQuery } from "@/features/auth/use-auth-status"
import { isGateOpen } from "@/features/auth/onboarding"
import type { TierTokenTotals } from "@/api/metrics"
import { AuthTokenSection } from "./AuthTokenSection"
import { DevicesSection } from "./DevicesSection"
import { ExtensionInstallSection } from "./ExtensionInstallSection"
import { FriendsCompactSection } from "./FriendsCompactSection"
import {
  useAppSettings,
  useRequestOpenRouterKey,
  useSaveOpenRouterKey,
  useTokenStats,
} from "./use-settings"
import { hasOpenRouterKey, openRouterKeyView } from "./openrouter-key-state"

const dangerBtnClass =
  "border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100 hover:text-rose-800"

function SettingsSection({
  title,
  hint,
  action,
  children,
  highlight,
  className,
}: {
  title: React.ReactNode
  hint?: string
  action?: React.ReactNode
  children?: React.ReactNode
  highlight?: boolean
  className?: string
}) {
  return (
    <section
      className={cn(
        "h-full rounded-xl border bg-white p-4 transition-shadow duration-300",
        highlight && "border-sky-300 shadow-[0_0_0_3px_rgba(56,189,248,0.25)]",
        className,
      )}
    >
      <div className={cn("flex items-center justify-between gap-3", children ? "mb-3" : "h-full")}>
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
          {hint && <span className="text-sm text-slate-500">{hint}</span>}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      {children}
    </section>
  )
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) {
    return `${(n / 1_000_000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}M`
  }
  if (n >= 10_000) {
    return `${Math.round(n / 1000).toLocaleString("ru-RU")}K`
  }
  return n.toLocaleString("ru-RU")
}

function tokenCell(v: number | undefined): string {
  return v == null ? "—" : formatTokens(v)
}

/** Блок «Статистика»: токены по тирам (базовые/продвинутые) — сегодня и за месяц, вход/выход. */
function UsageStats({
  todayBasic,
  todayAdvanced,
  monthBasic,
  monthAdvanced,
}: {
  todayBasic: TierTokenTotals | undefined
  todayAdvanced: TierTokenTotals | undefined
  monthBasic: TierTokenTotals | undefined
  monthAdvanced: TierTokenTotals | undefined
}) {
  const rows: Array<{
    label: string
    today: TierTokenTotals | undefined
    month: TierTokenTotals | undefined
  }> = [
    { label: "Базовые токены", today: todayBasic, month: monthBasic },
    { label: "Продвинутые токены", today: todayAdvanced, month: monthAdvanced },
  ]

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/50 px-4 py-3">
      <table className="w-full table-fixed border-collapse text-xs">
        <colgroup>
          <col className="w-[34%]" />
          <col className="w-[16.5%]" />
          <col className="w-[16.5%]" />
          <col className="w-[16.5%]" />
          <col className="w-[16.5%]" />
        </colgroup>
        <thead>
          <tr>
            <th
              rowSpan={2}
              className="pb-1.5 text-left align-bottom text-[11px] font-semibold uppercase tracking-wide text-slate-400"
            >
              Статистика
            </th>
            <th
              colSpan={2}
              className="pb-1 text-center text-[11px] font-semibold uppercase tracking-wide text-slate-400"
            >
              Сегодня
            </th>
            <th
              colSpan={2}
              className="border-l border-slate-200/70 pb-1 pl-3 text-center text-[11px] font-semibold uppercase tracking-wide text-slate-400"
            >
              За месяц
            </th>
          </tr>
          <tr>
            <th className="pb-1.5 text-right text-xs font-medium text-slate-400">Вход</th>
            <th className="pb-1.5 pr-1 text-right text-xs font-medium text-slate-400">Выход</th>
            <th className="border-l border-slate-200/70 pb-1.5 pl-3 text-right text-xs font-medium text-slate-400">
              Вход
            </th>
            <th className="pb-1.5 pr-1 text-right text-xs font-medium text-slate-400">Выход</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200/70">
          {rows.map(({ label, today, month }) => (
            <tr key={label}>
              <td className="py-1.5 pr-3 text-slate-500">{label}</td>
              <td className="py-1.5 text-right font-medium tabular-nums text-slate-800">
                {tokenCell(today?.tokens_in)}
              </td>
              <td className="py-1.5 pr-1 text-right font-medium tabular-nums text-slate-800">
                {tokenCell(today?.tokens_out)}
              </td>
              <td className="border-l border-slate-200/70 py-1.5 pl-3 text-right font-medium tabular-nums text-slate-800">
                {tokenCell(month?.tokens_in)}
              </td>
              <td className="py-1.5 pr-1 text-right font-medium tabular-nums text-slate-800">
                {tokenCell(month?.tokens_out)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SettingsForm({ initial }: { initial: AppSettings }) {
  const saveKey = useSaveOpenRouterKey()
  const requestKey = useRequestOpenRouterKey()
  const { shouldShow, dismissHint } = useOnboardingHints()
  const { data: authStatus } = useAuthStatusQuery()
  const qc = useQueryClient()

  const view = openRouterKeyView(initial)
  const hasKey = hasOpenRouterKey(view)
  const [openrouterKey, setOpenrouterKey] = useState("")
  const [showKeyHelp, setShowKeyHelp] = useState(!hasKey)
  // Ключ от администратора: поле «свой ключ» спрятано за раскрытием — по умолчанию человеку
  // делать здесь нечего, всё уже работает.
  const [showOwnKeyField, setShowOwnKeyField] = useState(false)
  const needsSetup = !hasKey
  const inputRef = useRef<HTMLInputElement>(null)
  const lastAutoSaved = useRef("")
  const { data: tokenStats } = useTokenStats(hasKey)

  useEffect(() => {
    if (needsSetup) {
      inputRef.current?.focus()
    }
  }, [needsSetup])

  // Ключ мог приехать не от нас, а от администратора (опрос в useAppSettings). Гейт разделов
  // читает свой `/auth/status` — без этой инвалидации бейдж уже зелёный, а меню ещё закрыто.
  useEffect(() => {
    if (hasKey && !authStatus?.openrouter_key_configured) {
      void qc.invalidateQueries({ queryKey: AUTH_STATUS_KEY })
    }
  }, [hasKey, authStatus?.openrouter_key_configured, qc])

  // Автосейв при вставке/вводе ключа корректного вида — без кнопки «Сохранить».
  // lastAutoSaved ставим только после успеха: иначе таймаут/обрыв блокирует повтор
  // (ключ в поле тот же, isPending уже false — эффект больше не стреляет).
  useEffect(() => {
    const trimmed = openrouterKey.trim()
    if (!looksLikeOpenRouterKey(trimmed)) return
    if (trimmed === lastAutoSaved.current) return
    if (saveKey.isPending) return

    const timer = window.setTimeout(() => {
      void saveKey
        .mutateAsync(trimmed)
        .then(() => {
          lastAutoSaved.current = trimmed
          setOpenrouterKey("")
          setShowOwnKeyField(false)
          dismissHint(ONBOARDING_HINT_IDS.settingsPasteKey)
        })
        .catch(() => {
          /* тост уже в useSaveOpenRouterKey; оставляем поле — можно повторить */
        })
    }, 500)
    return () => window.clearTimeout(timer)
  }, [openrouterKey, saveKey, dismissHint])

  async function saveOpenRouterKey() {
    const trimmed = openrouterKey.trim()
    await saveKey.mutateAsync(trimmed)
    lastAutoSaved.current = trimmed
    setOpenrouterKey("")
    setShowOwnKeyField(false)
    dismissHint(ONBOARDING_HINT_IDS.settingsPasteKey)
  }

  async function resetOpenRouterKey() {
    await saveKey.mutateAsync("")
    lastAutoSaved.current = ""
    setOpenrouterKey("")
    setShowKeyHelp(true)
  }

  const keyField = (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
      <div className="block min-w-0 flex-1 space-y-1.5">
        <div className="flex items-center gap-1.5">
          <HelpTip id="settings.openrouter-key">
            <span className="cursor-help text-xs font-medium text-slate-600">API-ключ</span>
          </HelpTip>
          {needsSetup && <span className="text-xs font-medium text-sky-700">← вставьте сюда</span>}
        </div>
        <Input
          ref={inputRef}
          type="password"
          autoComplete="new-password"
          placeholder="sk-or-v1-…"
          value={openrouterKey}
          onChange={(e) => setOpenrouterKey(e.target.value)}
          aria-label="API-ключ OpenRouter"
          className={cn(
            needsSetup &&
              "border-sky-400 bg-sky-50/40 ring-2 ring-sky-300/80 ring-offset-2 placeholder:text-sky-600/50 focus-visible:ring-sky-400",
            needsSetup && "animate-[pulse_2.4s_ease-in-out_infinite]",
          )}
        />
        {openrouterKey.trim() && !looksLikeOpenRouterKey(openrouterKey) && (
          <p className="text-xs text-amber-700">
            Ключ должен начинаться с <span className="font-mono">sk-or-</span> (как на
            openrouter.ai).
          </p>
        )}
        {looksLikeOpenRouterKey(openrouterKey) && (
          <p className="text-xs text-emerald-700">
            {saveKey.isPending ? "Сохраняю…" : "Ключ похож на настоящий — сохраняю автоматически"}
          </p>
        )}
      </div>
      <div className="flex shrink-0 gap-2">
        <Button
          type="button"
          size="sm"
          disabled={!openrouterKey.trim() || saveKey.isPending}
          onClick={() => void saveOpenRouterKey()}
        >
          {saveKey.isPending ? <Loader2 className="size-4 animate-spin" strokeWidth={2} /> : null}
          Сохранить ключ
        </Button>
      </div>
    </div>
  )

  const keyHelp = (
    <div className={cn(needsSetup ? "mt-4 border-t border-slate-100 pt-4" : "mt-1")}>
      <button
        type="button"
        onClick={() => setShowKeyHelp((v) => !v)}
        className="inline-flex items-center gap-1 text-sm text-slate-500 transition-colors hover:text-slate-700"
      >
        {showKeyHelp ? (
          <ChevronUp className="size-3.5" strokeWidth={2} />
        ) : (
          <ChevronDown className="size-3.5" strokeWidth={2} />
        )}
        Как получить ключ самостоятельно
      </button>
      {showKeyHelp && (
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-slate-500">
          <li>
            Откройте{" "}
            <a
              href="https://openrouter.ai/keys"
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2 hover:text-slate-700"
            >
              openrouter.ai → Keys
            </a>{" "}
            → Create Key.
          </li>
          <li>
            Скопируйте ключ (начинается на <span className="font-mono">sk-or-</span>).
          </li>
          <li>Вставьте в поле выше — сохранится автоматически.</li>
          <li>Бесплатных моделей нет — платится по факту; лимит трат — на сайте OpenRouter.</li>
        </ol>
      )}
    </div>
  )

  const requestBlock = (
    <div className="rounded-xl border border-slate-200 bg-slate-50/60 px-4 py-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium text-slate-900">
            {view === "requested" ? "Заявка отправлена" : "Попросить ключ у администратора"}
          </p>
          <p className="mt-0.5 text-sm text-slate-500">
            {view === "requested"
              ? "Когда администратор выдаст ключ, разделы откроются сами — перезагружать страницу не нужно."
              : view === "rejected"
                ? "По прошлой заявке отказали. Можно попросить снова или вставить свой ключ ниже."
                : "Администратор выдаст ключ со своего счёта OpenRouter. Свой ключ можно вставить ниже в любой момент."}
          </p>
        </div>
        <Button
          type="button"
          size="sm"
          className="shrink-0"
          disabled={view === "requested" || requestKey.isPending}
          onClick={() => requestKey.mutate()}
        >
          {requestKey.isPending ? (
            <Loader2 className="size-4 animate-spin" strokeWidth={2} />
          ) : (
            <KeyRound className="size-4" strokeWidth={2} />
          )}
          {view === "requested" ? "Ждём ответа" : "Запросить ключ"}
        </Button>
      </div>
    </div>
  )

  const badgeLabel =
    view === "managed"
      ? "Ключ от администратора"
      : view === "own"
        ? "Ключ настроен"
        : view === "requested"
          ? "Заявка в работе"
          : "Ключ не задан"

  return (
    <div className="space-y-4">
      {needsSetup && (
        <div className="rounded-xl border border-sky-200 bg-sky-50/60 px-4 py-3 text-sm text-sky-900">
          Остался шаг: получите ключ OpenRouter — запросите его у администратора или вставьте свой.
          Дальше система поведёт сама (Расширение → Резюме).
        </div>
      )}

      {!needsSetup && shouldShow(ONBOARDING_HINT_IDS.settingsAfterKeyResume) && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 px-4 py-3 text-sm text-emerald-900">
          Ключ на месте. Следующий шаг —{" "}
          <Link
            to="/resume"
            className="font-medium underline underline-offset-2"
            onClick={() => dismissHint(ONBOARDING_HINT_IDS.settingsAfterKeyResume)}
          >
            заполнить Резюме
          </Link>{" "}
          (критерии поиска и опыт).
        </div>
      )}

      <SettingsSection
        title="OpenRouter"
        highlight={needsSetup}
        action={
          <Badge
            variant="outline"
            className={cn(
              hasKey
                ? "border-emerald-200 bg-emerald-50/50 text-emerald-700"
                : "border-sky-200 bg-sky-50 text-sky-700",
            )}
          >
            {hasKey ? <Check strokeWidth={2.5} /> : null}
            {badgeLabel}
          </Badge>
        }
      >
        {hasKey ? (
          <div className="motion-pop space-y-4">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex min-w-0 items-center gap-3">
                <span className="grid size-10 shrink-0 place-items-center rounded-full bg-emerald-50 ring-1 ring-emerald-200">
                  <Check className="size-5 text-emerald-600" strokeWidth={2.5} />
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-900">
                    {view === "managed" ? "Ключ выдан администратором" : "Ключ принят"}
                  </p>
                  <p className="mt-0.5 text-sm text-slate-500">
                    {initial.openrouter_key_set_at
                      ? `${view === "managed" ? "Выдан" : "Вставлен"} ${formatDateTime(initial.openrouter_key_set_at)}`
                      : "Дата неизвестна"}
                  </p>
                </div>
              </div>
              {view === "own" && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className={cn("shrink-0", dangerBtnClass)}
                  disabled={saveKey.isPending}
                  onClick={() => void resetOpenRouterKey()}
                >
                  {saveKey.isPending ? (
                    <Loader2 className="size-4 animate-spin" strokeWidth={2} />
                  ) : null}
                  Сбросить ключ
                </Button>
              )}
            </div>
            <UsageStats
              todayBasic={tokenStats?.todayBasic}
              todayAdvanced={tokenStats?.todayAdvanced}
              monthBasic={tokenStats?.monthBasic}
              monthAdvanced={tokenStats?.monthAdvanced}
            />
            {view === "managed" && (
              <div className="border-t border-slate-100 pt-4">
                <button
                  type="button"
                  onClick={() => setShowOwnKeyField((v) => !v)}
                  className="inline-flex items-center gap-1 text-sm text-slate-500 transition-colors hover:text-slate-700"
                >
                  {showOwnKeyField ? (
                    <ChevronUp className="size-3.5" strokeWidth={2} />
                  ) : (
                    <ChevronDown className="size-3.5" strokeWidth={2} />
                  )}
                  Перейти на свой ключ
                </button>
                {showOwnKeyField && (
                  <div className="mt-3 space-y-3">
                    <p className="text-sm text-slate-500">
                      Свой ключ заменит выданный — расход пойдёт на ваш счёт OpenRouter.
                    </p>
                    {keyField}
                  </div>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            {requestBlock}
            <OnboardingHint
              open={shouldShow(ONBOARDING_HINT_IDS.settingsPasteKey)}
              onDismiss={() => dismissHint(ONBOARDING_HINT_IDS.settingsPasteKey)}
              content="Вставьте ключ сюда. Если он вида sk-or-… — сохранится сам, кнопку жать не нужно."
              side="bottom"
              align="start"
              autoHideMs={6000}
            >
              <div>{keyField}</div>
            </OnboardingHint>
            {keyHelp}
          </div>
        )}
      </SettingsSection>
    </div>
  )
}

function PageSkeleton() {
  return (
    <div className="flex-1 space-y-4 overflow-y-auto p-6">
      <div className="mx-auto w-full max-w-3xl space-y-4">
        {[0, 1].map((i) => (
          <SkeletonCard key={i} className="h-44 w-full" />
        ))}
      </div>
    </div>
  )
}

// AUTH-1: anon-режим — периметр закрыт, cookie нет. Единственный путь дальше — токен из бота,
// поэтому монтируем только публичную карточку входа (без /api-запросов: они словят 401).
function AnonSettingsView({ authStatus }: { authStatus: AuthStatus | undefined }) {
  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="mx-auto w-full max-w-3xl space-y-6">
        <div className="motion-rise motion-stagger-0">
          {authStatus ? (
            <AuthTokenSection status={authStatus} />
          ) : (
            <SkeletonCard className="h-44 w-full" />
          )}
        </div>
        <p className="motion-rise motion-stagger-1 text-sm text-slate-500">
          Остальные настройки и разделы откроются после входа.
        </p>
      </div>
    </div>
  )
}

function FullSettingsView({ authStatus }: { authStatus: AuthStatus | undefined }) {
  const { data, isLoading, isError, refetch } = useAppSettings()

  if (isLoading) return <PageSkeleton />

  if (isError || !data) {
    return (
      <ErrorState
        icon={Settings}
        title="Аккаунт недоступен"
        note="Не удалось загрузить настройки. Проверьте, что бэкенд запущен и Postgres доступен."
        action={{ label: "Повторить", onClick: () => void refetch() }}
      />
    )
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="mx-auto w-full max-w-6xl">
        <div className="grid gap-4 lg:grid-cols-2 lg:items-start">
          {/* Левая колонка — вход и устройства: токен/сессии, кому они принадлежат, друзья. */}
          <div className="space-y-4">
            {authStatus && (
              <div className="motion-rise motion-stagger-0">
                <AuthTokenSection status={authStatus} />
              </div>
            )}
            <div className="motion-rise motion-stagger-1">
              <DevicesSection />
            </div>
            <div className="motion-rise motion-stagger-2">
              <FriendsCompactSection />
            </div>
          </div>
          {/* Правая колонка — LLM-ключ и расширение. Контекстная помощь — «Что делать?» в сайдбаре. */}
          <div className="space-y-4">
            <div className="motion-rise motion-stagger-1">
              <SettingsForm initial={data} />
            </div>
            <div className="motion-rise motion-stagger-2">
              <ExtensionInstallSection />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export function SettingsPage() {
  const { status: authState } = useAuth()
  const { data: authStatus } = useAuthStatusQuery()
  const nav = useNavigate()

  // Онбординг (AUTH-1): как только гейт открылся прямо во время визита (вставлены и токен,
  // и ключ), ведём в «Расширение» — следующий шаг. Прямой заход уже настроенного пользователя
  // в Параметры не редиректим (sawClosed фиксирует, что мы видели незавершённое состояние).
  const sawClosed = useRef(false)
  useEffect(() => {
    if (!authStatus) return
    const open = authState === "authed" && isGateOpen(authStatus)
    if (!open) {
      sawClosed.current = true
      return
    }
    if (sawClosed.current) {
      sawClosed.current = false
      if (!authStatus.extension_confirmed) nav("/extension")
    }
  }, [authStatus, authState, nav])

  if (authState === "anon") {
    return <AnonSettingsView authStatus={authStatus} />
  }
  return <FullSettingsView authStatus={authStatus} />
}
