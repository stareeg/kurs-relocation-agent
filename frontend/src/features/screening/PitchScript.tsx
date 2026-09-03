import { useEffect, useMemo, useRef, useState } from "react"
import { AlertTriangle, ChevronDown, Loader2, Pin, RefreshCw } from "lucide-react"
import type { PitchBlock } from "@/api/screening"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { formatDateTime } from "@/lib/format"
import { formatSpeakDuration, speakSeconds } from "@/lib/speech"
import { cn } from "@/lib/utils"

/** Общий стиль CTA скрининга: приглушённый тёмно-синий primary палитры. */
export const screeningCtaClass =
  "bg-slate-700 text-white hover:bg-slate-800 disabled:bg-slate-700 disabled:opacity-60"

const AUTOSAVE_DEBOUNCE_MS = 1500

function oneLine(text: string, max = 90): string {
  const flat = text.replace(/\s+/g, " ").trim()
  return flat.length > max ? `${flat.slice(0, max).trimEnd()}…` : flat
}

/** Блоки → плоский текст для редактирования (тот же формат, что бэкенд пишет в `oral_pitch`
 * при ручной правке — см. `edit_pitch_manual`). */
function blocksToPlainText(blocks: PitchBlock[]): string {
  return blocks
    .map((b) => [b.label, (b.lines ?? []).join(" ")].filter(Boolean).join("\n"))
    .join("\n\n")
    .trim()
}

/** «Рассказ об опыте» (было «Легенда под вакансию») — закреплённое сообщение в верху чата
 * Скринингов (план п.2), по образцу `VacancyPinnedText.tsx`: свёрнутая шапка + клик-чтобы-
 * редактировать текст с автосохранением. Ручная правка схлопывает структурные `blocks` в плоский
 * текст (единственный источник правды дальше, как у `vacancy_text`). Отдельный нередактируемый
 * блок `why_company` («Почему сюда») больше не рисуем — тот же смысл уже есть в `pitch_blocks`. */
