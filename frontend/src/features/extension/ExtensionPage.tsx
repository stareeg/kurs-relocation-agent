import { usePersistedBoolean, usePersistedString } from "@/lib/use-persisted-boolean"
import { cn } from "@/lib/utils"
import { HowAutoApplyWorks } from "./HowAutoApplyWorks"
import {
  ApplyQueuePanel,
  DiscoveryQueuePanel,
  GlobalScoreThresholds,
  PlatformPipelineSection,
  type ApplyQueueFilter,
} from "./PlatformPipelineSection"
import { useUnifiedQueue } from "./useUnifiedQueue"
import {
  useClearAutoApplyQueue,
  useClearDiscoveryEvents,
  useDiscoveryConfig,
  useDiscoverySessionAction,
  useDiscoveryStatus,
} from "@/features/settings/use-settings"
import { useAutoApplyConfig, useUpdateAutoApplyConfig } from "@/features/settings/use-settings"
import { Button } from "@/components/ui/button"
import { ChipToggleGroup } from "@/components/ui/chip-toggle-group"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { useMutation } from "@tanstack/react-query"
import { Loader2, OctagonPause, Play, Send, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { manualSendAutoApply } from "@/api/auto-apply"
import type { AutoApplyConfig } from "@/api/settings"
import type { DiscoveryPlatform } from "@/api/discovery"
import { useState } from "react"

type LeftTab = "discovery" | "apply"

const PLATFORM_LABEL: Record<DiscoveryPlatform, string> = {
  hh: "hh.ru",
  getmatch: "getmatch",
  habr: "Habr Карьера",
}

const PLATFORM_COLORS: Record<DiscoveryPlatform, string> = {
  hh: "bg-red-500",
  getmatch: "bg-emerald-500",
  habr: "bg-amber-500",
}

export function ExtensionPage() {
  const [acknowledged, setAcknowledged] = usePersistedBoolean(
    "extension.autoApplyHowto.acknowledged",
  )
  const [leftTab, setLeftTab] = usePersistedString<LeftTab>(
    "extension.leftTab",
    "discovery",
  )

  const hhStatus = useDiscoveryStatus("hh", true)
  const getmatchStatus = useDiscoveryStatus("getmatch", true)
  const habrStatus = useDiscoveryStatus("habr", true)
  const allStatus = [hhStatus, getmatchStatus, habrStatus]

  const hhAction = useDiscoverySessionAction("hh")
  const getmatchAction = useDiscoverySessionAction("getmatch")
  const habrAction = useDiscoverySessionAction("habr")
  const allActions = [hhAction, getmatchAction, habrAction]

  const discoveryConfig = useDiscoveryConfig()
  const applyConfig = useAutoApplyConfig()
  const saveApplyConfig = useUpdateAutoApplyConfig()

  const anyDiscoveryRunning = allStatus.some((q) => q.data && q.data.state !== "idle")
  const anyApplyRunning = applyConfig != null && ["hh", "getmatch", "habr"].some((p) => applyConfig[p].enabled)

  const unifiedQueue = useUnifiedQueue(leftTab === "apply")

  const applyAutoTotal = unifiedQueue.auto.length
  const applyManualTotal = unifiedQueue.manual.length
  const applyAppliedTotal = unifiedQueue.applied.length
  const applyFailedTotal = unifiedQueue.manual.filter((e) => e.failure_reason).length
  const applyPlatformCounts = Object.fromEntries(
    ["hh", "getmatch", "habr"]
      .map((platform) => [
        platform,
        unifiedQueue.auto.filter((e) => e.platform === platform).length +
          unifiedQueue.manual.filter((e) => e.platform === platform).length,
      ])
      .filter(([, total]) => (total as number) > 0),
  ) as Record<DiscoveryPlatform, number>

  const discoveryStats = allStatus.map((q, i) => {
    const platform = ["hh", "getmatch", "habr"][i] as DiscoveryPlatform
    const s = q.data
    return {
      platform,
      opened: s?.opened ?? 0,
      queuedAuto: s?.queued_auto ?? 0,
      queuedManual: s?.queued_manual ?? 0,
      excluded: s?.excluded ?? 0,
    }
  })

  const totalOpened = discoveryStats.reduce((sum, s) => sum + s.opened, 0)
  const totalQueuedAuto = discoveryStats.reduce((sum, s) => sum + s.queuedAuto, 0)
  const totalQueuedManual = discoveryStats.reduce((sum, s) => sum + s.queuedManual, 0)
  const totalExcluded = discoveryStats.reduce((sum, s) => sum + s.excluded, 0)

  const discoveryPending = allActions.some((a) => a.isPending)

  const clearDiscovery = useClearDiscoveryEvents()
  const clearApply = useClearAutoApplyQueue()
  const [confirmClearApply, setConfirmClearApply] = useState(false)

  const manualSend = useMutation({
    mutationFn: manualSendAutoApply,
    onSuccess: () => toast.success("Ручная отправка запущена — раннер обработает очередь на следующем тике"),
    onError: () => toast.error("Не удалось запустить ручную отправку"),
  })

  const [discoveryFilter, setDiscoveryFilter] = useState<"new" | "known" | "skipped">("new")
  // Фильтр по СОСТОЯНИЮ вакансии, а не по способу отправки (было «Все / Авто / Ручной»).
  // Способ уже виден на самой строке подсвеченной кнопкой решения; а «куда делась вакансия,
  // которую я только что пропустил» прежний набор не отвечал вообще.
  const [applyFilter, setApplyFilter] = useState<ApplyQueueFilter>("queued")

  // Любая включённая площадка, не только hh (`anyApplyRunning`): с проверкой одного hh
  // кнопка была мертва у того, кто включил getmatch/habr, а тултип при этом уверял, что
  // автоотклики не запущены.
  const canManualSend = anyApplyRunning && !manualSend.isPending

  function handleStopAllDiscovery() {
    allActions.forEach((action, i) => {
      const status = allStatus[i].data
      if (status && status.state !== "idle") {
        action.mutate({ action: "stop" })
      }
    })
    toast.success("Автопросмотр остановлен на всех площадках")
  }

  function handleStartAllDiscovery() {
    const platforms = ["hh", "getmatch", "habr"] as const
    let started = 0
    platforms.forEach((platform, i) => {
      const status = allStatus[i].data
      if (status && status.state !== "idle") return
      const cfg = discoveryConfig?.[platform]
      const hasUrl = cfg?.search_urls?.some((u) => u.trim())
      if (!hasUrl) return
      allActions[i].mutate({ action: "start" })
      started++
    })
    if (started > 0) {
      toast.success(`Автопросмотр запущен на ${started} площадках`)
    } else {
      toast.info("Нет площадок с настроенной ссылкой для запуска")
    }
  }

  function handleStopAllApply() {
    if (!applyConfig) return
    const next: AutoApplyConfig = {
      hh: { ...applyConfig.hh, enabled: false },
      getmatch: { ...applyConfig.getmatch, enabled: false },
      habr: { ...applyConfig.habr, enabled: false },
    }
    saveApplyConfig.mutate(next, {
      onSuccess: () => toast.success("Автоотклики остановлены на всех площадках"),
    })
  }

  function handleStartAllApply() {
    if (!applyConfig) return
    const next: AutoApplyConfig = {
      hh: { ...applyConfig.hh, enabled: true, dry_run: false, require_confirmation: false },
      getmatch: { ...applyConfig.getmatch, enabled: true, dry_run: false, require_confirmation: false },
      habr: { ...applyConfig.habr, enabled: true, dry_run: false, require_confirmation: false },
    }
    saveApplyConfig.mutate(next, {
      onSuccess: () => toast.success("Автоотклики запущены на всех площадках"),
    })
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:flex-row lg:overflow-hidden">
      <div className="flex min-h-0 flex-col border-b lg:h-full lg:w-1/2 lg:shrink-0 lg:border-b-0 lg:border-r">
        {/* Табы */}
        <div className="flex shrink-0 items-center gap-2 border-b bg-white px-4 py-3">
          <button
            type="button"
            onClick={() => setLeftTab("discovery")}
            className={cn(
              "rounded-lg px-4 py-2 text-base font-semibold transition-colors",
              leftTab === "discovery"
                ? "border border-slate-900 bg-white text-slate-900 shadow-sm"
                : "text-slate-500 hover:bg-slate-200/60",
            )}
          >
            Просмотр
          </button>
          <button
            type="button"
            onClick={() => setLeftTab("apply")}
            className={cn(
              "rounded-lg px-4 py-2 text-base font-semibold transition-colors",
              leftTab === "apply"
                ? "border border-slate-900 bg-white text-slate-900 shadow-sm"
                : "text-slate-500 hover:bg-slate-200/60",
            )}
          >
            Отклики
          </button>
        </div>

        {/* Управление — своя строка; фильтр очереди — следующая. Раньше кнопки и фильтр
            стояли встык в одном ряду и на узкой панели переносились вперемешку, из-за чего
            «что я нажимаю» и «что я смотрю» читались как один набор. Кнопки очистки прижаты
            к правому краю (`ml-auto`): это разрушающее действие, ему не место вплотную к
            «Запустить». */}
        <div className="shrink-0 border-b bg-white px-4 py-2">
          {leftTab === "discovery" ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={discoveryPending}
                  onClick={handleStartAllDiscovery}
                >
                  {discoveryPending ? (
                    <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
                  ) : (
                    <Play className="size-3.5" strokeWidth={2} />
                  )}
                  Запустить
                </Button>
                {anyDiscoveryRunning && (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={discoveryPending}
                    onClick={handleStopAllDiscovery}
                    className="border border-rose-200 bg-rose-50 text-rose-600 hover:bg-rose-100 hover:text-rose-700"
                  >
                    {discoveryPending ? (
                      <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
                    ) : (
                      <OctagonPause className="size-3.5" strokeWidth={2} />
                    )}
                    Стоп
                  </Button>
                )}
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={clearDiscovery.isPending}
                  onClick={() => clearDiscovery.mutate()}
                  className="ml-auto border border-rose-200 bg-rose-50 text-rose-600 hover:bg-rose-100 hover:text-rose-700"
                  title="Убрать строки из этого списка. Сессию не останавливает, вакансии не трогает."
                >
                  {clearDiscovery.isPending ? (
                    <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
                  ) : (
                    <Trash2 className="size-3.5" strokeWidth={2} />
                  )}
                  Очистить лог
                </Button>
              </div>
              <div className="mt-2">
                <ChipToggleGroup
                  options={[
                    { value: "new", label: "Новые" },
                    { value: "known", label: "Были" },
                    { value: "skipped", label: "Пропуски" },
                  ]}
                  value={[discoveryFilter]}
                  onChange={(next) =>
                    setDiscoveryFilter((next[0] as "new" | "known" | "skipped") ?? "new")
                  }
                  multiple={false}
                  allowEmpty={false}
                  size="md"
                />
              </div>
            </>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                {anyApplyRunning && (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={saveApplyConfig.isPending}
                    onClick={handleStopAllApply}
                    className="border border-rose-200 bg-rose-50 text-rose-600 hover:bg-rose-100 hover:text-rose-700"
                  >
                    {saveApplyConfig.isPending ? (
                      <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
                    ) : (
                      <OctagonPause className="size-3.5" strokeWidth={2} />
                    )}
                    Стоп
                  </Button>
                )}
                {!anyApplyRunning && applyConfig && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={saveApplyConfig.isPending}
                    onClick={handleStartAllApply}
                  >
                    <Play className="size-3.5" strokeWidth={2} />
                    Начать
                  </Button>
                )}
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={!canManualSend}
                  onClick={() => manualSend.mutate()}
                  title={
                    applyConfig == null
                      ? "Очередь пуста"
                      : !anyApplyRunning
                        ? "Автоотклики не запущены ни на одной площадке"
                        : "Отправить все автоотклики из очереди сейчас"
                  }
                >
                  {manualSend.isPending ? (
                    <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
                  ) : (
                    <Send className="size-3.5" strokeWidth={2} />
                  )}
                  Отправить
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={clearApply.isPending || applyConfig == null}
                  onClick={() => setConfirmClearApply(true)}
                  className="ml-auto border border-rose-200 bg-rose-50 text-rose-600 hover:bg-rose-100 hover:text-rose-700"
                  title="Пропустить все вакансии из очереди (Автоотклик + Ручной разбор)"
                >
                  {clearApply.isPending ? (
                    <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
                  ) : (
                    <Trash2 className="size-3.5" strokeWidth={2} />
                  )}
                  Очистить очередь
                </Button>
              </div>
              <div className="mt-2">
                <ChipToggleGroup
                  options={[
                    { value: "queued", label: "В очереди" },
                    { value: "applied", label: "Отправлено" },
                    { value: "skipped", label: "Пропуски" },
                  ]}
                  value={[applyFilter]}
                  onChange={(next) =>
                    setApplyFilter((next[0] as ApplyQueueFilter) ?? "queued")
                  }
                  multiple={false}
                  allowEmpty={false}
                  size="md"
                />
              </div>
            </>
          )}
        </div>

        {/* Метрики */}
        <div className="shrink-0 border-b bg-slate-50/50 px-4 py-2.5">
          {leftTab === "discovery" ? (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-slate-500">За эту очередь</span>
                <span className="text-lg font-bold tabular-nums text-slate-900">{totalOpened}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-slate-500">Автоотклики</span>
                <span className="text-lg font-bold tabular-nums text-slate-900">{totalQueuedAuto}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-slate-500">Вручную</span>
                <span className="text-lg font-bold tabular-nums text-slate-900">{totalQueuedManual}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-slate-500">Пропущено</span>
                <span className="text-lg font-bold tabular-nums text-slate-900">{totalExcluded}</span>
              </div>
              <div className="ml-auto flex items-center gap-2">
                {["hh", "getmatch", "habr"].map((platform) => {
                  const s = discoveryStats.find((d) => d.platform === platform)
                  const total = (s?.opened ?? 0) + (s?.queuedAuto ?? 0) + (s?.queuedManual ?? 0) + (s?.excluded ?? 0)
                  if (total === 0) return null
                  return (
                    <span key={platform} className="flex items-center gap-1 text-xs font-semibold tabular-nums text-slate-700">
                      <span className={cn("size-2 rounded-full", PLATFORM_COLORS[platform as DiscoveryPlatform])} />
                      {PLATFORM_LABEL[platform as DiscoveryPlatform]}: {total}
                    </span>
                  )
                })}
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
              {/* «Всего» — то же число, что раньше стояло отдельной строкой-шапкой «Отклики N»
                  над списком. Одна метрика в одном месте, а не счётчик над очередью плюс
                  соседние метрики под ним. */}
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-slate-500">Всего</span>
                <span className="text-lg font-bold tabular-nums text-slate-900">
                  {applyAutoTotal + applyManualTotal}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-slate-500">В очереди</span>
                <span className="text-lg font-bold tabular-nums text-slate-900">{applyAutoTotal}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-slate-500">Отправлено сегодня</span>
                <span className="text-lg font-bold tabular-nums text-emerald-700">{applyAppliedTotal}</span>
              </div>
              {applyFailedTotal > 0 && (
                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-slate-500">Не удалось</span>
                  <span className="text-lg font-bold tabular-nums text-amber-800">{applyFailedTotal}</span>
                </div>
              )}
              <div className="ml-auto flex items-center gap-2">
                {Object.entries(applyPlatformCounts).map(([platform, total]) => (
                  <span key={platform} className="flex items-center gap-1 text-xs font-semibold tabular-nums text-slate-700">
                    <span className={cn("size-2 rounded-full", PLATFORM_COLORS[platform as DiscoveryPlatform])} />
                    {PLATFORM_LABEL[platform as DiscoveryPlatform]}: {total}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Очередь */}
        <div className="min-h-0 flex-1">
          {leftTab === "discovery" ? (
            <DiscoveryQueuePanel
              className="h-full"
              filter={discoveryFilter}
            />
          ) : (
            <ApplyQueuePanel
              className="h-full"
              filter={applyFilter}
            />
          )}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="max-w-5xl space-y-3 p-6">
          <HowAutoApplyWorks
            acknowledged={acknowledged}
            onAcknowledge={() => setAcknowledged(true)}
          />
          <GlobalScoreThresholds />
          <div className="relative">
            <div
              className={!acknowledged ? "pointer-events-none select-none opacity-40" : undefined}
              aria-hidden={!acknowledged}
              inert={!acknowledged}
            >
              <PlatformPipelineSection />
            </div>
            {!acknowledged && (
              <div className="absolute inset-x-0 top-0 flex justify-center pt-6">
                <p className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm text-slate-500 shadow-sm">
                  Прочитайте инструкцию выше и нажмите «Прочитано», чтобы настроить площадки.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={confirmClearApply}
        onOpenChange={setConfirmClearApply}
        title="Очистить очередь автооткликов?"
        description={`${
          applyAutoTotal + applyManualTotal
        } ${
          applyAutoTotal + applyManualTotal === 1
            ? "вакансия будет помечена"
            : "вакансий будут помечены"
        } пропущенными и уйдут из очереди. Автопросмотр и автоотклики при этом продолжают работать — если просмотр запущен, он снова наберёт очередь. Вернуть вакансии можно на доске «Вакансии».`}
        confirmLabel="Очистить"
        onConfirm={() => {
          clearApply.mutate()
          setConfirmClearApply(false)
        }}
      />
    </div>
  )
}
