# profile

Резюме и профиль кандидата (`ResumeData`, `CandidateProfile`; `SearchProfile` — алиас).

Владеет: JSON-канон резюме, гэпы/скор, ATS-fit, усиление, PDF-парс, статистика hh/getmatch/habr/tg.
`derive_candidate_profile` — чистая функция от резюме; карьерные поля (позиция, выход,
горизонт, рост, локация/виза) — overlay из `app_settings.candidate_profile`
(`load_candidate_profile_enriched`). Оверлей из `career.profile_hints` удалён вместе с
Целями/skill-таргетами (Э9.7, `plans/dual_employment_and_contracting_2026.md`) — источника
данных для него всё равно не было ни разу.
Привязка Telegram-владельца: `telegram_link.py` — токен/owner/identity в
`app_settings` (общий код для API и бота).
Пуши бота: `telegram_prefs.py` — `digest` / `warmup_summary` / `card_style` /
`batch_cleanup` в `app_settings.telegram_prefs`.
Источник правды резюме — таблица `resumes` в Postgres (по `account_id`), см.
`structured_store.py`; файл `resume/resume_data.json` — только bootstrap/dev-путь.
География кандидата — одно поле `personal.city` (город проживания); страна и часовой
пояс выводятся из него (`kernel.timezones.city_geo`), `work_countries` в форме нет.
Публикует: `ResumeUpdated` — после сохранения резюме в `resumes`. Точка входа UI: вкладка «Резюме».

Форма: `models` / `service` / `repo` / `llm` / `events`. Фичевые модули рядом
(`ats_fit`, `strengthen`, `gap`, `telegram_link`, `telegram_prefs`, …) — до сборки в единый service в треке A.
