// @vitest-environment jsdom
import { useState } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { CityInput, type CitySuggestion } from "./city-input"

const suggestions: CitySuggestion[] = [
  { city: "Москва", country: "Россия", utcOffset: "UTC+3" },
  { city: "Тбилиси", country: "Грузия", utcOffset: "UTC+4" },
  { city: "Берлин", country: "Германия", utcOffset: "UTC+1" },
]

function Harness({ onSelect }: { onSelect?: (item: CitySuggestion) => void }) {
  const [value, setValue] = useState("")
  return (
    <CityInput value={value} onChange={setValue} onSelect={onSelect} suggestions={suggestions} />
  )
}

afterEach(() => {
  cleanup()
})

describe("CityInput", () => {
  it("фильтрует подсказки по подстроке и выбирает кликом", () => {
    const onSelect = vi.fn()
    render(<Harness onSelect={onSelect} />)
    const input = screen.getByRole("combobox")
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: "тбил" } })
    expect(screen.getByRole("option").textContent).toMatch(/Тбилиси/)
    fireEvent.click(screen.getByRole("option"))
    expect(onSelect).toHaveBeenCalledWith(suggestions[1])
  })

  it("пустой список подсказок не роняет ввод", () => {
    render(<CityInput value="Хогвартс" onChange={() => undefined} suggestions={[]} />)
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "Хогвартс" } })
    expect(screen.queryByRole("listbox")).toBeNull()
  })
})
