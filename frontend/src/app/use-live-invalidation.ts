import { useEffect, useState } from "react"
import { useQueryClient, type QueryKey } from "@tanstack/react-query"
import { liveEvents, type LiveEventPayload } from "@/api/live-events"

/**
 * Событие домена (`kernel/events.py`) → какие query keys освежить (L-45, F-04).
 *
 * Соответствует дирти-мэппингу снапшотов рынка (`domains/market/events.py`, L-26): grid/pulse/
 * search грязнятся теми же событиями; calibration/money/chance-history/companies — живые срезы
 * «Рынка» с тем же входом (вакансии/этапы/офферы/HR). `["resume","skills"]` — скорингом и
 * резюме; доска вакансий — всем, что меняет карточку.
 *
 * Каждый тип из `FIRST_ORDER_EVENTS` обязан иметь запись здесь — тест `use-live-invalidation.
 * test.ts` сверяет список с `core/kernel/events.py`. Резолвер получает весь payload, а не только
 * `type`: `ScreeningPackReady`/`InterviewDebriefed` точечно инвалидируют по `subject`
 * (`vacancy_id`), а не весь раздел целиком.
 */
type QueryKeysResolver = (payload: LiveEventPayload) => readonly QueryKey[]

/** Срезы «Рынка», которые пересчитываются при смене воронки/скоринга (F-04). */
const MARKET_ANALYTICS_KEYS: readonly QueryKey[] = [
  ["market-pulse"],
  ["market-search"],
  ["market-calibration"],
  ["market-money"],
  ["market-chance-history"],
  ["companies"],
]

const JOB_BOARD_KEYS: readonly QueryKey[] = [
  ["jobs"],
  ["jobs", "active-count"],
  ["jobs", "stage-counts"],
  ["vacancy-events"],
  ...MARKET_ANALYTICS_KEYS,
]

/** Ключи для событий, у которых `subject` — id вакансии; без subject раздел не трогаем. */
function byVacancySubject(keys: (vacancyId: string) => readonly QueryKey[]): QueryKeysResolver {
  return (payload) => (payload.subject ? keys(payload.subject) : [])
}

export const EVENT_QUERY_KEYS: Readonly<Record<string, QueryKeysResolver>> = {
  // ["discovery","status"] — правка 2026-08-19 (баг 5): вакансия из «Просмотра», которую не
  // удалось оценить с первого раза, донасчитывается позже (владелец открыл её вручную) — без
  // этого ключа список «Автопросмотр» не узнаёт о свежем скоре, пока сессия не бежит (поллинг
  // discovery-статуса включён только при state === "running").
  VacancyScored: () => [...JOB_BOARD_KEYS, ["resume", "skills"], ["discovery", "status"]],
  VacancyDeduplicated: () => JOB_BOARD_KEYS,
  ApplicationStageChanged: () => JOB_BOARD_KEYS,
  HrMessageReceived: () => JOB_BOARD_KEYS,
  ScreeningPackReady: byVacancySubject((vacancyId) => [["screening-questions", vacancyId]]),
  InterviewDebriefed: byVacancySubject((vacancyId) => [
    ["prep", vacancyId],
    ["debrief", vacancyId],
    ["interview-stages", vacancyId],
    ["vacancy-events", vacancyId],
  ]),
  OfferReceived: () => JOB_BOARD_KEYS,
  // Профиль/списки компаний → подписи KPI, money.salary_min, verdict в реестре.
  ResumeUpdated: () => [
    ["market-pulse"],
    ["market-money"],
    ["companies"],
    ["resume", "skills"],
    ["resume", "international"],
  ],
  // Распознавание стартует на upload, до привязки к сообщению/вакансии — инвалидируем само
  // вложение (`["attachment", id]`), а не раздел целиком (F-04, chat_image_attachments plan §Э1-7).
  AttachmentAnalyzed: byVacancySubject((attachmentId) => [["attachment", attachmentId]]),
  // ST-01: переключение режима освежает пилюли (обычно и так обновлены оптимистично).
  SearchModeChanged: () => [["career", "search-mode"]],
  SearchTrackChanged: () => [
    ["career", "search-track"],
    ["resume", "international"],
  ],
}

/**
 * F-05: полный рефреш всех ключей из карты на реконнект — по первому сегменту, React Query
 * матчит query key по префиксу, так что `["screening-questions"]` накрывает и
 * `["screening-questions", vacancyId]`. Дёшево и покрывает то, что канал молча потерял, пока
 * был разорван (бэк реплей не хранит).
 */
export function allTrackedKeyPrefixes(): readonly QueryKey[] {
  const sample: LiveEventPayload = { type: "", subject: "reconnect" }
  const seen = new Map<string, QueryKey>()
  for (const resolve of Object.values(EVENT_QUERY_KEYS)) {
    for (const key of resolve(sample)) {
      const prefix = [key[0]]
      seen.set(JSON.stringify(prefix), prefix)
    }
  }
  return [...seen.values()]
}

/** Один раз на приложение (AppShell): подписка на живой канал + инвалидация по мэппингу. */
export function useLiveEventInvalidation(): void {
  const qc = useQueryClient()
  useEffect(() => {
    liveEvents.start()
    const unbindVisibility = liveEvents.bindVisibilityPause()
    const unsubEvent = liveEvents.onEvent((payload: LiveEventPayload) => {
      const resolve = EVENT_QUERY_KEYS[payload.type]
      if (!resolve) return
      for (const key of resolve(payload)) {
        void qc.invalidateQueries({ queryKey: key })
      }
    })
    const unsubReconnect = liveEvents.onReconnect(() => {
      for (const key of allTrackedKeyPrefixes()) {
        void qc.invalidateQueries({ queryKey: key })
      }
    })
    return () => {
      unbindVisibility()
      unsubEvent()
      unsubReconnect()
    }
  }, [qc])
}

/** Состояние живого канала — потребители переключаются на поллинг-фолбэк, пока `false`. */
export function useLiveEventsConnected(): boolean {
  const [connected, setConnected] = useState(() => liveEvents.isConnected())
  useEffect(() => liveEvents.onConnectionChange(setConnected), [])
  return connected
}
