/**
 * Поля бумаг кабинки — id совпадают с `FRAUD_MARKERS` в `core/domains/multiplayer/deck.py`.
 * Улики кликабельны; правда (fraud_pair) остаётся на сервере.
 */

export type PaperField = {
  id: string
  /** Короткая подпись строки на бланке */
  label: string
  /** Текст «как в резюме / акте» */
  resumeText: string
  /** Текст «как в JD / требовании» — для сопоставления глазом */
  jdText: string
}

/** Канон маркеров несостыковки (порядок = deck.FRAUD_MARKERS). */
export const FRAUD_MARKERS: readonly string[] = [
  "dates_mismatch",
  "ip_surname",
  "stack_lie",
  "team_size",
  "calendar_clash",
  "act_fake",
] as const

export const PAPER_FIELDS: readonly PaperField[] = [
  {
    id: "dates_mismatch",
    label: "Сроки",
    resumeText: "2022–2024 тимлид платформы, без разрывов",
    jdText: "Опыт от 3 лет на одном продукте, вёл его сам",
  },
  {
    id: "ip_surname",
    label: "Юрлицо / ФИО",
    resumeText: "Акт ИП на Иванова К. — совпадает с резюме",
    jdText: "Договор только с тем же ФИО, что в анкете",
  },
  {
    id: "stack_lie",
    label: "Стек",
    resumeText: "Vue + немного React, Kafka «видел»",
    jdText: "Нужен рабочий стек из бюллетеня, без «видел»",
  },
  {
    id: "team_size",
    label: "Команда",
    resumeText: "Вёл 40 человек — «почти весь бэкенд»",
    jdText: "Руководил людьми: 5–8 разработчиков, не дирекция из 40",
  },
  {
    id: "calendar_clash",
    label: "Календарь",
    resumeText: "Стендап 10:00 и «второй синк» в 19:00",
    jdText: "Полный день на одном месте; две работы разом — тревожный знак",
  },
  {
    id: "act_fake",
    label: "Акт / ИП",
    resumeText: "Скан акта за квартал — печать размыта, ИНН читается",
    jdText: "Оригинал акта или выписка ЕГРИП до оффера",
  },
] as const

export function paperFieldById(id: string): PaperField | undefined {
  return PAPER_FIELDS.find((f) => f.id === id)
}
