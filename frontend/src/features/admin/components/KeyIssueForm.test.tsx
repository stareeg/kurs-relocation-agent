// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"

const mutateAsyncIssue = vi.fn().mockResolvedValue({ ok: true })
const mutateAsyncVerify = vi.fn()

vi.mock("@/features/admin/use-admin", () => ({
  useIssueAdminKey: () => ({
    isPending: false,
    mutate: vi.fn(),
    mutateAsync: mutateAsyncIssue,
  }),
  useVerifyAdminKey: () => ({
    isPending: false,
    mutateAsync: mutateAsyncVerify,
  }),
  useVerifyStoredAdminKey: () => ({
    isPending: false,
    mutateAsync: vi.fn(),
  }),
}))

import { KeyIssueForm } from "./KeyIssueForm"

afterEach(() => {
  cleanup()
  mutateAsyncIssue.mockClear()
  mutateAsyncVerify.mockClear()
})

const VALID = "sk-or-v1-abcdefghijklmnop"

describe("KeyIssueForm", () => {
  it("маскирует ключ: password, без автозаполнения и проверки орфографии", () => {
    render(<KeyIssueForm accountId={1} submitLabel="Выдать" />)
    const input = screen.getByLabelText("Ключ OpenRouter")
    expect(input).toHaveProperty("type", "password")
    expect(input.getAttribute("autocomplete")).toBe("off")
    expect(input.getAttribute("spellcheck")).toBe("false")
  })

  it("срезает переносы при вставке", () => {
    render(<KeyIssueForm accountId={1} submitLabel="Выдать" />)
    const input = screen.getByLabelText("Ключ OpenRouter") as HTMLInputElement
    fireEvent.change(input, { target: { value: `\n${VALID}  \r\n` } })
    expect(input.value).toBe(VALID)
  })

  it("не даёт выдать ключ без префикса sk-or-", () => {
    render(<KeyIssueForm accountId={1} submitLabel="Выдать" />)
    fireEvent.change(screen.getByLabelText("Ключ OpenRouter"), {
      target: { value: "not-a-key-at-all-abcdefgh" },
    })
    expect(screen.getByText(/должен начинаться с sk-or-/)).toBeTruthy()
    expect((screen.getByRole("button", { name: "Выдать" }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole("button", { name: "Проверить" }) as HTMLButtonElement).disabled).toBe(true)
  })

  it("глаз переключает видимость ключа", () => {
    render(<KeyIssueForm accountId={1} submitLabel="Выдать" />)
    const input = screen.getByLabelText("Ключ OpenRouter")
    fireEvent.change(input, { target: { value: VALID } })
    fireEvent.click(screen.getByRole("button", { name: "Показать ключ" }))
    expect(input).toHaveProperty("type", "text")
    fireEvent.click(screen.getByRole("button", { name: "Скрыть ключ" }))
    expect(input).toHaveProperty("type", "password")
  })

  it("чистит поле даже если выдача упала", async () => {
    mutateAsyncIssue.mockRejectedValueOnce(new Error("boom"))
    render(<KeyIssueForm accountId={1} submitLabel="Выдать" />)
    const input = screen.getByLabelText("Ключ OpenRouter") as HTMLInputElement
    fireEvent.change(input, { target: { value: VALID } })
    fireEvent.click(screen.getByRole("button", { name: "Выдать" }))
    await waitFor(() => expect(input.value).toBe(""))
    expect(mutateAsyncIssue).toHaveBeenCalled()
  })

  it("перевыпуск поверх своего ключа не уходит без подтверждения", () => {
    render(<KeyIssueForm accountId={1} submitLabel="Перевыпустить" existingOrigin="self" />)
    fireEvent.change(screen.getByLabelText("Ключ OpenRouter"), { target: { value: VALID } })
    fireEvent.click(screen.getByRole("button", { name: "Перевыпустить" }))
    expect(mutateAsyncIssue).not.toHaveBeenCalled()
    expect(screen.getByText(/Ваш заменит его/)).toBeTruthy()
  })
})
