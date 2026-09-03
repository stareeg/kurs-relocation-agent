-- 0068: market_coverage может быть NULL («нет данных», шаг 25 universal profile).
-- Раньше cold start писали 0 — пользователь читал это как «плохое резюме».

alter table resume_score_history alter column market_coverage drop not null;
