-- 0085_tg_hr_pending — pending HR-кнопок переживает рестарт бота (TB-7.3 / B7).
-- Токен из callback_data → payload (HrMessageAnalysis + контекст). TTL сутки;
-- просроченное подчищает tg_cleanup / expire_due при save/get/pop.

create table tg_hr_pending (
    token       text        primary key,
    chat_id     bigint      not null,
    payload     jsonb       not null,
    created_at  timestamptz not null default now(),
    expires_at  timestamptz not null
);

create index tg_hr_pending_expires_idx on tg_hr_pending (expires_at);
create index tg_hr_pending_chat_idx on tg_hr_pending (chat_id);
