import { describe, expect, it } from "vitest"
import {
  DAYS,
  FAILURES,
  atHandle,
  compactNumber,
  formatDay,
  formatLogTs,
  formatMoment,
  plural,
  pluralize,
  formatBytes,
  formatSize,
  sharedKeyNotes,
  relativeSeen,
  remainingLabel,
  remainingTone,
  roleLabel,
  shownOfLabel,
  silenceLabel,
  sparklineDayLabel,
  statusLabel,
  tokens,
  updatedAtLabel,
  usd,
  msLabel,
  pctLabel,
} from "./admin-format"

describe("usd / tokens", () => {
  it("держит два знака и не падает на пустом значении", () => {
    expect(usd(1.5)).toBe("$1.50")
    expect(usd(undefined)).toBe("$0.00")
    expect(usd(null)).toBe("$0.00")
  })

  it("разделяет разряды по-русски", () => {
    expect(tokens(1234567)).toBe("1 234 567".replace(/ /g, " "))
    expect(tokens(undefined)).toBe("0")
  })
})

describe("склонение", () => {
  it("выбирает форму по последней цифре, кроме подростковых", () => {
    expect(plural(1, FAILURES)).toBe("сбой")
    expect(plural(2, FAILURES)).toBe("сбоя")
    expect(plural(4, FAILURES)).toBe("сбоя")
    expect(plural(5, FAILURES)).toBe("сбоев")
    expect(plural(0, FAILURES)).toBe("сбоев")
  })

  it("11–14 — всегда множественное, как бы ни кончалось число", () => {
    expect(plural(11, FAILURES)).toBe("сбоев")
    expect(plural(12, FAILURES)).toBe("сбоев")
    expect(plural(14, FAILURES)).toBe("сбоев")
    expect(plural(111, FAILURES)).toBe("сбоев")
  })

  it("на живых числах из прода: было «23 сбоев» и «1 сбоев»", () => {
    expect(pluralize(23, FAILURES)).toBe("23 сбоя")
    expect(pluralize(1, FAILURES)).toBe("1 сбой")
    expect(pluralize(21, DAYS)).toBe("21 день")
  })
})

describe("форматы дат раздела", () => {
  const at = new Date(2026, 7, 12, 17, 11, 6)

  it("день — «12.08», момент — «12.08 17:11», запись журнала — с секундами", () => {
    expect(formatDay(at.toISOString())).toBe("12.08")
    expect(formatMoment(at.toISOString())).toBe("12.08 17:11")
    expect(formatLogTs(at.toISOString())).toBe("12.08 17:11:06")
  })

  it("пустое и мусор — тире, а не «Invalid Date»", () => {
    expect(formatMoment(null)).toBe("—")
    expect(formatLogTs("мусор")).toBe("—")
  })

  it("старше двух суток relativeSeen отдаёт числовую дату", () => {
    const now = new Date(2026, 7, 15, 12, 0, 0).getTime()
    expect(relativeSeen(at.toISOString(), now)).toBe("12.08 17:11")
  })
})

describe("compactNumber", () => {
  it("сжимает крупные числа под узкую ячейку", () => {
    expect(compactNumber(940)).toBe("940")
    expect(compactNumber(1200)).toBe("1.2 тыс.")
    expect(compactNumber(19192)).toBe("19 тыс.")
    expect(compactNumber(1_166_918)).toBe("1.2 М")
    expect(compactNumber(9_475_335)).toBe("9.5 М")
    expect(compactNumber(35_372_000)).toBe("35 М")
  })

  it("пустое — ноль, а не «NaN»", () => {
    expect(compactNumber(null)).toBe("0")
    expect(compactNumber(undefined)).toBe("0")
  })
})

describe("msLabel / pctLabel", () => {
  it("пустые значения — тире, не ноль", () => {
    expect(msLabel(null)).toBe("—")
    // Ноль — не измерение: LLM-вызов не бывает мгновенным, так писались попадания в кэш.
    expect(msLabel(0)).toBe("—")
    expect(msLabel(340)).toBe("340 мс")
    expect(msLabel(1200)).toBe("1.2 с")
    expect(pctLabel(null)).toBe("—")
    expect(pctLabel(0.34)).toBe("34%")
  })
})

describe("atHandle", () => {
  it("не удваивает собаку и честно говорит про пустой ник", () => {
    expect(atHandle("kate")).toBe("@kate")
    expect(atHandle("@kate")).toBe("@kate")
    expect(atHandle(null)).toBe("без @")
    expect(atHandle("")).toBe("без @")
  })
})

describe("relativeSeen", () => {
  const now = new Date("2026-08-25T12:00:00Z").getTime()
  const ago = (minutes: number) => new Date(now - minutes * 60_000).toISOString()

  it("свежие минуты округляет в «сейчас»", () => {
    expect(relativeSeen(ago(0), now)).toBe("сейчас")
    expect(relativeSeen(ago(4), now)).toBe("сейчас")
  })

  it("минуты и часы", () => {
    expect(relativeSeen(ago(30), now)).toBe("30 мин")
    expect(relativeSeen(ago(180), now)).toBe("3 ч")
  })

  it("отсутствие визита — не «только что»", () => {
    expect(relativeSeen(null, now)).toBe("не заходил")
    expect(relativeSeen("мусор", now)).toBe("не заходил")
  })
})

