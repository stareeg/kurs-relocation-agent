import { describe, expect, it } from "vitest"
import type { Job } from "@/api/jobs"
import type { components } from "@/api/schema"
import {
  BOARD_COLUMNS,
  bucketByStage,
  cardDay,
  chatButtonLabel,
  competitionInsightLabel,
  competitionInsightOf,
  countActiveJobs,
  effectiveWorkFormat,
  fmtChanged,
  formatConflictOf,
  headerSalaryLabel,
  isSalaryStillPending,
  isActiveJob,
  levelLabel,
  type RemoteFeasibilityView,
  resolveJobSalary,
  resolveStage,
  scoreBreakdownRows,
  scoreCalibrationDelta,
  salaryProvenanceLabel,
  scoreTone,
  sectionJumpFor,
  needsVacancyText,
  workFormatChip,
} from "./funnel"

function job(p: Partial<Job>): Job {
  return { vacancy_text: "x".repeat(50), ...p } as Job
}

// B-03: job.score теперь типизирован полным ScoreResult (не голым dict) — тестам нужен полный
// валидный объект под override; только зарплата варьируется по кейсам ниже.
type ScoreResult = components["schemas"]["ScoreResult"]
type SalaryInfo = components["schemas"]["SalaryInfo"]

function fakeSalary(overrides: Partial<SalaryInfo> = {}): SalaryInfo {
  return {
    meets_min: false,
    value_or_range: "",
    estimated_range: "",
    note: "",
    confidence: "low",
    source: "none",
    estimate_pending: false,
    ...overrides,
  }
}

function fakeScore(overrides: Partial<ScoreResult> = {}): ScoreResult {
  return {
    overall_score: 0,
    recommendation: "maybe",
    remote_abroad_compat: { level: "ok", reasoning: "" },
    grade_match: { level: "match", reasoning: "", off_profile_kind: "" },
    salary: fakeSalary(),
    role_content_match: { score: 0, matched_niche: [], reasoning: "" },
    burnout_risk: { level: "medium", reasoning: "" },
    company_type: "unknown",
    pros: [],
    cons: [],
    red_flags: [],
    one_line_verdict: "",
    work_city: "",
    currency_remote: false,
    weights_version: "",
    track: "primary",
    ...overrides,
  }
}

describe("resolveStage", () => {
  it("каноничный статус остаётся собой", () => {
    expect(resolveStage("Отклик")).toBe("Отклик")
    expect(resolveStage("Оффер")).toBe("Оффер")
    expect(resolveStage("Финал")).toBe("Финал")
  })
  it("пусто/неизвестно → Просмотр, Архив → Отказ", () => {
    expect(resolveStage(null)).toBe("Просмотр")
    expect(resolveStage("")).toBe("Просмотр")
    expect(resolveStage("мусор")).toBe("Просмотр")
    expect(resolveStage("Архив")).toBe("Отказ")
    expect(resolveStage("Просмотрено")).toBe("Просмотр") // легаси-вариант
  })
})

describe("bucketByStage", () => {
  it("раскладывает по колонкам (воронка + Пропущено); skipped уходит в Пропущено", () => {
    const cols = bucketByStage([
      job({ id: 1, status: "Отклик" }),
      job({ id: 2, status: null }),
      job({ id: 3, status: "Архив" }),
      job({ id: 4, status: "Отклик" }),
      job({ id: 5, status: "Отклик", skipped: true }), // skipped → «Пропущено» независимо от статуса
      job({ id: 6, status: "Финал" }),
    ])
    expect(cols.map((c) => c.stage)).toEqual([...BOARD_COLUMNS])
    const byStage = Object.fromEntries(cols.map((c) => [c.stage, c.jobs.map((j) => j.id)]))
    expect(byStage["Отклик"]).toEqual([1, 4]) // вак.5 ушла в «Пропущено», не сюда
    expect(byStage["Просмотр"]).toEqual([2])
    expect(byStage["Отказ"]).toEqual([3]) // Архив свёрнут в Отказ
    expect(byStage["Скрининг"]).toEqual([])
    expect(byStage["Финал"]).toEqual([6])
    expect(byStage["Пропущено"]).toEqual([5])
  })
})

