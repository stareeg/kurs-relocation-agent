# preparation

Скрининг (пакет самопрезентации), технички, разбор, контекст вакансии.

Владеет: screening-pack, prep-сессии/пакеты/темы, debrief,
этапы собеседований, screening_questions, competency, vacancy Q&A.
Лента prep-чата — в `assistant`.
Публикует: `ScreeningPackReady`, `InterviewDebriefed`.
Подписан: `ApplicationStageChanged` — переход в «Техничку» гасит кружок HR-скрининга
(раньше это делал сам `opportunities.add_stage` прямым вызовом).

Форма: `models` / `service` / `repo` / `llm` / `events`.
Подпакеты: `screening/`, `interview/`. Repo-этапы — `interview_stages`
(не путать с пакетом `interview/`).
