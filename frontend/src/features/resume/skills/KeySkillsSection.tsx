import { memo, useState } from "react"
import { Copy, Trash2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { HelpTip } from "@/components/ui/help-tip"
import { cn } from "@/lib/utils"
import { NeedsFillWrap, Section } from "../section"
import { SkillsPanel } from "./SkillsPanel"

// hh.ru режет ключевые навыки на 30 тегов — держим предупреждение везде, где их трогаем.
const SKILLS_LIMIT = 30

// Ввод сразу в область тегов: Enter/запятая/; /таб — добавить, blur — добрать остаток,
// Backspace на пустом поле снимает последний тег, вставка многострочного списка — парсится
// в теги сразу. Автосохранение — в родителе (onChange → PATCH).
function TagEditor({
  tags,
  onChange,
  needsFill,
}: {
  tags: string[]
  onChange: (next: string[]) => void
  needsFill?: boolean
}) {
  const [draft, setDraft] = useState("")
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [dropIndex, setDropIndex] = useState<number | null>(null)

  const parseDraft = (text: string): string[] =>
    text
      .split(/[,;\t\n]+/)
      .map((t) => t.trim())
      .filter(Boolean)

  // Лимита hh (30) на вводе нет — бэк не режет, а пользователь может держать больше и потом
  // чистить; счётчик в заголовке секции показывает перебор, но не блокирует.
  const mergeTags = (parts: string[]) => {
    const fresh = parts.filter((t) => !tags.includes(t))
    if (fresh.length === 0) return
    onChange([...tags, ...fresh])
  }

  const addFromDraft = () => {
    mergeTags(parseDraft(draft))
    setDraft("")
  }

  const removeTag = (tag: string) => {
    onChange(tags.filter((x) => x !== tag))
  }

  const onPaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
    const text = e.clipboardData.getData("text")
    // Многострочная/списочная вставка — сразу в теги, без промежуточного состояния в поле.
    if (!/[,;\t\n]/.test(text)) return
    e.preventDefault()
    mergeTags(parseDraft(text))
  }

  const onDragStart = (e: React.DragEvent<HTMLSpanElement>, index: number) => {
    e.dataTransfer.setData("text/plain", tags[index])
    e.dataTransfer.effectAllowed = "move"
    setDragIndex(index)
  }

  const onDragOverTag = (e: React.DragEvent<HTMLSpanElement>, index: number) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = "move"
    if (dropIndex !== index) setDropIndex(index)
  }

  const onDropTag = (e: React.DragEvent<HTMLSpanElement>, index: number) => {
    e.preventDefault()
    if (dragIndex === null || dragIndex === index) {
      setDragIndex(null)
      setDropIndex(null)
      return
    }
    const next = [...tags]
    const [moved] = next.splice(dragIndex, 1)
    next.splice(index, 0, moved)
    onChange(next)
    setDragIndex(null)
    setDropIndex(null)
  }

  const onDragEnd = () => {
    setDragIndex(null)
    setDropIndex(null)
  }

  return (
    <NeedsFillWrap active={needsFill}>
      <div className="flex min-h-[42px] flex-wrap items-center gap-1.5 rounded-lg border bg-slate-50/50 p-2">
        {tags.map((t, index) => (
          <span
            key={`${t}-${index}`}
            draggable
            onDragStart={(e) => onDragStart(e, index)}
            onDragOver={(e) => onDragOverTag(e, index)}
            onDrop={(e) => onDropTag(e, index)}
            onDragEnd={onDragEnd}
            className={cn(
              "inline-flex cursor-grab items-center gap-1 rounded-md bg-white px-2 py-1 text-xs text-slate-700 shadow-xs transition-colors",
              dragIndex === index && "opacity-40",
              dropIndex === index && dragIndex !== null && "ring-2 ring-sky-300",
              "active:cursor-grabbing",
            )}
          >
            {t}
            <button
              type="button"
              onClick={() => removeTag(t)}
              className="text-slate-400 transition-colors hover:text-slate-700"
              aria-label={`Убрать ${t}`}
            >
              <X className="size-3" strokeWidth={2} />
            </button>
          </span>
        ))}
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onPaste={onPaste}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === "," || e.key === ";" || e.key === "Tab") {
              e.preventDefault()
              addFromDraft()
            } else if (e.key === "Backspace" && draft === "" && tags.length > 0) {
              e.preventDefault()
              onChange(tags.slice(0, -1))
            } else if (e.key === "Escape") {
              setDraft("")
            }
          }}
          onBlur={addFromDraft}
          placeholder="добавить…"
          className="min-w-24 flex-1 bg-transparent px-1 py-1 text-sm outline-none placeholder:text-slate-400"
        />
      </div>
    </NeedsFillWrap>
  )
}

export const KeySkillsSection = memo(function KeySkillsSection({
  tags,
  onChange,
}: {
  tags: string[]
  onChange: (next: string[]) => void
}) {
  const clearAll = () => {
    if (tags.length === 0) return
    onChange([])
  }

  const copyAll = async () => {
    try {
      await navigator.clipboard.writeText(tags.join(", "))
    } catch {
      // Без clipboard API — молча ничего, UI не рушим.
    }
  }

  return (
    <Section
      id="skills"
      title="Навыки"
      helpId="resume.section-skills"
      needsFill={tags.length === 0}
      className="scroll-mt-4"
      hint={`${tags.length}/${SKILLS_LIMIT}`}
      action={
        <div className="flex shrink-0 items-center gap-1.5">
          <HelpTip id="resume.skills-limit" />
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={clearAll}
            disabled={tags.length === 0}
            className="h-7 border-rose-200 bg-rose-50 px-2 text-xs text-rose-700 hover:bg-rose-100 hover:text-rose-800"
            aria-label="Удалить все теги разом"
          >
            <Trash2 className="size-3" strokeWidth={2} />
            Очистить
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={copyAll}
            disabled={tags.length === 0}
            className="h-7 px-2 text-xs"
            aria-label="Скопировать список навыков"
          >
            <Copy className="size-3" strokeWidth={2} />
            Копировать
          </Button>
        </div>
      }
    >
      <TagEditor tags={tags} onChange={onChange} needsFill={tags.length === 0} />
      <div id="skills-panel" className="mt-5 border-t border-slate-100 pt-5">
        <SkillsPanel />
      </div>
    </Section>
  )
})
