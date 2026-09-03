import { describe, expect, it } from "vitest"
import {
  attachmentGridLayout,
  classifyImage,
  singleImageLayout,
  visibleAttachmentCount,
} from "./layout"

describe("classifyImage", () => {
  it("мелкая — обе стороны < 96px", () => {
    expect(classifyImage(80, 60)).toBe("tiny")
  })

  it("обычная — аспект в [0.5, 3]", () => {
    expect(classifyImage(600, 400)).toBe("normal")
    expect(classifyImage(300, 600)).toBe("normal") // ratio 0.5 — граница включена
    expect(classifyImage(900, 300)).toBe("normal") // ratio 3 — граница включена
  })

  it("длинный скрин — w/h < 0.5", () => {
    expect(classifyImage(200, 900)).toBe("tall")
  })

  it("широкая — w/h > 3", () => {
    expect(classifyImage(1000, 200)).toBe("wide")
  })

  it("одна сторона >= 96px — уже не мелкая, даже если вторая крошечная", () => {
    expect(classifyImage(96, 40)).not.toBe("tiny")
  })
})

describe("singleImageLayout", () => {
  it("мелкая — обёртка с рамкой/подложкой, без растяжения", () => {
    const layout = singleImageLayout(64, 48)
    expect(layout.case).toBe("tiny")
    expect(layout.showExpandButton).toBe(false)
    expect(layout.wrapClassName).toContain("border")
  })

  it("длинный скрин без expanded — обрезан, кнопка+градиент показаны", () => {
    const layout = singleImageLayout(200, 900)
    expect(layout.case).toBe("tall")
    expect(layout.showExpandButton).toBe(true)
    expect(layout.showFadeOverlay).toBe(true)
    expect(layout.objectPosition).toBe("top")
  })

  it("длинный скрин c expanded — кнопка/градиент скрыты, высота больше", () => {
    const collapsed = singleImageLayout(200, 900)
    const expanded = singleImageLayout(200, 900, { expanded: true })
    expect(expanded.showExpandButton).toBe(false)
    expect(expanded.showFadeOverlay).toBe(false)
    expect(expanded.wrapClassName).not.toBe(collapsed.wrapClassName)
  })

  it("широкая — object-position left, без кнопки разворота", () => {
    const layout = singleImageLayout(1200, 300)
    expect(layout.case).toBe("wide")
    expect(layout.objectPosition).toBe("left")
    expect(layout.showExpandButton).toBe(false)
  })

  it("обычная — object-position center, без спецэффектов", () => {
    const layout = singleImageLayout(640, 480)
    expect(layout.case).toBe("normal")
    expect(layout.objectPosition).toBe("center")
    expect(layout.showExpandButton).toBe(false)
    expect(layout.showFadeOverlay).toBe(false)
  })
})

describe("attachmentGridLayout", () => {
  it("1 картинка — одна ячейка, без переполнения", () => {
    const grid = attachmentGridLayout(1)
    expect(grid.cellClassNames).toHaveLength(1)
    expect(grid.overflowCount).toBe(0)
  })

  it("2 картинки — 1×2 равные", () => {
    const grid = attachmentGridLayout(2)
    expect(grid.cellClassNames).toHaveLength(2)
    expect(grid.overflowCount).toBe(0)
  })

  it("3 картинки — первая ячейка растянута на обе строки", () => {
    const grid = attachmentGridLayout(3)
    expect(grid.cellClassNames).toHaveLength(3)
    expect(grid.cellClassNames[0]).toContain("row-span-2")
    expect(grid.overflowCount).toBe(0)
  })

  it("4 картинки — 2×2, без переполнения", () => {
    const grid = attachmentGridLayout(4)
    expect(grid.cellClassNames).toHaveLength(4)
    expect(grid.overflowCount).toBe(0)
  })

  it("5+ картинок — 2×2 сетка, остаток уходит в overflowCount", () => {
    const grid = attachmentGridLayout(7)
    expect(grid.cellClassNames).toHaveLength(4)
    expect(grid.overflowCount).toBe(3)
  })
})

describe("visibleAttachmentCount", () => {
  it("не больше 4 видимых ячеек", () => {
    expect(visibleAttachmentCount(2)).toBe(2)
    expect(visibleAttachmentCount(4)).toBe(4)
    expect(visibleAttachmentCount(9)).toBe(4)
  })
})
