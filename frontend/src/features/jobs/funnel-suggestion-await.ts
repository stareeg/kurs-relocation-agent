/**
 * FR3-75 / FR3-77: ожидание фонового funnel_suggest после импорта дампа.
 * Состояние ключуется vacancyId — смена вакансии не должна ни поллить чужой тред,
 * ни гасить ожидание «чужим» suggested_funnel_status / общим таймером.
 */

export const FUNNEL_SUGGEST_POLL_MS = 2_500
export const FUNNEL_SUGGEST_AWAIT_MS = 30_000

export type FunnelAwaitState = {
  vacancyId: string
  startedAt: number
} | null

export function startFunnelAwait(
  vacancyId: string,
  now: number = Date.now(),
): NonNullable<FunnelAwaitState> {
  return { vacancyId, startedAt: now }
}

/** Поллить только если ждём именно текущую вакансию. */
export function shouldPollFunnelSuggestion(
  awaitState: FunnelAwaitState,
  currentVacancyId: string | null,
): boolean {
  return awaitState != null && currentVacancyId != null && awaitState.vacancyId === currentVacancyId
}

export function remainingAwaitMs(awaitState: FunnelAwaitState, now: number = Date.now()): number {
  if (!awaitState) return 0
  return Math.max(0, FUNNEL_SUGGEST_AWAIT_MS - (now - awaitState.startedAt))
}

/**
 * После рефетча / смены вакансии: сбросить ожидание только для «своей» карточки
 * (появился suggested_status или истекли 30с с момента импорта).
 * На чужой вакансии состояние не трогаем.
 */
export function resolveFunnelAwait(opts: {
  awaitState: FunnelAwaitState
  currentVacancyId: string | null
  suggestedStatus?: string | null
  now?: number
}): FunnelAwaitState {
  const { awaitState, currentVacancyId, suggestedStatus, now = Date.now() } = opts
  if (!shouldPollFunnelSuggestion(awaitState, currentVacancyId)) {
    return awaitState
  }
  if ((suggestedStatus || "").trim()) {
    return null
  }
  if (remainingAwaitMs(awaitState, now) <= 0) {
    return null
  }
  return awaitState
}
