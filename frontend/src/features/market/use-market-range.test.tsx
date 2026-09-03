// @vitest-environment jsdom
import type { ReactNode } from "react"
import { act, renderHook } from "@testing-library/react"
import { MemoryRouter, useSearchParams } from "react-router-dom"
import { afterEach, describe, expect, it } from "vitest"
import { useMarketRange } from "./use-market-range"

afterEach(() => {
  sessionStorage.clear()
})

function wrapperWithEntries(initialEntries: string[]) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
  }
}

function useHarness() {
  const [range, setRange] = useMarketRange()
  const [searchParams] = useSearchParams()
  return { range, setRange, search: searchParams.toString() }
}

describe("useMarketRange (шкала периода 2026-08-03)", () => {
  it("без параметра в адресе — дефолт: 14 дней назад по сегодня", () => {
    const { result } = renderHook(() => useHarness(), { wrapper: wrapperWithEntries(["/market"]) })
    expect(result.current.range).toEqual({ fromDays: 14, toDays: 0 })
  })

  it("читает диапазон из ?range=", () => {
    const { result } = renderHook(() => useHarness(), {
      wrapper: wrapperWithEntries(["/market?range=30-5"]),
    })
    expect(result.current.range).toEqual({ fromDays: 30, toDays: 5 })
  })

  it("незнакомое значение в адресе — фолбэк на дефолт", () => {
    const { result } = renderHook(() => useHarness(), {
      wrapper: wrapperWithEntries(["/market?range=abc"]),
    })
    expect(result.current.range).toEqual({ fromDays: 14, toDays: 0 })
  })

  it("setRange переписывает ?range= в адресе (клампнутым значением)", () => {
    const { result } = renderHook(() => useHarness(), { wrapper: wrapperWithEntries(["/market"]) })
    act(() => result.current.setRange({ fromDays: 90, toDays: 10 }))
    expect(result.current.range).toEqual({ fromDays: 90, toDays: 10 })
    expect(result.current.search).toBe("range=90-10")
  })

  it("значение переживает переход без явного ?range= (sessionStorage)", () => {
    sessionStorage.setItem("copilot.market.range", "60-20")
    const { result } = renderHook(() => useHarness(), { wrapper: wrapperWithEntries(["/market"]) })
    expect(result.current.range).toEqual({ fromDays: 60, toDays: 20 })
  })
})
