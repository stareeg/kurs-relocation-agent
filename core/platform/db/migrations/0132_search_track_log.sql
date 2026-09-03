-- 0132_search_track_log — журнал включённых треков поиска (основная / вторая работа).
-- Отдельный журнал, а не колонка в search_state_log: интенсивность поиска (active/passive) и
-- набор треков — ортогональные оси, в одной строке половина колонок была бы пустой.

create table search_track_log (
    id          bigint generated always as identity primary key,
    account_id  bigint      not null references accounts (id) on delete cascade,
    tracks      text[]      not null check (array_length(tracks, 1) between 1 and 2),
    prev_tracks text[]      not null default '{}',
    actor       text        not null default 'owner' check (actor in ('owner', 'suggestion')),
    reason      text        not null default '',
    created_at  timestamptz not null default now(),
    constraint search_track_log_values_check
        check (tracks <@ array['primary', 'second_job']::text[]),
    constraint search_track_log_primary_present_check
        check ('primary' = any (tracks))
);

create index search_track_log_account_idx on search_track_log (account_id, created_at desc);

alter table search_track_log enable row level security;
create policy search_track_log_account_isolation on search_track_log
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on search_track_log to app_rls, app_admin;
grant usage, select on sequence search_track_log_id_seq to app_rls, app_admin;

-- Переход трека — событие карьерной ленты (пишется подпиской на SearchTrackChanged).
alter table career_timeline drop constraint if exists career_timeline_kind_check;
alter table career_timeline add constraint career_timeline_kind_check
    check (kind in (
        'application', 'stage', 'offer', 'job_start', 'promotion',
        'project', 'certificate', 'relocation', 'other',
        'goal', 'skill', 'search_mode', 'search_track'
    ));
