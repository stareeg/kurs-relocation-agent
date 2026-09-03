import { readFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const src = readFileSync(
  path.resolve(path.dirname(fileURLToPath(import.meta.url)), "toasts.ts"),
  "utf-8",
)

describe("showSeriousErrorToast", () => {
  it("кнопка «Скачать логи» зовёт downloadLogsBundle синхронно из клика", () => {
    expect(src).toContain('import { downloadLogsBundle } from "@/api/logs"')
    expect(src).not.toContain('import("@/api/logs")')
    expect(src).toContain("void downloadLogsBundle()")
  })
})
