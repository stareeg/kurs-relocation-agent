-- 0031_user_settings — персональные настройки владельца (single-user система).
-- Пока один тумблер: auto_score_enabled — автоскоринг вакансии при открытии на hh.ru
-- (расширение дёргает /api/settings перед автозапуском). Синглтон-строка (id=1) —
-- как profile, отдельная таблица чтобы не смешивать с jsonb-профилем и легко расширять.
create table if not exists user_settings (
    id                  integer primary key default 1 check (id = 1),
    auto_score_enabled  boolean not null default false,
    updated_at          timestamptz not null default now()
);

insert into user_settings (id) values (1)
on conflict (id) do nothing;
