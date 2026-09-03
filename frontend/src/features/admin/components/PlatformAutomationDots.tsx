import type { AdminPipelineBrief } from "@/api/admin"
import { StatusDot, type StatusTone } from "@/components/ui/status-chip"
import { AUTOMATION_PLATFORMS, countActive } from "@/features/admin/automation-status"

const PLATFORM_LABEL: Record<string, string> = { hh: "hh", getmatch: "gm", habr: "hb" }

const DISCOVERY_WORD: Record<string, string> = {
  running: "работает",
  paused: "на паузе",
  idle: "выключен",
  off: "выключен",
}
const APPLY_WORD: Record<string, string> = {
  live: "работает",
  stale: "раннер молчит",
  off: "выключен",
}

/** Тон точки по «худшему» состоянию из трёх площадок: работает → strong, пауза/молчит → warn. */
function rowTone(
  map: Record<string, string> | undefined,
  running: (s: string) => boolean,
  warning: (s: string) => boolean,
): StatusTone {
  const states = AUTOMATION_PLATFORMS.map((p) => map?.[p] ?? "")
  if (states.some(warning)) return "warn"
  if (states.some(running)) return "strong"
  return "info"
}

function rowTitle(
  kind: string,
  map: Record<string, string> | undefined,
  words: Record<string, string>,
): string {
  const parts = AUTOMATION_PLATFORMS.map(
    (p) => `${PLATFORM_LABEL[p]}: ${words[map?.[p] ?? "off"] ?? "выключен"}`,
  )
  return `${kind} — ${parts.join(" · ")}`
}

/** Две строки для таблицы «Люди»: автопросмотр / автоотклик — точка-сигнал + «сколько из 3». */
export function PlatformAutomationDots({
  pipeline,
}: {
  pipeline: AdminPipelineBrief | null | undefined
}) {
  if (!pipeline) return <span className="text-slate-300">—</span>

  const rows: {
    key: string
    label: string
    tone: StatusTone
    active: number
    title: string
  }[] = [
    {
      key: "discovery",
      label: "Просмотр",
      tone: rowTone(
        pipeline.discovery,
        (s) => s === "running",
        (s) => s === "paused",
      ),
      active: countActive(pipeline.discovery, (s) => s === "running"),
      title: rowTitle("Автопросмотр", pipeline.discovery, DISCOVERY_WORD),
    },
    {
      key: "apply",
      label: "Отклик",
      tone: rowTone(
        pipeline.auto_apply,
        (s) => s === "live",
        (s) => s === "stale",
      ),
      active: countActive(pipeline.auto_apply, (s) => s === "live"),
      title: rowTitle("Автоотклик", pipeline.auto_apply, APPLY_WORD),
    },
  ]

  return (
    <div className="flex flex-col gap-1 text-xs">
      {rows.map((row) => (
        <div key={row.key} className="flex items-center gap-1.5" title={row.title}>
          <StatusDot tone={row.tone} />
          <span className="text-slate-500">{row.label}</span>
          <span className="tabular-nums text-slate-700">
            {row.active > 0 ? `${row.active}/3` : "—"}
          </span>
        </div>
      ))}
    </div>
  )
}
