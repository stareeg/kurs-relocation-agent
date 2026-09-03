import { Eye, Loader2, X } from "lucide-react"
import type { ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { scoreTone } from "@/features/jobs/funnel"
import { SourceIcon } from "@/features/jobs/SourceIcon"
import type { SourceGroup } from "@/features/jobs/source"
import { VacancyHoverPreview } from "@/features/jobs/VacancyHoverPreview"
import { cn } from "@/lib/utils"

// Правка 2026-08-20: жёсткий обрез названия/компании до фиксированного числа символов — раньше
// обрез был только CSS `truncate`, который зависит от того, сколько ширины реально досталось
// строке во флексе; при длинных названиях это варьировалось и в «Просмотре» регулярно съедало
// всю доступную ширину, выталкивая `actions` за границу колонки (см. фикс переноса ниже). Жёсткий
// лимит в JS делает ширину блока названия/компании предсказуемой независимо от вёрстки.
const MAX_LABEL_CHARS = 30

function truncateLabel(text: string | null | undefined): string {
  const value = (text ?? "").trim()
  return value.length > MAX_LABEL_CHARS ? `${value.slice(0, MAX_LABEL_CHARS)}…` : value
}

// Общая строка вакансии для обеих очередей «Расширения» — «Просмотр» (discovery-лог) и «Отклики»
// (auto-apply preview): иконка площадки + крупный скор (с опциональной подписью под ним —
// правка 2026-08-19 пункт 2, например время просмотра) рядом с ней, название (обрезка в 1 строку)
// → компания → `actions` (кнопки квик-экшенов, справа от названия/компании — правка пункт 3) →
// квадрат-предпросмотр (правка 2026-08-20) → `line3` (произвольный нижний слот).
function QueueVacancyRowContent({
  platform,
  title,
  company,
  score,
  scoreCaption,
}: {
  platform: SourceGroup
  title: string | null | undefined
  company: string | null | undefined
  score: number | null | undefined
  scoreCaption?: ReactNode
}) {
  return (
    <div className="flex min-w-0 flex-1 items-start gap-2">
      <SourceIcon group={platform} className="mt-0.5 shrink-0" />
      <div className="mt-0.5 flex shrink-0 flex-col items-center">
        <span
          className={cn(
            "text-2xl font-semibold leading-none tabular-nums",
            scoreTone(score),
          )}
        >
          {score ?? "—"}
        </span>
        {scoreCaption && (
          <span className="mt-0.5 text-[11px] leading-none text-slate-400">{scoreCaption}</span>
        )}
      </div>
      <div className="min-w-0 flex-1 overflow-hidden">
        <p className="truncate text-sm font-medium text-slate-800">{truncateLabel(title) || "Без названия"}</p>
        <p className="truncate text-xs text-slate-500">{truncateLabel(company) || "—"}</p>
      </div>
    </div>
  )
}

// Правка 2026-08-20: раньше весь блок иконка+скор+название+компания был обёрнут в ховер-триггер
// (`VacancyHoverPreview`) — переменной ширины область, из-за которой а) триггер прыгал по X от
// строки к строке (не наводишься «прямо вниз», нужно каждый раз целиться заново) и б) вложенные
// div'ы триггера ломали пропагацию `min-w-0` вниз по флекс-дереву (триггер сам не был flex-item
// ни в одном из мест использования), из-за чего `truncate` переставал резать длинные названия и
// они физически раздвигали строку, выталкивая `actions` за пределы видимой области. Ховер теперь
// живёт в отдельном квадрате фиксированного размера справа от кнопок — одна и та же X-координата
// в каждой строке списка, курсор просто ведётся вниз.
function PreviewTrigger({ vacancyId }: { vacancyId: string | null | undefined }) {
  if (!vacancyId) return <div className="size-8 shrink-0" aria-hidden />
  return (
    <VacancyHoverPreview vacancyId={vacancyId}>
      <div
        title="Навести — предпросмотр вакансии"
        className="flex size-8 shrink-0 cursor-default items-center justify-center rounded border border-dashed border-slate-300 text-slate-400 transition-colors hover:border-sky-400 hover:bg-sky-50 hover:text-sky-600"
      >
        <Eye className="size-3.5" strokeWidth={2} />
      </div>
    </VacancyHoverPreview>
  )
}

export function QueueVacancyRow({
  platform,
  vacancyId,
  title,
  company,
  score,
  scoreCaption,
  href,
  actions,
  beforePreview,
  line3,
  className,
}: {
  platform: SourceGroup
  vacancyId: string | null | undefined
  title: string | null | undefined
  company: string | null | undefined
  score: number | null | undefined
  /** Подпись под баллом слева (например время просмотра) — правка 2026-08-19 пункт 2. */
  scoreCaption?: ReactNode
  /** Правка 2026-08-20: реальная ссылка на вакансию на площадке (hh.ru/getmatch.ru/habr), не
   * внутренний дровер `/jobs/:id` — клик по названию в очереди открывал полноценный дровер в
   * разделе «Вакансии», что неудобно посреди разбора большой очереди автопросмотра/автооткликов;
   * открывается в новой вкладке, чтобы очередь не терялась. */
  href?: string | null
  /** Кнопки квик-экшенов справа от названия/компании — правка пункт 3, вне ссылки, чтобы клик
   * по кнопке не triggерил переход по `href`. */
  actions?: ReactNode
  /** Квадрат слева от превью-глазка (правка 2026-08-20, UX-правка «сопроводительное на виду») —
   * тот же размер/стиль, что у `PreviewTrigger`, для попапа сопроводительного письма. */
  beforePreview?: ReactNode
  line3?: ReactNode
  className?: string
}) {
  const content = (
    <QueueVacancyRowContent
      platform={platform}
      title={title}
      company={company}
      score={score}
      scoreCaption={scoreCaption}
    />
  )
  return (
    <div className={cn("px-4 py-2.5", className)}>
      {/* Правка 2026-08-20: `actions`+превью раньше жили в отдельном `shrink-0` блоке внутри
          НЕ-переносящейся (`flex`, без `flex-wrap`) строки — `shrink-0` запрещал ему сжиматься,
          а без `flex-wrap` на родителе ему было некуда перенестись, поэтому при нехватке ширины
          (длинное название в «Просмотре») блок кнопок просто вылезал за правую границу колонки и
          пропадал из виду. Теперь кнопки и квадрат-превью — один блок, а строка умеет переносить
          его целиком на вторую строку (`flex-wrap` на родителе), `ml-auto` прижимает его вправо
          что на первой строке, что на второй. */}
      <div className="flex flex-wrap items-start gap-2">
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            className="flex min-w-0 flex-1 hover:opacity-90"
          >
            {content}
          </a>
        ) : (
          content
        )}
        <div className="ml-auto mt-0.5 flex shrink-0 flex-wrap items-center justify-end gap-1.5">
          {actions}
          {beforePreview}
          <PreviewTrigger vacancyId={vacancyId} />
        </div>
      </div>
      {line3 && <div className="mt-1 pl-14">{line3}</div>}
    </div>
  )
}

