import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  fetchAppSettings,
  patchAppSettings,
  requestOpenRouterKey,
  type AppSettings,
  type AutoApplyConfig,
  type DisclosurePolicy,
  type ScoringImportance,
  type ScoringWeights,
} from "@/api/settings"
import {
  clearAutoApplyQueue,
  confirmAnketa,
  fetchAnketaPending,
  fetchAutoApplyDailyCount,
  fetchAutoApplyPreview,
  moveAutoApplyQueueItem,
  pauseAutoApply,
  rejectAnketa,
  type AnketaAnswer,
  type AutoApplyPlatform,
  type QueueOverride,
} from "@/api/auto-apply"
import {
  fetchDiscoveryStatus,
  postDiscoverySession,
  removeDiscoveryEvent,
  type DiscoveryConfig,
  type DiscoveryPauseReason,
  type DiscoveryPlatform,
  type DiscoverySessionAction,
} from "@/api/discovery"
import { fetchTelegramStatus, pushToTelegram, type TelegramPushRequest } from "@/api/telegram"
import { fetchMetrics, tokenStatsFromMetrics } from "@/api/metrics"
import { AUTH_STATUS_KEY } from "@/features/auth/use-auth-status"

const KEY = ["settings"] as const
const TELEGRAM_STATUS_KEY = ["telegram", "status"] as const
const METRICS_KEY = ["metrics"] as const

/** Текущие параметры приложения (веса скоринга, калибровка, бюджет LLM, флаг ключа OpenRouter).
 *
 * Пока ключа нет — короткий опрос: ключ может появиться от действия администратора в другой
 * вкладке, живого события на это нет, а страница обязана открыться сама. Опрос ограничен
 * состоянием «ключа нет» — а это ровно то состояние, когда кроме «Аккаунта» ничего и не
 * открыто (гейт онбординга), так что фоном по всему приложению он не крутится.
 */
export function useAppSettings() {
  return useQuery({
    queryKey: KEY,
    queryFn: fetchAppSettings,
    staleTime: 60_000,
    refetchInterval: (query) => (query.state.data?.openrouter_key_configured ? false : 20_000),
  })
}

/** Статус бота и привязки — для кнопок «В Telegram» (пуши). */
export function useTelegramStatus() {
  return useQuery({
    queryKey: TELEGRAM_STATUS_KEY,
    queryFn: fetchTelegramStatus,
    staleTime: 15_000,
  })
}

/** «В Telegram» из веба → очередь tg_push (TB-6.3). Toast на 200. */
export function usePushToTelegram() {
  return useMutation({
    mutationFn: (body: TelegramPushRequest) => pushToTelegram(body),
    onSuccess: () => toast.success("Отправлено в Telegram"),
    onError: (err: Error) => toast.error(err.message || "Не удалось отправить в Telegram"),
  })
}

/** Токены по тирам (сегодня / за месяц) — для блока статистики OpenRouter. */
export function useTokenStats(enabled: boolean) {
  return useQuery({
    queryKey: METRICS_KEY,
    queryFn: fetchMetrics,
    enabled,
    staleTime: 60_000,
    select: tokenStatsFromMetrics,
  })
}

// B-04: `scoring_weights` уже нормализованы к 100 (валидация на PATCH) — это и есть максимум
// баллов на критерий для «X из Y» в разборе балла. Один хук вместо константы, задублированной
// с расширением (F-14 для фиксированных весов, здесь — для пользовательских).
export function useScoringWeights(): ScoringWeights | undefined {
  return useAppSettings().data?.scoring_weights
}

// Автосейв весов скоринга (UX6): тихая мутация без тоста — шкала 1-5 шлёт PATCH на каждый клик.
export function useUpdateScoringWeights() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: { weights: ScoringWeights; importance: ScoringImportance }) =>
      patchAppSettings({
        scoring_weights: payload.weights,
        scoring_importance: payload.importance,
      }),
    onSuccess: (saved) => qc.setQueryData<AppSettings>(KEY, saved),
    onError: (err: Error) => toast.error(err.message || "Не удалось сохранить веса оценки"),
  })
}

