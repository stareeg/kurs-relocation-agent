-- 0145_llm_usage_model_idx — разрез расхода по модели (plans/admin_panel_2026_08_25.md Этап 8.1).
-- Уже есть (day), (day, agent) из 0075 и (account_id, day) из 0109; для group by model
-- этого мало — без (day, model) админский разрез «по моделям» идёт seq-scan по дню.
create index if not exists llm_usage_day_model_idx on llm_usage (day, model);
