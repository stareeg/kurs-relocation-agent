import {
  ChevronDown,
  CircleCheck,
  ClipboardList,
  Loader2,
  Mail,
  Plus,
  RefreshCw,
  RotateCcw,
  Trash2,
  Undo2,
  X,
} from "lucide-react"
import { useEffect, useRef, useState, type ReactNode } from "react"
import type { CoverLetterLang } from "@/api/cover-letters"
import type { Job } from "@/api/jobs"
import type { AutoApplyConfig, AutoApplyPlatformConfig } from "@/api/settings"
import type {
  AutoApplyPlatform,
} from "@/api/auto-apply"
import type {
  DiscoveryConfig,
  DiscoveryEvent,
  DiscoveryPlatform,
  DiscoveryPlatformConfig,
} from "@/api/discovery"
import { Button } from "@/components/ui/button"
import { ChipToggleGroup, type ChipOption } from "@/components/ui/chip-toggle-group"
import { Input } from "@/components/ui/input"
import { LabeledSlider } from "@/components/ui/labeled-slider"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Progress } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Textarea } from "@/components/ui/textarea"
import { AnketaPanel } from "@/features/jobs/AnketaPanel"
import { useGenerateCoverLetter } from "@/features/jobs/use-cover-letter"
import { useJobPreview } from "@/features/jobs/use-job-preview"
import { useUpdateJobApplyFields } from "@/features/jobs/use-job-apply-fields"
import { useSkipJob, useSkippedList, useUnskipJob } from "@/features/jobs/use-skip"
import { resolveStage, type FunnelStage } from "@/features/jobs/funnel"
import { resolveSourceGroup } from "@/features/jobs/source"
import type { SkippedVacancy } from "@/api/skipped"
import { DecisionButtons, type DecisionKind, QueueVacancyRow } from "./QueueVacancyRow"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { StatusChip, type StatusTone } from "@/components/ui/status-chip"
import { cn } from "@/lib/utils"
import { useNow } from "@/lib/use-now"
import { usePersistedBoolean } from "@/lib/use-persisted-boolean"
import {
  computeQueueEtaMs,
  formatEtaShort,
} from "./auto-apply-eta"
import {
  useAutoApplyConfig,
  useAutoApplyDailyCount,
  useAutoApplyPreview,
  useDiscoveryConfig,
  useDiscoverySessionAction,
  useDiscoveryStatus,
  useMoveAutoApplyQueueItem,
  useRemoveDiscoveryEvent,
  useUpdateAutoApplyConfig,
  useUpdateDiscoveryConfig,
} from "@/features/settings/use-settings"

const PLATFORM_LABEL: Record<AutoApplyPlatform, string> = {
  hh: "hh.ru",
  getmatch: "getmatch",
  habr: "Habr Карьера",
}

// Плейсхолдер — рабочий пример целиком, а не обрезанный многоточием огрызок (Этап 1.3 плана
// `plans/ui_slop_cleanup_2026_08_25.md`): по «https://hh.ru/search/vacancy?text=...» нельзя было
// понять, что вставлять — адрес поиска с фильтрами или адрес одной вакансии.
const SEARCH_URL_PLACEHOLDER: Record<DiscoveryPlatform, string> = {
  hh: "https://hh.ru/search/vacancy?text=AI+engineer&schedule=remote",
  getmatch: "https://getmatch.ru/vacancies?sp=ml&remote=true",
  habr: "https://career.habr.com/vacancies?type=all&qid=3&remote=true",
}

// --- «Просмотр» (discovery) --------------------------------------------------------------

// 2026-08-28 (owner's spec): суточный лимит автопросмотра снова настоящий — считается по
// календарному дню (`discovery_session.py::_daily_count_today`), «новую очередь» сверх него
// запустить нельзя, просмотр продолжится завтра сам. Кнопки «Новая очередь» больше нет.
const STATE_LABEL: Record<string, string> = {
  idle: "Не запущено",
  running: "Работает",
  paused_by_user: "На паузе",
  paused_daily_cap: "Дневной лимит автопросмотра исчерпан — продолжится завтра",
  paused_pages_exhausted: "Эта выдача просмотрена — нажмите «Продолжить» или смените ссылку поиска",
  paused_suspected_block: "Похоже на блокировку площадки",
}

/** Прогресс-бар «сколько уже» вместо голого числа лимита. Оба потребителя (2026-08-28) —
 * НАСТОЯЩИЙ суточный лимит по календарному дню: «Просмотр» — `daily_used` против жёсткого
 * `daily_cap`; «Отклики» — `count` реально отправленных `application_stages` против
 * `auto_apply_daily_hard_cap`. Не сбрасывается на «Начать»/«Запустить». `label` — без числа,
 * компонент сам рисует «N / cap». */
function DailyProgress({
  label,
  current,
  cap,
  rightLabel,
}: {
  label: string
  current: number
  cap: number
  rightLabel?: string
}) {
  const pct = cap > 0 ? Math.min(100, Math.round((current / cap) * 100)) : 0
  return (
    <div>
      <div className="flex items-end justify-between gap-2">
        <span className="text-sm font-medium text-slate-700">{label}</span>
        <span className="flex items-baseline gap-1.5">
          <span className="text-base font-semibold tabular-nums text-slate-900">{current}</span>
          <span className="text-sm text-slate-400">/ {cap}</span>
          {rightLabel ? (
            <span className="ml-1.5 text-xs text-slate-400">{rightLabel}</span>
          ) : null}
        </span>
      </div>
      <Progress value={pct} className="mt-2 h-2.5" indicatorClassName="bg-sky-500" />
    </div>
  )
}

// Правка 2026-08-19 (пункт 8): панель разбита на состояние-хук + управление в шапке карточки
// (статус + кнопки Начать/Пауза/Продолжить/Стоп — рядом с названием площадки) + тело (настройки,
// статистика). Раньше всё это было одним компонентом целиком внутри карточки, ниже переключателя.
function useDiscoveryPanelState(
  platform: DiscoveryPlatform,
  discoveryConfig: DiscoveryConfig,
  saveConfig: ReturnType<typeof useUpdateDiscoveryConfig>,
) {
  const config = discoveryConfig[platform]
  const { data: status, isLoading } = useDiscoveryStatus(platform, true)
  const action = useDiscoverySessionAction(platform)
  const [draft, setDraft] = useState(config)
  const dirty = JSON.stringify(draft) !== JSON.stringify(config)

  function patch(next: Partial<DiscoveryPlatformConfig>) {
    setDraft((d) => ({ ...d, ...next }))
  }

  // Правка 2026-08-20 (баг «вечно висит Сохраняю…»): «Начать» ниже смотрит на `hasSearchUrl`
  // (черновик, не то, что реально сохранено) — владелец мог вставить ссылку и сразу же нажать
  // «Начать» ДО того, как сработает 600мс-дебаунс автосохранения; бэк на старте сессии проверяет
  // search-URL из БД, где ещё пусто — `discovery/session` отвечал 400 «не задан search-URL»
  // (живой пример в проде, 2026-08-19 19:22-19:25). `flush` — тот же PATCH вне дебаунса, зовём его
  // синхронно перед «Начать», чтобы бэк точно увидел актуальный черновик.
  const discoveryConfigRef = useRef(discoveryConfig)
  const draftRef = useRef(draft)
  useEffect(() => {
    discoveryConfigRef.current = discoveryConfig
    draftRef.current = draft
  })

  function flush() {
    if (JSON.stringify(draftRef.current) === JSON.stringify(config)) return undefined
    return saveConfig.mutateAsync({
      ...discoveryConfigRef.current,
      [platform]: draftRef.current,
    })
  }

  // Правка 2026-08-19 пункт 6: автосохранение вместо кнопки «Сохранить» — та же схема, что уже
  // есть у `ScoreThresholdFields` ниже: вставил ссылку/подвинул лимит, через
  // паузу без изменений PATCH уходит сам. Раньше вставка search-URL требовала отдельного клика
  // «Сохранить» — легко забыть, и «Начать» ниже видел старый (пустой) список ссылок.
  useEffect(() => {
    if (JSON.stringify(draft) === JSON.stringify(config)) return
    const timer = setTimeout(() => {
      void flush()
    }, 600)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- дебаунс срабатывает по изменению draft; остальное — стабильные замыкания на момент срабатывания
  }, [draft])

  // Этап 5 редизайна «Расширения»: несколько search-URL на площадку, раннер обходит их по кругу
  // за сессию — снимает «всегда одни и те же рекомендованные». `?? []` — `search_urls` в
  // сгенерированной схеме помечен опциональным (Pydantic `default_factory`, не голый `default`,
  // не попадает в OpenAPI как обычный дефолт), хотя бэк всегда отдаёт реальный массив — тот же
  // приём, что уже используется для `status.events` ниже по файлу. Пустая строка-заглушка, если
  // список пуст, чтобы всегда было куда напечатать первую ссылку; не пишется в draft, пока
  // владелец что-то в неё не введёт.
  const urls = draft.search_urls?.length ? draft.search_urls : [""]

  function updateUrl(index: number, value: string) {
    const next = [...urls]
    next[index] = value
    patch({ search_urls: next })
  }

  function removeUrl(index: number) {
    patch({ search_urls: urls.filter((_, i) => i !== index) })
  }

  function addUrl() {
    patch({ search_urls: [...urls, ""] })
  }

  const hasSearchUrl = (draft.search_urls ?? []).some((u) => u.trim())

  return {
    platform,
    config,
    status,
    isLoading,
    action,
    draft,
    dirty,
    patch,
    saveConfig,
    flush,
    urls,
    updateUrl,
    removeUrl,
    addUrl,
    hasSearchUrl,
  }
}