/** Конфиг автооткликов (hh/getmatch/habr) — читается вместе с остальными «Параметрами». */
export function useAutoApplyConfig(): AutoApplyConfig | undefined {
  return useAppSettings().data?.auto_apply_config
}

// Настройки автооткликов задаются в «Расширении» (ближе к месту использования), не в
// «Параметрах», но живут в том же app_settings-блобе — PATCH шлёт конфиг целиком (замена
// объекта, не merge на бэке), поэтому вызывающая сторона обязана передать уже смерженный
// AutoApplyConfig (изменила один блок площадки — остальные два взяла из текущего состояния).
export function useUpdateAutoApplyConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (config: AutoApplyConfig) => patchAppSettings({ auto_apply_config: config }),
    onSuccess: (saved) => {
      qc.setQueryData<AppSettings>(KEY, saved)
      // Порог/лимит могли измениться — превью очереди (кэш по площадке, staleTime 30с) должно
      // пересчитаться сразу, а не через полминуты, иначе «Показать очередь» врёт по старым цифрам.
      void qc.invalidateQueries({ queryKey: ["auto-apply", "preview"] })
      void qc.invalidateQueries({ queryKey: ["auto-apply", "daily-count"] })
      // Без toast.success: автосейв слайдеров спамил «сохранено» на каждое движение; старт/стоп
      // площадки и так видны по кнопке Пауза/Запустить.
    },
    onError: (err: Error) =>
      toast.error(err.message || "Не удалось сохранить настройки автооткликов"),
  })
}

// Kill switch (Фаза 7.4, расширен 2026-08-19 пункт 8): мгновенно enabled=false на всех площадках
// автооткликов И останов идущих сессий автопросмотра — одна ручка вместо двух кнопок остановки
// под одной шапкой «Расширения» (см. core/app/scenarios/auto_apply.py::pause_all). Тот же
// сценарий, что у `/pause_autoapply` в боте.
export function usePauseAutoApply() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: pauseAutoApply,
    onSuccess: (res) => {
      qc.setQueryData<AppSettings>(KEY, (prev) =>
        prev ? { ...prev, auto_apply_config: res.config } : prev,
      )
      // Бэк мог остановить и сессии автопросмотра — статусы площадок в шапке карточек должны
      // обновиться сразу, не дожидаясь их собственного 2.5с поллинга.
      void qc.invalidateQueries({ queryKey: ["discovery", "status"] })
      toast.success("Остановлено на всех площадках: автоотклики и автопросмотр")
    },
    onError: (err: Error) => toast.error(err.message || "Не удалось остановить автоотклики"),
  })
}

// Пункт 1 редизайна «Расширения» (2026-08-19): ручная очистка очереди — не kill switch (площадки
// остаются в прежнем режиме), просто пропускает всё, что сейчас видно в auto + manual_review.
export function useClearAutoApplyQueue() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: clearAutoApplyQueue,
    onSuccess: (res) => {
      void qc.invalidateQueries({ queryKey: ["auto-apply", "preview"] })
      void qc.invalidateQueries({ queryKey: ["jobs"] })
      toast.success(
        res.cleared > 0
          ? `Очередь очищена: ${res.cleared} вакансий помечены пропущенными`
          : "Очередь уже пуста",
      )
    },
    onError: (err: Error) => toast.error(err.message || "Не удалось очистить очередь"),
  })
}