describe("silenceLabel", () => {
  it("склоняет дни", () => {
    expect(silenceLabel(1)).toBe("молчит 1 день")
    expect(silenceLabel(3)).toBe("молчит 3 дня")
    expect(silenceLabel(8)).toBe("молчит 8 дней")
    expect(silenceLabel(11)).toBe("молчит 11 дней")
    expect(silenceLabel(21)).toBe("молчит 21 день")
    expect(silenceLabel(112)).toBe("молчит 112 дней")
  })

  it("«не заходил ни разу» — это не ноль дней", () => {
    expect(silenceLabel(null)).toBe("не заходил ни разу")
    expect(silenceLabel(undefined)).toBe("не заходил ни разу")
    expect(silenceLabel(0)).toBe("молчит 0 дней")
  })
})

describe("shownOfLabel", () => {
  it("молчит, когда список и счётчик сошлись", () => {
    expect(shownOfLabel(5, 5)).toBe("")
    expect(shownOfLabel(5, 3)).toBe("")
  })

  it("называет полное число, когда список урезан", () => {
    expect(shownOfLabel(20, 137)).toBe("показано 20 из 137")
  })
})

describe("подписи роли и статуса", () => {
  it("оператор и участник — две роли, а не роль и сущность", () => {
    expect(roleLabel("owner")).toBe("оператор")
    expect(roleLabel("member")).toBe("участник")
    expect(statusLabel("active")).toBe("активен")
    expect(statusLabel("disabled")).toBe("отключён")
  })
})

describe("updatedAtLabel", () => {
  it("показывает время последнего обновления витрины", () => {
    const at = new Date(2026, 7, 25, 14, 32).getTime()
    expect(updatedAtLabel(at)).toBe("обновлено в 14:32")
  })

  it("молчит, пока витрину не грузили", () => {
    expect(updatedAtLabel(0)).toBe("")
    expect(updatedAtLabel(undefined)).toBe("")
  })
})

describe("sparklineDayLabel", () => {
  it("последняя точка — сегодня, первая — N дней назад", () => {
    expect(sparklineDayLabel(13, 14)).toBe("сегодня")
    expect(sparklineDayLabel(12, 14)).toBe("вчера")
    expect(sparklineDayLabel(0, 14)).toBe("13 дн. назад")
  })
})

describe("formatBytes", () => {
  it("пустое значение — прочерк, не ноль байт", () => {
    expect(formatBytes(null)).toBe("—")
    expect(formatBytes(undefined)).toBe("—")
  })

  it("килобайты с одним знаком", () => {
    expect(formatBytes(800)).toBe("800 Б")
    expect(formatBytes(2048)).toBe("2.0 КБ")
  })
})

describe("formatSize", () => {
  it("поднимается до мегабайт и гигабайт", () => {
    expect(formatSize(512)).toBe("512 Б")
    expect(formatSize(128 * 1024 * 1024)).toBe("128.0 МБ")
    expect(formatSize(2 * 1024 * 1024 * 1024)).toBe("2.0 ГБ")
  })
})

describe("remainingLabel / remainingTone", () => {
  it("пока не обновляли — тире, не ноль долларов", () => {
    expect(remainingLabel(undefined)).toBe("—")
    expect(remainingTone(undefined)).toBeUndefined()
  })

  it("живой ключ с остатком", () => {
    const probe = {
      alive: true,
      network_error: false,
      limit_remaining: 12.5,
      is_free_tier: false,
    }
    expect(remainingLabel(probe)).toBe("$12.50")
    expect(remainingTone(probe)).toBe("good")
  })

  it("сеть и мёртвый ключ читаются без числа", () => {
    expect(
      remainingLabel({ alive: false, network_error: true, limit_remaining: null, is_free_tier: false }),
    ).toBe("нет ответа")
    expect(
      remainingTone({ alive: false, network_error: true, limit_remaining: null, is_free_tier: false }),
    ).toBe("warn")
    expect(
      remainingLabel({ alive: false, network_error: false, limit_remaining: null, is_free_tier: false }),
    ).toBe("мёртв")
    expect(
      remainingTone({ alive: false, network_error: false, limit_remaining: null, is_free_tier: false }),
    ).toBe("bad")
  })

  it("безлимитный и free-tier", () => {
    expect(
      remainingLabel({ alive: true, network_error: false, limit_remaining: null, is_free_tier: false }),
    ).toBe("без лимита")
    expect(
      remainingLabel({ alive: true, network_error: false, limit_remaining: null, is_free_tier: true }),
    ).toBe("free-tier")
  })
})

describe("sharedKeyNotes", () => {
  const holder = (id: number, handle: string | null, hint: string | null) => ({
    account_id: id,
    telegram_username: handle,
    key_hint: hint,
  })

  it("называет соседа по ключу с обеих сторон", () => {
    const notes = sharedKeyNotes([
      holder(1, "lil_hate", "…15fb"),
      holder(2, "stareeg", "…15fb"),
      holder(3, "kate", "…77aa"),
    ])
    expect(notes[1]).toBe("тот же ключ, что у @stareeg")
    expect(notes[2]).toBe("тот же ключ, что у @lil_hate")
    expect(notes[3]).toBeUndefined()
  })

  it("перечисляет всех соседей, если ключ один на троих", () => {
    const notes = sharedKeyNotes([
      holder(1, "a", "…15fb"),
      holder(2, "b", "…15fb"),
      holder(3, "c", "…15fb"),
    ])
    expect(notes[1]).toBe("тот же ключ, что у @b, @c")
  })

  it("пустой хвост — не совпадение: без ключа людей может быть много", () => {
    expect(sharedKeyNotes([holder(1, "a", ""), holder(2, "b", null), holder(3, "c", "  ")])).toEqual(
      {},
    )
  })
})
