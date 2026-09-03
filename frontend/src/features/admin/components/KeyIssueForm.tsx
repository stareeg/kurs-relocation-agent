import { useState, type ReactNode } from "react"
import { Eye, EyeOff } from "lucide-react"
import type { AdminKeyVerify } from "@/api/admin"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { looksLikeOpenRouterKey, sanitizeOpenRouterKey } from "@/lib/openrouter-key"
import { remainingLabel } from "@/features/admin/admin-format"
import { useIssueAdminKey, useVerifyAdminKey, useVerifyStoredAdminKey } from "@/features/admin/use-admin"

const SELF_REPLACE_COPY =
  "У человека свой ключ. Ваш заменит его, и человек больше не сможет управлять ключом сам."

/**
 * Выдача ключа: вставил → проверить → плашка с остатком → выдать.
 * Поле — password с глазом; секрет чистится в finally, даже если выдача упала (В10).
 */
export function KeyIssueForm({
  accountId,
  submitLabel,
  extra,
  existingOrigin,
  hasStoredKey = false,
  onIssued,
}: {
  accountId: number
  submitLabel: string
  extra?: ReactNode
  existingOrigin?: "self" | "admin" | null
  /** Есть сохранённый ключ — «Проверить» работает и без вставки нового. */
  hasStoredKey?: boolean
  /** Закрыть диалог выдачи после успеха — поле всё равно чистится в finally. */
  onIssued?: () => void
}) {
  const issue = useIssueAdminKey()
  const verify = useVerifyAdminKey()
  const verifyStored = useVerifyStoredAdminKey()
  const [key, setKey] = useState("")
  const [visible, setVisible] = useState(false)
  const [probe, setProbe] = useState<AdminKeyVerify | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const cleaned = sanitizeOpenRouterKey(key)
  const looksValid = looksLikeOpenRouterKey(cleaned)
  const busy = issue.isPending || verify.isPending || verifyStored.isPending
  const canCheck = looksValid || hasStoredKey

  const applyInput = (raw: string) => {
    const next = sanitizeOpenRouterKey(raw)
    setKey(next)
    setProbe(null)
  }

  const runIssue = async () => {
    try {
      await issue.mutateAsync({
        accountId,
        key: cleaned,
      })
      onIssued?.()
    } catch {
      // тост уже из хука; поле всё равно чистим — секрет не должен оставаться в DOM
    } finally {
      setKey("")
      setProbe(null)
    }
  }

  const onSubmit = () => {
    if (existingOrigin === "self") {
      setConfirmOpen(true)
      return
    }
    void runIssue()
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-end gap-1.5">
        <div className="min-w-0 flex-1">
          <div className="mb-1">
            <span className="text-xs font-medium text-slate-500">Ключ</span>
          </div>
          <div className="relative">
            <Input
              type={visible ? "text" : "password"}
              value={key}
              onChange={(e) => applyInput(e.target.value)}
              placeholder="sk-or-v1-…"
              autoComplete="off"
              spellCheck={false}
              aria-label="Ключ OpenRouter"
              className="pr-9 font-mono text-sm"
            />
            <button
              type="button"
              onClick={() => setVisible((v) => !v)}
              aria-label={visible ? "Скрыть ключ" : "Показать ключ"}
              className="absolute top-1/2 right-1 -translate-y-1/2 rounded p-0.5 text-slate-400 hover:text-slate-700"
            >
              {visible ? <EyeOff className="size-3.5" strokeWidth={2} /> : <Eye className="size-3.5" strokeWidth={2} />}
            </button>
          </div>
        </div>
      </div>
      {key && !looksValid && (
        <p className="text-xs text-status-warn-fg">Ключ должен начинаться с sk-or-.</p>
      )}
      {probe && <VerifyBanner probe={probe} />}
      <div className="flex flex-wrap gap-1.5">
        <Button
          size="sm"
          variant="outline"
          disabled={busy || !canCheck}
          onClick={() => {
            if (looksValid) {
              void verify.mutateAsync(cleaned).then(setProbe)
              return
            }
            void verifyStored.mutateAsync(accountId).then(setProbe)
          }}
        >
          Проверить
        </Button>
        <Button size="sm" disabled={busy || !looksValid} onClick={onSubmit}>
          {submitLabel}
        </Button>
        {extra}
      </div>
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Заменить свой ключ человека?"
        description={SELF_REPLACE_COPY}
        confirmLabel="Заменить"
        onConfirm={() => {
          setConfirmOpen(false)
          void runIssue()
        }}
      />
    </div>
  )
}

function VerifyBanner({ probe }: { probe: AdminKeyVerify }) {
  const tone = probe.network_error ? "warn" : probe.alive ? "ok" : "bad"
  const text = probe.network_error
    ? "OpenRouter не ответил — выдать всё равно можно"
    : probe.alive
      ? `Жив · ${remainingLabel(probe)}`
      : probe.error || "ключ не принят"
  return (
    <p
      className={cn(
        "rounded-md px-2 py-1 text-xs",
        tone === "ok" && "bg-slate-100 text-slate-700",
        tone === "warn" && "bg-status-warn-soft text-status-warn-fg",
        tone === "bad" && "bg-status-bad-soft text-status-bad-fg",
      )}
    >
      {text}
    </p>
  )
}
