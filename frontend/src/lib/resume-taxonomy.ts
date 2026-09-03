import type { ChipOption } from "@/components/ui/chip-toggle-group"

// Справочники для «Желаемая должность и зарплата» (RD-4). Разные таксономии — не путать
// с COMPANY_TYPE_LABEL (`features/jobs/funnel.ts`), которая описывает тип КОМПАНИИ-РАБОТОДАТЕЛЯ
// по вакансии (LLM-классификация скорера). Здесь — предпочтения КАНДИДАТА.

export type MultiSelectOption = { value: string; label: string }

export const EMPLOYMENT_OPTIONS = ["Полная занятость", "Подработка", "Стажировка"]

export const SCHEDULE_OPTIONS: ChipOption[] = [
  { value: "Офис", label: "Офис" },
  { value: "Гибрид", label: "Гибрид" },
  { value: "Удалённо", label: "Удалённо" },
]

export const RESUME_GRADES: ChipOption[] = [
  { value: "Junior", label: "Junior" },
  { value: "Middle", label: "Middle" },
  { value: "Senior", label: "Senior" },
  { value: "Lead", label: "Lead" },
  { value: "C-level", label: "C-level" },
]

// Типы компаний, которые кандидат готов рассматривать — мульти-чипы.
// Ярлыки синхронны с `_CANDIDATE_COMPANY_TYPE_MAP` (core/domains/opportunities/score_breakdown.py):
// каждый чип обязан мапиться на слаг `company_type`, иначе он не влияет на балл. «Валютка» именно
// поэтому и убрана — она описывала валюту оклада, а не тип компании; валютный рынок теперь
// выражается осью «Рынок поиска» ниже.
export const CANDIDATE_COMPANY_TYPES: ChipOption[] = [
  { value: "Биг тех", label: "Биг тех" },
  { value: "Продукт", label: "Продукт" },
  { value: "Стартап", label: "Стартап" },
  { value: "Аутсорс", label: "Аутсорс" },
  { value: "Аутстафф", label: "Аутстафф" },
]

// Рынок поиска (SearchCriteria.market_scope). Пустое значение в резюме = «Только РФ»:
// нормализация — `market_scope_label` в core/domains/profile/model.py.
export const MARKET_SCOPE_DEFAULT = "Только РФ"

export const MARKET_SCOPE_OPTIONS: ChipOption[] = [
  { value: "Только РФ", label: "Только РФ" },
  { value: "Международный", label: "Международный" },
  { value: "Любой", label: "Любой" },
]

// Профиль поиска (universal profile UX): закрытые оси + справочник рынка.
// value — канон резюме (скоринг/парсер PDF). label — подпись чипа в панели.
export const ROLE_KIND_OPTIONS: ChipOption[] = [
  { value: "Делаю руками", label: "Исполнитель" },
  { value: "Управляю людьми", label: "Управленец" },
  { value: "И то, и другое", label: "Обе" },
]

export function roleKindLabel(value: string): string {
  return ROLE_KIND_OPTIONS.find((o) => o.value === value)?.label ?? value
}

export const SALARY_BASIS_OPTIONS: ChipOption[] = [
  { value: "На руки", label: "На руки" },
  { value: "До вычета", label: "До вычета" },
]

// Совпадает с core.resume.search_profile_suggest.MARKET_SEGMENT_OPTIONS.
// Мульти-выбор: несколько отраслей можно выбрать одновременно.
// «Любые» — значение по умолчанию = без фильтра (пустая строка в market_segment).
// При выборе других отраслей «Любые» снимается автоматически (фронт).
export const ANY_MARKET_SEGMENT = "Любые"

export const MARKET_SEGMENT_SUGGESTIONS: string[] = [
  ANY_MARKET_SEGMENT,
  "IT",
  "Банки / Финтех",
  "Ритейл / E-commerce",
  "Телеком",
  "Медиа / Продакшн",
  "Маркетинг / Реклама",
  "Образование / EdTech",
  "Производство / Промышленность",
  "Госсектор / GovTech",
  "Здравоохранение / MedTech",
  "Нефтегаз / Энергетика",
]

