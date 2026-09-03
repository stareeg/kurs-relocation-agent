import { readFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import { SELF_REJECT_REASONS, canonicalSelfReason } from "./reject-reasons"

// FR2-78: эталон — core/domains/opportunities/skip_reasons.json (дамп SELF_SKIP_REASONS).
// Хардкод зеркала в тесте больше не держим: рассинхрон ловится против снапшота.
const CANON_JSON = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../../core/domains/opportunities/skip_reasons.json",
)
const CANON_SELF_SKIP_REASONS: readonly string[] = (
  JSON.parse(readFileSync(CANON_JSON, "utf-8")) as { self_skip_reasons: string[] }
).self_skip_reasons

describe("SELF_REJECT_REASONS синхронизирован с каноном skip_reasons.json (FR2-78)", () => {
  it("тот же перечень в том же порядке", () => {
    expect([...SELF_REJECT_REASONS]).toEqual([...CANON_SELF_SKIP_REASONS])
  })

  it("6 причин (стек+домен слиты, EXT-P1)", () => {
    expect(SELF_REJECT_REASONS).toHaveLength(6)
    expect(CANON_SELF_SKIP_REASONS).toHaveLength(6)
  })
})

describe("canonicalSelfReason — каноничные строки проходят как есть", () => {
  for (const reason of SELF_REJECT_REASONS) {
    it(`канон: ${reason}`, () => {
      expect(canonicalSelfReason(reason)).toBe(reason)
    })
  }
})

describe("canonicalSelfReason — legacy-строки из _LEGACY_EXACT (Python)", () => {
  // Зеркало _LEGACY_EXACT из core/domains/opportunities/skip_reasons.py.
  // Если бэк добавит/удалит legacy-маппинг — тест упадёт, рассинхрон виден.
  const legacyCases: Array<[string, string]> = [
    ["Зарплата ниже целевой", "Низкая зарплата"],
    ["Грейд ниже Senior+", "Низкий грейд"],
    ["Грейд не совпадает", "Низкий грейд"],
    ["Не полная удалёнка", "Не тот формат"],
    ["Офис / нет удалёнки", "Не тот формат"],
    // Переименования 2026-08-10: legacy-лейблы матчатся в новый канон.
    ["Риск выгорания", "Не та роль (IC vs рук)"],
    ["Сомнительная компания", "Избегать компанию"],
    ["Другое", "Избегать компанию"],
    ["Не интересно", "Избегать компанию"],
    ["без причины", "Избегать компанию"],
  ]
  for (const [raw, expected] of legacyCases) {
    it(`legacy: ${raw} → ${expected}`, () => {
      expect(canonicalSelfReason(raw)).toBe(expected)
    })
  }
})

describe("canonicalSelfReason — edge cases", () => {
  it("пусто/null/undefined → Избегать компанию", () => {
    expect(canonicalSelfReason(undefined)).toBe("Избегать компанию")
    expect(canonicalSelfReason(null)).toBe("Избегать компанию")
    expect(canonicalSelfReason("")).toBe("Избегать компанию")
    expect(canonicalSelfReason("   ")).toBe("Избегать компанию")
  })

  it("recommendation=skip / skip → Избегать компанию", () => {
    expect(canonicalSelfReason("recommendation=skip")).toBe("Избегать компанию")
    expect(canonicalSelfReason("skip")).toBe("Избегать компанию")
  })

  it("зарплата: варианты текста → Низкая зарплата", () => {
    expect(canonicalSelfReason("зарплата ниже целевой")).toBe("Низкая зарплата")
    expect(canonicalSelfReason("Вилка низкая")).toBe("Низкая зарплата")
    expect(canonicalSelfReason("мало платят")).toBe("Низкая зарплата")
    expect(canonicalSelfReason("low salary")).toBe("Низкая зарплата")
  })

  it("роль/выгорание: варианты → Не та роль (IC vs рук)", () => {
    expect(canonicalSelfReason("burnout risk")).toBe("Не та роль (IC vs рук)")
    expect(canonicalSelfReason("токсичная среда")).toBe("Не та роль (IC vs рук)")
    expect(canonicalSelfReason("переработки")).toBe("Не та роль (IC vs рук)")
    expect(canonicalSelfReason("слишком много управления")).toBe("Не та роль (IC vs рук)")
    expect(canonicalSelfReason("people manager")).toBe("Не та роль (IC vs рук)")
    expect(canonicalSelfReason("мало хендс-он")).toBe("Не та роль (IC vs рук)")
  })

  it("формат: варианты → Не тот формат", () => {
    expect(canonicalSelfReason("офис без удалёнки")).toBe("Не тот формат")
    expect(canonicalSelfReason("гибрид только")).toBe("Не тот формат")
    expect(canonicalSelfReason("on-site")).toBe("Не тот формат")
    expect(canonicalSelfReason("требуют релок")).toBe("Не тот формат")
  })

  it("грейд: варианты → Низкий грейд", () => {
    expect(canonicalSelfReason("junior grade")).toBe("Низкий грейд")
    expect(canonicalSelfReason("middle уровень")).toBe("Низкий грейд")
    expect(canonicalSelfReason("не тот грейд")).toBe("Низкий грейд")
  })

  it("стек/домен: legacy-строки сходятся в один канон (EXT-P1)", () => {
    expect(canonicalSelfReason("Стек/домен далёкий")).toBe("Не тот стек/домен")
    expect(canonicalSelfReason("Не тот стек / домен")).toBe("Не тот стек/домен")
    expect(canonicalSelfReason("Не тот стек")).toBe("Не тот стек/домен")
    expect(canonicalSelfReason("Не тот домен")).toBe("Не тот стек/домен")
  })

  it("домен: текст с domain/BI/CV → Не тот стек/домен", () => {
    expect(canonicalSelfReason("не тот domain")).toBe("Не тот стек/домен")
    expect(canonicalSelfReason("классический ML")).toBe("Не тот стек/домен")
    expect(canonicalSelfReason("BI аналитика")).toBe("Не тот стек/домен")
  })

  it("стек: текст со stack/rag/agent/llm → Не тот стек/домен", () => {
    expect(canonicalSelfReason("не тот stack")).toBe("Не тот стек/домен")
    expect(canonicalSelfReason("без RAG")).toBe("Не тот стек/домен")
    expect(canonicalSelfReason("нет agent-стека")).toBe("Не тот стек/домен")
    expect(canonicalSelfReason("не тот стек")).toBe("Не тот стек/домен")
  })

  it("аутстафф/аутсорс/избегать → Избегать компанию", () => {
    expect(canonicalSelfReason("аутстафф")).toBe("Избегать компанию")
    expect(canonicalSelfReason("аутсорс")).toBe("Избегать компанию")
    expect(canonicalSelfReason("избегать эту контору")).toBe("Избегать компанию")
  })

  it("незнакомый текст → fallback Избегать компанию", () => {
    expect(canonicalSelfReason("какая-то непонятная причина")).toBe("Избегать компанию")
  })

  it("ё→е нормализация работает", () => {
    expect(canonicalSelfReason("Вилка ниже целевой")).toBe("Низкая зарплата")
  })
})