/** Живое превью очереди автооткликов одной площадки — что уйдёт само, что на ручной разбор. */
// Правка (пункт 3 «Расширения»): без `refetchInterval` очередь «Отклики» обновлялась только по
// явному действию (клик по кнопке решения → invalidate, старт/пауза/стоп сессии «Просмотра») —
// вакансия, которую discovery-тик классифицировал ТУДА ЖЕ, куда и хотел владелец (bucket уже
// совпадает с желаемым решением, кнопка для него задизейблена — нечего кликать, нечем вызвать
// invalidate), реально попадала в живую очередь на бэке сразу, но здесь, в «Отклики»-панели,
// появлялась только когда стухший (`staleTime`) кэш кто-то ещё перезапрашивал — на практике это
// оказывалось только по окончании очереди «Просмотра» (там свои explicit action'ы). Лёгкий поллинг,
// пока страница «Расширение» открыта (единственное место использования этого хука) — та же
// частота порядка, что и у живого статуса `useDiscoveryStatus` (2.5с), не агрессивнее.
export function useAutoApplyPreview(platform: AutoApplyPlatform, enabled: boolean) {
  return useQuery({
    queryKey: ["auto-apply", "preview", platform],
    queryFn: () => fetchAutoApplyPreview(platform),
    enabled,
    staleTime: 30_000,
    refetchInterval: enabled ? 5_000 : false,
  })
}

/** Сколько уже отправлено сегодня против дневного лимита площадки — прогресс-бар «Отклики»
 * (Этап 3 редизайна «Расширения»), тот же источник, что и сам гейт `daily_cap` в раннере. */
export function useAutoApplyDailyCount(platform: AutoApplyPlatform, enabled: boolean) {
  return useQuery({
    queryKey: ["auto-apply", "daily-count", platform],
    queryFn: () => fetchAutoApplyDailyCount(platform),
    enabled,
    staleTime: 30_000,
  })
}

const AUTO_APPLY_PLATFORMS: AutoApplyPlatform[] = ["hh", "getmatch", "habr"]

// Фаза 7.5: job_id вакансий «на ручной разбор» автооткликов — объединение по всем ВКЛЮЧЁННЫМ
// площадкам (каждая уже отфильтрована preview_queue на auto/manual_review/excluded). Питает
// тумблер на доске «Вакансий» (JobsToolbar) — раньше это было видно только внутри раскрытой
// секции «Автоотклики» в «Расширении». Пусто, если ни одна площадка не включена.
export function useAutoApplyManualReviewIds(): number[] {
  const config = useAutoApplyConfig()
  const enabledPlatforms = AUTO_APPLY_PLATFORMS.filter((p) => config?.[p]?.enabled)
  const results = useQueries({
    queries: enabledPlatforms.map((platform) => ({
      queryKey: ["auto-apply", "preview", platform],
      queryFn: () => fetchAutoApplyPreview(platform),
      staleTime: 30_000,
    })),
  })
  const ids = new Set<number>()
  for (const result of results) {
    for (const item of result.data?.manual_review ?? []) ids.add(item.job_id)
  }
  return [...ids]
}

// Фаза 3.3/3.4: job_id вакансий в очереди подтверждения (status=pending) — анкета
// работодателя (сегодня фактически только hh.ru) ИЛИ, с 3.4, простое подтверждение письма в
// режиме «Тест» на любой площадке. Тот же паттерн объединения по включённым площадкам, что
// useAutoApplyManualReviewIds — интерфейс не завязан на конкретную площадку.
export function useAnketaPendingIds(): number[] {
  const config = useAutoApplyConfig()
  const enabledPlatforms = AUTO_APPLY_PLATFORMS.filter((p) => config?.[p]?.enabled)
  const results = useQueries({
    queries: enabledPlatforms.map((platform) => ({
      queryKey: ["auto-apply", "anketa-pending", platform],
      queryFn: () => fetchAnketaPending(platform),
      staleTime: 30_000,
    })),
  })
  const ids = new Set<number>()
  for (const result of results) {
    for (const item of result.data?.items ?? []) ids.add(item.job_id)
  }
  return [...ids]
}

/** Владелец подтверждает отклик в очереди — анкету (возможно отредактированные ответы) ИЛИ
 * (Фаза 3.4) простое письмо без анкеты (`answers: []`) — раннер реально отправит на следующем
 * тике. */
