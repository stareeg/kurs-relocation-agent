import { describe, expect, it } from "vitest"
import { categoryBarsLayout, type CategoryBarsInput } from "./category-bars-geometry"

const W = 320
const H = 180

function input(rows: { key: string; label: string; value: number }[]): CategoryBarsInput {
  return { rows, unit: "вак." }
}

describe("categoryBarsLayout", () => {
  it("возвращает null при пустом входе", () => {
    expect(categoryBarsLayout(input([]), W, H)).toBeNull()
  })

  it("возвращает null при слишком малой ширине", () => {
    expect(categoryBarsLayout(input([{ key: "a", label: "A", value: 5 }]), 10, H)).toBeNull()
  })

  it("возвращает null при слишком малой высоте", () => {
    expect(categoryBarsLayout(input([{ key: "a", label: "A", value: 5 }]), W, 10)).toBeNull()
  })

  it("кладёт столбцы в слоты одинаковой ширины", () => {
    const layout = categoryBarsLayout(
      input([
        { key: "a", label: "A", value: 1 },
        { key: "b", label: "B", value: 2 },
        { key: "c", label: "C", value: 3 },
      ]),
      W,
      H,
    )!
    expect(layout.rows).toHaveLength(3)
    const slot = layout.chartW / 3
    expect(layout.rows[0]!.x).toBeCloseTo(0 + (slot * 0.18) / 2, 1)
    // Второй слот начинается правее первого на ширину slot.
    expect(layout.rows[1]!.x).toBeGreaterThan(layout.rows[0]!.x + layout.rows[0]!.width)
    expect(layout.rows[2]!.x).toBeGreaterThan(layout.rows[1]!.x + layout.rows[1]!.width)
    // Все столбцы одинаковой ширины.
    expect(layout.rows[0]!.width).toBeCloseTo(layout.rows[2]!.width, 5)
  })

  it("масштабирует высоту по домену Y", () => {
    const layout = categoryBarsLayout(
      input([
        { key: "a", label: "A", value: 0 },
        { key: "b", label: "B", value: 100 },
      ]),
      W,
      H,
    )!
    // Нулевой столбец — нулевая высота, второй — на всю chartH (после niceMax ~ 100..200).
    expect(layout.rows[0]!.height).toBe(0)
    expect(layout.rows[1]!.height).toBeCloseTo(layout.chartH, 1)
  })

  it("yMax из input бьёт niceMax", () => {
    const layout = categoryBarsLayout(
      { rows: [{ key: "a", label: "A", value: 30 }], unit: "%", yMax: 100 },
      W,
      H,
    )!
    expect(layout.yMax).toBe(100)
    // Высота = 30/100 от chartH.
    expect(layout.rows[0]!.height).toBeCloseTo(layout.chartH * 0.3, 1)
  })

  it("три тика оси Y: 0, середина, max", () => {
    const layout = categoryBarsLayout(input([{ key: "a", label: "A", value: 10 }]), W, H)!
    expect(layout.yTicks).toHaveLength(3)
    expect(layout.yTicks[0]!.label).toBe("0")
    expect(layout.yTicks[2]!.y).toBe(0) // max — сверху
  })

  it("поворачивает подписи X при тесноте (>4 категорий и длинные)", () => {
    const longRows = Array.from({ length: 6 }, (_, i) => ({
      key: `k${i}`,
      label: `Длинная категория ${i}`,
      value: i + 1,
    }))
    const layout = categoryBarsLayout(input(longRows), W, H)!
    expect(layout.xLabelMode).toBe("rotated")
  })

  it("горизонтальные подписи при коротких категориях", () => {
    const layout = categoryBarsLayout(
      input([
        { key: "a", label: "A", value: 1 },
        { key: "b", label: "B", value: 2 },
      ]),
      W,
      H,
    )!
    expect(layout.xLabelMode).toBe("horizontal")
  })

  it("valueLabel включает единицу", () => {
    const layout = categoryBarsLayout(input([{ key: "a", label: "A", value: 7 }]), W, H)!
    expect(layout.rows[0]!.valueLabel).toBe("7 вак.")
  })

  it("не падает на отрицательных / NaN значениях — фильтрует их", () => {
    const layout = categoryBarsLayout(
      input([
        { key: "a", label: "A", value: -5 },
        { key: "b", label: "B", value: 3 },
        { key: "c", label: "C", value: Number.NaN },
      ]),
      W,
      H,
    )!
    expect(layout.rows.map((r) => r.key)).toEqual(["b"])
  })

  describe("showPercent", () => {
    it("считает долю от суммы строк, когда `.pct` не задан", () => {
      const layout = categoryBarsLayout(
        {
          rows: [
            { key: "a", label: "A", value: 1 },
            { key: "b", label: "B", value: 3 },
          ],
          showPercent: true,
        },
        W,
        H,
      )!
      expect(layout.rows[0]!.valueLabel).toBe("25%")
      expect(layout.rows[1]!.valueLabel).toBe("75%")
    })

    it("предпочитает готовую `.pct` с бэка вместо доли от суммы", () => {
      const layout = categoryBarsLayout(
        {
          rows: [{ key: "a", label: "A", value: 5, pct: 41.7 }],
          showPercent: true,
        },
        W,
        H,
      )!
      expect(layout.rows[0]!.valueLabel).toBe("42%")
    })

    it("tooltipValueLabel — всегда абсолютное число с единицей, даже в процентном режиме", () => {
      const layout = categoryBarsLayout(
        {
          rows: [{ key: "a", label: "A", value: 5 }],
          unit: "вак.",
          showPercent: true,
        },
        W,
        H,
      )!
      expect(layout.rows[0]!.tooltipValueLabel).toBe("5 вак.")
      expect(layout.rows[0]!.valueLabel).toBe("100%")
    })

    it("без showPercent tooltipValueLabel совпадает с valueLabel", () => {
      const layout = categoryBarsLayout(input([{ key: "a", label: "A", value: 7 }]), W, H)!
      expect(layout.rows[0]!.tooltipValueLabel).toBe(layout.rows[0]!.valueLabel)
    })
  })

  describe("placeholder", () => {
    it("столбец-плейсхолдер с value=0 получает минимальную высоту, а не 0", () => {
      const layout = categoryBarsLayout(
        {
          rows: [
            { key: "a", label: "A", value: 50 },
            { key: "b", label: "Скиллы", value: 0, placeholder: true },
          ],
        },
        W,
        H,
      )!
      const placeholderBar = layout.rows[1]!
      expect(placeholderBar.height).toBeGreaterThan(0)
      expect(placeholderBar.height).toBeLessThan(layout.rows[0]!.height)
      // Подпись значения не рисуется — плейсхолдер не выглядит как настоящий 0-балльный вклад.
      expect(placeholderBar.value).toBe(0)
    })

    it("плейсхолдер не влияет на масштаб оси Y", () => {
      const withPlaceholder = categoryBarsLayout(
        {
          rows: [
            { key: "a", label: "A", value: 10 },
            { key: "b", label: "B", value: 0, placeholder: true },
          ],
        },
        W,
        H,
      )!
      const withoutPlaceholder = categoryBarsLayout(
        input([{ key: "a", label: "A", value: 10 }]),
        W,
        H,
      )!
      expect(withPlaceholder.yMax).toBe(withoutPlaceholder.yMax)
    })
  })
})
