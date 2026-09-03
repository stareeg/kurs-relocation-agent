import { useEffect, useRef, useState, type ChangeEvent, type ReactNode } from "react"
import { CalendarClock, Check, FileText, Loader2, MapPin, Wallet } from "lucide-react"
import type { Job } from "@/api/jobs"
import type { OfferUpdateRequest } from "@/api/offers"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { ChipToggleGroup, type ChipOption } from "@/components/ui/chip-toggle-group"
import { HelpTip } from "@/components/ui/help-tip"
import { OfferRow } from "@/components/offers/OfferRow"
import { FORMAT_OPTS, TAX_BASIS_OPTS, rowByKey } from "@/features/offers/rows"
import { BONUS_PCT_DEFAULT, type BonusKind } from "@/features/offers/bonus"
import { effectiveWorkFormat } from "@/features/jobs/funnel"
import { useResumeData } from "@/features/resume/use-resume"
import { useCreateOffer, useParseOffer, usePatchOffer } from "@/features/offers/use-offers"
import type { HelpTextId } from "@/lib/help-texts"

const PERIOD_OPTS: ChipOption[] = [
  { value: "month", label: "В месяц" },
  { value: "year", label: "В год" },
]

const CURRENCY_OPTS: ChipOption[] = [
  { value: "RUB", label: "₽" },
  { value: "USD", label: "$" },
  { value: "EUR", label: "€" },
]

type DraftState = {
  base_salary: string
  base_salary_tax_basis: "gross" | "net"
  base_salary_period: "month" | "year"
  base_salary_currency: string
  bonus_types: BonusKind[]
  annual_bonus_pct: number | null
  quarterly_bonus_pct: number | null
  bonus: string
  signon: string
  equity: string
  work_format: "remote" | "hybrid" | "office" | "currency" | "unknown"
  office_days_per_week: string
  location: string
  location_country: string
  vacation_days: string
  contract_type: "employment" | "gph" | "ip" | "self_employed"
  deadline: string
  notes: string
}

// Формат работы вакансии часто уже понятен из скоринга (валютная удалёнка/обычная удалёнка/
// гибрид/офис) — не заставлять переспрашивать очевидное в черновике.
function inferWorkFormat(job: Job): DraftState["work_format"] {
  const currencyRemote = (job.score as { currency_remote?: boolean } | undefined)?.currency_remote
  if (currencyRemote) return "currency"
  const raw = (effectiveWorkFormat(job) ?? "").toLowerCase().replace(/ё/g, "е")
  if (/удален|remote|дистанц/.test(raw)) return "remote"
  if (/гибрид|hybrid/.test(raw)) return "hybrid"
  if (/офис|на месте|office|on-?site|разъезд/.test(raw)) return "office"
  return "unknown"
}

function emptyDraft(job: Job): DraftState {
  return {
    base_salary: "",
    base_salary_tax_basis: "gross",
    base_salary_period: "month",
    base_salary_currency: "RUB",
    bonus_types: [],
    annual_bonus_pct: null,
    quarterly_bonus_pct: null,
    bonus: "",
    signon: "",
    equity: "",
    work_format: inferWorkFormat(job),
    office_days_per_week: "",
    location: "",
    location_country: "",
    // Дефолт только на фронте (не в БД) — иначе сломается merge-семантика парсинга письма,
    // см. план шага 20.
    vacation_days: "28",
    contract_type: "employment",
    deadline: "",
    notes: "",
  }
}

function Field({
  label,
  hint,
  helpId,
  children,
}: {
  label: string
  hint?: string
  helpId?: HelpTextId
  children: ReactNode
}) {
  return (
    <div className="space-y-0.5">
      <div className="flex items-center gap-1">
        <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
          {label}
          {hint && (
            <span className="ml-1 normal-case tracking-normal text-slate-400">· {hint}</span>
          )}
        </p>
        {helpId && <HelpTip id={helpId} />}
      </div>
      {children}
    </div>
  )
}

function groupThousands(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, " ")
}

