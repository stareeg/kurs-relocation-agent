# pipeline

Воронка откликов, HR-переписка, аутрич, сопроводительные, синк переговоров,
аналитика конверсии (`analytics`, `source_funnel`).

Владеет: стадии/enrichment-действия, HR-треды/журнал/registry, cover letter,
funnel-/source-funnel-аналитика. Заметки-диалоги — в `assistant`.
Публикует: `HrMessageReceived`. Стадию воронки публикует `opportunities`
(`add_stage` — единственная точка записи, pipeline ходит в неё же).

Форма: `models` / `service` / `repo` / `llm` / `events`. Парсеры переписки —
здесь (не в `bot_app`); бот только хендлеры + prep-reminders (aiogram).