type DiscoveryPanelState = ReturnType<typeof useDiscoveryPanelState>

// Правка 2026-08-19 (пункт 8): статус и кнопки управления живут в шапке карточки площадки —
// рядом с названием и по правому краю, а не внутри тела ниже переключателя. Тело монтируется
// только когда конфиг реально загружен (см. `PlatformPipelineCard`), поэтому хук состояния и
// оба фрагменты шапки рендерятся отсюда через портал в узлы шапки, которые всегда на месте.

function DiscoveryBody({ state }: { state: DiscoveryPanelState }) {
  const {
    platform,
    status,
    isLoading,
    dirty,
    saveConfig,
    urls,
    updateUrl,
    removeUrl,
    addUrl,
  } = state

  if (isLoading || !status) return null

  return (
    <div className="rounded-lg border border-dashed p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-slate-700">
          Ссылки на вакансии
        </span>
        {(dirty || saveConfig.isPending) && (
          <span className="flex items-center gap-1.5 text-xs text-slate-400">
            <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
            Сохраняю…
          </span>
        )}
      </div>

      <div className="mt-3 space-y-1.5">
        {urls.map((url, i) => (
          <div key={i} className="flex items-center gap-1.5">
            <Input
              value={url}
              placeholder={SEARCH_URL_PLACEHOLDER[platform]}
              onChange={(e) => updateUrl(i, e.target.value)}
            />
            {urls.length > 1 && (
              <button
                type="button"
                onClick={() => removeUrl(i)}
                title="Убрать ссылку"
                className="shrink-0 rounded p-1.5 text-slate-400 hover:bg-red-100 hover:text-red-600"
              >
                <X className="size-3.5" strokeWidth={2} />
              </button>
            )}
          </div>
        ))}
        <Button type="button" size="sm" variant="outline" onClick={addUrl}>
          <Plus className="size-3.5" strokeWidth={2} />
          Добавить ссылку
        </Button>
      </div>

    </div>
  )
}

// --- «Отклики» (auto-apply) ---------------------------------------------------------------

const ORDER_LABEL: Record<AutoApplyPlatformConfig["order"], string> = {
  score_desc: "сначала высокий скор",
  published_desc: "сначала свежие",
  smart: "умный (скор − конкуренция)",
}

// Правка 2026-08-19 (пункт 8): та же разбивка, что у DiscoveryPanel — состояние-хук + шапка
// Правка 2026-08-19 (пункт 8): та же разбивка, что у DiscoveryPanel — состояние-хук + шапка
// (статус + Пауза/Запустить рядом с названием площадки) + тело (настройки).
// useApplyPanelState убран — управление автооткликами живёт в левой панели и в ScoreThresholdFields.


// Порог скора — единый для всех площадок, над карточками. Дебаунс-автосейв применяет значение
// к hh/getmatch/habr сразу.
//
// Ползунок ОДИН (2026-09-01, owner's spec). Их было два — порог автоотклика и полоса «ручного
// разбора» под ним, — и второй никто не понимал: он молча решал, где кончается ручной разбор и
// начинается «не показывать вовсе». Теперь граница одна: выше порога — автоотклик, ниже —
// ручной разбор, а «не показывать» это отдельное решение человека (кнопка «Пропуск»).
// `manual_review_band` в конфиге остался легаси-полем и гейтом больше не читается — см.
// `core/domains/pipeline/auto_apply/gate.py`.
export function GlobalScoreThresholds() {
  const applyConfig = useAutoApplyConfig()
  const save = useUpdateAutoApplyConfig()
  const ref = applyConfig?.["hh"] ?? applyConfig?.["getmatch"] ?? applyConfig?.["habr"]
  const [minScore, setMinScore] = useState(ref?.min_score ?? 70)
  const [order, setOrder] = useState<AutoApplyPlatformConfig["order"]>(ref?.order ?? "score_desc")
  const [syncedKey, setSyncedKey] = useState(
    `${ref?.min_score ?? 70}|${ref?.order ?? "score_desc"}`,
  )
  const serverKey = applyConfig ? `${applyConfig.hh.min_score}|${applyConfig.hh.order}` : ""
  if (syncedKey !== serverKey) {
    setSyncedKey(serverKey)
    setMinScore(applyConfig.hh.min_score)
    setOrder(applyConfig.hh.order)
  }
  const dirty =
    applyConfig == null ||
    minScore !== applyConfig.hh.min_score ||
    order !== applyConfig.hh.order
  const applyConfigRef = useRef(applyConfig)
  useEffect(() => {
    applyConfigRef.current = applyConfig
  })

  useEffect(() => {
    if (!dirty || applyConfig == null) return
    const timer = setTimeout(() => {
      const live = applyConfigRef.current
      if (!live) return
      const next: AutoApplyConfig = { ...live }
      for (const p of ["hh", "getmatch", "habr"]) {
        next[p] = { ...live[p], min_score: minScore, order }
      }
      save.mutate(next)
    }, 600)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- дебаунс по порогу; конфиг берём из ref
  }, [minScore, order, dirty, save])

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-slate-700">Порог скора</span>
        {(dirty || save.isPending) && applyConfig != null && (
          <span className="flex items-center gap-1.5 text-xs text-slate-400">
            <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
            Сохраняю…
          </span>
        )}
      </div>
      <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex-1">
          <LabeledSlider
            label="Скор автоотклика"
            hint={`${minScore} и выше — автоотклик, ниже — ручной разбор`}
            value={minScore}
            onChange={setMinScore}
            min={0}
            max={100}
            step={5}
          />
        </div>
        <div className="sm:w-48">
          <label className="space-y-1 text-xs text-slate-600">
            <span>Порядок разбора очереди</span>
            <Select
              value={order}
              onValueChange={(v) => setOrder(v as AutoApplyPlatformConfig["order"])}
            >
              <SelectTrigger className="h-8 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(ORDER_LABEL) as AutoApplyPlatformConfig["order"][]).map((key) => (
                  <SelectItem key={key} value={key}>
                    {ORDER_LABEL[key]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
        </div>
      </div>
    </div>
  )
}

// --- Карточка площадки: шапка (имя+статус+переключатель+кнопки) + активная под-секция -----

// Обёртки, монтируемые только когда свой конфиг реально загружен (как раньше DiscoveryPanel/
// ApplyPanel целиком) — хук состояния вызывается ровно один раз за монтирование, шапка уходит
// в портал (см. *HeaderControls выше), тело рендерится на месте.
function DiscoveryCardContent({
  platform,
  discoveryConfig,
  saveConfig,
}: {
  platform: DiscoveryPlatform
  discoveryConfig: DiscoveryConfig
  saveConfig: ReturnType<typeof useUpdateDiscoveryConfig>
}) {
  const state = useDiscoveryPanelState(platform, discoveryConfig, saveConfig)
  return <DiscoveryBody state={state} />
}