describe("isActiveJob / countActiveJobs", () => {
  it("engaged-статусы активны, пропущенные и Просмотр без HR — нет", () => {
    expect(isActiveJob(job({ status: "Отклик" }))).toBe(true)
    expect(isActiveJob(job({ status: "Скрининг" }))).toBe(true)
    expect(isActiveJob(job({ status: "Финал" }))).toBe(true)
    expect(isActiveJob(job({ status: "Оффер" }))).toBe(true)
    expect(isActiveJob(job({ status: "Просмотр" }))).toBe(false)
    expect(isActiveJob(job({ status: "Отказ" }))).toBe(false)
    expect(isActiveJob(job({ status: "Отклик", skipped: true }))).toBe(false)
  })

  it("Просмотр + HR-диалог ≈ активный процесс", () => {
    expect(isActiveJob(job({ status: "Просмотр", has_hr_dialog: true }))).toBe(true)
  })

  it("countActiveJobs считает только активные", () => {
    expect(
      countActiveJobs([
        job({ id: 1, status: "Отклик" }),
        job({ id: 2, status: "Просмотр" }),
        job({ id: 3, status: "Техничка" }),
        job({ id: 4, status: "Просмотр", has_hr_dialog: true }),
      ]),
    ).toBe(3)
  })
})

describe("cardDay / fmtChanged", () => {
  it("Финал — продвинутый этап, дата = последнее изменение (updated_at), не отклик", () => {
    const j = job({ status: "Финал", updated_at: "2026-07-10T00:00:00Z", applied_at: "2026-06-01" })
    expect(cardDay(j)).toEqual({ text: "10.07", label: "Финал" })
    expect(fmtChanged(j)).toBe("10.07")
  })
})

describe("scoreTone", () => {
  it("тон по силе фита", () => {
    expect(scoreTone(90)).toContain("emerald")
    expect(scoreTone(70)).toContain("amber")
    expect(scoreTone(50)).toContain("slate-500")
    expect(scoreTone(null)).toContain("slate-400")
  })
})

describe("needsVacancyText", () => {
  it("true для пустого stub без скора", () => {
    expect(needsVacancyText(job({ vacancy_text: "", overall_score: null }))).toBe(true)
    expect(needsVacancyText(job({ vacancy_text: "коротко", overall_score: undefined }))).toBe(true)
  })
  it("false если есть скор или длинный текст", () => {
    expect(needsVacancyText(job({ vacancy_text: "", overall_score: 70 }))).toBe(false)
    expect(needsVacancyText(job({ vacancy_text: "x".repeat(50), overall_score: null }))).toBe(false)
  })
})

describe("workFormatChip", () => {
  it("удалёнка → strong, гибрид → warn, офис → bad", () => {
    expect(workFormatChip("удалённо")).toMatchObject({ label: "Удалёнка", tone: "strong" })
    expect(workFormatChip("гибрид")).toMatchObject({ label: "Гибрид", tone: "warn" })
    expect(workFormatChip("на месте работодателя")).toMatchObject({ label: "Офис", tone: "bad" })
  })
  it("комбо отдаёт самый удобный для кандидата вариант (удалёнка > гибрид > офис)", () => {
    expect(workFormatChip("на месте работодателя, удалённо, гибрид")?.label).toBe("Удалёнка")
    expect(workFormatChip("на месте работодателя, гибрид")?.label).toBe("Гибрид")
  })
  it("пусто/неизвестно → нет чипа", () => {
    expect(workFormatChip(null)).toBeNull()
    expect(workFormatChip("")).toBeNull()
    expect(workFormatChip("полный день")).toBeNull()
  })
  it("currencyRemote=true перекрывает обычный формат меткой «Валютка» (info)", () => {
    expect(workFormatChip("удалённо", true)).toMatchObject({ label: "Валютка", tone: "info" })
    expect(workFormatChip(null, true)).toMatchObject({ label: "Валютка", tone: "info" })
  })
})

