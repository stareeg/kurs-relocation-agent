import { useRef, useState, type DragEvent } from "react"
import { CheckCircle2, FileUp, Loader2 } from "lucide-react"
import type { ResumeData } from "@/api/resume"
import { HelpTip } from "@/components/ui/help-tip"
import { cn } from "@/lib/utils"
import { useParseResumePdf } from "./use-resume"

const PDF_META_KEY = "copilot.resume.pdf-meta"

type PdfMeta = { name: string; uploadedAt: number }

function readPdfMeta(): PdfMeta | null {
  try {
    const raw = localStorage.getItem(PDF_META_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as PdfMeta
    if (typeof parsed?.name === "string" && parsed.name.trim()) return parsed
  } catch {
    /* ignore */
  }
  return null
}

function writePdfMeta(meta: PdfMeta) {
  try {
    localStorage.setItem(PDF_META_KEY, JSON.stringify(meta))
  } catch {
    /* ignore */
  }
}

export function ResumePdfUpload({
  onParsed,
  disabled,
  hasManualEdits,
  compact,
}: {
  onParsed: (data: ResumeData) => void
  disabled?: boolean
  hasManualEdits?: boolean
  compact?: boolean
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const [pdfMeta, setPdfMeta] = useState<PdfMeta | null>(() => readPdfMeta())
  const parse = useParseResumePdf()

  async function handleFile(file: File | null | undefined) {
    if (!file || disabled || parse.isPending) return
    const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")
    if (!isPdf) {
      parse.reset()
      return
    }
    parse.mutate(file, {
      onSuccess: (data) => {
        const meta = { name: file.name, uploadedAt: Date.now() }
        writePdfMeta(meta)
        setPdfMeta(meta)
        onParsed(data)
      },
    })
  }

  const busy = disabled || parse.isPending
  const uploaded = pdfMeta != null && !parse.isPending

  const dropHandlers = {
    onDragOver: (e: DragEvent) => {
      e.preventDefault()
      if (!busy) setDragOver(true)
    },
    onDragLeave: () => setDragOver(false),
    onDrop: (e: DragEvent) => {
      e.preventDefault()
      setDragOver(false)
      void handleFile(e.dataTransfer.files?.[0])
    },
  }

  if (compact) {
    const compactLabel = parse.isPending
      ? "Разбираю PDF…"
      : uploaded
        ? (pdfMeta?.name ?? "PDF загружен")
        : "Загрузить PDF"
    return (
      <div className="flex min-w-0 flex-1 items-center gap-1">
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          disabled={busy}
          onChange={(e) => {
            void handleFile(e.target.files?.[0])
            e.target.value = ""
          }}
        />
        <button
          type="button"
          disabled={busy}
          onClick={() => inputRef.current?.click()}
          {...dropHandlers}
          aria-label={uploaded ? "Загрузить другую версию резюме в PDF" : "Загрузить резюме в PDF"}
          className={cn(
            "flex h-9 min-w-0 flex-1 items-center gap-2 rounded-lg border border-dashed px-2.5 text-left text-xs font-medium transition-colors",
            dragOver && "border-sky-400 bg-sky-50",
            !dragOver &&
              uploaded &&
              (hasManualEdits
                ? "border-amber-300 bg-amber-50/50 text-amber-900"
                : "border-emerald-300 bg-emerald-50/50 text-emerald-900"),
            !dragOver &&
              !uploaded &&
              "border-sky-200 bg-sky-50/50 text-sky-900 hover:border-sky-300",
            busy && "cursor-not-allowed opacity-60",
          )}
        >
          {parse.isPending ? (
            <Loader2 className="size-3.5 shrink-0 animate-spin text-sky-600" strokeWidth={2} />
          ) : (
            <FileUp className="size-3.5 shrink-0 text-sky-600" strokeWidth={2} />
          )}
          <span className="min-w-0 truncate">{compactLabel}</span>
        </button>
        <HelpTip id="resume.pdf-upload" />
      </div>
    )
  }

  return (
    <div className="flex min-w-0 flex-1 items-center gap-1.5">
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        disabled={busy}
        onChange={(e) => {
          void handleFile(e.target.files?.[0])
          e.target.value = ""
        }}
      />
      <button
        type="button"
        disabled={busy}
        onClick={() => inputRef.current?.click()}
        {...dropHandlers}
        aria-label={uploaded ? "Загрузить другую версию резюме в PDF" : "Загрузить резюме в PDF"}
        className={cn(
          "flex min-w-0 flex-1 items-center gap-3 rounded-xl border border-dashed px-4 py-3.5 text-left transition-[border-color,background-color,box-shadow] duration-200",
          dragOver && "border-sky-400 bg-sky-50 shadow-sm shadow-sky-100/80",
          !dragOver &&
            uploaded &&
            (hasManualEdits
              ? "border-amber-300/80 bg-amber-50/40 hover:border-amber-400 hover:bg-amber-50/70"
              : "border-emerald-300/80 bg-emerald-50/40 hover:border-emerald-400 hover:bg-emerald-50/70"),
          !dragOver &&
            !uploaded &&
            "border-sky-200 bg-sky-50/40 hover:border-sky-300 hover:bg-sky-50/80",
          busy && "cursor-not-allowed opacity-60",
        )}
      >
        {parse.isPending ? (
          <Loader2 className="size-5 shrink-0 animate-spin text-sky-600" strokeWidth={2} />
        ) : uploaded ? (
          hasManualEdits ? (
            <CheckCircle2 className="size-5 shrink-0 text-amber-600" strokeWidth={2} />
          ) : (
            <CheckCircle2 className="size-5 shrink-0 text-emerald-600" strokeWidth={2} />
          )
        ) : (
          <FileUp className="size-5 shrink-0 text-sky-600" strokeWidth={2} />
        )}
        <span className="min-w-0 flex-1">
          {parse.isPending ? (
            <span className="block text-sm font-medium text-sky-800">Разбираю PDF…</span>
          ) : uploaded ? (
            hasManualEdits ? (
              <>
                <span className="block truncate text-sm font-medium text-amber-900">
                  PDF ({pdfMeta.name}) · есть ручные правки в форме
                </span>
                <span className="mt-0.5 block text-xs text-amber-700/80">
                  Оценка и отклики используют актуальные данные из формы ниже
                </span>
              </>
            ) : (
              <>
                <span className="block truncate text-sm font-medium text-emerald-900">
                  PDF загружен · {pdfMeta.name}
                </span>
                <span className="mt-0.5 block text-xs text-emerald-700/80">
                  Оценка строится по данным формы ниже · можно заменить другой версией
                </span>
              </>
            )
          ) : (
            <>
              <span className="block text-sm font-medium text-sky-900">Загрузить резюме в PDF</span>
              <span className="mt-0.5 block text-xs text-sky-700/75">
                Перетащите файл или нажмите — заполним поля формы
              </span>
            </>
          )}
        </span>
      </button>
      <HelpTip id="resume.pdf-upload" />
    </div>
  )
}
