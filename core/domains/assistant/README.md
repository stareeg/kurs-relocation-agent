# assistant

Свободный чат, чат по вакансии, контексты диалогов (заметки, prep-чат).

Владеет: `stream_answer` (SSE), `notes` (шпаргалки + RAG в чат), `prep_chat`
(лента «Технички»), модель `AskMessage`, промпт `prompts/assistant/system.md`.
Точка входа API: `POST /api/chat/stream`. Публикует: `AttachmentAnalyzed`.

Форма: `models` / `service` / `repo` / `llm` / `events`.