// --- Три взаимоисключающие кнопки-решения (Автоотклик/Вручную/Пропуск) — правка 2026-08-20 -----
// Раньше решение системы («Откликнуться»/«На разбор»/«Пропущено») выводилось третьей строкой
// текстом под строкой вакансии — занимало вертикальное место и дублировало то, что и так можно
// увидеть по подсвеченной кнопке. Теперь оно подсвечивается прямо на одной из трёх кнопок —
// активная не кликабельна (уже применённое решение), две другие переводят вакансию в свою корзину.

export type DecisionKind = "auto" | "manual" | "skip"

const DECISION_ACTIVE_CLASS: Record<DecisionKind, string> = {
  auto: "border-status-strong-line bg-status-strong-soft text-status-strong-fg hover:bg-status-strong-soft",
  manual: "border-status-warn-line bg-status-warn-soft text-status-warn-fg hover:bg-status-warn-soft",
  skip: "border-status-bad-line bg-status-bad-soft text-status-bad-fg hover:bg-status-bad-soft",
}

function DecisionButton({
  kind,
  label,
  active,
  locked = true,
  forceClickable = false,
  pending,
  onClick,
}: {
  kind: DecisionKind
  label: string
  active: boolean
  /** Правка 2026-08-20: `active && !locked` — мягкая рекомендация системы (например «Пропуск» по
   * низкому скору свежей вакансии), ещё не применённое решение — кнопка подсвечена, как и у
   * настоящего решения, но остаётся кликабельной: клик применяет рекомендацию по-настоящему,
   * не дожидаясь конца очереди. Пунктирная рамка отличает «рекомендовано» от «уже применено». */
  locked?: boolean
  /** Правка (пункт 3, «в моменте», очередь «Автопросмотр»): раньше, когда решение владельца
   * совпадало с готовым решением системы (`active && locked`), кнопку задизейбливали — кликать
   * было нечего, а значит нечем было и вызвать перенос в живую очередь «Отклики» ПРЯМО СЕЙЧАС —
   * приходилось ждать фонового обновления/конца очереди. Кнопка остаётся визуально «решённой»
   * (сплошная рамка, тот же тон), но клик всё равно работает — идемпотентно переприменяет то же
   * решение и форсирует немедленный `invalidate` очереди «Отклики» (см. `useMoveAutoApplyQueueItem`). */
  forceClickable?: boolean
  pending?: boolean
  onClick?: () => void
}) {
  const isDecided = active && locked
  return (
    <Button
      type="button"
      size="xs"
      variant="outline"
      disabled={(isDecided && !forceClickable) || pending}
      onClick={onClick}
      title={
        isDecided
          ? forceClickable
            ? `Решение: ${label} — нажмите, чтобы перенести в «Отклики» сейчас`
            : `Решение: ${label}`
          : active
            ? `Рекомендация системы — нажмите, чтобы применить: ${label}`
            : `Перевести — ${label}`
      }
      className={cn(active && DECISION_ACTIVE_CLASS[kind], active && !locked && "border-dashed")}
    >
      {pending ? (
        <Loader2 className="size-3 animate-spin" strokeWidth={2} />
      ) : kind === "skip" ? (
        <X className="size-3" strokeWidth={2} />
      ) : null}
      {label}
    </Button>
  )
}

