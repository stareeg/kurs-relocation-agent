import { describe, expect, it } from "vitest"
import { canAddInterviewStage, stageChainBlockedReason } from "./stage-chain-gate"

// Гейт «Добавить этап»: раньше можно было накрутить цепочку собесов на вакансии, которая по
// факту ещё не сдвинулась дальше отклика (или уже закрыта) — тупиковый UX-путь.
describe("canAddInterviewStage", () => {
  it("без переданного статуса (гейт не подключён вызывающей стороной) — всегда true", () => {
    expect(canAddInterviewStage(null)).toBe(true)
    expect(canAddInterviewStage(undefined)).toBe(true)
  })

  it("Просмотр/Отклик/Отказ — рано вести цепочку, гейт закрыт", () => {
    expect(canAddInterviewStage("Просмотр")).toBe(false)
    expect(canAddInterviewStage("Отклик")).toBe(false)
    expect(canAddInterviewStage("Отказ")).toBe(false)
  })

  it("Скрининг/Техничка/Финал/Оффер — гейт открыт", () => {
    expect(canAddInterviewStage("Скрининг")).toBe(true)
    expect(canAddInterviewStage("Техничка")).toBe(true)
    expect(canAddInterviewStage("Финал")).toBe(true)
    expect(canAddInterviewStage("Оффер")).toBe(true)
  })

  it("Пропущено (skipped=true) закрывает гейт даже на подходящем статусе воронки", () => {
    expect(canAddInterviewStage("Техничка", true)).toBe(false)
  })
})

// Этап 1.2 плана `plans/ui_slop_cleanup_2026_08_25.md`: закрытый гейт больше не одна бледная
// строка на все случаи. Из «слишком рано» есть выход кнопкой перевода, из остальных — нет,
// и текст обязан говорить именно про свою причину.
describe("stageChainBlockedReason", () => {
  it("рано вести цепочку — причина не названа: чинится переводом на «Скрининг»", () => {
    expect(stageChainBlockedReason("Просмотр")).toBeNull()
    expect(stageChainBlockedReason("Отклик")).toBeNull()
  })

  it("пропущенная вакансия — сперва вернуть в воронку, перевод не поможет", () => {
    expect(stageChainBlockedReason("Отклик", true)).toContain("пропущенных")
  })

  it("после отказа цепочка не нужна вовсе", () => {
    expect(stageChainBlockedReason("Отказ")).toContain("отказ")
  })

  it("пропуск перевешивает статус воронки", () => {
    expect(stageChainBlockedReason("Техничка", true)).toContain("пропущенных")
  })
})
