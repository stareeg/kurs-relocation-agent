import { useState } from "react"
import { Check, Pencil, X } from "lucide-react"
import { hrContactName, resolveHrTelegramUrl } from "@/api/conversations"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

function InlineEdit({
  value,
  placeholder,
  onSave,
  onCancel,
  disabled,
}: {
  value: string
  placeholder: string
  onSave: (v: string) => void
  onCancel: () => void
  disabled?: boolean
}) {
  const [draft, setDraft] = useState(value)
  return (
    <span className="inline-flex items-center gap-1">
      <Input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder={placeholder}
        className="h-7 max-w-[180px] text-xs"
        disabled={disabled}
        autoFocus
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault()
            onSave(draft.trim())
          }
          if (e.key === "Escape") onCancel()
        }}
      />
      <button
        type="button"
        disabled={disabled}
        onClick={() => onSave(draft.trim())}
        className="rounded p-1 text-emerald-600 hover:bg-emerald-50"
        title="Сохранить"
      >
        <Check className="size-3.5" strokeWidth={2} />
      </button>
      <button
        type="button"
        disabled={disabled}
        onClick={onCancel}
        className="rounded p-1 text-slate-400 hover:bg-slate-100"
        title="Отмена"
      >
        <X className="size-3.5" strokeWidth={2} />
      </button>
    </span>
  )
}

function EditPencil({
  title,
  onClick,
  disabled,
}: {
  title: string
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className="rounded p-0.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:opacity-40"
    >
      <Pencil className="size-3" strokeWidth={2} />
    </button>
  )
}

/** Имя HR (клик → Telegram) + ссылка на HR, редактирование карандашом. */
export function HrContactRow({
  contactName,
  hrLink,
  onSave,
  disabled,
}: {
  contactName?: string | null
  hrLink?: string | null
  onSave?: (patch: { contactName?: string; hrLink?: string }) => void
  disabled?: boolean
}) {
  const [editName, setEditName] = useState(false)
  const [editLink, setEditLink] = useState(false)

  const name = hrContactName({ contact_name: contactName })
  const tgUrl = resolveHrTelegramUrl(hrLink)
  const linkLabel = tgUrl?.replace(/^https?:\/\//, "") ?? (hrLink || "").trim()

  // Кегль чуть крупнее заголовка вакансии (text-base против text-sm) — правый угол шапки иначе
  // терялся рядом с более заметным (кликабельным) названием вакансии слева.
  const linkCls = "text-[15px] text-slate-500 hover:text-violet-700 hover:underline"
  const nameLinkCls =
    "text-base font-semibold text-violet-700 hover:text-violet-800 hover:underline"
  const namePlainCls = "text-base font-semibold text-slate-700"
  const rowCls = "text-sm"

  return (
    <div className={cn("flex min-w-0 flex-wrap items-center justify-end gap-x-3 gap-y-0", rowCls)}>
      <span className="inline-flex min-w-0 items-center gap-1">
        {editName ? (
          <InlineEdit
            value={name}
            placeholder="Имя HR"
            disabled={disabled || !onSave}
            onCancel={() => setEditName(false)}
            onSave={(v) => {
              onSave?.({ contactName: v })
              setEditName(false)
            }}
          />
        ) : (
          <>
            {name && tgUrl ? (
              <a
                href={tgUrl}
                target="_blank"
                rel="noopener noreferrer"
                className={cn(nameLinkCls, "truncate")}
              >
                {name}
              </a>
            ) : name ? (
              <span className={cn(namePlainCls, "truncate")}>{name}</span>
            ) : (
              <span className="text-slate-400">HR не указан</span>
            )}
            {onSave && (
              <EditPencil
                title="Изменить имя HR"
                disabled={disabled}
                onClick={() => setEditName(true)}
              />
            )}
          </>
        )}
      </span>

      {(linkLabel || editLink || onSave) && (
        <span className="inline-flex min-w-0 items-center gap-1 text-slate-400">
          <span aria-hidden>·</span>
          {editLink ? (
            <InlineEdit
              value={(hrLink ?? "").trim()}
              placeholder="t.me/username"
              disabled={disabled || !onSave}
              onCancel={() => setEditLink(false)}
              onSave={(v) => {
                onSave?.({ hrLink: v })
                setEditLink(false)
              }}
            />
          ) : linkLabel && tgUrl ? (
            <>
              <a
                href={tgUrl}
                target="_blank"
                rel="noopener noreferrer"
                className={cn(linkCls, "truncate")}
              >
                {linkLabel}
              </a>
              {onSave && (
                <EditPencil
                  title="Изменить ссылку на HR"
                  disabled={disabled}
                  onClick={() => setEditLink(true)}
                />
              )}
            </>
          ) : onSave ? (
            <>
              <button
                type="button"
                onClick={() => setEditLink(true)}
                className="text-slate-400 hover:text-slate-600"
              >
                Добавить Telegram
              </button>
              <EditPencil
                title="Добавить ссылку на HR"
                disabled={disabled}
                onClick={() => setEditLink(true)}
              />
            </>
          ) : null}
        </span>
      )}
    </div>
  )
}
