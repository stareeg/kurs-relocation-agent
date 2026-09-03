/* Context + hook в одном файле — бейдж сайдбара и панель очереди дня. */
/* eslint-disable react-refresh/only-export-components */
import { Bell, CalendarClock, Check, type LucideIcon, MessagesSquare, Sparkles } from "lucide-react"
import { useNavigate } from "react-router-dom"
import {
  type AttentionStage,
  type AttentionStrongJob,
  conversationListSubtitle,
  conversationTitle,
} from "@/api/conversations"
import { EmptyState, ErrorState } from "@/components/ui/empty-state"
import { StatusDot, type StatusTone } from "@/components/ui/status-chip"
import { formatEventLabel } from "@/lib/format"
import { cn } from "@/lib/utils"
import { useReminderDismiss } from "@/lib/use-reminder-dismiss"
import { fmtChatWhen } from "./fmt-chat-when"
import { useTodayAttention } from "@/features/chat/use-conversations"

const STAGE_TYPE_LABEL: Record<string, string> = {
  hr_screening: "HR-скрининг",
  live_coding: "Лайвкодинг",
  system_design: "System design",
  theory: "Теория",
  soft_skills: "Софт-скиллы",
  manager: "С менеджером",
}

const STAGE_FORMAT_LABEL: Record<string, string> = {
  online: "онлайн",
  offline: "офлайн",
}

type TodayTone = "bad" | "warn" | "info" | "strong"

const TODAY_TONE_TEXT: Record<TodayTone, string> = {
  bad: "text-status-bad-fg",
  warn: "text-status-warn-fg",
  info: "text-status-info-fg",
  strong: "text-status-strong-fg",
}

function silenceDays(iso?: string | null): number {
  if (!iso) return 0
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return 0
  return Math.max(0, Math.floor((Date.now() - then) / 86_400_000))
}

function pluralDela(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod100 >= 11 && mod100 <= 14) return "дел"
  if (mod10 === 1) return "дело"
  if (mod10 >= 2 && mod10 <= 4) return "дела"
  return "дел"
}

function pluralSobes(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return "собес"
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return "собеса"
  return "собесов"
}

function pluralStrong(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return "сильная"
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return "сильные"
  return "сильных"
}

function SectionCard({
  icon: Icon,
  tone,
  title,
  count,
  children,
}: {
  icon: LucideIcon
  tone: StatusTone
  title: string
  count: number
  children: React.ReactNode
}) {
  if (count === 0) return null
  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <StatusDot tone={tone} />
        <Icon className="size-4 text-muted-foreground" strokeWidth={2} />
        <span className="text-sm font-semibold text-foreground">{title}</span>
        <span className="ml-auto text-xs text-muted-foreground">{count}</span>
      </div>
      <ul className="divide-y">{children}</ul>
    </div>
  )
}

function Row({
  onClick,
  onDismiss,
  title,
  subtitle,
  meta,
}: {
  onClick: () => void
  onDismiss?: () => void
  title: string
  subtitle?: string
  meta?: string
}) {
  return (
    <li className="flex items-center gap-0.5 pl-1.5">
      <button
        type="button"
        onClick={onDismiss}
        title="Отметить выполненным"
        aria-label="Отметить выполненным"
        className="flex size-6 shrink-0 items-center justify-center rounded-full text-muted-foreground/40 transition-colors hover:bg-accent hover:text-emerald-600"
      >
        <Check className="size-3.5" strokeWidth={2} />
      </button>
      <button
        type="button"
        onClick={onClick}
        className="flex min-w-0 flex-1 items-center gap-2 py-2 pr-3 text-left text-sm transition-colors hover:bg-accent"
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium text-foreground">{title}</span>
          {subtitle ? (
            <span className="block truncate text-xs text-muted-foreground">{subtitle}</span>
          ) : null}
        </span>
        {meta ? (
          <span className="shrink-0 text-xs font-medium tabular-nums text-muted-foreground">
            {meta}
          </span>
        ) : null}
      </button>
    </li>
  )
}

/** Счётчик живых уведомлений (после клиентских «выполнено») — бейдж в сайдбаре. */
export function useNotificationBadgeCount(): number {
  const { data } = useTodayAttention()
  const { isDismissed } = useReminderDismiss()
  const reply = (data?.reply ?? []).filter((t) => !isDismissed("reply", t.vacancy_id)).length
  const remind = (data?.remind ?? []).filter((t) => !isDismissed("remind", t.vacancy_id)).length
  const upcoming = (data?.upcoming ?? []).filter(
    (s) => !isDismissed("upcoming", s.vacancy_id),
  ).length
  const strong = (data?.strong_unapplied ?? []).filter(
    (j) => !isDismissed("strong", j.vacancy_id),
  ).length
  return reply + remind + upcoming + strong
}

