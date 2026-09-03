import { describe, expect, it } from "vitest"
import type { ConvMessage } from "@/api/conversations"
import { exchangePersistedInMessages } from "./use-vacancy-conversation"

function msg(kind: ConvMessage["kind"], body: string, id = 1): ConvMessage {
  return {
    id,
    thread_id: 1,
    direction: kind === "llm_user" || kind === "hr_out" ? "out" : "in",
    kind,
    body,
  }
}

describe("exchangePersistedInMessages", () => {
  it("false when лента пуста — иначе pending нельзя гасить (баг «ответ исчез»)", () => {
    expect(exchangePersistedInMessages([], "Вопрос?", "Ответ")).toBe(false)
  })

  it("true when user+assistant уже в ленте", () => {
    expect(
      exchangePersistedInMessages(
        [msg("llm_user", "Вопрос?", 1), msg("llm_assistant", "Ответ", 2)],
        "Вопрос?",
        "Ответ",
      ),
    ).toBe(true)
  })

  it("false when есть вопрос, но нет ответа ассистента", () => {
    expect(exchangePersistedInMessages([msg("llm_user", "Вопрос?")], "Вопрос?", "Ответ")).toBe(
      false,
    )
  })

  it("true when ответ пуст, но вопрос уже записан", () => {
    expect(exchangePersistedInMessages([msg("llm_user", "Вопрос?")], "Вопрос?", "")).toBe(true)
  })

  it("игнорирует пробелы по краям", () => {
    expect(
      exchangePersistedInMessages(
        [msg("llm_user", "Вопрос?"), msg("llm_assistant", "Ответ")],
        "  Вопрос?  ",
        "  Ответ  ",
      ),
    ).toBe(true)
  })
})
