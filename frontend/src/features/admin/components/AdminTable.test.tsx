// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"

import { AdminTable } from "./AdminTable"

afterEach(cleanup)

type Row = { id: number; name: string }

const rows: Row[] = [
  { id: 1, name: "Kate" },
  { id: 2, name: "Misha" },
]

const columns = [
  { key: "name", title: "Человек", render: (row: Row) => row.name },
]

describe("AdminTable", () => {
  it("Enter на строке открывает карточку", () => {
    const onSelect = vi.fn()
    render(
      <AdminTable
        rows={rows}
        columns={columns}
        rowKey={(row) => row.id}
        onSelect={onSelect}
      />,
    )
    const bodyRow = screen.getAllByRole("row")[1]
    expect(bodyRow.tabIndex).toBe(0)
    bodyRow.focus()
    fireEvent.keyDown(bodyRow, { key: "Enter" })
    expect(onSelect).toHaveBeenCalledWith(rows[0])
  })

  it("Space на строке тоже открывает", () => {
    const onSelect = vi.fn()
    render(
      <AdminTable
        rows={rows}
        columns={columns}
        rowKey={(row) => row.id}
        onSelect={onSelect}
      />,
    )
    const bodyRow = screen.getAllByRole("row")[1]
    fireEvent.keyDown(bodyRow, { key: " " })
    expect(onSelect).toHaveBeenCalledWith(rows[0])
  })

  it("пустое состояние называет причину, а не рисует пустую таблицу", () => {
    render(
      <AdminTable
        rows={[]}
        columns={columns}
        rowKey={(row) => row.id}
        empty={{ title: "Никто не подошёл", note: "Снимите фильтр или измените поиск." }}
      />,
    )
    expect(screen.getByText("Никто не подошёл")).toBeTruthy()
    expect(screen.queryByRole("table")).toBeNull()
  })

  it("шеврон раскрывает подробности и не открывает карточку", () => {
    const onSelect = vi.fn()
    render(
      <AdminTable
        rows={rows}
        columns={columns}
        rowKey={(row) => row.id}
        onSelect={onSelect}
        renderExpanded={(row) => <div>детали {row.name}</div>}
      />,
    )
    expect(screen.queryByText("детали Kate")).toBeNull()
    fireEvent.click(screen.getAllByRole("button", { name: "Показать подробности" })[0])
    expect(screen.getByText("детали Kate")).toBeTruthy()
    expect(onSelect).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole("button", { name: "Скрыть подробности" }))
    expect(screen.queryByText("детали Kate")).toBeNull()
  })

  it("visibleKeys прячет колонки, не трогая порядок оставшихся", () => {
    const wide = [
      { key: "name", title: "Человек", render: (row: Row) => row.name },
      { key: "age", title: "Возраст", render: () => "—" },
      { key: "city", title: "Город", render: () => "—" },
    ]
    render(
      <AdminTable
        rows={rows}
        columns={wide}
        rowKey={(row) => row.id}
        visibleKeys={["name", "city"]}
      />,
    )
    expect(screen.getByText("Человек")).toBeTruthy()
    expect(screen.queryByText("Возраст")).toBeNull()
    expect(screen.getByText("Город")).toBeTruthy()
  })

  it("колонка действий не открывает карточку", () => {
    const onSelect = vi.fn()
    render(
      <AdminTable
        rows={rows}
        columns={columns}
        rowKey={(row) => row.id}
        onSelect={onSelect}
        renderActions={(row) => <button type="button">ещё {row.name}</button>}
      />,
    )
    fireEvent.click(screen.getByText("ещё Kate"))
    expect(onSelect).not.toHaveBeenCalled()
  })
})
