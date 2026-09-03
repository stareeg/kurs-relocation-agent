-- 0035_getmatch_sync_freshness — S3: метка времени последнего успешного синка
-- getmatch /applications → Postgres. Расширение синкает только при ручном открытии страницы,
-- без heartbeat-фона. Если владелец не заходил на /applications неделю — статусы устаревают,
-- а KPI воронки getmatch (GM-8) врёт. Эта таблица даёт pulse уведомлять владельца.
--
-- Single-row (id=1 фикс): один «последний синк», upsert по id. Не история — перезапись.

create table if not exists getmatch_sync_freshness (
    id           int          not null default 1 primary key,
    last_sync_at timestamptz  not null default now(),
    check (id = 1)
);
insert into getmatch_sync_freshness (id, last_sync_at) values (1, now())
    on conflict (id) do nothing;