/** Очередь дня — во всплывающем окне сайдбара (наведение на «Сегодня»). */
export function NotificationsPanel({ onNavigate }: { onNavigate?: () => void }) {
  const navigate = useNavigate()
  const { data, isLoading, isError, refetch } = useTodayAttention()
  const { isDismissed, dismiss } = useReminderDismiss()

  const go = (to: string) => {
    onNavigate?.()
    navigate(to)
  }

  if (isLoading) {
    return <p className="px-3 py-6 text-center text-sm text-muted-foreground">Загрузка…</p>
  }

  if (isError) {
    return (
      <div className="p-2">
        <ErrorState
          compact
          icon={Sparkles}
          title="Очередь дня не загрузилась"
          note="Не удалось загрузить ответы HR, напоминания и ближайшие собесы."
          action={{ label: "Повторить", onClick: () => void refetch() }}
        />
      </div>
    )
  }

  const reply = (data?.reply ?? []).filter((t) => !isDismissed("reply", t.vacancy_id))
  const remind = (data?.remind ?? []).filter((t) => !isDismissed("remind", t.vacancy_id))
  const upcoming = (data?.upcoming ?? []).filter((s) => !isDismissed("upcoming", s.vacancy_id))
  const strong = (data?.strong_unapplied ?? []).filter((j) => !isDismissed("strong", j.vacancy_id))
  const total = reply.length + remind.length + upcoming.length + strong.length
  const breakdown = [
    { count: reply.length, label: `${reply.length} ответить`, tone: "bad" as TodayTone },
    { count: remind.length, label: `${remind.length} напомнить`, tone: "warn" as TodayTone },
    {
      count: upcoming.length,
      label: `${upcoming.length} ${pluralSobes(upcoming.length)}`,
      tone: "info" as TodayTone,
    },
    {
      count: strong.length,
      label: `${strong.length} ${pluralStrong(strong.length)}`,
      tone: "strong" as TodayTone,
    },
  ].filter((i) => i.count > 0)

  const todayLabel = new Date().toLocaleDateString("ru-RU", { day: "numeric", month: "long" })

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex items-baseline justify-between gap-2 px-0.5">
        <h2 className="text-sm font-semibold text-foreground">Сегодня</h2>
        <span className="text-xs text-muted-foreground">
          {todayLabel}
          {total > 0 ? ` · ${total} ${pluralDela(total)}` : ""}
        </span>
      </div>

      {total === 0 ? (
        <EmptyState
          icon={Sparkles}
          title="Очередь дня пуста"
          note="Оцените вакансии через расширение или откройте диалог — появятся ответы HR, напоминания и ближайшие собесы."
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5 px-0.5">
            {breakdown.map(({ label, tone }) => (
              <span key={label} className={cn("text-xs font-medium", TODAY_TONE_TEXT[tone])}>
                {label}
              </span>
            ))}
          </div>

          <SectionCard icon={CalendarClock} tone="info" title="Скоро собес" count={upcoming.length}>
            {upcoming.map((s: AttentionStage) => (
              <Row
                key={`${s.vacancy_id}-${s.scheduled_at ?? ""}`}
                onClick={() => go(`/tech?vacancy=${encodeURIComponent(s.vacancy_id)}`)}
                onDismiss={() => dismiss("upcoming", s.vacancy_id)}
                title={s.company || `Вакансия ${s.vacancy_id}`}
                subtitle={[
                  STAGE_TYPE_LABEL[s.stage_type] ?? s.stage_type,
                  STAGE_FORMAT_LABEL[s.format],
                ]
                  .filter(Boolean)
                  .join(" · ")}
                meta={formatEventLabel(s.scheduled_at)}
              />
            ))}
          </SectionCard>

          <SectionCard icon={MessagesSquare} tone="bad" title="Ответить" count={reply.length}>
            {reply.map((t) => (
              <Row
                key={t.id}
                onClick={() => go(`/chat?vacancy=${encodeURIComponent(t.vacancy_id)}`)}
                onDismiss={() => dismiss("reply", t.vacancy_id)}
                title={conversationTitle(t)}
                subtitle={conversationListSubtitle(t) ?? undefined}
                meta={t.last_hr_at ? fmtChatWhen(t.last_hr_at) : undefined}
              />
            ))}
          </SectionCard>

          <SectionCard icon={Bell} tone="warn" title="Напомнить" count={remind.length}>
            {remind.map((t) => (
              <Row
                key={t.id}
                onClick={() => go(`/chat?vacancy=${encodeURIComponent(t.vacancy_id)}`)}
                onDismiss={() => dismiss("remind", t.vacancy_id)}
                title={conversationTitle(t)}
                subtitle={conversationListSubtitle(t) ?? undefined}
                meta={`${silenceDays(t.last_hr_at)}д`}
              />
            ))}
          </SectionCard>

          <SectionCard icon={Sparkles} tone="strong" title="Свежие сильные" count={strong.length}>
            {strong.map((j: AttentionStrongJob) => (
              <Row
                key={j.vacancy_id}
                onClick={() => go(`/jobs/${encodeURIComponent(j.vacancy_id)}`)}
                onDismiss={() => dismiss("strong", j.vacancy_id)}
                title={j.title || j.company || `Вакансия ${j.vacancy_id}`}
                subtitle={j.company ?? undefined}
                meta={j.overall_score != null ? `${j.overall_score}` : undefined}
              />
            ))}
          </SectionCard>
        </>
      )}
    </div>
  )
}