// Отрасль места работы: тот же справочник, но «Любые» (фильтр поиска) заменяется на «Другое»
// (LLM не смогла классифицировать компанию). Совпадает с EXPERIENCE_INDUSTRY_OPTIONS на бэке.
export const EXPERIENCE_INDUSTRY_OTHER = "Другое"

export const EXPERIENCE_INDUSTRY_OPTIONS: string[] = [
  ...MARKET_SEGMENT_SUGGESTIONS.filter((s) => s !== ANY_MARKET_SEGMENT),
  EXPERIENCE_INDUSTRY_OTHER,
]

/** Значение select отрасли опыта: пусто → placeholder, неизвестное / «Любые» → «Другое». */
export function experienceIndustrySelectValue(raw: string): string | undefined {
  const value = raw.trim()
  if (!value) return undefined
  const hit = EXPERIENCE_INDUSTRY_OPTIONS.find((opt) => opt.toLowerCase() === value.toLowerCase())
  return hit ?? EXPERIENCE_INDUSTRY_OTHER
}

// Ред флаги — закрытый список стоп-условий РФ IT (UX6). Пустой список - норма (не ошибка):
// в промпт скоринга секция просто не попадает (`SearchCriteria.dealbreakers`).
// value = label: в резюме и {{RESUME}} хранится человекочитаемая строка.
export const RED_FLAG_OPTIONS: ChipOption[] = [
  { value: "Офис без удалёнки", label: "Офис без удалёнки" },
  { value: "Только ГПХ / ИП", label: "Только ГПХ / ИП" },
  { value: "Релокация обязательна", label: "Релокация обязательна" },
  { value: "Гостайна / допуск", label: "Гостайна / допуск" },
  { value: "Частые командировки", label: "Частые командировки" },
  { value: "Чистый аутстафф", label: "Чистый аутстафф" },
  { value: "Серая зарплата", label: "Серая зарплата" },
  { value: "Тестовое больше дня", label: "Тестовое больше дня" },
  { value: "Онколл / дежурства 24/7", label: "Онколл / дежурства 24/7" },
  { value: "Учёт часов / микроменеджмент", label: "Учёт часов / микроменеджмент" },
  { value: "Стек закрыт до оффера", label: "Стек закрыт до оффера" },
]

const RED_FLAG_VALUES = new Set(RED_FLAG_OPTIONS.map((o) => o.value))

// Старые длинные формулировки → новый канон. Пустая строка = выкинуть (не редфлаг вакансии /
// противоречит правилам: «вилка не указана» - норма hh, не стоп).
const LEGACY_RED_FLAG_MAP: Record<string, string> = {
  "Обязательный офис 5/5 без гибрида": "Офис без удалёнки",
  "Обязательный ежедневный офис 5/5": "Офис без удалёнки",
  "обязательный офис 5/5": "Офис без удалёнки",
  "Серая зарплата «в конверте»": "Серая зарплата",
  "Испытательный срок без оформления по ТК": "Только ГПХ / ИП",
  "оформление только ГПХ": "Только ГПХ / ИП",
  "Переработки / ненормированный график как норма": "Онколл / дежурства 24/7",
  "Объёмное тестовое задание (более 1 дня)": "Тестовое больше дня",
  "Задержки зарплаты у сотрудников": "Серая зарплата",
  "Микроменеджмент / жёсткий контроль рабочего времени": "Учёт часов / микроменеджмент",
  "Закрытый проект — нельзя узнать стек/задачи до оффера": "Стек закрыт до оффера",
  // Дефис здесь не опечатка: ключ повторяет строку, уже лежащую в чужих сохранённых резюме.
  // Правило «тире, а не дефис» (Этап 3 ui_slop_cleanup_2026_08_25) к ключам миграции не
  // применяется — иначе старое значение перестанет мигрировать.
  "Закрытый проект - нельзя узнать стек/задачи до оффера": "Стек закрыт до оффера",
  "Без ЗП-вилки в вакансии": "",
  "Нет обратной связи по офферу дольше 2 недель": "",
  "Высокая текучка / частая смена руководства": "",
}