function PlatformPipelineCard({
  platform,
  hasDiscovery,
  discoveryConfig,
  applyConfig,
  updateDiscovery,
}: {
  platform: AutoApplyPlatform
  hasDiscovery: boolean
  discoveryConfig: DiscoveryConfig | undefined
  applyConfig: AutoApplyConfig | undefined
  updateDiscovery: ReturnType<typeof useUpdateDiscoveryConfig>
}) {
  const applyPlatformConfig = applyConfig?.[platform]

  const loading = hasDiscovery
    ? discoveryConfig === undefined || applyConfig === undefined
    : applyConfig === undefined

  const { data: discoveryStatus } = useDiscoveryStatus(platform as DiscoveryPlatform, hasDiscovery)
  const { data: applyDailyCount } = useAutoApplyDailyCount(platform, true)


  const hasSearchUrl = (discoveryConfig?.[platform as DiscoveryPlatform]?.search_urls ?? []).some((u) =>
    u.trim(),
  )

  const discoveryTitle = discoveryStatus
    ? `Просмотр — ${STATE_LABEL[discoveryStatus.state] ?? discoveryStatus.state} · открыто ${discoveryStatus.opened}`
    : "Просмотр — загрузка…"

  const applyEnabled = Boolean(applyPlatformConfig?.enabled)
  const applyTitle = applyDailyCount
    ? `Отклики — ${applyEnabled ? "Работает" : "Остановлено"} · ${applyDailyCount.count} из ${applyDailyCount.cap} сегодня`
    : `Отклики — ${applyEnabled ? "Работает" : "Остановлено"}`

  const discoveryStatusText = hasDiscovery
    ? `Автопросмотр (${
        discoveryStatus?.state === "running"
          ? "Вкл"
          : discoveryStatus?.state === "idle"
            ? "Выкл"
            : "Пауза"
      })`
    : null
  const applyStatusText = applyPlatformConfig
    ? `Автоотклик (${applyEnabled ? "Вкл" : "Выкл"})`
    : null

  return (
    <div className="rounded-xl border bg-white">
      <div className="flex flex-wrap items-center gap-3 px-5 py-3">
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-base font-bold text-slate-900">{PLATFORM_LABEL[platform]}</span>
          {!hasSearchUrl && hasDiscovery && (
            <span title="Не задана ссылка на вакансии" className="flex items-center">
              <span className="flex size-5 items-center justify-center rounded-full bg-amber-100 text-amber-600">
                !
              </span>
            </span>
          )}
        </div>
        <div className="flex flex-1 justify-end items-center gap-3">
          {discoveryStatusText && (
            <span title={discoveryTitle} className="text-sm text-slate-600">
              {discoveryStatusText}
            </span>
          )}
          {applyStatusText && (
            <span title={applyTitle} className="text-sm text-slate-600">
              {applyStatusText}
            </span>
          )}
        </div>
      </div>
      <div className="border-t px-5 pb-5 pt-4">
        {loading ? (
          <Loader2 className="size-4 animate-spin text-slate-400" strokeWidth={2} />
        ) : (
          <div className="space-y-3">
            {(hasDiscovery || applyConfig) && (
              <div className="rounded-lg border p-4 space-y-4">
                {hasDiscovery && discoveryStatus && (
                  <DailyProgress
                    label="Просмотрено сегодня"
                    current={discoveryStatus.daily_used}
                    cap={discoveryStatus.daily_cap}
                    rightLabel={
                      discoveryStatus.pages_visited > 0
                        ? `Страница ${discoveryStatus.pages_visited}`
                        : undefined
                    }
                  />
                )}
                {applyConfig && applyDailyCount && (
                  <DailyProgress
                    label="Отправлено сегодня"
                    current={applyDailyCount.count}
                    cap={applyDailyCount.cap}
                  />
                )}
              </div>
            )}


            {hasDiscovery && discoveryConfig && (
              <DiscoveryCardContent
                platform={platform as DiscoveryPlatform}
                discoveryConfig={discoveryConfig}
                saveConfig={updateDiscovery}
              />
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// --- Раздел целиком -------------------------------------------------------------------------

const PLATFORMS: { platform: AutoApplyPlatform; hasDiscovery: boolean }[] = [
  { platform: "hh", hasDiscovery: true },
  { platform: "getmatch", hasDiscovery: true },
  { platform: "habr", hasDiscovery: true },
]

// --- Оболочка панели очереди: заголовок + скролл на всю оставшуюся высоту, без карточной рамки
// (Этап «Очередь как половина страницы») ----------------------------------------------------

// Правка: небольшая кнопка слева от названия сворачивает список до одной строки шапки —
// освобождает вертикальное место соседней очереди (обе — flex-1 в общей flex-col колонке, у
// свёрнутой снимаем lg:flex-1, она садится по высоте контента, вся свободная высота уходит
// соседке автоматически, безо всякой ручной арифметики). Состояние — per-очередь (свой
// storageKey), переживает перезагрузку страницы, как и CollapsibleRail рядом.
function QueuePanelShell({
  className,
  storageKey,
  title,
  count,
  headerExtra,
  leftExtra,
  collapsible = true,
  hideHeader = false,
  children,
}: {
  className?: string
  storageKey: string
  title: string
  count: number
  headerExtra?: ReactNode
  leftExtra?: ReactNode
  collapsible?: boolean
  hideHeader?: boolean
  children: ReactNode
}) {
  const [collapsed, setCollapsed] = usePersistedBoolean(storageKey)
  const isCollapsed = collapsible ? collapsed : false
  if (hideHeader) {
    return (
      <section className={cn("flex min-h-0 flex-col", className)}>
        <ScrollArea className="min-h-0 flex-1">{children}</ScrollArea>
      </section>
    )
  }
  return (
    <section className={cn("flex min-h-0 flex-col", className, isCollapsed && "lg:flex-none")}>
      <div className="flex shrink-0 items-center justify-between gap-2 border-b bg-white px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          {collapsible && (
            <button
              type="button"
              onClick={() => setCollapsed((v) => !v)}
              title={collapsed ? `Развернуть «${title}»` : `Свернуть «${title}»`}
              aria-label={collapsed ? `Развернуть «${title}»` : `Свернуть «{title}»`}
              className="flex size-5 shrink-0 items-center justify-center rounded text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
            >
              <ChevronDown
                className={cn("size-3.5 transition-transform", isCollapsed && "-rotate-90")}
                strokeWidth={2}
              />
            </button>
          )}
          <div className="flex items-baseline gap-1.5">
            <h2 className="text-sm font-semibold text-slate-700">{title}</h2>
            {count > 0 && (
              <span className="text-sm font-semibold tabular-nums text-slate-500">{count}</span>
            )}
          </div>
          {leftExtra}
        </div>
        {!isCollapsed && headerExtra}
      </div>
      {!isCollapsed && <ScrollArea className="min-h-0 flex-1">{children}</ScrollArea>}
    </section>
  )
}

// --- «Просмотр» — живой лог решений discovery по всем площадкам разом ----------------------

type DiscoveryEventEntry = DiscoveryEvent & { platform: DiscoveryPlatform }

function useUnifiedDiscoveryEvents(): { events: DiscoveryEventEntry[]; isLoading: boolean } {
  const hh = useDiscoveryStatus("hh", true)
  const getmatch = useDiscoveryStatus("getmatch", true)
  const habr = useDiscoveryStatus("habr", true)
  const byPlatform = [
    { platform: "hh" as const, query: hh },
    { platform: "getmatch" as const, query: getmatch },
    { platform: "habr" as const, query: habr },
  ]
  const events: DiscoveryEventEntry[] = []
  for (const { platform, query } of byPlatform) {
    for (const event of query.data?.events ?? []) events.push({ ...event, platform })
  }
  events.sort((a, b) => (a.ts < b.ts ? 1 : -1))
  return { events, isLoading: byPlatform.some(({ query }) => query.isLoading) }
}

// Правка 2026-08-19 пункт 2: reconstruct URL вакансии по vacancy_id — та же схема, что
// `resolveJobListingUrl` в `features/jobs/source.ts`, но платформа тут уже известна из события
// (не нужно парсить префикс vacancy_id), поэтому проще держать маленькую локальную версию, не
// тащить `Job`-типизированный хелпер ради одной строки.
// Правка 2026-08-20: раньше третья строка текстом дублировала решение бэкенда (`event.label`,
// например «60 баллов → в очередь автооткликов» — правка 2026-08-19 сократила это до короткого
// `BUCKET_DECISION_LABEL`) — занимала строку и всё равно дублировала то, что уже видно по баллу
// слева. Теперь решение подсвечивается прямо на одной из трёх кнопок (`DecisionButtons` —
// QueueVacancyRow.tsx) — `bucket` маппится на активную кнопку ниже, отдельный текстовый лейбл
// не нужен.
function bucketToDecision(bucket: DiscoveryEvent["bucket"]): DecisionKind | null {
  if (bucket === "queued_auto") return "auto"
  if (bucket === "queued_manual") return "manual"
  if (bucket === "excluded") return "skip"
  return null
}

// Баг «кнопки не работают» + «на некоторых вакансиях не выбирается никакой статус» (прод,
// 2026-08-20): `event.bucket` — застывшая запись решения НА МОМЕНТ обнаружения, клик по
// `DecisionButtons` пишет решение в отдельное место (`auto_apply_queue_overrides`/`job.skipped`,
// см. move.ts/use-skip.ts) и НЕ переписывает эту историческую запись задним числом — бэк на клик
// исправно отвечал 200 (видно в `copilot_logs`), но подсветка кнопки никогда не двигалась, что
// выглядело как «не работает» (владелец кликал по одной и той же вакансии по 5-8 раз подряд).
// Для `bucket === "already_known"` та же причина оборачивалась «никакой статус не выбран» — эти
// вакансии могли давно иметь решение из прошлой сессии, а `bucketToDecision` для них всегда
// возвращал `null`. Правим оба разом: `useLiveQueueDecisionMap` — актуальный бакет живой очереди
// автооткликов (preview_queue уже учитывает оверрайд), приоритетнее статичного `event.bucket`;
// `localOverrides` в `DiscoveryQueuePanel` — немедленный оптимистичный оверлей поверх обоих,
// выставляется по факту успешного клика (auto/manual идут через ту же живую очередь и без него,
// но live-карта обновится только после инвалидации + рефетча, оверлей закрывает этот зазор; skip
// в неё вообще не попадает — пропущенные вакансии живая очередь просто не показывает).
function useLiveQueueDecisionMap(): Map<number, DecisionKind> {
  const hh = useAutoApplyPreview("hh", true)
  const getmatch = useAutoApplyPreview("getmatch", true)
  const habr = useAutoApplyPreview("habr", true)
  const map = new Map<number, DecisionKind>()
  for (const q of [hh, getmatch, habr]) {
    for (const item of q.data?.auto ?? []) map.set(item.job_id, "auto")
    for (const item of q.data?.applied ?? []) map.set(item.job_id, "auto")
    for (const item of q.data?.manual_review ?? []) map.set(item.job_id, "manual")
  }
  return map
}

// Правка 2026-08-20 (кнопки решения на уже известных вакансиях): «уже в системе» — не значит
// «ещё не решено». Если с момента лога вакансия успела продвинуться по воронке (Скрининг/
// Техничка/Финал/Оффер/Отказ) или получить отклик/пропуск, три кнопки решения поверх нее вводят
// в заблуждение — а «Пропуск», реально нажатый по ошибке, ломает её текущий этап: `skip_job`
// пишет только в `skipped_vacancies`, статус воронки не трогает и не проверяет (см.
// core/domains/opportunities/service.py::skip_job). `event.job_status`/`job_skipped` — живые
// поля, бэк подмешивает их на каждый опрос статуса (`discovery_session._attach_live_job_state`),
// а не застывшая запись на момент обнаружения.
const ADVANCED_STAGE_BADGE: Partial<Record<FunnelStage, { label: string; tone: StatusTone }>> = {
  Скрининг: { label: "В Скрининге", tone: "info" },
  Техничка: { label: "В Техничке", tone: "info" },
  Финал: { label: "В Финале", tone: "warn" },
  Оффер: { label: "В Оффере", tone: "strong" },
  Отказ: { label: "Отказ", tone: "bad" },
}

type PipelineRowState =
  | { kind: "open" }
  | { kind: "applied" }
  | { kind: "skipped" }
  | { kind: "advanced"; badge: { label: string; tone: StatusTone } }

function pipelineRowState(event: DiscoveryEventEntry): PipelineRowState {
  if (event.job_skipped) return { kind: "skipped" }
  const stage = resolveStage(event.job_status)
  const badge = ADVANCED_STAGE_BADGE[stage]
  if (badge) return { kind: "advanced", badge }
  // «Отклик» — отклик уже ушёл (вручную или раньше автооткликом), решать больше нечего, но
  // владелец может сознательно передумать — единственная осмысленная кнопка тут «Пропуск».
  if (stage === "Отклик") return { kind: "applied" }
  return { kind: "open" }
}

// Правка 2026-08-20 («Вернуть»): локальный оверлей поверх решения по вакансии в эту сессию —
// "skip" (клик «Пропуск»/применённая рекомендация) или "none" (клик «Вернуть» — явный откат
// пропуска, до подтверждения живым статусом). `ts` — момент клика, нужен только для сортировки
// вкладки «Пропуски» по свежести (см. `DiscoveryQueuePanel::visible`).
type LocalDecision = DecisionKind | "none"
type LocalOverride = { decision: LocalDecision; ts: number }

// Правка 2026-08-20 (3, «Новые»/«Уже были» — только нерешённое): вакансия с уже принятым реальным
// решением — пропущена, откликнулась или продвинулась по воронке (`pipelineRowState.kind !==
// "open"`) — решать по ней больше нечего, показывать её среди «Новые»/«Уже были» только вводит в
// заблуждение (этап и так виден на доске «Вакансии», а реальный пропуск — во вкладке «Пропуски»
// ниже). `localOverrides` — оптимистичный клик «Пропуск»/«Вернуть» в эту сессию: `event.job_skipped`
// подтверждается только следующим опросом статуса, без учёта локального оверлея строка на
// мгновение осталась бы в противоречивом состоянии.
function isUndecided(
  event: DiscoveryEventEntry,
  localOverrides: Map<number, LocalOverride>,
): boolean {
  const override = event.job_id != null ? localOverrides.get(event.job_id) : undefined
  if (override?.decision === "skip") return false
  if (override?.decision === "none") return true
  return pipelineRowState(event).kind === "open"
}

// Вкладка «Пропуски» — единственное место для РЕАЛЬНО пропущенных (`job_skipped`/локальный клик
// в эту сессию), независимо от того, свежая это находка или вакансия уже была в системе раньше.
// Мягкая рекомендация системы «Пропустить» по низкому скору свежей вакансии (`bucket ===
// "excluded"`) реальным решением не считается — такая строка остаётся в «Новые» с подсвеченной,
// но не задизейбленной кнопкой «Пропуск» (см. `decisionFor`/`bucketToDecision` ниже).
function isReallySkipped(
  event: DiscoveryEventEntry,
  localOverrides: Map<number, LocalOverride>,
): boolean {
  const override = event.job_id != null ? localOverrides.get(event.job_id) : undefined
  if (override) return override.decision === "skip"
  return event.job_skipped
}

// Правка 2026-08-20: переименована из `discoveryEventUrl` — раньше строила ссылку только для
// «Повторить вручную» на parse_error, теперь и для `href` названия строки в обеих очередях
// («Просмотр»/«Отклики»), см. `QueueVacancyRow.href`.
function vacancyExternalUrl(platform: DiscoveryPlatform, vacancyId: string): string {
  const numeric = vacancyId.replace(/^(gm_|habr_)/, "")
  if (platform === "getmatch") return `https://getmatch.ru/vacancies/${numeric}`
  if (platform === "habr") return `https://career.habr.com/vacancies/${numeric}`
  return `https://hh.ru/vacancy/${numeric}`
}

function DiscoveryEventRow({
  event,
  active,
  activeLocked,
  localOverride,
  onDecided,
}: {
  event: DiscoveryEventEntry
  active: DecisionKind | null
  /** Правка 2026-08-20: `false` — `active` не факт принятого решения, а мягкая рекомендация
   * системы (например «Пропуск» по низкому скору свежей вакансии, `bucket === "excluded"`) —
   * кнопка подсвечена, но остаётся кликабельной, применяет решение по-настоящему сразу, не
   * дожидаясь конца очереди (баг с прода: рекомендованный «Пропуск» висел задизейбленным). */
  activeLocked: boolean
  /** Правка 2026-08-20 (3 и «Вернуть»): оптимистичный клик «Пропуск»/«Вернуть» в эту сессию, до
   * подтверждения живым статусом — без него строка на секунду продолжала бы рендериться по
   * устаревшему `event.job_skipped` (см. `isUndecided`/`isReallySkipped` в `DiscoveryQueuePanel`). */
  localOverride?: LocalDecision
  onDecided: (jobId: number, decision: LocalDecision) => void
}) {
  const time = new Date(event.ts).toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  })
  const skip = useSkipJob()
  const unskip = useUnskipJob()
  const move = useMoveAutoApplyQueueItem()
  const removeEvt = useRemoveDiscoveryEvent()
  // parse_error — вакансию не удалось прочитать, в системе её нет и открывать нечего (ни ссылки,
  // ни ховер-превью, ни job_id для квик-экшенов) — но vacancy_id известен (пришёл со страницы
  // листинга ДО попытки прочитать саму вакансию), поэтому «Повторить» всё равно можно открыть.
  // Правка 2026-08-20: `_heal_stale_scores` на бэке теперь умеет задним числом переклассифицировать
  // parse_error, если вакансия на самом деле доскорилась (см. discovery_session.py) — эта строка
  // сама переедет в queued_auto/queued_manual/excluded на следующем опросе статуса, а не зависнет
  // тут навсегда.
  const hasJob = event.bucket !== "parse_error" && event.job_id != null
  const jobId = event.job_id ?? null
  // Правка 2026-08-20: цветом отличаем свежие находки этой сессии от вакансий, которые уже были
  // в системе раньше (`bucket === "already_known"`) — раньше обе выглядели одинаково, и в фильтре
  // «Все» их было не различить с первого взгляда.
  const isKnown = event.bucket === "already_known"
  const forcedSkipped =
    localOverride === "skip" ? true : localOverride === "none" ? false : undefined
  const rowState = pipelineRowState(
    forcedSkipped !== undefined ? { ...event, job_skipped: forcedSkipped } : event,
  )
  const skipPending = skip.isPending && skip.variables?.id === jobId
  const unskipPending = unskip.isPending && unskip.variables?.id === jobId
  const onSkip =
    jobId != null
      ? () => skip.mutate({ id: jobId }, { onSuccess: () => onDecided(jobId, "skip") })
      : undefined
  const onRevert =
    jobId != null
      ? () => unskip.mutate({ id: jobId }, { onSuccess: () => onDecided(jobId, "none") })
      : undefined

  return (
    <QueueVacancyRow
      className={cn(
        "border-b border-l-2 last:border-b-0",
        !hasJob && "opacity-70",
        isKnown ? "border-l-transparent bg-slate-50" : "border-l-sky-400 bg-sky-50/70",
      )}
      platform={event.platform}
      vacancyId={hasJob ? event.vacancy_id : null}
      title={event.title}
      company={event.company}
      score={event.overall_score}
      scoreCaption={time}
      // Правка 2026-08-20: название ведёт на реальную вакансию на площадке (hh.ru/getmatch.ru/
      // habr), не на внутренний дровер `/jobs/:id` — см. `QueueVacancyRow.href`.
      href={vacancyExternalUrl(event.platform, event.vacancy_id)}
      // Правка 2026-08-20: три кнопки-решения вместо текстовой третьей строки — активная (по
      // живому статусу очереди/локальному оверлею, см. `active`/`useLiveQueueDecisionMap` выше и
      // `DiscoveryQueuePanel` ниже) подсвечена и задизейблена, две другие переводят вакансию в
      // свою корзину (`move` — персистентный оверрайд бакета, владелец может сознательно перебить
      // рекомендацию системы; `skip` — «Пропустить» по-настоящему, `job.skipped`). Правка 2026-08-20
      // (see `pipelineRowState` выше): вакансия, ушедшая по воронке дальше «Просмотрено» —
      // Скрининг/Техничка/Финал/Оффер/Отказ — вместо кнопок показывает бейдж с текущим этапом;
      // уже пропущенная — только подсвеченная (задизейбленная) «Пропуск»; уже с откликом —
      // только реально кликабельная «Пропуск», остальные кнопки решения тут не имеют смысла.
      actions={
        jobId == null ? null : rowState.kind === "advanced" ? (
          <StatusChip tone={rowState.badge.tone}>{rowState.badge.label}</StatusChip>
        ) : rowState.kind === "skipped" ? (
          <>
            {/* Правка 2026-08-20 («Вернуть»): слева от «Пропуск» — случайный клик по рекомендации
                легко исправить на месте, не открывая доску «Вакансии»; та же мутация `unskip_job`,
                что и «Вернуть» на канбане (`useUnskipJob`). */}
            <Button
              type="button"
              size="xs"
              variant="outline"
              disabled={unskipPending}
              onClick={onRevert}
              title="Вернуть — снять пропуск, вакансия снова нерешена"
              className="border-dashed text-slate-600"
            >
              {unskipPending ? (
                <Loader2 className="size-3 animate-spin" strokeWidth={2} />
              ) : (
                <RotateCcw className="size-3" strokeWidth={2} />
              )}
              Вернуть
            </Button>
            <DecisionButtons active="skip" onSkip={onSkip} skipPending={skipPending} />
          </>
        ) : rowState.kind === "applied" ? (
          <DecisionButtons active={null} onSkip={onSkip} skipPending={skipPending} />
        ) : (
          <DecisionButtons
            active={active}
            activeLocked={activeLocked}
            // Правка (пункт 3, «в моменте»): совпадение решения владельца с готовым решением
            // системы не должно требовать ждать конца очереди/фонового поллинга — клик по уже
            // подсвеченной кнопке форсирует немедленный перенос в «Отклики» (см. `DecisionButton`).
            forceClickable
            onAuto={() =>
              move.mutate({ jobId, target: "auto" }, { onSuccess: () => onDecided(jobId, "auto") })
            }
            onManual={() =>
              move.mutate(
                { jobId, target: "manual_review" },
                { onSuccess: () => onDecided(jobId, "manual") },
              )
            }
            onSkip={onSkip}
            autoPending={
              move.isPending && move.variables?.jobId === jobId && move.variables?.target === "auto"
            }
            manualPending={
              move.isPending &&
              move.variables?.jobId === jobId &&
              move.variables?.target === "manual_review"
            }
            skipPending={skipPending}
          />
        )
      }
      // Правка: сломанные вакансии (`parse_error`, самопочинка не долечила — см.
      // `_heal_stale_scores`) засоряют лог «Просмотра» без реальной кнопки решения — квадрат
      // «Удалить» слева от глазка-превью (тот пуст для таких строк, т.к. вакансии нет в системе),
      // тот же размер/стиль, что у `PreviewTrigger`, но с корзиной.
      beforePreview={
        event.bucket === "parse_error" ? (
          <button
            type="button"
            title="Удалить сломанную вакансию из списка — вакансия не прочиталась"
            disabled={removeEvt.isPending}
            onClick={() =>
              removeEvt.mutate({ platform: event.platform, vacancyId: event.vacancy_id })
            }
            className="flex size-8 shrink-0 cursor-default items-center justify-center rounded border border-dashed border-rose-300 text-rose-500 transition-colors hover:border-rose-400 hover:bg-rose-50 hover:text-rose-600 disabled:opacity-60"
          >
            {removeEvt.isPending ? (
              <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
            ) : (
              <Trash2 className="size-3.5" strokeWidth={2} />
            )}
          </button>
        ) : null
      }
      line3={
        event.bucket === "parse_error" && (
          <a
            href={vacancyExternalUrl(event.platform, event.vacancy_id)}
            target="_blank"
            rel="noreferrer"
            className="flex w-fit items-center gap-1 rounded px-1.5 py-0.5 text-xs text-sky-700 hover:bg-sky-100"
          >
            <RefreshCw className="size-3" strokeWidth={2} />
            Повторить вручную
          </a>
        )
      }
    />
  )
}

// Правка 2026-08-20 (пункт 8, «Лимит за очередь»): границы очередей (старт новой/пауза) теперь
// живут прямо в логе «Просмотра» — `bucket: "session_boundary"`, не обычная строка вакансии
// (пустые `vacancy_id`/`title`/`score`), рендерится отдельным тонким разделителем.
function SessionBoundaryRow({ event }: { event: DiscoveryEventEntry }) {
  const time = new Date(event.ts).toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  })
  return (
    <div className="flex items-center gap-2 bg-slate-50 px-4 py-1.5">
      <span className="h-px flex-1 bg-slate-200" />
      <span className="shrink-0 text-[11px] font-medium uppercase tracking-wide text-slate-400">
        {event.label} · {time}
      </span>
      <span className="h-px flex-1 bg-slate-200" />
    </div>
  )
}