export function PitchScript({
  blocks,
  oralPitch,
  generatedAt,
  generating = false,
  onRebuild,
  rebuilding = false,
  onSave,
  saving = false,
}: {
  blocks: PitchBlock[]
  oralPitch: string
  whyCompany?: string
  generatedAt?: string | null
  /** LLM ещё собирает первичный пакет — контента пока нет вовсе. */
  generating?: boolean
  /** Пересобрать через LLM (вопросы HR не трогаем). */
  onRebuild?: () => void
  rebuilding?: boolean
  /** Сохранить ручную правку (флэттит blocks → oral_pitch на бэкенде). */
  onSave?: (text: string) => void
  saving?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState("")
  const [dirty, setDirty] = useState(false)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const savedTextRef = useRef("")

  const hasBlocks = blocks.length > 0
  const hasOral = oralPitch.trim().length > 0
  const hasContent = hasBlocks || hasOral
  const flatText = hasBlocks ? blocksToPlainText(blocks) : oralPitch.trim()

  const seconds = useMemo(() => {
    if (hasBlocks) return speakSeconds(blocks.flatMap((b) => b.lines ?? []).join(" "))
    return speakSeconds(oralPitch)
  }, [blocks, hasBlocks, oralPitch])

  useEffect(
    () => () => {
      if (saveTimer.current) clearTimeout(saveTimer.current)
    },
    [],
  )

  function startEdit() {
    savedTextRef.current = flatText
    setDraft(flatText)
    setDirty(false)
    setEditing(true)
  }

  function toggleOpen() {
    setOpen((v) => {
      const next = !v
      if (next && !hasContent && !generating) startEdit()
      return next
    })
  }

  function stopEdit() {
    if (saveTimer.current) {
      clearTimeout(saveTimer.current)
      saveTimer.current = null
    }
    setEditing(false)
    setDirty(false)
    if (!savedTextRef.current) setOpen(false)
  }

  function commit(value: string) {
    const v = value.trim()
    if (!v || v === savedTextRef.current || saving || !onSave) return
    savedTextRef.current = v
    onSave(v)
  }

  function scheduleSave(value: string) {
    setDirty(true)
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      saveTimer.current = null
      setDirty(false)
      commit(value)
    }, AUTOSAVE_DEBOUNCE_MS)
  }

  function flushSave() {
    if (saveTimer.current) {
      clearTimeout(saveTimer.current)
      saveTimer.current = null
    }
    setDirty(false)
    commit(draft)
  }

  if (generating && !hasContent) {
    return (
      <div className="border-b bg-white px-4 py-2.5">
        <div className="flex items-center gap-2 text-sm">
          <Loader2 className="size-4 shrink-0 animate-spin text-slate-400" strokeWidth={2} />
          <span className="font-medium text-slate-700">Рассказ об опыте</span>
          <span className="text-slate-500">собираю…</span>
        </div>
      </div>
    )
  }

  const missing = !hasContent

  return (
    <div className={cn("border-b", missing ? "bg-amber-50/60" : "bg-white")}>
      <button
        type="button"
        onClick={toggleOpen}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm transition-colors hover:bg-black/[0.02]"
      >
        {missing ? (
          <AlertTriangle className="size-4 shrink-0 text-amber-600" strokeWidth={2} />
        ) : (
          <Pin className="size-4 shrink-0 text-slate-400" strokeWidth={2} />
        )}
        <span className="min-w-0 flex-1 truncate">
          <span className={cn("font-medium", missing ? "text-amber-800" : "text-slate-700")}>
            Рассказ об опыте
          </span>
          {!missing && flatText ? <span className="text-slate-500"> · {oneLine(flatText)}</span> : null}
          {missing ? (
            <span className="text-amber-700"> · не собран, нажмите, чтобы написать</span>
          ) : null}
        </span>
        {!missing && seconds > 0 && (
          <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
            ≈ {formatSpeakDuration(seconds)}
          </span>
        )}
        {!missing && generatedAt && (
          <span className="shrink-0 text-xs tabular-nums text-slate-400">
            {formatDateTime(generatedAt)}
          </span>
        )}
        {saving || dirty ? (
          <Loader2 className="size-3.5 shrink-0 animate-spin text-slate-400" strokeWidth={2} />
        ) : null}
        <ChevronDown
          className={cn(
            "size-3.5 shrink-0 text-slate-400 transition-transform",
            open && "rotate-180",
          )}
          strokeWidth={2}
        />
      </button>

      {open ? (
        <div className="space-y-2 px-4 pb-3">
          {editing ? (
            <>
              <Textarea
                value={draft}
                onChange={(e) => {
                  setDraft(e.target.value)
                  scheduleSave(e.target.value)
                }}
                onBlur={flushSave}
                onKeyDown={(e) => {
                  if (e.key === "Escape") {
                    e.currentTarget.blur()
                    stopEdit()
                  }
                }}
                placeholder="Расскажите об опыте своими словами — как рассказали бы на скрининге вслух."
                className="w-full bg-white text-sm"
                maxHeight={320}
                autoFocus
              />
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs text-slate-400">
                  {dirty ? "сохраняю…" : "сохранено — просто начните печатать, чтобы изменить"}
                </p>
                {onRebuild && (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={rebuilding}
                    onClick={onRebuild}
                    aria-label="Пересобрать рассказ"
                  >
                    <RefreshCw
                      className={cn("size-3.5", rebuilding && "animate-spin")}
                      strokeWidth={2}
                    />
                    {rebuilding ? "Собираю…" : "Пересобрать"}
                  </Button>
                )}
              </div>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={startEdit}
                title="Нажмите, чтобы редактировать"
                className="block w-full text-left"
              >
                <div className="max-h-72 space-y-3 overflow-y-auto rounded-lg border bg-white p-3 transition-colors hover:bg-slate-50">
                  {hasBlocks ? (
                    blocks.map((block, i) => (
                      <div key={i}>
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                          {block.label}
                        </p>
                        <p className="mt-1 text-sm leading-6 text-slate-800">
                          {(block.lines ?? []).join(" ")}
                        </p>
                      </div>
                    ))
                  ) : (
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
                      {oralPitch}
                    </p>
                  )}
                </div>
              </button>

              {onRebuild && (
                <div className="flex justify-end">
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={rebuilding}
                    onClick={onRebuild}
                    aria-label="Пересобрать рассказ"
                  >
                    <RefreshCw
                      className={cn("size-3.5", rebuilding && "animate-spin")}
                      strokeWidth={2}
                    />
                    {rebuilding ? "Собираю…" : "Пересобрать"}
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      ) : null}
    </div>
  )
}