/** Привести сохранённые dealbreakers к актуальному списку. Пустой вход → []. */
export function normalizeDealbreakers(raw: string[] | null | undefined): string[] {
  if (!raw?.length) return []
  const out: string[] = []
  const seen = new Set<string>()
  for (const item of raw) {
    const trimmed = (item || "").trim()
    if (!trimmed) continue
    const mapped =
      LEGACY_RED_FLAG_MAP[trimmed] !== undefined
        ? LEGACY_RED_FLAG_MAP[trimmed]
        : RED_FLAG_VALUES.has(trimmed)
          ? trimmed
          : null
    if (!mapped || seen.has(mapped)) continue
    seen.add(mapped)
    out.push(mapped)
  }
  return out
}

// Специальности в «Профиле»: 18 IT и около-IT ролей, по 9 в колонке селекта.
// value = label — так же уходит в резюме-markdown и промпты. Старые getmatch-слаги
// мапятся в `normalizeCategories` (зеркало `core/domains/profile/categories.py`).
export const RESUME_CATEGORIES: MultiSelectOption[] = [
  { value: "Backend", label: "Backend" },
  { value: "Frontend", label: "Frontend" },
  { value: "Fullstack", label: "Fullstack" },
  { value: "Mobile", label: "Mobile" },
  { value: "QA / тестирование", label: "QA / тестирование" },
  { value: "Аналитика / Data", label: "Аналитика / Data" },
  { value: "ML / DS / AI", label: "ML / DS / AI" },
  { value: "DevOps / инфраструктура", label: "DevOps / инфраструктура" },
  { value: "КиберБез", label: "КиберБез" },
  { value: "Техподдержка", label: "Техподдержка" },
  { value: "Product Management", label: "Product Management" },
  { value: "Project Management", label: "Project Management" },
  { value: "Системный анализ", label: "Системный анализ" },
  { value: "Дизайн / UX", label: "Дизайн / UX" },
  { value: "Embedded / IoT", label: "Embedded / IoT" },
  { value: "Архитектура", label: "Архитектура" },
  { value: "Маркетинг", label: "Маркетинг" },
  { value: "Руководство", label: "Руководство" },
]

export const RESUME_CATEGORIES_MAX = 3

const RESUME_CATEGORY_VALUES = new Set(RESUME_CATEGORIES.map((c) => c.value))

const LEGACY_CATEGORY_MAP: Record<string, string> = {
  QA: "QA / тестирование",
  "Product/Project/Architecture": "Product Management",
  "Project Manager": "Project Management",
  "Design & UX": "Дизайн / UX",
  Analytics: "Аналитика / Data",
  Аналитика: "Аналитика / Data",
  "Information Security": "КиберБез",
  "Информационная безопасность": "КиберБез",
  "Infrastructure & DevOps": "DevOps / инфраструктура",
  Support: "Техподдержка",
  "Data & ML": "ML / DS / AI",
  "Data / ML": "ML / DS / AI",
  "HR & Recruitment": "",
  "HR / рекрутинг": "",
  "Top Management": "Руководство",
  "1C": "",
  "1С": "",
  Sales: "",
  Продажи: "",
  Marketing: "Маркетинг",
  "Technical Engineering": "Системный анализ",
  "UX & Tech Writers": "Дизайн / UX",
}

/** Привести сохранённые специальности к актуальному списку. Пустой вход → []. */
export function normalizeCategories(raw: string[] | null | undefined): string[] {
  if (!raw?.length) return []
  const out: string[] = []
  const seen = new Set<string>()
  for (const item of raw) {
    const trimmed = (item || "").trim()
    if (!trimmed) continue
    const mapped = LEGACY_CATEGORY_MAP[trimmed] ?? trimmed
    if (!mapped || !RESUME_CATEGORY_VALUES.has(mapped) || seen.has(mapped)) continue
    seen.add(mapped)
    out.push(mapped)
    if (out.length >= RESUME_CATEGORIES_MAX) break
  }
  return out
}
