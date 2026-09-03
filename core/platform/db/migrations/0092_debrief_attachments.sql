-- 0092_debrief_attachments — связки вложений-картинок с разборами собеса (Э4-4,
-- plans/chat_image_attachments_2026_08_03.md §3/§8). Разбор — не лента сообщений (одна строка
-- `interview_debriefs` на весь разбор, не поток реплик), поэтому отдельная таблица со своим FK,
-- а не ещё одна запись в реестре `_SURFACE_TABLES` (0091) под колонку `message_id`.
-- `on delete restrict` на attachment_id — тот же принцип, что в 0091: блоб не пропадает из-под
-- живой связки, чистит его только GC (`core/domains/assistant/attachments/repo.py::gc_candidates`),
-- который проверяет отсутствие ссылок и в этой таблице тоже.

create table debrief_attachments (
    id            bigint      generated always as identity primary key,
    debrief_id    bigint      not null references interview_debriefs (id) on delete cascade,
    attachment_id bigint      not null references attachments (id) on delete restrict,
    position      integer     not null default 0,
    created_at    timestamptz not null default now(),
    unique (debrief_id, attachment_id)
);
create index debrief_attachments_debrief_idx on debrief_attachments (debrief_id, position);