describe("formatConflictOf (V-05)", () => {
  const remoteChip = { label: "Удалёнка", tone: "strong" as const }
  const relocationChip = { label: "Релокация", tone: "good" as const }
  const hybridChip = { label: "Гибрид", tone: "warn" as const }
  const officeChip = { label: "Офис", tone: "bad" as const }

  it("удалёнка + вердикт unlikely — конфликт, тон по вердикту, короткая подпись", () => {
    const remote: RemoteFeasibilityView = {
      score: 35,
      verdict: "unlikely",
      signals: [{ text: "требуется присутствие в офисе 3 дня в неделю", polarity: "contra" }],
    }
    expect(formatConflictOf(remoteChip, remote)).toEqual({
      tone: "bad",
      caption: "Скорее Офис",
    })
  })

  it("релокация (good) + вердикт conditional — тоже конфликт", () => {
    const remote: RemoteFeasibilityView = { score: 50, verdict: "conditional", signals: [] }
    expect(formatConflictOf(relocationChip, remote)?.tone).toBe("warn")
  })

  it("без контра-сигналов — подпись падает на короткий ярлык вердикта", () => {
    const remote: RemoteFeasibilityView = { score: 40, verdict: "conditional", signals: [] }
    expect(formatConflictOf(remoteChip, remote)).toEqual({
      tone: "warn",
      caption: "Скорее Гибрид",
    })
  })

  it("вердикт real — конфликта нет", () => {
    const remote: RemoteFeasibilityView = { score: 90, verdict: "real", signals: [] }
    expect(formatConflictOf(remoteChip, remote)).toBeNull()
  })

  it("чип уже «Офис» (bad) — конфликт не нужен, проблема и так видна по цвету чипа", () => {
    const remote: RemoteFeasibilityView = { score: 20, verdict: "unlikely", signals: [] }
    expect(formatConflictOf(officeChip, remote)).toBeNull()
  })

  it("«Гибрид» (warn) — не считается позитивным чипом, конфликта не рисуем", () => {
    const remote: RemoteFeasibilityView = { score: 20, verdict: "unlikely", signals: [] }
    expect(formatConflictOf(hybridChip, remote)).toBeNull()
  })

  it("нет чипа формата или нет remote_feasibility — конфликта нет", () => {
    expect(formatConflictOf(null, { score: 20, verdict: "unlikely", signals: [] })).toBeNull()
    expect(formatConflictOf(remoteChip, undefined)).toBeNull()
  })
})

describe("competitionInsightOf / competitionInsightLabel (Этап 6 §6.2)", () => {
  it("level=favorable — читается и рендерится в good-бейдж", () => {
    const j = job({
      competition: { level: "favorable", responses_per_day: 0.3, age_days: 10, reasoning: "r" },
    })
    const insight = competitionInsightOf(j)
    expect(insight?.level).toBe("favorable")
    expect(competitionInsightLabel(insight!)).toEqual({ text: "хороший шанс", tone: "good" })
  })

  it("level=crowded — bad-бейдж", () => {
    const j = job({ competition: { level: "crowded", reasoning: "r" } })
    expect(competitionInsightLabel(competitionInsightOf(j)!)).toEqual({
      text: "высокая конкуренция",
      tone: "bad",
    })
  })

  it("level=unknown — доступен через competitionInsightOf, но label не рисуется", () => {
    const j = job({ competition: { level: "unknown", reasoning: "нет данных" } })
    const insight = competitionInsightOf(j)
    expect(insight?.level).toBe("unknown")
    expect(competitionInsightLabel(insight!)).toBeNull()
  })

  it("job.competition отсутствует (запись до Этапа 6) — undefined, не падение", () => {
    const j = job({})
    expect(competitionInsightOf(j)).toBeUndefined()
  })

  it("битое/неизвестное значение level — undefined (B-02: сырой ключ не рендерим)", () => {
    const j = job({ competition: { level: "future_level_from_newer_backend" } } as unknown as Partial<Job>)
    expect(competitionInsightOf(j)).toBeUndefined()
  })
})

