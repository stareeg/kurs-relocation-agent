# platform

Инфраструктура Career Copilot: ничего не знает о карьере и вакансиях.

Состав: `llm/` (OpenRouter, LlmFeature, call.run, usage), `db/` (пул + миграции),
`http/` (keep-alive, warmup, retry/budget), `observability/` (логи, витрина `copilot_logs`,
LangSmith), `config/` (слоистый конфиг + `ConfigError`), `cache/` (result cache +
single-flight), `events/` (журнал доменных событий), `images/` (нормализация вложений),
`tasks/` (очередь фоновых задач + daily cron).

Зависит только от stdlib и внешних SDK.
