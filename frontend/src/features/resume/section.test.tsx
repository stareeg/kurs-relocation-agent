// @vitest-environment jsdom
import { useEffect } from "react"
import { cleanup, render } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"
import { NeedsFillWrap } from "./section"

afterEach(() => {
  cleanup()
})

describe("NeedsFillWrap", () => {
  it("не размонтирует children при смене active — иначе инпут теряет фокус", () => {
    let mounts = 0
    function Probe() {
      useEffect(() => {
        mounts += 1
      }, [])
      return <input data-testid="probe" />
    }

    const { rerender } = render(
      <NeedsFillWrap active>
        <Probe />
      </NeedsFillWrap>,
    )
    expect(mounts).toBe(1)

    rerender(
      <NeedsFillWrap active={false}>
        <Probe />
      </NeedsFillWrap>,
    )
    expect(mounts).toBe(1)
  })
})