// Правка 2026-08-19 пункт 2: фильтр очереди «Просмотр» — Новые/Уже были/Пропуски, тот же паттерн,
// что уже есть у очереди «Отклики». По умолчанию «Новые» — «уже были» (bucket already_known)
// обычно не то, ради чего открывают лог. Значения фильтра, счётчик в шапке — по тому же принципу,
// что и в ApplyQueuePanel: общий тотал независимо от фильтра, фильтр только режет видимые строки.
// Правка 2026-08-20 (2): «Все» убран — на реальном логе (сотни строк за очередь) он почти всегда
// был лишним шумом поверх «Новые».
// Правка 2026-08-20 (3, вариант «Б»): «Новые» и «Уже были» показывают ТОЛЬКО вакансии без
// реального решения (`isUndecided` — ещё не пропущена, без отклика, не продвинулась по воронке);
// как только решение есть, строка пропадает из обоих — этап и так виден на доске «Вакансии».
// «Пропуски» — единственное место для РЕАЛЬНО пропущенных (`isReallySkipped`), независимо от
// происхождения; мягкая рекомендация системы по низкому скору (`bucket === "excluded"`) сюда не
// попадает, пока владелец не нажал «Пропуск» по-настоящему — раньше оба смысла жили в одном
// фильтре и путали (см. обсуждение с владельцем).

