// @vitest-environment jsdom
import type { ReactNode } from "react"
import { act, renderHook } from "@testing-library/react"
import { MemoryRouter, useSearchParams } from "react-router-dom"
import { afterEach, describe, expect, it } from "vitest"
import { usePersistedRouteState } from "./use-persisted-route-state"

afterEach(() => {
  sessionStorage.clear()
})

function wrapperWithEntries(initialEntries: string[]) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
  }
}

// Собирает и значение, и сырую строку запроса — чтобы проверять и то, что хук читает
// из URL (разбор параметров, F-10), и то, что он туда пишет.
function useHarness(options: Parameters<typeof usePersistedRouteState<string>>[0]) {
  const [value, setValue] = usePersistedRouteState<string>(options)
  const [searchParams] = useSearchParams()
  return { value, setValue, search: searchParams.toString() }
}

// Пара хуков на одном экране, как в ChatPage: выбор вакансии и выбор панели.
function useTwoParamHarness() {
  const [vacancy, setVacancy] = usePersistedRouteState<string>({
    param: "vacancy",
    storageKey: "chat-vacancy",
  })
  const [panel, setPanel] = usePersistedRouteState<string>({
    param: "panel",
    storageKey: "chat-panel",
  })
  const [searchParams] = useSearchParams()
  return { vacancy, panel, setVacancy, setPanel, search: searchParams.toString() }
}

describe("usePersistedRouteState — параметр в URL (F-10)", () => {
  it("читает значение из query-параметра", () => {
    const { result } = renderHook(
      () => useHarness({ param: "vacancy", storageKey: "prep-vacancy" }),
      {
        wrapper: wrapperWithEntries(["/screening?vacancy=hh_123"]),
      },
    )
    expect(result.current.value).toBe("hh_123")
  })

  it("URL побеждает sessionStorage, если оба заполнены", () => {
    sessionStorage.setItem("prep-vacancy", "hh_stale")
    const { result } = renderHook(
      () => useHarness({ param: "vacancy", storageKey: "prep-vacancy" }),
      {
        wrapper: wrapperWithEntries(["/tech?vacancy=hh_fresh"]),
      },
    )
    expect(result.current.value).toBe("hh_fresh")
  })

  it("без параметра в URL — фолбэк на sessionStorage", () => {
    sessionStorage.setItem("prep-vacancy", "hh_from_session")
    const { result } = renderHook(
      () => useHarness({ param: "vacancy", storageKey: "prep-vacancy" }),
      {
        wrapper: wrapperWithEntries(["/tech"]),
      },
    )
    expect(result.current.value).toBe("hh_from_session")
  })

  it("нет ни параметра, ни сессии — fallback по умолчанию", () => {
    const { result } = renderHook(
      () => useHarness({ param: "vacancy", storageKey: "prep-vacancy", fallback: null }),
      { wrapper: wrapperWithEntries(["/tech"]) },
    )
    expect(result.current.value).toBeNull()
  })

  it("set() пишет и в URL, и в sessionStorage", () => {
    const { result } = renderHook(
      () => useHarness({ param: "vacancy", storageKey: "prep-vacancy" }),
      {
        wrapper: wrapperWithEntries(["/tech"]),
      },
    )
    act(() => result.current.setValue("hh_new"))
    expect(result.current.value).toBe("hh_new")
    expect(result.current.search).toBe("vacancy=hh_new")
    expect(sessionStorage.getItem("prep-vacancy")).toBe("hh_new")
  })

  it("set(null) снимает параметр из URL и из sessionStorage", () => {
    const { result } = renderHook(
      () => useHarness({ param: "vacancy", storageKey: "prep-vacancy" }),
      {
        wrapper: wrapperWithEntries(["/tech?vacancy=hh_123"]),
      },
    )
    act(() => result.current.setValue(null))
    expect(result.current.value).toBeNull()
    expect(result.current.search).toBe("")
    expect(sessionStorage.getItem("prep-vacancy")).toBeNull()
  })

  // Два параметра, снятых/выставленных в одном обработчике (ChatPage: выбор «Сегодня» и
  // контекста снимает `vacancy` и правит `panel`). До фикса второй вызов уходил в роутер со
  // снимком с прошлого рендера и воскрешал `vacancy` — переключиться из диалога вакансии на
  // «Сегодня» было невозможно.
  it("два параметра в одном обработчике не затирают правки друг друга", () => {
    const { result } = renderHook(() => useTwoParamHarness(), {
      wrapper: wrapperWithEntries(["/chat?vacancy=hh_123"]),
    })
    act(() => {
      result.current.setVacancy(null)
      result.current.setPanel(null)
    })
    expect(result.current.search).toBe("")
    expect(result.current.vacancy).toBeNull()
    expect(result.current.panel).toBeNull()
  })

  it("снять один параметр и выставить другой в одном обработчике", () => {
    const { result } = renderHook(() => useTwoParamHarness(), {
      wrapper: wrapperWithEntries(["/chat?vacancy=hh_123"]),
    })
    act(() => {
      result.current.setVacancy(null)
      result.current.setPanel("context:7")
    })
    expect(result.current.vacancy).toBeNull()
    expect(result.current.panel).toBe("context:7")
    expect(new URLSearchParams(result.current.search).get("vacancy")).toBeNull()
  })

  it("следующий обработчик стартует с актуального URL, а не с буфера прошлого", () => {
    const { result } = renderHook(() => useTwoParamHarness(), {
      wrapper: wrapperWithEntries(["/chat?vacancy=hh_123"]),
    })
    act(() => {
      result.current.setVacancy(null)
      result.current.setPanel("new")
    })
    act(() => {
      result.current.setPanel(null)
      result.current.setVacancy("hh_999")
    })
    expect(result.current.vacancy).toBe("hh_999")
    expect(result.current.panel).toBeNull()
    expect(result.current.search).toBe("vacancy=hh_999")
  })

  // Баг 2026-08-11: «Шанс офферов» в меню слева (AppShell, смонтирован один раз на всё
  // приложение) скакал/расходился с графиком на «Рынке» — его собственный инстанс хука кэшировал
  // sessionStorage в useState на момент СВОЕГО монтирования и не видел правок, сделанных другим
  // инстансом (шкалой периода на самой странице), пока URL-параметр отсутствовал (т.е. везде,
  // кроме самой /market). Правка: sessionStorage читается напрямую при каждом рендере.
  it("другой инстанс хука пишет в тот же storageKey — значение видно после рендера без remount", () => {
    const { result, rerender } = renderHook(
      () => useHarness({ param: "range", storageKey: "shared-range" }),
      { wrapper: wrapperWithEntries(["/tech"]) }, // URL без ?range= — как вне /market
    )
    expect(result.current.value).toBeNull()
    // Другой инстанс этого хука (например, шкала периода на «Рынке») пишет в тот же ключ.
    sessionStorage.setItem("shared-range", "14-0")
    rerender()
    expect(result.current.value).toBe("14-0")
  })

  it("без `param` (вид/раскладка) значение живёт только в sessionStorage, URL не трогается", () => {
    const { result } = renderHook(
      () => useHarness({ storageKey: "jobs-view", fallback: "board" }),
      {
        wrapper: wrapperWithEntries(["/jobs?vacancy=hh_123"]),
      },
    )
    expect(result.current.value).toBe("board")
    act(() => result.current.setValue("list"))
    expect(result.current.value).toBe("list")
    // Query-параметр другого хука (vacancy) остаётся нетронутым.
    expect(result.current.search).toBe("vacancy=hh_123")
    expect(sessionStorage.getItem("jobs-view")).toBe("list")
  })
})
