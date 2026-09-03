import { describe, expect, it } from "vitest"
import {
  FUNNEL_SUGGEST_AWAIT_MS,
  remainingAwaitMs,
  resolveFunnelAwait,
  shouldPollFunnelSuggestion,
  startFunnelAwait,
} from "./funnel-suggestion-await"

describe("funnel-suggestion-await (FR3-75/77)", () => {
  const t0 = 1_000_000

  it("поллит только вакансию, для которой ждём предложение", () => {
    const awaitA = startFunnelAwait("vac-a", t0)
    expect(shouldPollFunnelSuggestion(awaitA, "vac-a")).toBe(true)
    expect(shouldPollFunnelSuggestion(awaitA, "vac-b")).toBe(false)
    expect(shouldPollFunnelSuggestion(awaitA, null)).toBe(false)
    expect(shouldPollFunnelSuggestion(null, "vac-a")).toBe(false)
  })

  it("смена вакансии не гасит ожидание чужим suggested_status", () => {
    const awaitA = startFunnelAwait("vac-a", t0)
    // На B уже есть старый чип — не должен обнулить ожидание A.
    const next = resolveFunnelAwait({
      awaitState: awaitA,
      currentVacancyId: "vac-b",
      suggestedStatus: "Техничка",
      now: t0 + 5_000,
    })
    expect(next).toEqual(awaitA)
    expect(shouldPollFunnelSuggestion(next, "vac-b")).toBe(false)
  })

  it("возврат на исходную вакансию возобновляет полл; suggestion снимает ожидание", () => {
    const awaitA = startFunnelAwait("vac-a", t0)
    const whileAway = resolveFunnelAwait({
      awaitState: awaitA,
      currentVacancyId: "vac-b",
      suggestedStatus: null,
      now: t0 + 5_000,
    })
    expect(whileAway).toEqual(awaitA)

    const backWithout = resolveFunnelAwait({
      awaitState: whileAway,
      currentVacancyId: "vac-a",
      suggestedStatus: null,
      now: t0 + 6_000,
    })
    expect(backWithout).toEqual(awaitA)
    expect(shouldPollFunnelSuggestion(backWithout, "vac-a")).toBe(true)

    const backWith = resolveFunnelAwait({
      awaitState: backWithout,
      currentVacancyId: "vac-a",
      suggestedStatus: "Скрининг",
      now: t0 + 7_000,
    })
    expect(backWith).toBeNull()
  })

  it("таймер 30с считается от старта импорта, не от возврата на карточку", () => {
    const awaitA = startFunnelAwait("vac-a", t0)
    expect(remainingAwaitMs(awaitA, t0 + 10_000)).toBe(FUNNEL_SUGGEST_AWAIT_MS - 10_000)

    // Ушли на B почти до конца окна — на B не сбрасываем.
    const mid = resolveFunnelAwait({
      awaitState: awaitA,
      currentVacancyId: "vac-b",
      suggestedStatus: null,
      now: t0 + FUNNEL_SUGGEST_AWAIT_MS - 1_000,
    })
    expect(mid).toEqual(awaitA)

    // Вернулись после истечения — снимаем ожидание, не крутим полл вечно.
    const expired = resolveFunnelAwait({
      awaitState: mid,
      currentVacancyId: "vac-a",
      suggestedStatus: null,
      now: t0 + FUNNEL_SUGGEST_AWAIT_MS + 500,
    })
    expect(expired).toBeNull()
  })
})