export function DiscoveryQueuePanel({
  className,
  filter,
}: {
  className?: string
  filter: "new" | "known" | "skipped"
}) {
  const { events, isLoading } = useUnifiedDiscoveryEvents()
  // Живой бакет очереди автооткликов (переживает перезагрузку — приходит с бэка) + локальный
  // оверлей по факту клика в этой сессии (закрывает зазор до следующего рефетча живой очереди и
  // покрывает «Пропуск», которого в живой очереди нет вовсе — см. комментарий у
  // `useLiveQueueDecisionMap`). Приоритет: локальный клик > живая очередь > исторический bucket.
  const liveDecisions = useLiveQueueDecisionMap()
  const [localOverrides, setLocalOverrides] = useState<Map<number, LocalOverride>>(new Map())

  function markDecided(jobId: number, decision: LocalDecision) {
    setLocalOverrides((prev) => {
      const next = new Map(prev)
      next.set(jobId, { decision, ts: Date.now() })
      return next
    })
  }

  // Мягкая рекомендация системы по историческому bucket'у лога — используется как запасной
  // вариант ниже: когда нет ни локального оверлея, ни живого статуса очереди/факта пропуска.
  // «excluded» → «skip» намеренно НЕ реальное решение (см. `real` ниже) — это просто «система не
  // поставила в очередь», а не «владелец пропустил», в отличие от «queued_auto»/«queued_manual»,
  // которые УЖЕ реально записаны в очередь автооткликов раннером.
  function bucketRecommendation(
    event: DiscoveryEventEntry,
  ): { kind: DecisionKind; real: boolean } | null {
    const bucketDecision = bucketToDecision(event.bucket)
    if (bucketDecision == null) return null
    return { kind: bucketDecision, real: bucketDecision !== "skip" }
  }

  // Какую из трёх кнопок подсветить на строке и заблокирована ли она (используется только для
  // рядов с `pipelineRowState.kind === "open"` — см. `DiscoveryEventRow`; принадлежность к
  // фильтру «Пропуски» с 2026-08-20 (3) решает отдельно `isReallySkipped`, не эта функция).
  // Правка 2026-08-20 (разлочка «Пропуска»): раньше мягкая рекомендация «excluded» → skip
  // считалась таким же принятым решением, как реальный пропуск, — кнопка подсвечивалась и сразу
  // дизейблилась, хотя ничего пропущено ещё не было. Теперь у рекомендации `real: false` —
  // кнопка подсвечена, но кликабельна, применяет пропуск по-настоящему одним кликом.
  function decisionFor(event: DiscoveryEventEntry): { kind: DecisionKind; real: boolean } | null {
    const jobId = event.job_id
    const override = jobId != null ? localOverrides.get(jobId) : undefined
    if (override) {
      // "none" — только что нажали «Вернуть»: живой статус/job_skipped ещё не переопросились и
      // могут быть устаревшими, поэтому смотрим сразу на историческую рекомендацию по bucket'у,
      // как будто пропуска никогда не было.
      if (override.decision === "none") return bucketRecommendation(event)
      return { kind: override.decision, real: true }
    }
    if (event.job_skipped) return { kind: "skip", real: true }
    if (jobId != null && liveDecisions.has(jobId)) {
      const d = liveDecisions.get(jobId)
      return d ? { kind: d, real: true } : null
    }
    return bucketRecommendation(event)
  }

  // Правка 2026-08-20 (сортировка «Пропуски»): раньше вкладка наследовала общий порядок
  // `events` (по времени ПРОСМОТРА, убывание) — только что нажатый «Пропуск» мог оказаться где
  // угодно в середине длинного лога вместо самого верха. Ключ сортировки — момент локального
  // клика «Пропуск» этой сессии (`ts`, всегда позже любого исторического `event.ts`), иначе —
  // время просмотра (лучшее доступное приближение к «когда пропущено» для решений из прошлых
  // сессий — бэк не хранит отдельную метку времени пропуска).
  function skippedSortKey(event: DiscoveryEventEntry, jobId: number | null): number {
    const override = jobId != null ? localOverrides.get(jobId) : undefined
    if (override?.decision === "skip") return override.ts
    return new Date(event.ts).getTime()
  }

  const visible =
    filter === "known"
      ? events.filter((e) => e.bucket === "already_known" && isUndecided(e, localOverrides))
      : filter === "skipped"
        ? events
            .filter((e) => isReallySkipped(e, localOverrides))
            .sort((a, b) => skippedSortKey(b, b.job_id) - skippedSortKey(a, a.job_id))
        : events.filter((e) => e.bucket !== "already_known" && isUndecided(e, localOverrides))

  return (
    <QueuePanelShell
      className={className}
      storageKey="extension.queue.discovery.collapsed"
      title="Просмотр"
      count={events.length}
      hideHeader
    >
      {isLoading ? (
        <Loader2 className="m-4 size-4 animate-spin text-slate-400" strokeWidth={2} />
      ) : events.length === 0 ? (
        <p className="px-4 py-3 text-sm text-slate-400">
          Пусто — включите автопросмотр на площадке справа.
        </p>
      ) : visible.length === 0 ? (
        <p className="px-4 py-3 text-sm text-slate-400">Нет вакансий под этот фильтр.</p>
      ) : (
        <div className="divide-y">
          {visible.map((event) => {
            if (event.bucket === "session_boundary") {
              return (
                <SessionBoundaryRow key={`${event.platform}-${event.ts}-boundary`} event={event} />
              )
            }
            const decision = decisionFor(event)
            const override = event.job_id != null ? localOverrides.get(event.job_id) : undefined
            return (
              <DiscoveryEventRow
                key={`${event.platform}-${event.ts}-${event.vacancy_id}`}
                event={event}
                active={decision?.kind ?? null}
                activeLocked={decision?.real ?? true}
                localOverride={override?.decision}
                onDecided={markDecided}
              />
            )
          })}
        </div>
      )}
    </QueuePanelShell>
  )
}