/** `active=null` — ни одна кнопка не подсвечена (решения ещё нет/не применимо, например «уже в
 * системе»). Любой из `onAuto`/`onManual`/`onSkip`, оставленный `undefined`, просто не рендерит
 * свою кнопку — используется в «Отклики», где «Пропуск» ведёт себя иначе, чем «В корзину excluded».
 * `activeLocked=false` (правка 2026-08-20) — `active` не факт принятого решения, а мягкая
 * рекомендация системы: кнопка подсвечена, но не задизейблена.
 * `forceClickable` (правка, пункт 3) — прокидывается в каждую кнопку как `forceClickable`, см.
 * комментарий у `DecisionButton`: даже «уже решённая» (`active && activeLocked`) кнопка остаётся
 * кликабельной, идемпотентно форсирует немедленный перенос вакансии в живую очередь. */
export function DecisionButtons({
  active,
  activeLocked = true,
  forceClickable = false,
  onAuto,
  onManual,
  onSkip,
  autoPending,
  manualPending,
  skipPending,
}: {
  active: DecisionKind | null
  activeLocked?: boolean
  forceClickable?: boolean
  onAuto?: () => void
  onManual?: () => void
  onSkip?: () => void
  autoPending?: boolean
  manualPending?: boolean
  skipPending?: boolean
}) {
  return (
    <>
      {onAuto && (
        <DecisionButton
          kind="auto"
          label="Автоотклик"
          active={active === "auto"}
          locked={activeLocked}
          forceClickable={forceClickable}
          pending={autoPending}
          onClick={onAuto}
        />
      )}
      {onManual && (
        <DecisionButton
          kind="manual"
          label="Вручную"
          active={active === "manual"}
          locked={activeLocked}
          forceClickable={forceClickable}
          pending={manualPending}
          onClick={onManual}
        />
      )}
      {onSkip && (
        <DecisionButton
          kind="skip"
          label="Пропуск"
          active={active === "skip"}
          locked={activeLocked}
          forceClickable={forceClickable}
          pending={skipPending}
          onClick={onSkip}
        />
      )}
    </>
  )
}
