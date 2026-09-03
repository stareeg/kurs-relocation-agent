-- 0150_drop_career_goals_relocation — уборка мёртвого кода раздела «Карьера» (Э9.7).
-- Цели/skill-таргеты (A-23) и граф релокации (A-25) не имели ни одного живого UI-потребителя
-- ни разу за всё время (GoalsSection.tsx не импортировалась, RelocationSection.tsx удаляется
-- этим же заходом) — данных без потребителя не жалко. Владелец подтвердил явное «да» на
-- удаление релокации отдельно (см. plans/dual_employment_and_contracting_2026.md §8 вопрос 5).
-- Приватность портфолио (`privacy`) — тоже без потребителя: шаринга портфолио нет.
-- career_timeline.goal_id (FK → career_goals) должен уйти раньше самой career_goals.
alter table career_timeline drop column if exists goal_id;
alter table career_timeline drop constraint if exists career_timeline_kind_check;
alter table career_timeline add constraint career_timeline_kind_check check (kind in (
    'application', 'stage', 'offer', 'job_start', 'promotion',
    'project', 'certificate', 'relocation', 'other',
    'search_mode', 'search_track'   -- 'search_mode'/'search_track' добавлены 0132;
                                     -- 'goal'/'skill' из 0072 не переносим — писателя не стало
));

drop index if exists career_portfolio_items_privacy_idx;
alter table career_portfolio_items drop column if exists privacy;

drop table if exists career_skill_targets;
drop table if exists career_goals;
drop table if exists career_relocation_steps;
