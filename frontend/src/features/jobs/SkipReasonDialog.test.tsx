// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { SkipReasonDialog } from "./SkipReasonDialog"

// Этап 1.4 плана `plans/ui_slop_cleanup_2026_08_25.md`: причина пропуска обязательна — из неё
// собирается блок «Причины в пропуске» на «Рынке». Плюс обещание отмены должно называть место,
// где вакансию искать («Пропущено»), а не просто кнопку «Вернуть».

function renderDialog(props: Partial<Parameters<typeof SkipReasonDialog>[0]> = {}) {
  const onConfirm = vi.fn()
  const onSelect = vi.fn()
  render(
    <SkipReasonDialog
      open
      onOpenChange={() => {}}
      reasons={[]}
      selected={undefined}
      onSelect={onSelect}
      skipPending={false}
      onConfirm={onConfirm}
      {...props}
    />,
  )
  return { onConfirm, onSelect }
}

function skipButton(): HTMLButtonElement {
  const btn = screen
    .getAllByRole("button")
    .find((b) => b.textContent?.trim() === "Пропустить") as HTMLButtonElement
  expect(btn).toBeTruthy()
  return btn
}

afterEach(cleanup)

describe("SkipReasonDialog", () => {
  it("без выбранной причины «Пропустить» заблокирована и объясняет, чего ждёт", () => {
    const { onConfirm } = renderDialog()
    const btn = skipButton()
    expect(btn.disabled).toBe(true)
    expect(btn.getAttribute("title")).toBeTruthy()
    expect(screen.getByText("Сначала выберите причину")).toBeTruthy()
    fireEvent.click(btn)
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it("с выбранной причиной кнопка работает", () => {
    const { onConfirm } = renderDialog({ selected: "Низкая зарплата" })
    const btn = skipButton()
    expect(btn.disabled).toBe(false)
    expect(screen.queryByText("Сначала выберите причину")).toBeNull()
    fireEvent.click(btn)
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it("отмена описана местом, где вакансию искать, а не одной кнопкой «Вернуть»", () => {
    renderDialog()
    const description = screen.getByText(/Вакансия уйдёт из активной воронки/)
    expect(description.textContent).toContain("Пропущено")
    expect(description.textContent).not.toContain("«Вернуть»")
  })

  it("показывает статичный набор причин, когда LLM-чипов нет", () => {
    renderDialog()
    for (const label of ["Низкий грейд", "Низкая зарплата", "Не тот формат"]) {
      expect(screen.getByText(label)).toBeTruthy()
    }
  })
})