// Живая разбивка суммы по 3 знака прямо во время ввода — окладом обычно вводят 6-7-значные
// суммы, без разбивки трудно сходу прочитать, сколько нулей набрал. Значение наружу отдаётся
// как строка чистых цифр (без пробелов), пробелы — только для отображения.
function SalaryInput({ value, onChange }: { value: string; onChange: (digits: string) => void }) {
  const ref = useRef<HTMLInputElement>(null)

  function handleChange(e: ChangeEvent<HTMLInputElement>) {
    const el = e.target
    const caret = el.selectionStart ?? el.value.length
    const digitsBeforeCaret = el.value.slice(0, caret).replace(/\D/g, "").length
    const digits = el.value.replace(/\D/g, "")
    onChange(digits)
    // Пересчёт каретки после реформатирования — иначе курсор улетает в конец на каждый ввод.
    requestAnimationFrame(() => {
      if (!ref.current) return
      const formatted = groupThousands(digits)
      let seen = 0
      let pos = formatted.length
      for (let i = 0; i < formatted.length; i++) {
        if (formatted[i] !== " ") seen++
        if (seen === digitsBeforeCaret) {
          pos = i + 1
          break
        }
      }
      if (digitsBeforeCaret === 0) pos = 0
      ref.current.setSelectionRange(pos, pos)
    })
  }

  return (
    <input
      ref={ref}
      inputMode="numeric"
      value={groupThousands(value)}
      onChange={handleChange}
      placeholder="0"
      className="h-11 w-full rounded-md border border-slate-300 bg-white px-3 text-lg font-semibold tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
    />
  )
}

function GroupHeading({ icon: Icon, title }: { icon: typeof Wallet; title: string }) {
  return (
    <div className="flex items-center gap-2 pt-1 first:pt-0">
      <Icon className="size-3.5 shrink-0 text-slate-400" strokeWidth={2} />
      <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">{title}</h4>
    </div>
  )
}

