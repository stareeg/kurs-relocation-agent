// @vitest-environment jsdom
/**
 * Диагностический аудит раскладки «Зарплат» (2026-08-08, редизайн 2026-08-11).
 *
 * Раньше медиана/P25/P75 рисовались как три подписанные линии, разведённые по строкам
 * («lanes») под осью — при близких значениях (медиана внутри целевого диапазона) подписи
 * всё равно наезжали друг на друга или тесно жались у края. Редизайн 2026-08-11 убрал сам
 * источник коллизии: числа живут в одной текстовой строке над графиком (обычный текст, не
 * SVG), а в графике остаются только непосписанные позиционные ориентиры (тонкая линия
 * медианы, две короткие насечки P25/P75) — им нечего разводить по строкам, наезжать не на что.
 *
 * Этот файл проверяет ровно это: у позиционных маркеров валидные координаты в границах
 * chart area независимо от того, насколько близко сходятся медиана/P25/P75/зона цели.
 */
import { describe, expect, it } from "vitest"
import { salaryDistributionLayout } from "./salary-distribution-geometry"

describe("SalaryDistribution: маркеры без коллизий подписей", () => {
  const input = {
    points: [300000, 330000, 360000, 390000, 420000, 450000, 480000, 510000, 540000],
    targetMin: 374000,
    targetMax: 450000,
    median: 400000,
    p25: 360000,
    p75: 480000,
    offers: [{ key: "o1", company: "Сбер", value: 540000 }],
  }

  it("медиана внутри целевого диапазона — координаты валидны, подписывать нечего", () => {
    const layout = salaryDistributionLayout(input, 528, 180)!
    expect(layout.medianMarker).not.toBeNull()
    expect(layout.medianMarker!.x).toBeGreaterThanOrEqual(0)
    expect(layout.medianMarker!.x).toBeLessThanOrEqual(528)
    expect(layout.quartileTicks).toHaveLength(2)
    for (const t of layout.quartileTicks) {
      expect(t.x).toBeGreaterThanOrEqual(0)
    }
    // Скобка цели — своя позиция, не завязана на лены маркеров (их больше нет в контракте).
    expect(layout.targetBracket).not.toBeNull()
    expect(layout.targetBracket!.width).toBeGreaterThan(0)
  })

  it("медиана/P75/зона у правого края — якорь скобки уходит внутрь (end), не обрезается", () => {
    const farRight: typeof input = {
      ...input,
      median: 530000,
      p75: 540000,
      targetMin: 520000,
      targetMax: 560000,
    }
    const layout = salaryDistributionLayout(farRight, 528, 180)!
    expect(layout.targetBracket!.labelAnchor).toBe("end")
    // Насечка P75 не вылезает за правую границу chart area.
    const p75Tick = layout.quartileTicks.find((t) => t.key === "p75")!
    expect(p75Tick.x).toBeLessThanOrEqual(528)
  })
})