import { useUnifiedQueue, type QueueEntry } from "./useUnifiedQueue"

// --- Иконки «Сопроводительное»/«Анкета» на строке очереди (Фаза E, пункт 4) ------------------
// Обе — попап по клику (не ховер, как у превью вакансии: тут владелец реально правит текст, а не
// просто смотрит), лениво подтягивают полный Job (useJobPreview — тот же кэш, что у ховер-превью)
// только когда открыты. Компонент письма/анкеты — те же, что в полном дровере
// (use-cover-letter.ts / AnketaPanel), без дублирования логики confirm/reject/генерации.

// Правка 2026-08-20 (UX-правка «сопроводительное на виду», пункт 1): бэк сам ставит письмо в
// фоновую пре-генерацию, как только вакансия попадает в бакет «Автоотклик» (`preview_with_pregen`,
// `core/app/scenarios/cover_letter.py`) — жать «Сгенерировать» вручную больше не нужно, кнопка
// всегда «Перегенерировать» (письмо, даже пустое на момент открытия попапа, уже в работе).
// Э4.4 dual_employment_and_contracting_2026.md: та же переключалка, что в дровере вакансии.
const LETTER_LANG_OPTIONS: ChipOption[] = [
  { value: "ru", label: "RU" },
  { value: "en", label: "EN" },
]

function CoverLetterEditor({ job, pregenPending }: { job: Job; pregenPending: boolean }) {
  // `draft === null` — владелец ещё не тронул поле: показываем `job.cover_letter_text` напрямую,
  // так фоновая пре-генерация (свежие данные приходят через поллинг `useJobPreview` в
  // `CoverLetterIcon`) сама подхватывается без лишнего эффекта. Как только он начал печатать,
  // `draft` перестаёт быть `null` и дальше живёт независимо от фоновых апдейтов `job`.
  const [draft, setDraft] = useState<string | null>(null)
  const save = useUpdateJobApplyFields()
  const gen = useGenerateCoverLetter()
  const letter = draft ?? job.cover_letter_text ?? ""
  const dirty = draft !== null && draft !== (job.cover_letter_text ?? "")
  const canGenerate = (job.vacancy_text?.trim().length ?? 0) >= 50
  // Переключалка RU/EN (Э4.4 dual_employment_and_contracting_2026.md) — тот же контракт, что в
  // дровере (JobDetailDrawer): null = автоопределение по резюме, клик ставит явный оверрайд.
  const [letterLang, setLetterLang] = useState<CoverLetterLang | null>(
    (job.cover_letter_lang as CoverLetterLang | null) ?? null,
  )

  return (
    <div className="space-y-2">
      {/* Правка (UX «сопроводительное на виду», ховер): попап заметно шире и выше, чем раньше
          (w-80/min-h-32) — письмо на 5-9 строк там целиком помещалось только со скроллом вверх-
          вниз внутри маленького textarea; теперь видно целиком без прокрутки в подавляющем
          большинстве случаев. */}
      <Textarea
        value={letter}
        onChange={(e) => setDraft(e.target.value)}
        className="min-h-72 bg-white text-sm"
        placeholder="Сопроводительное письмо…"
      />
      {pregenPending && !letter.trim() && (
        <p className="flex items-center gap-1.5 text-xs text-amber-600">
          <Loader2 className="size-3 animate-spin" strokeWidth={2} />
          Готовится в фоне — можно подождать или сгенерировать сейчас
        </p>
      )}
      <div className="flex items-center gap-1.5">
        <span className="text-xs text-slate-400">Язык</span>
        <ChipToggleGroup
          options={LETTER_LANG_OPTIONS}
          value={letterLang ? [letterLang] : []}
          onChange={([v]) => setLetterLang((v as CoverLetterLang) ?? null)}
          multiple={false}
        />
      </div>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          disabled={!dirty || job.id == null || save.isPending}
          onClick={() => job.id != null && save.mutate({ id: job.id, cover_letter_text: letter })}
        >
          {save.isPending && <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />}
          Сохранить
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!canGenerate || job.id == null || gen.isPending}
          onClick={() =>
            job.id != null &&
            gen.mutate(
              { jobId: job.id, lang: letterLang ?? undefined },
              {
                onSuccess: (res) => {
                  setDraft(res.cover_letter_text)
                  setLetterLang(res.lang as CoverLetterLang)
                },
              },
            )
          }
        >
          {gen.isPending && <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />}
          Перегенерировать
        </Button>
      </div>
    </div>
  )
}