// Карточка добавления оффера под конкретную вакансию — первая карточка рельса (OffersRail),
// единая форма без переключателя «Из письма / Вручную»: структурные поля правятся напрямую,
// «Подробности от HR» — просто текст, который при сабмите дозаполняет пустые поля через
// существующий merge-эндпоинт парсинга (overwrite не трогает уже указанное вручную).
export function OfferDraftCard({ job, onDone }: { job: Job; onDone?: () => void }) {
  const [draft, setDraft] = useState<DraftState>(() => emptyDraft(job))
  const prevVacancyId = useRef(job.vacancy_id)
  const resumeCityAppliedRef = useRef(false)

  const create = useCreateOffer()
  const patch = usePatchOffer()
  const parse = useParseOffer()
  const resumeData = useResumeData()

  // Смена выбранной вакансии в верхнем рельсе — черновик предыдущей вакансии не должен утечь
  // в новую. setState в эффекте неизбежен: реагируем на внешний проп job, не на своё состояние.
  useEffect(() => {
    if (prevVacancyId.current === job.vacancy_id) return
    prevVacancyId.current = job.vacancy_id
    resumeCityAppliedRef.current = false
    setDraft(emptyDraft(job))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.vacancy_id])

  // Локация по умолчанию — город из резюме, один раз, только пока черновик локации не тронут.
  useEffect(() => {
    if (resumeCityAppliedRef.current) return
    const city = resumeData.data?.personal?.city?.trim()
    if (!city) return
    resumeCityAppliedRef.current = true
    // eslint-disable-next-line react-hooks/set-state-in-effect -- одноразовый префилл из резюме
    setDraft((d) => (d.location ? d : { ...d, location: city }))
  }, [resumeData.data])

  function set<K extends keyof DraftState>(key: K, value: DraftState[K]) {
    setDraft((d) => ({ ...d, [key]: value }))
  }

  function commitText<K extends keyof DraftState>(key: K) {
    return (next: string | number | string[] | null) => {
      if (Array.isArray(next)) return
      set(key, (next == null ? "" : String(next)) as DraftState[K])
    }
  }

  async function handleSubmit() {
    if (!job.vacancy_id) return
    try {
      await create.mutateAsync({
        vacancy_id: job.vacancy_id,
        company: job.company ?? "",
        position: job.title ?? "",
      })
      const patchBody: OfferUpdateRequest = {}
      if (draft.base_salary.trim()) patchBody.base_salary = Number(draft.base_salary)
      patchBody.base_salary_period = draft.base_salary_period
      patchBody.base_salary_currency = draft.base_salary_currency
      patchBody.base_salary_tax_basis = draft.base_salary_tax_basis
      patchBody.bonus_types = draft.bonus_types
      if (draft.bonus_types.includes("annual") && draft.annual_bonus_pct != null) {
        patchBody.annual_bonus_pct = draft.annual_bonus_pct
      }
      if (draft.bonus_types.includes("quarterly") && draft.quarterly_bonus_pct != null) {
        patchBody.quarterly_bonus_pct = draft.quarterly_bonus_pct
      }
      if (draft.bonus_types.includes("kpi") && draft.bonus.trim()) {
        patchBody.bonus = draft.bonus.trim()
      }
      if (draft.bonus_types.includes("welcome") && draft.signon.trim()) {
        patchBody.signon = Number(draft.signon)
      }
      if (draft.bonus_types.includes("equity") && draft.equity.trim()) {
        patchBody.equity = draft.equity.trim()
      }
      patchBody.work_format = draft.work_format
      if (draft.work_format === "hybrid" && draft.office_days_per_week.trim())
        patchBody.office_days_per_week = Number(draft.office_days_per_week)
      if (draft.location.trim()) patchBody.location = draft.location.trim()
      if (draft.work_format === "currency" && draft.location_country.trim())
        patchBody.location_country = draft.location_country.trim()
      if (draft.vacation_days.trim()) patchBody.vacation_days = Number(draft.vacation_days)
      patchBody.contract_type = draft.contract_type
      if (draft.deadline) patchBody.deadline = draft.deadline
      if (draft.notes.trim()) patchBody.notes = draft.notes.trim()
      await patch.mutateAsync({ vacancyId: job.vacancy_id, patch: patchBody })

      if (draft.notes.trim().length >= 20) {
        await parse.mutateAsync({
          vacancy_id: job.vacancy_id,
          text: draft.notes.trim(),
          overwrite: false,
        })
      }
      onDone?.()
    } catch {
      // toast уже в hooks (useCreateOffer/usePatchOffer/useParseOffer)
    }
  }

  const submitting = create.isPending || patch.isPending || parse.isPending

  return (
    <div className="flex w-72 shrink-0 flex-col overflow-hidden rounded-xl border border-dashed border-slate-300 bg-white shadow-sm">
      <div className="space-y-0.5 border-b p-3">
        <h3 className="text-sm font-semibold text-slate-900">Новый оффер</h3>
        <p className="truncate text-xs text-slate-500">
          {job.company || "Компания"}
          {job.title ? ` · ${job.title}` : ""}
        </p>
      </div>

      <div className="flex-1 space-y-3 p-3">
        <div className="space-y-2">
          <GroupHeading icon={Wallet} title="Деньги" />
          <Field label="Оклад" helpId="offers.base-salary">
            <div className="space-y-1.5">
              <SalaryInput
                value={draft.base_salary}
                onChange={(digits) => set("base_salary", digits)}
              />
              <div className="flex items-center gap-1">
                <ChipToggleGroup
                  options={TAX_BASIS_OPTS}
                  value={[draft.base_salary_tax_basis]}
                  onChange={(n) =>
                    set(
                      "base_salary_tax_basis",
                      (n[0] as DraftState["base_salary_tax_basis"]) ?? "gross",
                    )
                  }
                  multiple={false}
                  allowEmpty={false}
                />
                <HelpTip id="offers.tax-basis" />
              </div>
            </div>
          </Field>
          <Field label="Вид договора">
            <OfferRow
              row={rowByKey("contract_type")!}
              value={draft.contract_type}
              onCommit={(next) =>
                set("contract_type", String(next ?? "employment") as DraftState["contract_type"])
              }
            />
          </Field>
          <Field label="Период">
            <ChipToggleGroup
              options={PERIOD_OPTS}
              value={[draft.base_salary_period]}
              onChange={(n) =>
                set("base_salary_period", (n[0] as DraftState["base_salary_period"]) ?? "month")
              }
              multiple={false}
              allowEmpty={false}
            />
          </Field>
          <Field label="Валюта">
            <ChipToggleGroup
              options={CURRENCY_OPTS}
              value={[draft.base_salary_currency]}
              onChange={(n) => set("base_salary_currency", n[0] ?? "RUB")}
              multiple={false}
              allowEmpty={false}
            />
            <p className="mt-1 text-xs text-slate-400">остальные суммы — в валюте оклада</p>
          </Field>
          <Field label="Тип премии" helpId="offers.bonus">
            <OfferRow
              row={rowByKey("bonus_types")!}
              value={draft.bonus_types}
              onCommit={(next) => {
                const types = (Array.isArray(next) ? next : []) as BonusKind[]
                setDraft((d) => ({
                  ...d,
                  bonus_types: types,
                  annual_bonus_pct:
                    types.includes("annual") && d.annual_bonus_pct == null
                      ? BONUS_PCT_DEFAULT
                      : d.annual_bonus_pct,
                  quarterly_bonus_pct:
                    types.includes("quarterly") && d.quarterly_bonus_pct == null
                      ? BONUS_PCT_DEFAULT
                      : d.quarterly_bonus_pct,
                }))
              }}
            />
          </Field>
          {draft.bonus_types.includes("annual") && (
            <Field label="Годовая, % от года">
              <OfferRow
                row={rowByKey("annual_bonus_pct")!}
                value={draft.annual_bonus_pct}
                onCommit={(next) =>
                  set("annual_bonus_pct", typeof next === "number" ? next : BONUS_PCT_DEFAULT)
                }
              />
            </Field>
          )}
          {draft.bonus_types.includes("quarterly") && (
            <Field label="Квартальная, % от квартала">
              <OfferRow
                row={rowByKey("quarterly_bonus_pct")!}
                value={draft.quarterly_bonus_pct}
                onCommit={(next) =>
                  set("quarterly_bonus_pct", typeof next === "number" ? next : BONUS_PCT_DEFAULT)
                }
              />
            </Field>
          )}
          {draft.bonus_types.includes("kpi") && (
            <Field label="Премия, детали">
              <OfferRow
                row={rowByKey("bonus")!}
                value={draft.bonus || null}
                onCommit={commitText("bonus")}
              />
            </Field>
          )}
          {draft.bonus_types.includes("welcome") && (
            <Field label="Welcome-бонус">
              <div className="flex items-center gap-1">
                <div className="flex-1">
                  <OfferRow
                    row={rowByKey("signon")!}
                    value={draft.signon || null}
                    onCommit={commitText("signon")}
                  />
                </div>
                <HelpTip text="Разовая сумма за принятие оффера" />
              </div>
            </Field>
          )}
          {draft.bonus_types.includes("equity") && (
            <Field label="Акции">
              <OfferRow
                row={rowByKey("equity")!}
                value={draft.equity || null}
                onCommit={commitText("equity")}
              />
            </Field>
          )}
        </div>

        <div className="space-y-2">
          <GroupHeading icon={MapPin} title="Условия работы" />
          <Field label="Формат">
            <OfferRow
              row={rowByKey("work_format")!}
              value={draft.work_format}
              formatOptions={FORMAT_OPTS}
              onCommit={(next) =>
                set("work_format", String(next ?? "unknown") as DraftState["work_format"])
              }
            />
          </Field>
          {draft.work_format === "hybrid" && (
            <Field label="Дней в офисе" hint="из 5 рабочих">
              <OfferRow
                row={rowByKey("office_days_per_week")!}
                value={draft.office_days_per_week || null}
                onCommit={commitText("office_days_per_week")}
              />
            </Field>
          )}
          <Field label="Локация" hint="город">
            <OfferRow
              row={rowByKey("location")!}
              value={draft.location || null}
              onCommit={commitText("location")}
            />
          </Field>
          {draft.work_format === "currency" && (
            <Field label="Страна">
              <OfferRow
                row={rowByKey("location_country")!}
                value={draft.location_country || null}
                onCommit={commitText("location_country")}
              />
            </Field>
          )}
          <Field label="Отпуск, дней">
            <OfferRow
              row={rowByKey("vacation_days")!}
              value={draft.vacation_days || null}
              onCommit={commitText("vacation_days")}
            />
          </Field>
        </div>

        <div className="space-y-2">
          <GroupHeading icon={CalendarClock} title="Срок ответа" />
          <Field label="Дедлайн ответа" helpId="offers.deadline">
            <OfferRow
              row={rowByKey("deadline")!}
              value={draft.deadline || null}
              onCommit={(next) => set("deadline", next ? String(next) : "")}
            />
          </Field>
        </div>

        <div className="space-y-2">
          <GroupHeading icon={FileText} title="Подробности от HR" />
          <Textarea
            placeholder="вставьте текст письма или впишите устные договорённости — модель дозаполнит пустые поля"
            value={draft.notes}
            onChange={(e) => set("notes", e.target.value)}
            className="min-h-16 w-full rounded-lg border border-slate-300 bg-white p-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
          />
        </div>
      </div>

      <div className="border-t p-3">
        <Button size="sm" className="w-full" onClick={handleSubmit} disabled={submitting}>
          {submitting ? (
            <Loader2 className="size-4 animate-spin" strokeWidth={2} />
          ) : (
            <Check className="size-4" strokeWidth={2} />
          )}
          Добавить оффер
        </Button>
      </div>
    </div>
  )
}