export function useConfirmAnketa() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: { jobId: number; answers: AnketaAnswer[] }) =>
      confirmAnketa(payload.jobId, payload.answers),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["auto-apply", "anketa-pending"] })
      void qc.invalidateQueries({ queryKey: ["jobs"] })
      // anketa.status денормализован в AutoApplyPreviewItem (иконка «Анкета» в очереди
      // «Расширения», Фаза E) и в ["jobs","by-vacancy",...] (ховер-превью попап).
      void qc.invalidateQueries({ queryKey: ["auto-apply", "preview"] })
      void qc.invalidateQueries({ queryKey: ["jobs", "by-vacancy"] })
      toast.success("Подтверждено — раннер отправит на следующем тике")
    },
    onError: (err: Error) => toast.error(err.message || "Не удалось подтвердить"),
  })
}

/** Владелец отклоняет отклик в очереди — раннер его больше не подхватит. */
export function useRejectAnketa() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: number) => rejectAnketa(jobId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["auto-apply", "anketa-pending"] })
      void qc.invalidateQueries({ queryKey: ["jobs"] })
      void qc.invalidateQueries({ queryKey: ["auto-apply", "preview"] })
      void qc.invalidateQueries({ queryKey: ["jobs", "by-vacancy"] })
      toast.success("Отклонено")
    },
    onError: (err: Error) => toast.error(err.message || "Не удалось отклонить"),
  })
}

/** Квик-экшен «переместить» (Фаза E редизайна «Расширения», пункт 4) — ручной оверрайд бакета
 * auto/manual_review очереди автооткликов; «В Отклик» из discovery-лога зовёт тем же путём
 * (target: "auto"). */
export function useMoveAutoApplyQueueItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ jobId, target }: { jobId: number; target: QueueOverride }) =>
      moveAutoApplyQueueItem(jobId, target),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["auto-apply", "preview"] })
    },
    onError: (err: Error) => toast.error(err.message || "Не удалось переместить вакансию"),
  })
}

/** Конфиг discovery (hh/getmatch) — читается вместе с остальными «Параметрами», настраивается
 * в «Расширении» (тот же паттерн, что useAutoApplyConfig). */
export function useDiscoveryConfig(): DiscoveryConfig | undefined {
  return useAppSettings().data?.discovery_config
}

// PATCH шлёт конфиг целиком — вызывающая сторона обязана передать уже смерженный DiscoveryConfig
// (изменила один блок площадки — вторую взяла из текущего состояния), тот же приём, что у
// useUpdateAutoApplyConfig.
export function useUpdateDiscoveryConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (config: DiscoveryConfig) => patchAppSettings({ discovery_config: config }),
    onSuccess: (saved) => {
      qc.setQueryData<AppSettings>(KEY, saved)
      toast.success("Настройки автопросмотра сохранены")
    },
    onError: (err: Error) =>
      toast.error(err.message || "Не удалось сохранить настройки автопросмотра"),
  })
}

/** Живой статус сессии discovery одной площадки — поллинг, только пока сессия реально бежит
 * (`running`); в остальных состояниях цифры меняются только по действию владельца. */
export function useDiscoveryStatus(platform: DiscoveryPlatform, enabled: boolean) {
  return useQuery({
    queryKey: ["discovery", "status", platform],
    queryFn: () => fetchDiscoveryStatus(platform),
    enabled,
    refetchInterval: (query) => (query.state.data?.state === "running" ? 2_500 : false),
  })
}

/** Старт/пауза/возобновление/стоп сессии discovery — левая панель «Расширения». */
export function useDiscoverySessionAction(platform: DiscoveryPlatform) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: { action: DiscoverySessionAction; reason?: DiscoveryPauseReason }) =>
      postDiscoverySession(platform, payload.action, payload.reason),
    onSuccess: (status) => {
      qc.setQueryData(["discovery", "status", platform], status)
      // Новые «Просмотрено» могли уже появиться за время сессии — очередь автооткликов должна
      // это увидеть сразу, а не через её собственный staleTime.
      void qc.invalidateQueries({ queryKey: ["auto-apply", "preview"] })
    },
    onError: (err: Error) => toast.error(err.message || "Не удалось изменить сессию автопросмотра"),
  })
}