// Правка (UX «сопроводительное на виду», ховер): те же тайминги открытия/закрытия, что у
// `VacancyHoverPreview` — задержка на открытие фильтрует случайный пролёт курсора мимо иконки,
// задержка на закрытие даёт курсору время долететь до портала попапа (тот вне DOM-поддерева
// триггера), не гася его раньше времени.
const HOVER_POPOVER_OPEN_DELAY_MS = 200
const HOVER_POPOVER_CLOSE_DELAY_MS = 250

/** Общая ховер-механика для квадратных иконок строки очереди (сопроводительное, анкета):
 * открытие/закрытие по наведению с задержками, попап держится, пока курсор над ним (внутри
 * правят текст — закрытие на полпути недопустимо). */
function useHoverPopover() {
  const [open, setOpen] = useState(false)
  const openTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  function clearOpenTimer() {
    if (openTimerRef.current) {
      clearTimeout(openTimerRef.current)
      openTimerRef.current = null
    }
  }
  function clearCloseTimer() {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current)
      closeTimerRef.current = null
    }
  }
  function handleEnter() {
    clearCloseTimer()
    clearOpenTimer()
    openTimerRef.current = setTimeout(() => setOpen(true), HOVER_POPOVER_OPEN_DELAY_MS)
  }
  function handleLeave() {
    clearOpenTimer()
    clearCloseTimer()
    closeTimerRef.current = setTimeout(() => setOpen(false), HOVER_POPOVER_CLOSE_DELAY_MS)
  }
  return {
    open,
    setOpen,
    triggerProps: { onMouseEnter: handleEnter, onMouseLeave: handleLeave },
    contentProps: { onMouseEnter: clearCloseTimer, onMouseLeave: handleLeave },
  }
}

function CoverLetterIcon({
  vacancyId,
  hasLetter,
  pregenPending,
}: {
  vacancyId: string
  hasLetter: boolean
  /** Бакет «Автоотклик», письма ещё нет — бэк уже готовит его в фоне (см. комментарий у
   * `CoverLetterEditor` выше). */
  pregenPending: boolean
}) {
  const { open, setOpen, triggerProps, contentProps } = useHoverPopover()
  // Пока попап открыт и письма всё ещё нет — коротко поллим, чтобы подхватить результат фоновой
  // генерации без ручного закрытия/переоткрытия попапа.
  const { data: job } = useJobPreview(vacancyId, open, {
    refetchInterval: (query) =>
      open && pregenPending && !query.state.data?.cover_letter_text?.trim() ? 4000 : false,
  })
  const ready = hasLetter || Boolean(job?.cover_letter_text?.trim())

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <div {...triggerProps}>
        <PopoverTrigger asChild>
          <button
            type="button"
            title={
              ready
                ? "Сопроводительное — навести для просмотра/правки"
                : pregenPending
                  ? "Сопроводительное готовится в фоне — навести можно уже сейчас"
                  : "Нужно сопроводительное письмо"
            }
            className={cn(
              "flex size-8 shrink-0 cursor-default items-center justify-center rounded border border-dashed transition-colors",
              ready
                ? "border-sky-300 text-sky-600 hover:border-sky-400 hover:bg-sky-50"
                : "border-amber-300 text-amber-600 hover:border-amber-400 hover:bg-amber-50",
            )}
          >
            {!ready && pregenPending ? (
              <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
            ) : (
              <Mail className="size-3.5" strokeWidth={2} />
            )}
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          side="right"
          sideOffset={12}
          collisionPadding={16}
          // Правка (UX «сопроводительное на виду», ховер): попап расширен с 320px (`w-80`) до
          // 560px и доступной по высоте до края вьюпорта (как у `VacancyHoverPreview`) — раньше
          // текст письма (5-9 строк) не помещался в узкий `min-h-32` textarea целиком, приходилось
          // скроллить внутри поля вверх-вниз, чтобы вычитать письмо перед отправкой.
          className="w-[560px] max-h-[var(--radix-popover-content-available-height)] overflow-y-auto"
          onOpenAutoFocus={(e) => e.preventDefault()}
          {...contentProps}
        >
          {!job ? (
            <Loader2 className="m-2 size-4 animate-spin text-slate-400" strokeWidth={2} />
          ) : (
            <CoverLetterEditor job={job} pregenPending={pregenPending && !ready} />
          )}
        </PopoverContent>
      </div>
    </Popover>
  )
}

// Анкета работодателя в строке очереди — та же ховер-механика и квадрат, что у сопроводительного
// (`CoverLetterIcon`): навёл — увидел, что 11m собирается отправить, поправил, сохранил. Ответы
// строятся на резюме ЭТОГО аккаунта (`generate_anketa_answers` → `read_resume_data_for_account`),
// не на чужом. Внутри — общий `AnketaPanel` (вопросы ИЛИ письмо, если анкеты нет).
function AnketaHoverIcon({ vacancyId }: { vacancyId: string }) {
  const { open, setOpen, triggerProps, contentProps } = useHoverPopover()
  const { data: job } = useJobPreview(vacancyId, open)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <div {...triggerProps}>
        <PopoverTrigger asChild>
          <button
            type="button"
            title="Анкета работодателя — навести для просмотра/правки, что уйдёт"
            className="flex size-8 shrink-0 cursor-default items-center justify-center rounded border border-dashed border-sky-300 text-sky-600 transition-colors hover:border-sky-400 hover:bg-sky-50"
          >
            <ClipboardList className="size-3.5" strokeWidth={2} />
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          side="right"
          sideOffset={12}
          collisionPadding={16}
          className="w-[440px] max-h-[var(--radix-popover-content-available-height)] overflow-y-auto"
          onOpenAutoFocus={(e) => e.preventDefault()}
          {...contentProps}
        >
          {!job ? (
            <Loader2 className="m-2 size-4 animate-spin text-slate-400" strokeWidth={2} />
          ) : (
            <AnketaPanel job={job} />
          )}
        </PopoverContent>
      </div>
    </Popover>
  )
}

// Правка 2026-08-19 пункт 3: bucket "applied" — вакансия, куда автоотклик уже ушёл сегодня,
// показывается той же строкой, но без кнопок (нечего больше решать) — зелёная галочка вместо
// них, приглушённая строка, в конце списка «Автоотклик» (порядок задаёт вызывающая сторона).
type ApplyQueueBucket = "auto" | "manual_review" | "applied"

function ApplyQueueRow({
  entry,
  bucket,
  onRemove,
  removePending,
  etaLabel,
}: {
  entry: QueueEntry
  bucket: ApplyQueueBucket
  onRemove?: () => void
  removePending?: boolean
  /** «≈ через 4 мин» — оценка, когда раннер дойдёт до этой вакансии (только bucket «auto» на
   * реально работающей площадке). */
  etaLabel?: string
}) {
  const move = useMoveAutoApplyQueueItem()
  const hasLetter = Boolean(entry.cover_letter_text?.trim())
  const hasAnketa = entry.anketa?.status === "pending"
  // Правка 2026-08-20 (UX-правка «сопроводительное на виду», пункт 1): бакет «Автоотклик» без
  // готового письма — бэк уже поставил его в фоновую пре-генерацию на этот же пересчёт превью
  // (`preview_with_pregen`), не только «на разборе»/уже отправленные.
  const pregenPending = bucket === "auto" && !hasLetter

  return (
    <QueueVacancyRow
      className={cn("border-b last:border-b-0", bucket === "applied" && "opacity-60")}
      platform={entry.platform}
      vacancyId={entry.vacancy_id}
      title={entry.title}
      company={entry.company}
      score={entry.overall_score}
      scoreCaption={
        etaLabel ? <span className="text-emerald-600">{etaLabel}</span> : undefined
      }
      // Правка 2026-08-20: название ведёт на реальную вакансию на площадке, не на внутренний
      // дровер `/jobs/:id` — см. `QueueVacancyRow.href`.
      href={vacancyExternalUrl(entry.platform, entry.vacancy_id)}
      // Правка 2026-08-20: тот же трёхкнопочный `DecisionButtons`, что и в «Просмотре» — активная
      // (по текущему `bucket`) подсвечена и задизейблена, остальные переводят/пропускают.
      actions={
        bucket === "applied" ? (
          <span className="flex items-center gap-1 text-xs font-medium text-emerald-700">
            <CircleCheck className="size-3.5" strokeWidth={2} />
            Отклик отправлен
          </span>
        ) : (
          <DecisionButtons
            active={bucket === "auto" ? "auto" : "manual"}
            onAuto={() => move.mutate({ jobId: entry.job_id, target: "auto" })}
            onManual={() => move.mutate({ jobId: entry.job_id, target: "manual_review" })}
            onSkip={onRemove}
            autoPending={
              move.isPending &&
              move.variables?.jobId === entry.job_id &&
              move.variables?.target === "auto"
            }
            manualPending={
              move.isPending &&
              move.variables?.jobId === entry.job_id &&
              move.variables?.target === "manual_review"
            }
            skipPending={removePending}
          />
        )
      }
      // Правка 2026-08-20: квадрат сопроводительного — слева от превью-глазка (`beforePreview`),
      // тем же стилем, что и сам глазок, всегда виден для «Автоотклика» (готово или уже готовится
      // фоном), для «Ручного разбора» — только если площадка требует письмо или оно уже есть.
      beforePreview={
        bucket === "applied" ? null : (
          <>
            {hasAnketa ? <AnketaHoverIcon vacancyId={entry.vacancy_id} /> : null}
            {entry.letter_required || hasLetter || pregenPending ? (
              <CoverLetterIcon
                vacancyId={entry.vacancy_id}
                hasLetter={hasLetter}
                pregenPending={pregenPending}
              />
            ) : null}
          </>
        )
      }
      line3={
        bucket === "manual_review" && entry.failure_reason ? (
          <p className="text-xs text-amber-800">{entry.failure_reason}</p>
        ) : null
      }
    />
  )
}

