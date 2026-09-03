// @vitest-environment jsdom
/**
 * Скрининги: рельс слева + чат вопросов справа, «Рассказ об опыте» — закреплённое сообщение
 * вверху ленты (было отдельной колонкой PitchScript, план UI/UX-редизайна п.2).
 */
import { existsSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import { ScreeningPage } from "./ScreeningPage"

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..")
const PITCH_SECTION = path.join(ROOT, "src/features/jobs/VacancyPitchSection.tsx")
const PITCH_HOOK = path.join(ROOT, "src/features/jobs/use-vacancy-pitch.ts")

const JOB = {
  id: 1,
  vacancy_id: "hh_test_1",
  title: "Lead LLM Engineer",
  company: "Acme",
  status: "Скрининг",
  vacancy_text: "Нужен опыт с RAG и agentic пайплайнами. ".repeat(5),
  overall_score: 80,
  skipped: false,
}

const PACK = {
  vacancy_id: "hh_test_1",
  oral_pitch: "Lead LLM.\nТащил GraphRAG.",
  pitch_blocks: [{ label: "Кто я", lines: ["Lead LLM.", "Тащил GraphRAG."] }],
  why_company: "Стек близкий",
  hr_questions: [
    {
      question: "Опыт с RAG?",
      requirement: "Продовый опыт с RAG",
      intent: "проверяют глубину",
      draft_answer: "Гибрид двух слоёв.",
    },
  ],
  groups: [
    {
      title: "Размытые границы роли",
      hook: "работа в режиме многозадачности",
      questions: [
        { question: "Чем заменяете?", probe: "скрытая текучка", expect: "конкретика - хорошо" },
      ],
    },
  ],
  generated_at: "2026-07-22T12:00:00Z",
}

beforeAll(() => {
  class Observer {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return []
    }
  }
  Object.assign(globalThis, { ResizeObserver: Observer, IntersectionObserver: Observer })
  Element.prototype.scrollIntoView = () => {}
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

beforeEach(() => {
  // F-09: фолбэк-выбор вакансии живёт в sessionStorage под тем же ключом, что и
  // usePersistedRouteState({ storageKey: "prep-vacancy" }) в ScreeningPage/TechPage.
  sessionStorage.setItem("prep-vacancy", "hh_test_1")
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const json = (body: unknown) =>
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      if (url.includes("/api/jobs")) {
        return json({ jobs: [JOB], next_cursor: null, column_counts: {} })
      }
      if (url.includes("/api/screening/")) {
        return json(PACK)
      }
      return json({})
    }),
  )
})

function renderScreening() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/screening"]}>
        <ScreeningPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("мёртвый pitch-UI снесён", () => {
  it("VacancyPitchSection и use-vacancy-pitch отсутствуют", () => {
    expect(existsSync(PITCH_SECTION)).toBe(false)
    expect(existsSync(PITCH_HOOK)).toBe(false)
  })
})

describe("per-vacancy экран — «Рассказ об опыте» закреплён вверху ленты", () => {
  it("рендерит закреплённый рассказ и вопросы в одной ленте", async () => {
    renderScreening()

    await waitFor(() => {
      expect(screen.getByText("Рассказ об опыте")).toBeTruthy()
    })

    // Ровно один заголовок закреплённого сообщения.
    expect(screen.getAllByText("Рассказ об опыте")).toHaveLength(1)
    expect(screen.queryByText("Питч под вакансию")).toBeNull()
    // Превью в свёрнутой шапке уже показывает текст рассказа - открывать не нужно.
    expect(screen.getByText(/Тащил GraphRAG/)).toBeTruthy()

    // По умолчанию открыт режим «От HR» — подпись «Вопросы» одна на оба режима.
    expect(screen.getAllByText("Вопросы").length).toBeGreaterThan(0)
    expect(screen.getByText("Опыт с RAG?")).toBeTruthy()
    expect(screen.queryByText("Чем заменяете?")).toBeNull()

    // Требование вакансии рендерится прямо при вопросе HR.
    expect(screen.getByText("Продовый опыт с RAG")).toBeTruthy()
    expect(screen.queryByText("Требования вакансии")).toBeNull()

    // Переключалка «От себя» показывает вопросы для HR вместо вопросов от HR.
    fireEvent.click(screen.getByText("От себя"))
    expect(screen.getByText("Чем заменяете?")).toBeTruthy()
    expect(screen.queryByText("Опыт с RAG?")).toBeNull()

    // «Вопросы» (бывш. «Добавить») - под последней карточкой активного режима, одна кнопка.
    expect(screen.getByRole("button", { name: /Вопросы/ })).toBeTruthy()
    // Стрелки влево-вправо карусели убраны вместе с горизонтальным скроллом рельса.
    expect(screen.queryByLabelText("Назад")).toBeNull()
    expect(screen.queryByLabelText("Вперёд")).toBeNull()
  })

  it("клик по шапке раскрывает рассказ, «Пересобрать» доступно только там", async () => {
    renderScreening()

    await waitFor(() => {
      expect(screen.getByText("Рассказ об опыте")).toBeTruthy()
    })

    expect(screen.queryByLabelText("Пересобрать рассказ")).toBeNull()

    fireEvent.click(screen.getByText("Рассказ об опыте"))
    expect(await screen.findByLabelText("Пересобрать рассказ")).toBeTruthy()
    expect(screen.getByText("Кто я")).toBeTruthy()
    expect(screen.queryByText("Стек близкий")).toBeNull()
  })

  it("клик по карточке-сообщению раскрывает ответ под вопросом", async () => {
    // Вопросы рендерятся как QuestionBubble - вопрос остаётся на месте, ответ раскрывается
    // под ним (не заменяет вопрос).
    renderScreening()

    await waitFor(() => {
      expect(screen.getByText("Опыт с RAG?")).toBeTruthy()
    })

    fireEvent.click(screen.getByText("Опыт с RAG?"))
    expect(screen.getByText("Опыт с RAG?")).toBeTruthy()
    expect(screen.getByText("Гибрид двух слоёв.")).toBeTruthy()

    fireEvent.click(screen.getByText("Опыт с RAG?"))
    expect(screen.queryByText("Гибрид двух слоёв.")).toBeNull()
  })

  it("без рассказа шапка предлагает написать его, вопросы остаются", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        const json = (body: unknown) =>
          new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        if (url.includes("/api/jobs"))
          return json({ jobs: [JOB], next_cursor: null, column_counts: {} })
        if (url.includes("/api/screening/")) {
          return json({
            ...PACK,
            oral_pitch: "",
            pitch_blocks: [],
            why_company: "",
          })
        }
        return json({})
      }),
    )

    renderScreening()

    await waitFor(() => {
      expect(screen.getByText(/не собран, нажмите, чтобы написать/)).toBeTruthy()
    })
    expect(screen.getByText("Опыт с RAG?")).toBeTruthy()
    fireEvent.click(screen.getByText("От себя"))
    expect(screen.getByText("Чем заменяете?")).toBeTruthy()
  })
})
