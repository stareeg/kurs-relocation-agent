import { describe, expect, it } from "vitest"
import type { SkipReasonCount } from "@/api/market"
import { dropoutReasonBars } from "./dropout-reasons"

describe("dropoutReasonBars", () => {
  it("короткие подписи, в порядке Зарплата/Формат/Грейд/Роль/Домен/Компания", () => {
    const reasons: SkipReasonCount[] = [
      { reason: "Избегать компанию", count: 2 },
      { reason: "Низкая зарплата", count: 5 },
      { reason: "Не тот стек/домен", count: 1 },
      { reason: "Не та роль (IC vs рук)", count: 3 },
    ]
    const bars = dropoutReasonBars(reasons)
    expect(bars).toEqual([
      { key: "Низкая зарплата", label: "Зарплата", value: 5 },
      { key: "Не та роль (IC vs рук)", label: "Роль", value: 3 },
      { key: "Не тот стек/домен", label: "Домен", value: 1 },
      { key: "Избегать компанию", label: "Компания", value: 2 },
    ])
  })

  it("нулевые причины не рисуются", () => {
    const reasons: SkipReasonCount[] = [
      { reason: "Низкая зарплата", count: 0 },
      { reason: "Низкий грейд", count: 4 },
    ]
    expect(dropoutReasonBars(reasons)).toEqual([{ key: "Низкий грейд", label: "Грейд", value: 4 }])
  })

  it("нет данных → []", () => {
    expect(dropoutReasonBars(undefined)).toEqual([])
    expect(dropoutReasonBars([])).toEqual([])
  })
})