const DISCOVERY_PLATFORMS = ["hh", "getmatch", "habr"] as const

/** «Очистить» в шапке «Просмотра» — лог unified по площадкам, поэтому чистим все три сразу. */
export function useClearDiscoveryEvents() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      Promise.all(DISCOVERY_PLATFORMS.map((platform) => postDiscoverySession(platform, "clear"))),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["discovery", "status"] })
    },
    onError: (err: Error) => toast.error(err.message || "Не удалось очистить лог просмотра"),
  })
}

/** Кнопка «Удалить» на сломанной (parse_error) строке лога «Просмотра» — убирает одну вакансию. */
export function useRemoveDiscoveryEvent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ platform, vacancyId }: { platform: DiscoveryPlatform; vacancyId: string }) =>
      removeDiscoveryEvent(platform, vacancyId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["discovery", "status"] })
    },
    onError: (err: Error) => toast.error(err.message || "Не удалось удалить вакансию"),
  })
}

/** Сохранить или очистить ключ OpenRouter (write-only, не смешиваем с остальными PATCH).
 *
 * Таймаут/обрыв на клиенте не значит, что сервер не записал ключ (у @nektamol 2026-08-26
 * PATCH ушёл за 31 мс, а фронт уже показал Timeout после ~76 с ожидания в браузере). Сверка
 * с GET внутри mutationFn — чтобы mutateAsync резолвился и автосейв мог очистить поле.
 */
export function useSaveOpenRouterKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (key: string) => {
      try {
        return await patchAppSettings(
          { openrouter_api_key: key },
          { skipSeriousToast: true, timeoutMs: 60_000 },
        )
      } catch (err) {
        const wantConfigured = Boolean(key.trim())
        try {
          const fresh = await fetchAppSettings({ skipSeriousToast: true })
          if (fresh.openrouter_key_configured === wantConfigured) return fresh
        } catch {
          /* сверка не удалась — пробрасываем исходную ошибку */
        }
        throw err
      }
    },
    onSuccess: (saved) => {
      qc.setQueryData<AppSettings>(KEY, saved)
      // AUTH-1: от флага ключа зависит гейт разделов — освежить статус онбординга.
      void qc.invalidateQueries({ queryKey: AUTH_STATUS_KEY })
      toast.success(
        saved.openrouter_key_configured ? "Ключ OpenRouter сохранён" : "Ключ OpenRouter удалён",
      )
    },
    onError: (err: Error) => toast.error(err.message || "Не удалось сохранить ключ OpenRouter"),
  })
}

/** Политика раскрытия под международные письма (Э4.2) — что скрываем в исходящих артефактах. */
export function useDisclosurePolicy(): DisclosurePolicy | undefined {
  return useAppSettings().data?.disclosure_policy
}

// Автосейв тумблера «Скрывать текущее место» — тихая мутация без тоста (та же логика, что у
// весов скоринга: клик по чипу сохраняет сразу, без отдельной кнопки «Сохранить»).
export function useUpdateDisclosurePolicy() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (policy: DisclosurePolicy) => patchAppSettings({ disclosure_policy: policy }),
    onSuccess: (saved) => qc.setQueryData<AppSettings>(KEY, saved),
    onError: (err: Error) => toast.error(err.message || "Не удалось сохранить настройку"),
  })
}

/** Попросить ключ у администратора. Идемпотентна на бэке — повторный клик не плодит заявки. */
export function useRequestOpenRouterKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: requestOpenRouterKey,
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: KEY })
      toast.success(result.message)
    },
    onError: (err: Error) => toast.error(err.message || "Не удалось отправить заявку"),
  })
}
