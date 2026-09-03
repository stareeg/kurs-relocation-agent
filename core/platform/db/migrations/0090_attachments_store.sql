-- 0090_attachments_store — контент-адресуемое хранилище байт картинок (вложения чатов).
-- Одна таблица на всю систему: связки с конкретными лентами (hr_messages, prep_chat_messages,
-- …) заводятся отдельными миграциями (0091+), см. plans/chat_image_attachments_2026_08_03.md §2.
-- sha256 нормализованных байт — контент-адрес: повторная загрузка того же скрина не дублирует
-- строку. Кадрирование не портит оригинал: обрезанная картинка — новая строка с derived_from.

create table attachments (
    id            bigint      generated always as identity primary key,
    sha256        text        not null unique,
    mime          text        not null,
    width         integer     not null,
    height        integer     not null,
    bytes         integer     not null,
    data          bytea       not null,
    thumb         bytea       not null,
    thumb_width   integer     not null,
    thumb_height  integer     not null,
    derived_from  bigint      references attachments (id) on delete set null,
    crop          jsonb,
    analysis_status text      not null default 'pending'
        check (analysis_status in ('pending', 'ready', 'failed', 'skipped')),
    analysis      jsonb,
    analyzed_at   timestamptz,
    created_at    timestamptz not null default now()
);

-- GC осиротевших: загрузил в композер и передумал отправлять (см. Э0-5, ATTACHMENT_GC_AFTER_HOURS).
create index attachments_gc_idx on attachments (created_at) where analysis_status <> 'pending';
