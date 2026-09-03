import { describe, expect, it } from "vitest"
import {
  ATTACHMENT_MAX_PER_MESSAGE,
  clampToRemainingSlots,
  extractImageFiles,
  hasPastedText,
  isAcceptedAttachment,
  isImageFile,
  partitionAcceptedFiles,
} from "./use-paste-images"

function makeFile(name: string, type: string, lastModified = 1): File {
  return new File(["x"], name, { type, lastModified })
}

interface FakeItem {
  kind: string
  type: string
  getAsFile: () => File | null
}

function fakeDataTransfer(opts: {
  files?: File[]
  items?: FakeItem[]
  text?: string
}): DataTransfer {
  return {
    files: opts.files ?? [],
    items: opts.items ?? [],
    getData: (fmt: string) => (fmt === "text/plain" ? (opts.text ?? "") : ""),
  } as unknown as DataTransfer
}

function fileItem(file: File): FakeItem {
  return { kind: "file", type: file.type, getAsFile: () => file }
}

describe("extractImageFiles", () => {
  it("несколько файлов из одной вставки — все попадают в список", () => {
    const a = makeFile("a.png", "image/png")
    const b = makeFile("b.jpg", "image/jpeg")
    const data = fakeDataTransfer({ files: [a, b] })
    expect(extractImageFiles(data).map((f) => f.name)).toEqual(["a.png", "b.jpg"])
  })

  it("Chrome кладёт один и тот же файл в files и items — дедуп по имени/размеру/дате", () => {
    const a = makeFile("shot.png", "image/png", 12345)
    const data = fakeDataTransfer({ files: [a], items: [fileItem(a)] })
    expect(extractImageFiles(data)).toHaveLength(1)
  })

  it("нефайловые элементы буфера игнорируются молча", () => {
    const data = fakeDataTransfer({
      items: [{ kind: "string", type: "text/plain", getAsFile: () => null }],
    })
    expect(extractImageFiles(data)).toEqual([])
  })

  it("документы из белого списка (txt/md/pdf/docx) тоже проходят (2026-08-11)", () => {
    const doc = makeFile("resume.pdf", "application/pdf")
    const data = fakeDataTransfer({ files: [doc] })
    expect(extractImageFiles(data).map((f) => f.name)).toEqual(["resume.pdf"])
  })

  it("файлы вне белого списка (zip/svg) отфильтрованы", () => {
    const zip = makeFile("archive.zip", "application/zip")
    const data = fakeDataTransfer({ files: [zip] })
    expect(extractImageFiles(data)).toEqual([])
  })

  it(".md с пустым content-type проходит по расширению (фолбэк)", () => {
    const md = makeFile("readme.md", "")
    const data = fakeDataTransfer({ files: [md] })
    expect(extractImageFiles(data).map((f) => f.name)).toEqual(["readme.md"])
  })

  it("пустой clipboardData — пустой список", () => {
    expect(extractImageFiles(null)).toEqual([])
  })
})

describe("hasPastedText", () => {
  it("текст рядом с картинкой — true", () => {
    expect(hasPastedText(fakeDataTransfer({ text: "привет" }))).toBe(true)
  })

  it("только пробелы — как отсутствие текста", () => {
    expect(hasPastedText(fakeDataTransfer({ text: "   " }))).toBe(false)
  })

  it("нет текста — false", () => {
    expect(hasPastedText(fakeDataTransfer({}))).toBe(false)
  })
})

describe("partitionAcceptedFiles", () => {
  it("png/jpeg/webp/gif — приняты", () => {
    const files = [
      makeFile("a.png", "image/png"),
      makeFile("b.jpg", "image/jpeg"),
      makeFile("c.webp", "image/webp"),
      makeFile("d.gif", "image/gif"),
    ]
    const { accepted, rejected } = partitionAcceptedFiles(files)
    expect(accepted).toHaveLength(4)
    expect(rejected).toHaveLength(0)
  })

  it("HEIC/SVG — отклонены", () => {
    const files = [makeFile("a.heic", "image/heic"), makeFile("b.svg", "image/svg+xml")]
    const { accepted, rejected } = partitionAcceptedFiles(files)
    expect(accepted).toHaveLength(0)
    expect(rejected).toHaveLength(2)
  })

  it("txt/md/pdf/docx — приняты (2026-08-11)", () => {
    const files = [
      makeFile("a.txt", "text/plain"),
      makeFile("b.md", "text/markdown"),
      makeFile("c.pdf", "application/pdf"),
      makeFile("d.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ]
    const { accepted, rejected } = partitionAcceptedFiles(files)
    expect(accepted).toHaveLength(4)
    expect(rejected).toHaveLength(0)
  })
})

describe("isAcceptedAttachment / isImageFile", () => {
  it("картинка — принята и is image", () => {
    const f = makeFile("a.png", "image/png")
    expect(isAcceptedAttachment(f)).toBe(true)
    expect(isImageFile(f)).toBe(true)
  })

  it("документ — принят, но не image", () => {
    const f = makeFile("a.pdf", "application/pdf")
    expect(isAcceptedAttachment(f)).toBe(true)
    expect(isImageFile(f)).toBe(false)
  })

  it("неизвестный тип — не принят", () => {
    const f = makeFile("a.zip", "application/zip")
    expect(isAcceptedAttachment(f)).toBe(false)
  })
})

describe("clampToRemainingSlots", () => {
  it("укладывается в лимит — ничего не отбрасывает", () => {
    const files = [makeFile("a.png", "image/png")]
    expect(clampToRemainingSlots(files, 0, 10)).toEqual({ files, dropped: 0 })
  })

  it("превышает лимит на сообщение — обрезает и считает отброшенные", () => {
    const files = Array.from({ length: 5 }, (_, i) => makeFile(`${i}.png`, "image/png"))
    const result = clampToRemainingSlots(files, 8, 10)
    expect(result.files).toHaveLength(2)
    expect(result.dropped).toBe(3)
  })

  it("дефолтный лимит — ATTACHMENT_MAX_PER_MESSAGE", () => {
    const files = Array.from({ length: 3 }, (_, i) => makeFile(`${i}.png`, "image/png"))
    expect(clampToRemainingSlots(files, ATTACHMENT_MAX_PER_MESSAGE).dropped).toBe(3)
  })
})
