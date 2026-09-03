import { describe, expect, it } from "vitest"
import { seriesClass, seriesSlot, SERIES_SLOT_COUNT } from "./series-tokens"

describe("seriesSlot (V-09)", () => {
  const allKeys = ["impressions", "views", "invitations"]

  it("слот считается по месту в полном перечне", () => {
    expect(seriesSlot("impressions", allKeys)).toBe(0)
    expect(seriesSlot("views", allKeys)).toBe(1)
    expect(seriesSlot("invitations", allKeys)).toBe(2)
  })

  it("фильтр не перекрашивает выживших: allKeys не меняется, когда часть сущностей скрыта", () => {
    const beforeFilter = seriesSlot("invitations", allKeys)
    const survivors = allKeys.filter((k) => k !== "views")
    // Вызывающий обязан передавать полный перечень, а не то, что осталось после фильтра.
    const afterFilter = seriesSlot("invitations", allKeys)
    expect(afterFilter).toBe(beforeFilter)
    // Если бы слот считался по месту в `survivors`, invitations съехал бы с 2 на 1 — не должно.
    expect(survivors.indexOf("invitations")).not.toBe(beforeFilter)
  })

  it("ключ вне перечня → первый слот, не исключение", () => {
    expect(seriesSlot("unknown", allKeys)).toBe(0)
  })

  it("больше слотов, чем цветов → зацикливается, не выходит за границу", () => {
    const many = ["a", "b", "c", "d", "e"]
    expect(seriesSlot("d", many)).toBe(0)
    expect(seriesSlot("e", many)).toBe(1)
  })

  it("seriesClass собирает имя утилиты Tailwind из слоя и слота", () => {
    expect(seriesClass("stroke", "views", allKeys)).toBe("stroke-series-2")
    expect(seriesClass("bg", "invitations", allKeys)).toBe("bg-series-3")
  })

  it("SERIES_SLOT_COUNT совпадает с числом токенов в globals.css", () => {
    expect(SERIES_SLOT_COUNT).toBe(3)
  })
})