// Правка 2026-08-19 пункт 6: фильтр очереди «Отклики» — Все/Авто/Ручной, на одной строке с
// заголовком, слева от «Очистить». Только переключает видимость секций ниже (счётчик в шапке
// остаётся общим — сколько всего в очереди, независимо от фильтра).

/** Площадка реально шлёт отклики: включена и не в режиме проверки/подтверждения (тест-режим
 * из UI убран, но сохранённые конфиги ещё могут его нести). */
function platformReallySends(cfg: AutoApplyPlatformConfig | undefined): boolean {
  return Boolean(cfg?.enabled && !cfg.dry_run && !cfg.require_confirmation)
}

export type ApplyQueueFilter = "queued" | "applied" | "skipped"

/** Строка пропущенной вакансии — данных меньше, чем в очереди (площадка выводится из ссылки,
 *  скора может не быть вовсе), поэтому своя разметка, а не `ApplyQueueRow` с половиной пустых
 *  пропсов. Основное действие ровно одно — вернуть в очередь. */
function SkippedQueueRow({ item }: { item: SkippedVacancy }) {
  const unskip = useUnskipJob()
  // Площадка выводится из vacancy_id тем же правилом, что и на доске вакансий (`gm_`/`habr_`/
  // цифры = hh) — в `skipped_vacancies` отдельного поля источника нет.
  const platform = resolveSourceGroup(null, item.vacancy_id)
  return (
    <QueueVacancyRow
      className="border-b last:border-b-0 opacity-70"
      platform={platform}
      vacancyId={item.vacancy_id}
      title={item.title}
      company={item.company}
      score={item.overall_score}
      href={item.url}
      actions={
        item.id != null ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={unskip.isPending && unskip.variables?.id === item.id}
            onClick={() => unskip.mutate({ id: item.id as number })}
            title="Вернуть вакансию в очередь"
          >
            {unskip.isPending && unskip.variables?.id === item.id ? (
              <Loader2 className="size-3.5 animate-spin" strokeWidth={2} />
            ) : (
              <Undo2 className="size-3.5" strokeWidth={2} />
            )}
            Вернуть
          </Button>
        ) : null
      }
      line3={
        item.skip_reason ? <p className="text-xs text-slate-500">{item.skip_reason}</p> : null
      }
    />
  )
}

/** Очередь автооткликов — список без дублирующих кнопок/метрик (они живут в левой панели).
 *
 *  Фильтр — по СОСТОЯНИЮ вакансии («В очереди» / «Отправлено» / «Пропуски»), а не по тому,
 *  каким способом её собирались отправить (было «Все / Авто / Ручной»). Способ отправки уже
 *  виден на самой строке подсвеченной кнопкой решения, и фильтровать по нему было незачем;
 *  а вот «куда делась вакансия, которую я только что пропустил» — вопрос, на который прежний
 *  набор фильтров не отвечал вообще. Шапки со счётчиком у панели больше нет: то же число
 *  живёт в строке метрик слева как «Всего», дублировать его над списком незачем.
 */
export function ApplyQueuePanel({
  className,
  filter,
}: {
  className?: string
  filter: ApplyQueueFilter
}) {
  const { auto, manual, applied, schedules, isLoading } = useUnifiedQueue()
  const applyConfig = useAutoApplyConfig()
  const skip = useSkipJob()
  const skipped = useSkippedList(filter === "skipped")
  const now = useNow(30_000)

  const etaByJob = new Map<number, string>()
  for (const { platform } of PLATFORMS) {
    const sched = schedules[platform]
    if (!sched || !platformReallySends(applyConfig?.[platform])) continue
    const rows = auto.filter((e) => e.platform === platform)
    rows.forEach((entry, i) => {
      const eta = computeQueueEtaMs(sched, i, now)
      etaByJob.set(entry.job_id, formatEtaShort(eta, now))
    })
  }

  function remove(jobId: number) {
    skip.mutate({ id: jobId })
  }

  const skippedItems = skipped.data ?? []
  const busy = isLoading || (filter === "skipped" && skipped.isLoading)
  const emptyLabel =
    filter === "applied"
      ? "Сегодня автооткликов ещё не было."
      : filter === "skipped"
        ? "Пропущенных вакансий нет."
        : "Пусто — нет подходящих вакансий среди «Просмотрено»."
  const isEmpty =
    filter === "applied"
      ? applied.length === 0
      : filter === "skipped"
        ? skippedItems.length === 0
        : auto.length === 0 && manual.length === 0

  return (
    <QueuePanelShell
      className={className}
      storageKey="extension.queue.apply.collapsed"
      title="Отклики"
      count={auto.length + manual.length}
      collapsible={false}
      hideHeader
    >
      {busy ? (
        <Loader2 className="m-4 size-4 animate-spin text-slate-400" strokeWidth={2} />
      ) : isEmpty ? (
        <p className="px-4 py-3 text-sm text-slate-400">{emptyLabel}</p>
      ) : filter === "skipped" ? (
        <div className="divide-y">
          {skippedItems.map((item) => (
            <SkippedQueueRow key={item.vacancy_id} item={item} />
          ))}
        </div>
      ) : filter === "applied" ? (
        <div className="divide-y">
          {applied.map((entry) => (
            <ApplyQueueRow
              key={`applied-${entry.platform}-${entry.job_id}`}
              entry={entry}
              bucket="applied"
            />
          ))}
        </div>
      ) : (
        <>
          {auto.length > 0 && (
            <div>
              <p className="px-4 pb-1 pt-2 text-center text-base font-semibold text-emerald-700">
                Автоотклик ({auto.length})
              </p>
              <div className="divide-y">
                {auto.map((entry) => (
                  <ApplyQueueRow
                    key={`${entry.platform}-${entry.job_id}`}
                    entry={entry}
                    bucket="auto"
                    etaLabel={etaByJob.get(entry.job_id)}
                    onRemove={() => remove(entry.job_id)}
                    removePending={skip.isPending && skip.variables?.id === entry.job_id}
                  />
                ))}
              </div>
            </div>
          )}
          {manual.length > 0 && (
            <div>
              <p className="px-4 pb-1 pt-2 text-center text-base font-semibold text-amber-700">
                Ручной разбор ({manual.length})
              </p>
              <div className="divide-y">
                {manual.map((entry) => (
                  <ApplyQueueRow
                    key={`${entry.platform}-${entry.job_id}`}
                    entry={entry}
                    bucket="manual_review"
                    onRemove={() => remove(entry.job_id)}
                    removePending={skip.isPending && skip.variables?.id === entry.job_id}
                  />
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </QueuePanelShell>
  )
}

/** Карточки площадок — сразу видны, без спойлера. */
export function PlatformPipelineSection() {
  const discoveryConfig = useDiscoveryConfig()
  const applyConfig = useAutoApplyConfig()
  const updateDiscovery = useUpdateDiscoveryConfig()

  return (
    <div className="space-y-3">
      {PLATFORMS.map(({ platform, hasDiscovery }) => (
        <PlatformPipelineCard
          key={platform}
          platform={platform}
          hasDiscovery={hasDiscovery}
          discoveryConfig={hasDiscovery ? discoveryConfig : undefined}
          applyConfig={applyConfig}
          updateDiscovery={updateDiscovery}
        />
      ))}
    </div>
  )
}
