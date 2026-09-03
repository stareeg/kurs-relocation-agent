import { useState } from "react"
import { Loader2, MoreHorizontal } from "lucide-react"
import type { AdminPipelinePlatform, AdminUserRow } from "@/api/admin"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Metric } from "@/components/ui/metric"
import { Progress } from "@/components/ui/progress"
import { SectionTitle } from "@/components/ui/section-title"
import { Skeleton } from "@/components/ui/skeleton"
import { StatusChip } from "@/components/ui/status-chip"
import { formatMoment, relativeSeen } from "@/features/admin/admin-format"
import { useNow } from "@/lib/use-now"
import {
  applyStateChip,
  capPct,
  discoveryStateChip,
  runnerAsleep,
} from "@/features/admin/automation-status"
import {
  useAdminClearAutoApplyQueue,
  useAdminClearDiscoveryLog,
  useAdminPauseAutoApply,
  useAdminResumeAutoApply,
  useAdminStopDiscovery,
  useAdminUserPipeline,
} from "@/features/admin/use-admin"
import { cn } from "@/lib/utils"

const PLATFORM_LABEL: Record<string, string> = {
  hh: "hh.ru",
  getmatch: "getmatch",
  habr: "Habr",
}

/**
 * Вкладка «Автоматизация» дровера пользователя — автопросмотр + автоотклики одним экраном:
 * сводка сверху (сколько площадок работает, что за сутки, жив ли раннер), карточка на каждую
 * площадку с прогрессом к суточному потолку и очередью, операторские кнопки в шапке
 * (опасное — в «⋯»).
 */
