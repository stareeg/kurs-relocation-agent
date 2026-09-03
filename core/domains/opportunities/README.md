# opportunities

Вакансии: скоринг, доска, скипы, discovery (hh), источники (hh / getmatch / habr / telegram).

Владеет: `ScoreResult`, `jobs`/`skipped`/`score_revision`, skip-reasons канон,
нормализация компаний, batch discovery, версия рубрики скоринга (`weights_version.py` +
`jobs.score_weights_version`) и её перескор без LLM (`rescore.py`). `axis_alignment.py` —
read-only отчёт «скор vs решения владельца» (разделяющая сила осей + advisory-подсказка по
весам, без автоправки) и `rescore.simulate_weight_override` (превью топ-20 под неё, тоже без
записи). `preferences_digest.py` наполняет `score_vacancy(..., preferences=...)` выученными
предпочтениями (частые причины пропуска + ниши, куда владелец реально откликается) — без LLM.
Публикует: `VacancyScored` (после персиста скоринга),
`ApplicationStageChanged` (`add_stage` — единственная точка записи стадии воронки).
Подписан на `ResumeUpdated` (`profile`) — резюме сохранено → веса/role_kind рубрики могли
измениться, `rescore.schedule_rescore_all` ставит перескор базы без LLM в очередь (Этап 5).

Форма: `models` / `service` / `ports` (JobsRepository) / `repo` (PgJobsRepository) /
`llm` / `events`. Персист скоринга (`persist_scored`) пишет job+stage в одном UoW.
Адаптеры площадок — `sources/` (`VacancySource`: hh / getmatch / habr). hh: парсинг HTML
без сети (тесты/фикстуры); живой fetch карточки — только `GET api.hh.ru/vacancies/{id}`
(ссылка в бота), SERP с VM выключен. Контракт динамических CSS-селекторов hh —
`parser_config.py` + `sources/hh_selectors.json`
(allowlist ключей, без регексов с сервера; расширение валидирует тем же контрактом).
Горячий оверрайд — таблица `parser_selector_configs` (без `account_id`), отдача
`GET /api/opportunities/parser-config/hh` (`get_hh_selectors`: PG TTL 60 с, битый
оверрайд → репозиторный дефолт). `parser_health.py` — скользящее окно методов
разбора вакансии hh: доля `structural` > 10% за час → WARNING `hh_selectors_dead`
(без крона, на каждом `POST /score`). Точка входа: `POST /score`, доска; сценарий
`score_from_source` — fetch источника → скоринг.