describe("resolveJobSalary / headerSalaryLabel — оффер (OF-8)", () => {
  const target = 500_000

  it("активный оффер даёт точную сумму без пометки «(оценка)»", () => {
    const j = job({
      offer_status: "thinking",
      offer_base_salary: 500_000,
      offer_base_salary_currency: "RUB",
      offer_base_salary_period: "month",
      salary_text: "от 100 000 до 200 000 руб.",
    })
    expect(resolveJobSalary(j, target)).toMatchObject({
      text: "500 000 ₽/мес",
      isEstimate: false,
      meetsMin: true,
    })
    expect(headerSalaryLabel(j, target)).toMatchObject({
      text: "500к",
      isEstimate: false,
      meetsMin: true,
    })
  })

  it("оффер с премией — resolveJobSalary разворачивает хвост, headerSalaryLabel даёт компактную сумму", () => {
    const j = job({
      offer_status: "thinking",
      offer_base_salary: 500_000,
      offer_base_salary_currency: "RUB",
      offer_base_salary_period: "month",
      offer_bonus_monthly_equiv: 100_000,
    })
    expect(resolveJobSalary(j, target).text).toBe("500 000 ₽/мес + 100 000 ₽/мес премия")
    expect(headerSalaryLabel(j, target).text).toBe("500к + 100к")
  })

  it("оффер ниже целевого минимума → meetsMin=false", () => {
    const j = job({ offer_status: "accepted", offer_base_salary: 300_000 })
    expect(resolveJobSalary(j, target)).toMatchObject({ meetsMin: false })
  })

  it("без salary_min в резюме — meetsMin=null (не красим)", () => {
    const j = job({ offer_status: "accepted", offer_base_salary: 300_000 })
    expect(resolveJobSalary(j)).toMatchObject({ meetsMin: null })
    expect(resolveJobSalary(j, null)).toMatchObject({ meetsMin: null })
  })

  it("черновик/отклонённый/истёкший оффер не подменяет вилку (не active/accepted)", () => {
    const j = job({
      offer_status: "draft",
      offer_base_salary: 999_000,
      salary_text: "от 100 000 до 200 000 руб.",
    })
    expect(resolveJobSalary(j).text).not.toContain("999")
  })

  it("без оффера — старое поведение (HH-текст/LLM-оценка) не сломано", () => {
    const j = job({ salary_text: "от 100 000 до 200 000 руб." })
    expect(resolveJobSalary(j)).toMatchObject({
      text: "от 100 000 до 200 000 руб.",
      isEstimate: false,
      source: "explicit",
      estimateSuffix: null,
    })
  })

  it("source=none без данных → прочерк, не выдуманное число", () => {
    const j = job({
      score: fakeScore({
        salary: fakeSalary({ meets_min: false, value_or_range: "", source: "none" }),
      }),
    })
    expect(resolveJobSalary(j)).toMatchObject({ text: "—", source: "none", isEstimate: false })
  })

  it("llm-оценка — приглушённый суффикс; low → грубая оценка", () => {
    const j = job({
      score: fakeScore({
        salary: fakeSalary({
          meets_min: true,
          value_or_range: "",
          estimated_range: "от 300 000 до 400 000",
          source: "llm",
          confidence: "high",
        }),
      }),
    })
    expect(resolveJobSalary(j)).toMatchObject({
      isEstimate: true,
      source: "llm",
      estimateSuffix: "оценка",
    })
    const low = job({
      score: fakeScore({
        salary: fakeSalary({
          meets_min: false,
          estimated_range: "от 130 000 до 170 000",
          source: "llm",
          confidence: "low",
        }),
      }),
    })
    expect(resolveJobSalary(low).estimateSuffix).toBe("грубая оценка")
  })

  it("explicit из score — без суффикса оценки", () => {
    const j = job({
      score: fakeScore({
        salary: fakeSalary({
          meets_min: true,
          value_or_range: "500 000–600 000",
          source: "explicit",
          confidence: "high",
          note: "Вилка со слов HR.",
        }),
      }),
    })
    const r = resolveJobSalary(j)
    expect(r).toMatchObject({ isEstimate: false, source: "explicit", estimateSuffix: null })
    expect(salaryProvenanceLabel(j)).toBe("со слов HR")
  })
})

