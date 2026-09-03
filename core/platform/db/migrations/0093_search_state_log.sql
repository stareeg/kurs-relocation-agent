-- 0093_search_state_log — ST-01: первоклассная сущность «режим поиска» (SearchMode).
-- Журнал переходов: текущий режим = последняя запись (история сохраняется — кто переключил
-- и почему). Режимы paused/planning появятся в CY-01 вместе с сущностью цикла — пока
-- три значения, CHECK расширится той же миграцией циклов.

create table search_state_log (
    id          bigint      generated always as identity primary key,
    mode        text        not null
        check (mode in ('active', 'passive', 'offer_endgame')),
    prev_mode   text
        check (prev_mode is null or prev_mode in ('active', 'passive', 'offer_endgame')),
    actor       text        not null default 'owner'
        check (actor in ('owner', 'suggestion')),
    reason      text        not null default '',
    created_at  timestamptz not null default now()
);

create index search_state_log_created_idx on search_state_log (created_at desc, id desc);

-- Переход режима — событие карьерной ленты (пишется подпиской на SearchModeChanged,
-- career/timeline.py::timeline_from_search_mode_changed).
alter table career_timeline drop constraint if exists career_timeline_kind_check;
alter table career_timeline add constraint career_timeline_kind_check
    check (kind in (
        'application', 'stage', 'offer', 'job_start', 'promotion',
        'project', 'certificate', 'relocation', 'other',
        'goal', 'skill', 'search_mode'
    ));
