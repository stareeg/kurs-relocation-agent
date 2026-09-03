// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import { SectionCard } from "./section-card"

afterEach(() => {
  cleanup()
})

describe("SectionCard (V-10)", () => {
  it("content без refreshing — обычный кадр, без приглушения", () => {
    render(
      <SectionCard id="s" title="Заголовок" status="content">
        <p>данные</p>
      </SectionCard>,
    )
    const body = screen.getByText("данные").parentElement!
    expect(body.className).not.toMatch(/opacity-/)
    expect(body.getAttribute("aria-busy")).toBeNull()
  })

  it("content + refreshing — держит прошлый кадр приглушённым, не подменяет на скелет", () => {
    render(
      <SectionCard
        id="s"
        title="Заголовок"
        status="content"
        refreshing
        loading={<span>скелет</span>}
      >
        <p>прошлые данные</p>
      </SectionCard>,
    )
    expect(screen.queryByText("скелет")).toBeNull()
    const body = screen.getByText("прошлые данные").parentElement!
    expect(body.className).toMatch(/opacity-60/)
    expect(body.getAttribute("aria-busy")).toBe("true")
  })

  it("loading игнорирует refreshing — рисуется скелет, не дети", () => {
    render(
      <SectionCard
        id="s"
        title="Заголовок"
        status="loading"
        refreshing
        loading={<span>скелет</span>}
      >
        <p>данные</p>
      </SectionCard>,
    )
    expect(screen.getByText("скелет")).toBeTruthy()
    expect(screen.queryByText("данные")).toBeNull()
  })
})
