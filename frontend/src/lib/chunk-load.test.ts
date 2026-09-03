import { describe, expect, it } from "vitest"
import { isChunkLoadError } from "./chunk-load"

describe("isChunkLoadError", () => {
  it("recognizes Chrome's dynamic import 404", () => {
    expect(
      isChunkLoadError(
        new TypeError(
          "Failed to fetch dynamically imported module: https://example.com/assets/CareerPage-abc.js",
        ),
      ),
    ).toBe(true)
  })

  it("recognizes Safari's module script failure", () => {
    expect(isChunkLoadError(new TypeError("Importing a module script failed."))).toBe(true)
  })

  it("ignores ordinary errors", () => {
    expect(isChunkLoadError(new Error("Network timeout"))).toBe(false)
    expect(isChunkLoadError("nope")).toBe(false)
  })
})
