# market

Рынок: сетка, пульс, бенчмарки зарплат, ситуация, метрики поиска, калибровка вилок.

Владеет: market/pulse/grid/supply/relevance/search_metrics/situation/competency,
salary_calibration, персист snapshot/calib/situation_store.
Funnel-аналитика (конверсия этапов / по источнику) — в `pipeline.analytics`
и `pipeline.source_funnel`.
Не публикует событий шины (только слушает: `VacancyScored`, `ApplicationStageChanged`,
`OfferReceived`, `HrMessageReceived`, `ResumeUpdated`). Точка входа UI: вкладка «Рынок».

L-25: `snapshot_refresh.py` — фон пересчитывает grid/pulse/search каждые 5 минут (self-reschedule
через `platform.tasks`) и раз в сутки — LLM-сводку «Ситуация»; кэш снимков — `analytics_cache.py`
(`market_analytics_snapshot`). Роутеры читают снапшот вместо пересчёта на каждый заход.

Форма: `models` / `service` / `repo` / `llm` / `events`.
