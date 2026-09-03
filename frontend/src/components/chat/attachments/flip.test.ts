import { describe, expect, it } from "vitest"
import { flipKeyframes } from "./flip"

function rect(x: number, y: number, width: number, height: number): DOMRect {
  return { x, y, left: x, top: y, width, height, right: x + width, bottom: y + height } as DOMRect
}

describe("flipKeyframes", () => {
  it("конечный кадр всегда none — картинка оседает в натуральном месте", () => {
    const [, end] = flipKeyframes(rect(0, 0, 64, 64), rect(200, 100, 640, 480))
    expect(end).toEqual({ transform: "none" })
  })

  it("одинаковые rect-ы — вырожденный кадр без сдвига/масштаба", () => {
    const [start] = flipKeyframes(rect(10, 10, 100, 100), rect(10, 10, 100, 100))
    expect(start.transform).toBe("translate(0px, 0px) scale(1, 1)")
  })

  it("миниатюра меньше и левее — стартовый кадр сжимает и сдвигает влево-вверх", () => {
    const [start] = flipKeyframes(rect(20, 30, 64, 64), rect(200, 150, 640, 480))
    // Центр миниатюры (52, 62) минус центр финала (520, 390) → (-468, -328); масштаб 64/640=0.1, 64/480≈0.1333
    expect(start.transform).toBe("translate(-468px, -328px) scale(0.1, 0.13333333333333333)")
  })

  it("нулевой размер финального rect не делит на ноль", () => {
    const [start] = flipKeyframes(rect(0, 0, 64, 64), rect(0, 0, 0, 0))
    expect(start.transform).toContain("scale(1, 1)")
  })
})
