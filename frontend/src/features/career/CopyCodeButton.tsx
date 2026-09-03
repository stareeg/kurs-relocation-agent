import { useState } from "react"
import { Copy } from "lucide-react"

// Полный блок «Друзья» переехал в features/settings/FriendsCompactSection.tsx (Аккаунт, левая
// колонка) — правка 2026-08-19 (5). Здесь остаётся только кнопка копирования кода дружбы,
// переиспользуемая оттуда.
export function CopyCodeButton({ code }: { code: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      className="group/copy flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(code)
        } catch {
          // Fallback: select the text
        }
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
      }}
    >
      <Copy className="size-3" strokeWidth={2} />
      <span className="hidden group-hover/copy:inline">
        {copied ? "Скопировано!" : "Копировать"}
      </span>
    </button>
  )
}