export function AutomationTab({ user }: { user: AdminUserRow }) {
  const { data, isLoading } = useAdminUserPipeline(user.account_id)
  const pause = useAdminPauseAutoApply()
  const resume = useAdminResumeAutoApply()
  const clearQueue = useAdminClearAutoApplyQueue()
  const clearLog = useAdminClearDiscoveryLog()
  const stopDiscovery = useAdminStopDiscovery()
  const [confirm, setConfirm] = useState<"stop" | "resume" | "clearQueue" | null>(null)
  const now = useNow(30_000)

  if (isLoading && !data) {
    return (
      <div className="space-y-3">
        <SectionTitle>Автоматизация</SectionTitle>
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }
  if (!data) return <p className="text-sm text-slate-400">Нет данных.</p>

  const busy =
    pause.isPending ||
    resume.isPending ||
    clearQueue.isPending ||
    clearLog.isPending ||
    stopDiscovery.isPending

  const platforms = data.platforms ?? []
  const discRunning = platforms.filter((p) => p.discovery_state === "running").length
  const applyOn = platforms.filter((p) => p.auto_apply_enabled).length
  const viewedToday = platforms.reduce((s, p) => s + p.discovery_used_today, 0)
  const appliedToday = platforms.reduce((s, p) => s + p.applied_today, 0)
  const queueTotal = platforms.reduce((s, p) => s + p.queue_auto + p.queue_manual, 0)

  const discAsleep =
    data.any_discovery_running &&
    runnerAsleep(data.discovery_last_tick_at, data.discovery_tick_seconds, now)
  const applyAsleep =
    data.any_auto_apply_enabled && runnerAsleep(data.auto_apply_last_tick_at, data.tick_seconds, now)
  const asleep = discAsleep || applyAsleep
  const nothingOn = !data.any_discovery_running && !data.any_auto_apply_enabled

  const latestTick = [data.discovery_last_tick_at, data.auto_apply_last_tick_at]
    .filter((v): v is string => Boolean(v))
    .sort()
    .at(-1)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <Metric
          label="Автопросмотр"
          value={discRunning > 0 ? `${discRunning} из 3` : "выкл"}
          note={discRunning > 0 ? "работает" : "не запущен"}
        />
        <Metric
          label="Автоотклики"
          value={applyOn > 0 ? `${applyOn} из 3` : "выкл"}
          note={applyOn > 0 ? "включены" : "не включены"}
        />
        <Metric
          label="Сегодня"
          value={`${viewedToday} / ${appliedToday}`}
          note="просмотрено / откликов"
        />
        <Metric
          label="Раннер"
          value={
            asleep
              ? "молчит"
              : latestTick
                ? relativeSeen(latestTick, now)
                : nothingOn
                  ? "—"
                  : "ни разу"
          }
          note={asleep ? "расширение усыплено?" : "последний тик"}
          tone={asleep ? "bad" : "normal"}
        />
      </div>

      {asleep && (
        <p className="rounded-lg border border-status-warn-line bg-status-warn-soft px-3 py-2 text-xs text-status-warn-fg">
          Раннер{" "}
          {discAsleep && applyAsleep
            ? "автопросмотра и автооткликов"
            : discAsleep
              ? "автопросмотра"
              : "автооткликов"}{" "}
          молчит дольше трёх тиков — у пользователя, скорее всего, закрыт браузер или усыплено
          расширение. Процессы включены, но ничего не делают.
        </p>
      )}

      <div className="flex items-center justify-between gap-2">
        <SectionTitle>По площадкам</SectionTitle>
        <div className="flex items-center gap-1.5">
          {nothingOn ? (
            <Button size="sm" disabled={busy} onClick={() => setConfirm("resume")}>
              Возобновить автоотклики
            </Button>
          ) : (
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => setConfirm("stop")}
            >
              {busy && <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />}
              Остановить всё
            </Button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="icon-sm" variant="ghost" aria-label="Ещё действия" disabled={busy}>
                <MoreHorizontal className="size-4" strokeWidth={2} />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-60">
              <DropdownMenuItem onSelect={() => setConfirm("clearQueue")}>
                Очистить очередь автооткликов
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => clearLog.mutate(user.account_id)}>
                Очистить лог автопросмотра
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <div className="space-y-2">
        {platforms.map((p) => (
          <PlatformBlock
            key={p.platform}
            p={p}
            busy={busy}
            onStop={() =>
              stopDiscovery.mutate({
                accountId: user.account_id,
                platform: p.platform as "hh" | "getmatch" | "habr",
              })
            }
          />
        ))}
      </div>

      <ul className="rounded-lg bg-slate-50 p-2.5 text-xs">
        <TickRow label="Тик автопросмотра" at={data.discovery_last_tick_at} asleep={discAsleep} now={now} />
        <TickRow
          label="Тик автооткликов"
          at={data.auto_apply_last_tick_at}
          asleep={applyAsleep}
          now={now}
          next={data.auto_apply_next_tick_eta}
        />
      </ul>

      <ConfirmDialog
        open={confirm === "stop"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Остановить всю автоматику?"
        description="Выключит автоотклики на всех площадках и остановит идущие сессии автопросмотра. Настройки (пороги, ссылки) не меняются — можно возобновить."
        confirmLabel="Остановить"
        onConfirm={() => {
          pause.mutate(user.account_id)
          setConfirm(null)
        }}
      />
      <ConfirmDialog
        open={confirm === "resume"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Возобновить автоотклики?"
        description="Включит автоотклики на всех трёх площадках. Раннер в браузере пользователя подхватит на следующем тике. Автопросмотр запускается пользователем отдельно."
        confirmLabel="Возобновить"
        onConfirm={() => {
          resume.mutate(user.account_id)
          setConfirm(null)
        }}
      />
      <ConfirmDialog
        open={confirm === "clearQueue"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Очистить очередь автооткликов?"
        description={`${queueTotal} ${
          queueTotal === 1 ? "вакансия будет помечена" : "вакансий будут помечены"
        } пропущенными по всем площадкам. Автоматика продолжит работать; если автопросмотр запущен — снова наберёт очередь.`}
        confirmLabel="Очистить"
        onConfirm={() => {
          clearQueue.mutate(user.account_id)
          setConfirm(null)
        }}
      />
    </div>
  )
}

function PlatformBlock({
  p,
  busy,
  onStop,
}: {
  p: AdminPipelinePlatform
  busy: boolean
  onStop: () => void
}) {
  const disc = discoveryStateChip(p.discovery_state)
  const apply = applyStateChip(p.auto_apply_enabled, p.auto_apply_dry_run)
  const discRunning = p.discovery_state === "running"

  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium text-slate-800">
          {PLATFORM_LABEL[p.platform] ?? p.platform}
        </span>
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusChip tone={disc.tone}>просмотр: {disc.label}</StatusChip>
          <StatusChip tone={apply.tone}>отклик: {apply.label}</StatusChip>
        </div>
      </div>

      <div className="mt-2.5 grid gap-2.5 sm:grid-cols-2">
        <CapBar label="Просмотрено сегодня" current={p.discovery_used_today} cap={p.discovery_daily_cap} />
        <CapBar label="Отправлено сегодня" current={p.applied_today} cap={p.auto_apply_daily_cap} />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
        <span>
          В очереди <span className="font-medium tabular-nums text-slate-700">{p.queue_auto}</span>
        </span>
        {p.queue_manual > 0 && (
          <span>
            разбор{" "}
            <span className="font-medium tabular-nums text-slate-700">{p.queue_manual}</span>
          </span>
        )}
        {p.pending_confirm > 0 && (
          <span className="text-amber-700">
            на подтв. <span className="font-medium tabular-nums">{p.pending_confirm}</span>
          </span>
        )}
        {/* Порог один (2026-09-01): выше — автоотклик, ниже — ручной разбор. Диапазон
            «разбор X–Y» отсюда убран вместе с полосой `manual_review_band` — гейт её больше
            не читает, и печатать её здесь значило бы показывать оператору несуществующее
            правило. */}
        <span className="text-slate-400">
          скор ≥ {p.auto_apply_min_score} · ссылок {p.discovery_search_urls}
        </span>
        {discRunning && (
          <button
            type="button"
            disabled={busy}
            onClick={onStop}
            className="ml-auto rounded px-1.5 py-0.5 text-rose-600 hover:bg-rose-50 disabled:opacity-50"
          >
            остановить просмотр
          </button>
        )}
      </div>
    </div>
  )
}

function CapBar({ label, current, cap }: { label: string; current: number; cap: number }) {
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-slate-500">{label}</span>
        <span className="tabular-nums text-slate-700">
          {current} / {cap}
        </span>
      </div>
      <Progress value={capPct(current, cap)} className="mt-1 h-1.5" />
    </div>
  )
}

function TickRow({
  label,
  at,
  asleep,
  now,
  next,
}: {
  label: string
  at: string | null | undefined
  asleep: boolean
  now: number
  next?: string | null
}) {
  return (
    <li className="flex items-center justify-between border-b border-slate-200/70 py-1 last:border-b-0">
      <span className="text-slate-500">{label}</span>
      <span className={cn("tabular-nums", asleep ? "text-status-bad-fg" : "text-slate-700")}>
        {at ? relativeSeen(at, now) : "ни разу"}
        {next ? ` · след. ≈ ${formatMoment(next)}` : ""}
      </span>
    </li>
  )
}
