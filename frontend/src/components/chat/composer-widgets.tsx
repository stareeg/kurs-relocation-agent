import { Check, Copy, Eye, EyeOff, type LucideIcon, Trash2, X } from "lucide-react"
import { cn } from "@/lib/utils"

// Общие куски визуального языка диалоговых лент (Чаты/вакансия, Технички/подготовка): переключатель
// режима композера с "глазиком" скрытия, тулбар выделения сообщений, подсветка сообщения-источника
// цитаты. Вынесено из features/jobs/VacancyDialog.tsx — второй потребитель (features/tech/PrepChat)
// не может импортировать оттуда напрямую (chat → jobs → tech уже существует, обратный импорт дал бы
// цикл), а этот компонент ничего не знает о конкретной фиче.

// thumbUrl (план §6.6): цитата над полем ввода для сообщения с картинкой показывает миниатюру
// вместо текстового отрывка — body в этом случае несёт заголовок распознавания, не текст со скрина.
export type ReplyTarget = { id: number; label: string; body: string; thumbUrl?: string }

const HIGHLIGHT_MS = 1600

/** Прокрутить к сообщению-источнику цитаты и на мгновение подсветить его. */
// eslint-disable-next-line react-refresh/only-export-components -- утилита рядом с виджетами, общий модуль
export function flashMessage(id: number): void {
  const el = document.getElementById(`msg-${id}`)
  if (!el) return
  el.scrollIntoView({ behavior: "smooth", block: "center" })
  el.classList.add("ring-2", "ring-sky-300", "ring-offset-2", "transition-shadow")
  window.setTimeout(() => {
    el.classList.remove("ring-2", "ring-sky-300", "ring-offset-2", "transition-shadow")
  }, HIGHLIGHT_MS)
}

/** Русское склонение «сообщение/сообщения/сообщений» по числу — подтверждение удаления. */
// eslint-disable-next-line react-refresh/only-export-components -- утилита рядом с виджетами, общий модуль
export function pluralMessages(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return "сообщение"
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return "сообщения"
  return "сообщений"
}

// eslint-disable-next-line react-refresh/only-export-components -- утилита рядом с виджетами, общий модуль
export function oneLine(text: string, max = 90): string {
  const flat = text.replace(/\s+/g, " ").trim()
  return flat.length > max ? `${flat.slice(0, max).trimEnd()}…` : flat
}

/** Одна вкладка режима композера (Агент/HR, Агент/Расшифровка, …) + кнопка «глазик» скрытия из
 * ленты. `done` — по этому режиму уже есть содержимое (вставлена расшифровка): галка вместо
 * иконки режима и зелёный тон, чтобы «есть/нет» читалось прямо на переключалке, а не только по
 * ленте. */
export function ModeSegment({
  active,
  onClick,
  icon: Icon,
  label,
  hidden,
  onToggleHidden,
  hideTitle,
  done = false,
  doneTitle,
}: {
  active: boolean
  onClick: () => void
  icon: LucideIcon
  label: string
  hidden: boolean
  onToggleHidden: () => void
  hideTitle: string
  done?: boolean
  doneTitle?: string
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-0.5 rounded-lg transition-colors",
        active ? "bg-white shadow-sm" : "hover:bg-slate-200/60",
        done && "ring-1 ring-status-strong-line",
        done && active && "bg-status-strong-soft",
      )}
    >
      <button
        type="button"
        onClick={onClick}
        title={done ? doneTitle : undefined}
        className={cn(
          "flex items-center gap-1.5 rounded-lg py-1.5 pl-2.5 pr-1 text-sm font-medium transition-opacity",
          done ? "text-status-strong-fg" : active ? "text-slate-900" : "text-slate-500",
          hidden && "opacity-50",
        )}
      >
        {done ? (
          <Check className="size-4" strokeWidth={2.5} />
        ) : (
          <Icon className="size-4" strokeWidth={2} />
        )}
        {label}
      </button>
      <button
        type="button"
        onClick={onToggleHidden}
        aria-label={hidden ? `Показать: ${hideTitle}` : `Скрыть: ${hideTitle}`}
        title={hidden ? `Показать в ленте: ${hideTitle}` : `Скрыть из ленты: ${hideTitle}`}
        className="rounded-md p-1.5 text-slate-400 transition-colors hover:bg-slate-200/70 hover:text-slate-600"
      >
        {hidden ? (
          <EyeOff className="size-3.5" strokeWidth={2} />
        ) : (
          <Eye className="size-3.5" strokeWidth={2} />
        )}
      </button>
    </div>
  )
}

export function ComposerActionButton({
  icon: Icon,
  label,
  onClick,
  disabled,
  active,
  tone = "default",
}: {
  icon: LucideIcon
  label: string
  onClick: () => void
  disabled?: boolean
  active?: boolean
  tone?: "default" | "destructive"
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className={cn(
        "inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium transition-colors disabled:opacity-50",
        tone === "destructive"
          ? "text-rose-600 hover:bg-rose-50"
          : active
            ? "bg-slate-100 text-slate-900"
            : "text-slate-500 hover:bg-slate-100",
      )}
    >
      <Icon className="size-3.5" strokeWidth={2} />
      {label}
    </button>
  )
}

/** Панель массового действия над выделением сообщений (протяжка/right-click в ленте). */
export function SelectionToolbar({
  count,
  onCopy,
  onDelete,
  onClear,
}: {
  count: number
  onCopy: () => void
  onDelete: () => void
  onClear: () => void
}) {
  return (
    <div className="flex w-full items-center gap-2 rounded-xl bg-sky-50 px-2.5 py-1.5">
      <span className="pl-1 text-sm font-medium text-sky-900">Выделено: {count}</span>
      <div className="ml-auto flex items-center gap-1">
        <ComposerActionButton icon={Copy} label="Копировать" onClick={onCopy} />
        <ComposerActionButton icon={Trash2} label="Удалить" onClick={onDelete} tone="destructive" />
        <button
          type="button"
          onClick={onClear}
          aria-label="Снять выделение"
          className="rounded-md p-1.5 text-sky-700 transition-colors hover:bg-sky-100"
        >
          <X className="size-4" strokeWidth={2} />
        </button>
      </div>
    </div>
  )
}
