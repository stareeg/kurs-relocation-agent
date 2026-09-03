-- 0072_career_goal_timeline_link — A-23: связь целей/skill-таргетов с лентой.
-- goal_id на career_timeline; виды goal/skill для вех трека (без UI).

alter table career_timeline
    add column if not exists goal_id bigint
        references career_goals (id) on delete set null;

create index if not exists career_timeline_goal_idx
    on career_timeline (goal_id);

-- Расширяем CHECK kind: goal / skill (имена авто-констрейнта PG стабильны для column check).
alter table career_timeline drop constraint if exists career_timeline_kind_check;
alter table career_timeline add constraint career_timeline_kind_check
    check (kind in (
        'application', 'stage', 'offer', 'job_start', 'promotion',
        'project', 'certificate', 'relocation', 'other',
        'goal', 'skill'
    ));