describe("isSalaryStillPending", () => {
  it("не крутит спиннер, если вилка уже есть, а estimate_pending залип", () => {
    expect(isSalaryStillPending(true, "от 300к до 400к")).toBe(false)
    expect(isSalaryStillPending(true, "оценка…")).toBe(true)
    expect(isSalaryStillPending(false, "оценка…")).toBe(false)
  })
})

describe("effectiveWorkFormat (OF-8.3)", () => {
  it("активный оффер с другим форматом перекрывает исходный формат вакансии", () => {
    const j = job({ work_format: "гибрид", offer_status: "thinking", offer_work_format: "remote" })
    expect(effectiveWorkFormat(j)).toBe("remote")
  })

  it("без активного оффера — исходный формат вакансии как раньше", () => {
    const j = job({ work_format: "гибрид" })
    expect(effectiveWorkFormat(j)).toBe("гибрид")
  })
})

describe("levelLabel (B-02)", () => {
  const MAP = { match: "Совпадает", above: "Выше цели" }

  it("известный ключ — подписанный ярлык, raw в title не уходит", () => {
    expect(levelLabel(MAP, "match")).toEqual({ label: "Совпадает" })
  })

  it("неизвестный ключ (новая версия модели) — «—», сырое значение только в rawTitle", () => {
    expect(levelLabel(MAP, "нечто")).toEqual({ label: "—", rawTitle: "нечто" })
  })

  it("пусто/undefined/null — «—» без rawTitle", () => {
    expect(levelLabel(MAP, undefined)).toEqual({ label: "—" })
    expect(levelLabel(MAP, null)).toEqual({ label: "—" })
    expect(levelLabel(MAP, "")).toEqual({ label: "—" })
  })
})

describe("scoreBreakdownRows (V-04)", () => {
  it("легаси-запись (score_breakdown пуст) — null, а не полоса, которая не сойдётся", () => {
    const s = fakeScore()
    expect(scoreBreakdownRows(s, undefined)).toBeNull()
  })

  it("старая пятиключевая форма без company — тоже null", () => {
    const s = fakeScore({
      score_breakdown: {
        salary: 20,
        work_format: 20,
        grade_match: 15,
        role_content: 15,
        management: 15,
      },
    })
    expect(scoreBreakdownRows(s, undefined)).toBeNull()
  })

  it("полная форма — шесть строк в фиксированном порядке 2×3 (не по убыванию вклада)", () => {
    // Решение 9: порядок больше не зависит от value (иначе разбор перемешивался от вакансии к
    // вакансии) — фиксированная сетка: левая колонка Зарплата/Формат/Грейд, правая
    // Роль(management)/Домен/Компания (SCORE_BREAKDOWN_DISPLAY_ORDER, shared/criteria.ts).
    const s = fakeScore({
      overall_score: 96,
      score_breakdown: {
        salary: 25,
        work_format: 21,
        grade_match: 16,
        role_content: 16,
        management: 11,
        company: 7,
      },
    })
    const rows = scoreBreakdownRows(s, undefined)
    expect(rows).not.toBeNull()
    expect(rows!.map((r) => r.key)).toEqual([
      "salary",
      "management",
      "work_format",
      "role_content",
      "grade_match",
      "company",
    ])
    expect(rows!.map((r) => r.value)).toEqual([25, 11, 21, 16, 16, 7])
  })

  it("рубрика второго трека — пять осей в фиксированном порядке", () => {
    const s = fakeScore({
      score_breakdown: {
        flexibility: 20,
        role_content: 18,
        compat: 14,
        rate: 11,
        company: 8,
      },
    })
    const rows = scoreBreakdownRows(s, undefined)
    expect(rows).not.toBeNull()
    expect(rows!.map((r) => r.key)).toEqual([
      "flexibility",
      "compat",
      "role_content",
      "rate",
      "company",
    ])
    expect(rows!.find((r) => r.key === "flexibility")!.max).toBe(25)
    expect(rows!.find((r) => r.key === "rate")!.max).toBe(20)
  })

  it("пользовательские веса (B-04) переопределяют дефолтный знаменатель", () => {
    const s = fakeScore({
      score_breakdown: {
        salary: 10,
        work_format: 10,
        grade_match: 10,
        role_content: 10,
        management: 10,
        company: 10,
      },
    })
    const rows = scoreBreakdownRows(s, {
      salary: 30,
      work_format: 10,
      grade_match: 20,
      role_content: 15,
      management: 15,
      company: 10,
    })
    expect(rows!.find((r) => r.key === "salary")!.max).toBe(30)
    expect(rows!.find((r) => r.key === "work_format")!.max).toBe(10)
  })

  it("тон по критерию — good/mid/bad, а не всегда neutral", () => {
    const s = fakeScore({
      salary: {
        meets_min: true,
        value_or_range: "300 000",
        estimated_range: "",
        note: "",
        confidence: "high",
        source: "explicit",
        estimate_pending: false,
      },
      grade_match: { level: "far_below", reasoning: "", off_profile_kind: "" },
      score_breakdown: {
        salary: 20,
        work_format: 10,
        grade_match: 5,
        role_content: 15,
        management: 15,
        company: 15,
      },
    })
    const rows = scoreBreakdownRows(s, undefined)
    expect(rows!.find((r) => r.key === "salary")!.tone).toBe("good")
    expect(rows!.find((r) => r.key === "grade_match")!.tone).toBe("bad")
  })
})

