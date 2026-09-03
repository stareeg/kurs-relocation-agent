# offers

Парсинг офферов, сравнение, торг с HR, оценка бонуса; HH-таксономия откликов.

Владеет: персист офферов (`store`), LLM parse/compare/negotiate/bonus,
модели оффера и HH negotiations (`models` / `hh_negotiations`).
Публикует: `OfferReceived` — при первом появлении оффера, не на каждой правке. Точка входа UI: вкладка «Офферы».

Форма: `models` / `service` / `ports` (OffersRepository) / `repo` (PgOffersRepository) /
`llm` / `events`. HH sync откликов остаётся сценарием `pipeline.negotiations`
(читает модели отсюда).
