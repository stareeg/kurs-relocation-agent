import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { OfferRecord } from "@/api/offers"
import { allOffersOverdue, deadlineCountdown, isOfferOverdue, isOfferUndecided } from "./deadline"

// Этап 1.5 плана `plans/ui_slop_cleanup_2026_08_25.md`: просроченный оффер продолжал считаться
// живым — попадал в сравнение и в разбор агента наравне с актуальными, а на экране был только
// красной строкой без действия. Здесь закреплено, кого считаем просроченным.

const NOW = new Date("2026-08-25T12:00:00Z")

function offer(p: Partial<OfferRecord>): OfferRecord {
  return { vacancy_id: "1", status: "thinking", ...p } as OfferRecord
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
})
afterEach(() => {
  vi.useRealTimers()
})

describe("deadlineCountdown", () => {
  it("пустой и неразобранный дедлайн — счётчика нет", () => {
    expect(deadlineCountdown(null)).toBeNull()
    expect(deadlineCountdown("")).toBeNull()
    expect(deadlineCountdown("не дата")).toBeNull()
  })

  it("будущая дата — сколько осталось, без пометки просрочки", () => {
    expect(deadlineCountdown("2026-08-28T12:00:00Z")).toEqual({
      text: "осталось 3 дн.",
      overdue: false,
    })
  })

  // Округление вверх по суткам: остаток меньше суток — уже «осталось 1 дн.», а «сегодня»
  // достаётся дедлайну, который прошёл меньше суток назад. Поведение перенесено из
  // `OfferCard.tsx` как есть — здесь оно только закреплено, чтобы не поехало при правках.
  it("меньше суток впереди — округляется вверх до одного дня", () => {
    expect(deadlineCountdown("2026-08-25T20:00:00Z")).toEqual({
      text: "осталось 1 дн.",
      overdue: false,
    })
  })

  it("прошёл сегодня, меньше суток назад — «сегодня», ещё не просрочка", () => {
    expect(deadlineCountdown("2026-08-25T06:00:00Z")).toEqual({ text: "сегодня", overdue: false })
  })

  it("прошедшая дата — просрочка", () => {
    expect(deadlineCountdown("2026-08-20T12:00:00Z")).toEqual({
      text: "дедлайн прошёл",
      overdue: true,
    })
  })
})

describe("isOfferUndecided", () => {
  it("решение не принято — только по такому офферу считаем дедлайн", () => {
    expect(isOfferUndecided(offer({ status: "thinking" }))).toBe(true)
  })

  it("и принятый, и отклонённый — закрытые истории", () => {
    expect(isOfferUndecided(offer({ status: "accepted" }))).toBe(false)
    expect(isOfferUndecided(offer({ status: "declined" }))).toBe(false)
  })
})

describe("isOfferOverdue", () => {
  it("оффер без дедлайна просроченным не считается", () => {
    expect(isOfferOverdue(offer({ deadline: null }))).toBe(false)
  })

  it("нерешённый оффер с прошедшей датой — просрочен", () => {
    expect(isOfferOverdue(offer({ deadline: "2026-08-20" }))).toBe(true)
  })

  it("отклонённый оффер не напоминает о дедлайне — он уже неважен", () => {
    expect(isOfferOverdue(offer({ deadline: "2026-08-20", status: "declined" }))).toBe(false)
  })

  // Живой случай владельца на 2026-08-25: оффер Сбера принят, дата ответа давно прошла.
  // Предлагать «отметить отклонённым» принятый оффер — прямой вред.
  it("принятый оффер тоже не просрочен: выбор уже сделан", () => {
    expect(isOfferOverdue(offer({ deadline: "2026-07-23", status: "accepted" }))).toBe(false)
  })
})

describe("allOffersOverdue", () => {
  it("пустой список — не повод писать «все дедлайны прошли»", () => {
    expect(allOffersOverdue([])).toBe(false)
  })

  it("один живой оффер среди просроченных снимает предупреждение", () => {
    expect(
      allOffersOverdue([
        offer({ vacancy_id: "1", deadline: "2026-08-20" }),
        offer({ vacancy_id: "2", deadline: "2026-09-10" }),
      ]),
    ).toBe(false)
  })

  it("все действующие просрочены — предупреждение уместно", () => {
    expect(
      allOffersOverdue([
        offer({ vacancy_id: "1", deadline: "2026-08-20" }),
        offer({ vacancy_id: "2", deadline: "2026-07-01" }),
      ]),
    ).toBe(true)
  })

  it("решённые в расчёт не идут: набор из одних отклонённых — не «все просрочены»", () => {
    expect(
      allOffersOverdue([offer({ vacancy_id: "1", deadline: "2026-08-20", status: "declined" })]),
    ).toBe(false)
  })

  it("принятый оффер снимает предупреждение: выбор сделан, а не сроки вышли", () => {
    expect(
      allOffersOverdue([
        offer({ vacancy_id: "1", deadline: "2026-07-23", status: "accepted" }),
        offer({ vacancy_id: "2", deadline: "2026-07-20", status: "declined" }),
      ]),
    ).toBe(false)
  })
})
