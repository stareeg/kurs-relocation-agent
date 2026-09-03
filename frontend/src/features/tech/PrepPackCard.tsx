import { useMemo, useState } from "react"
import { Check, ChevronDown, ClipboardList, Wand2, X } from "lucide-react"
import type { Job } from "@/api/jobs"
import { MarkdownView } from "@/components/markdown-view"
import { Button } from "@/components/ui/button"
import { SkeletonCard } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { formatDateTime } from "@/lib/format"
import { diffWords, hasChanges, stripMarks } from "@/lib/text-diff"
import { usePrepPack } from "./use-prep"

// RD-16: авто-бриф подготовки под конкретный этап («что спросят», слабые темы, фидбек рекрутёра)
// первым блоком режима «Подготовка». Персист+ревью — тот же паттерн, что «Перегенерировать
// легенду» (Скрининги): регенерация не сохраняет сама, фронт подсвечивает diff, владелец решает.

function PackDiffReview({
  current,
  candidate,
  onAccept,
  onDiscard,
  saving,
}: {
  current: string
  candidate: string
  onAccept: () => void
  onDiscard: () => void
  saving: boolean
}) {
  const segments = useMemo(
    () => diffWords(stripMarks(current), stripMarks(candidate)),
    [current, candidate],
  )
  const changed = hasChanges(segments)
  return (
    <div className="overflow-hidden rounded-xl border border-emerald-200 bg-emerald-50/40">
      <div className="flex items-center justify-between gap-3 border-b border-emerald-200/70 px-5 py-3">
        <div className="space-y-0.5">
          <p className="flex items-center gap-1.5 text-sm font-medium text-emerald-900">
            <Wand2 className="size-4" strokeWidth={2} />
            Собранный бриф подготовки
          </p>
          <p className="text-xs text-emerald-700/70">
            {current.trim()
              ? changed
                ? "Зелёным — что изменилось. Принять заменит бриф, Отклонить оставит текущий."
                : "Почти без изменений — бриф уже был точным."
              : "Принять сохранит бриф, Отклонить ничего не сохранит."}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Button size="sm" variant="ghost" onClick={onDiscard} disabled={saving}>
            <X className="size-4" strokeWidth={2} />
            Отклонить
          </Button>
          <Button size="sm" onClick={onAccept} disabled={saving}>
            <Check className="size-4" strokeWidth={2} />
            {saving ? "Сохраняю…" : "Принять"}
          </Button>
        </div>
      </div>
      <div className="p-5">
        {current.trim() ? (
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
            {segments.map((s, i) =>
              s.added ? (
                <mark key={i} className="rounded bg-emerald-200/70 text-emerald-950">
                  {s.text}
                </mark>
              ) : (
                <span key={i}>{s.text}</span>
              ),
            )}
          </p>
        ) : (
          <MarkdownView markdown={candidate} chat />
        )}
      </div>
    </div>
  )
}

// UX2-7.1: карточка чисто презентационная — генерацию/регенерацию триггерит общая кнопка
// «Подготовиться» в TechPage (одновременно с вопросами), сюда приходят только пропсы состояния
// текущего LLM-запроса. Свой локальный скелетон/статус, не пропадает под общим PrepSkeleton
// страницы, пока идёт генерация вопросов.
export function PrepPackCard({
  job,
  stage,
  regenerating,
  candidate,
  onAccept,
  onDiscard,
  saving,
}: {
  job: Job | null
  stage: string
  regenerating: boolean
  candidate: string | null
  onAccept: () => void
  onDiscard: () => void
  saving: boolean
}) {
  const vacancyId = job?.vacancy_id ?? null
  const { data: pack, isLoading } = usePrepPack(vacancyId, stage)
  const [collapsed, setCollapsed] = useState(false)

  if (!job) return null

  const content = pack?.content ?? ""

  if (isLoading || (regenerating && !content.trim())) {
    return <SkeletonCard className="h-24" />
  }

  if (candidate !== null) {
    return (
      <PackDiffReview
        current={content}
        candidate={candidate}
        onAccept={onAccept}
        onDiscard={onDiscard}
        saving={saving}
      />
    )
  }

  if (content.trim()) {
    return (
      <div className="rounded-xl border bg-white p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            className="flex min-w-0 items-center gap-2 text-left"
          >
            <ClipboardList className="size-4 shrink-0 text-slate-400" strokeWidth={2} />
            <h2 className="text-sm font-semibold text-slate-900">Бриф подготовки</h2>
            <ChevronDown
              className={cn(
                "size-3.5 shrink-0 text-slate-400 transition-transform",
                collapsed && "-rotate-90",
              )}
              strokeWidth={2}
            />
          </button>
          <div className="flex items-center gap-2">
            {pack?.updated_at && (
              <span className="text-xs text-slate-400">
                Собран {formatDateTime(pack.updated_at)}
              </span>
            )}
            {regenerating && <span className="text-xs text-slate-400">Собираю свежий…</span>}
          </div>
        </div>
        {!collapsed && (
          <div className="mt-3 border-t border-dashed pt-3">
            <MarkdownView markdown={content} chat />
          </div>
        )}
      </div>
    )
  }

  return null
}
