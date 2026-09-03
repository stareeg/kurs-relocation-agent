-- 0051_drop_retro_snapshots — UX5-20: «Сводка ситуации» и «Ретро воронки» слиты в один бэкенд-вызов
-- (core/analytics/situation.py::gather_retro_facts + SituationNarrative.actions). Отдельная
-- append-only лента ретро (0043) больше не пишется и не читается — история прошлых срезов не
-- переносится (владелец подтвердил: держать только последний объединённый бриф).
-- grid_fingerprint (0032) обслуживал баннер устаревания «Сводки ситуации», который тоже убран.
drop table if exists retro_snapshots;
alter table situation_narratives drop column if exists grid_fingerprint;
