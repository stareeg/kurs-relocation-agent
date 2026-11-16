// @vitest-environment jsdom
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { MarkdownView } from "./markdown-view"

describe("MarkdownView", () => {
  it("renders tables, inline code, links, italic and nested lists", () => {
    const md = [
      "## Итог",
      "Лучшая вакансия — **Acme**, *удалённо*, id `demo-101`.",
      "",
      "| Вакансия | Балл |",
      "|---|---:|",
      "| Acme | 82 |",
      "| Globex | 64 |",
      "",
      "- Плюсы",
      "  - оплата в USD",
      "1) первый",
      "---",
      "> цитата из условий",
      "Источник: [hh](https://example.com/v/1) и https://example.com/v/2",
      "Инструмент read_work_terms вернул ошибку",
    ].join("\n")
    const { container } = render(<MarkdownView markdown={md} chat />)
    expect(container.querySelector("table")).not.toBeNull()
    expect(container.querySelectorAll("tbody tr")).toHaveLength(2)
    expect(screen.getByText("demo-101").tagName).toBe("CODE")
    expect(screen.getByText("удалённо").tagName).toBe("EM")
    expect(screen.getByText("hh").closest("a")?.getAttribute("href")).toBe("https://example.com/v/1")
    expect(container.querySelector('a[href="https://example.com/v/2"]')).not.toBeNull()
    expect(container.querySelector("hr")).not.toBeNull()
    expect(container.querySelector("blockquote")?.textContent).toContain("цитата")
    expect(screen.getByText("оплата в USD").tagName).toBe("LI")
    // snake_case в именах инструментов не превращается в курсив
    expect(screen.getByText(/read_work_terms/).textContent).toContain("read_work_terms")
    expect(container.textContent).not.toContain("|---|")
    expect(container.textContent).not.toContain("**")
  })
})