describe("scoreCalibrationDelta (V-04)", () => {
  it("сумма разбора совпадает с итогом — остаток 0", () => {
    const s = fakeScore({
      overall_score: 96,
      score_breakdown: {
        salary: 25,
        work_format: 21,
        grade_match: 16,
        role_content: 16,
        management: 11,
        company: 7,
      },
    })
    const rows = scoreBreakdownRows(s, undefined)!
    expect(scoreCalibrationDelta(s, rows)).toBe(0)
  })

  it("калибровка/гейт сдвигают итог — остаток объясняет разницу", () => {
    const s = fakeScore({
      overall_score: 55,
      score_breakdown: {
        salary: 20,
        work_format: 20,
        grade_match: 15,
        role_content: 15,
        management: 15,
        company: 15,
      },
    })
    const rows = scoreBreakdownRows(s, undefined)!
    expect(scoreCalibrationDelta(s, rows)).toBe(55 - 100)
  })
})

describe("sectionJumpFor", () => {
  it("даёт переход в раздел для активного этапа воронки", () => {
    expect(sectionJumpFor(job({ status: "Техничка", skipped: false }))?.path).toBe("/tech")
  })

  it("гасит переход для «Пропущено», даже если status указывает на активный этап", () => {
    expect(sectionJumpFor(job({ status: "Техничка", skipped: true }))).toBeUndefined()
  })

  it("гасит переход для «Отказ» (в SECTION_JUMP нет записи)", () => {
    expect(sectionJumpFor(job({ status: "Отказ", skipped: false }))).toBeUndefined()
  })

  it("нет перехода для ранних этапов без записи в SECTION_JUMP", () => {
    expect(sectionJumpFor(job({ status: "Просмотр", skipped: false }))).toBeUndefined()
  })
})

// corner_case_1: «Продолжить чат» обещало живой процесс, даже когда вакансия давно в Отказе/
// Пропущено и её диалог автоматически ушёл в архив Чатов — регрессия на честную метку кнопки.
describe("chatButtonLabel", () => {
  it("нет диалога — предлагает начать", () => {
    expect(chatButtonLabel(job({ status: "Просмотр", skipped: false, has_hr_dialog: false }))).toBe(
      "Начать чат",
    )
  })

  it("активная воронка — предлагает продолжить", () => {
    expect(chatButtonLabel(job({ status: "Скрининг", skipped: false, has_hr_dialog: true }))).toBe(
      "Продолжить чат",
    )
  })

  it("Отказ — честно помечает архивный чат", () => {
    expect(chatButtonLabel(job({ status: "Отказ", skipped: false, has_hr_dialog: true }))).toBe(
      "Архивный чат",
    )
  })

  it("Пропущено — тот же архивный лейбл, даже если status ещё «активный»", () => {
    expect(chatButtonLabel(job({ status: "Скрининг", skipped: true, has_hr_dialog: true }))).toBe(
      "Архивный чат",
    )
  })
})
