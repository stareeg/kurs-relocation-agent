-- 0016_interview_debriefs — персист разборов собеса (UI-5): накопление по вакансии, история.
-- По образцу prep_sessions (0009). vacancy_id = HH id, БЕЗ FK на jobs (разбор может быть для
-- вакансии вне jobs, как enrichment S4 / prep S9). analysis — весь DebriefAnalysis как jsonb
-- (вопросы/слабые/сильные/темы + сигнал/впечатление/summary), денормализованные signal/impression/
-- summary вынесены отдельными колонками для дешёвого списка/сортировки без разбора jsonb.
create table interview_debriefs (
    id              bigint      generated always as identity primary key,
    vacancy_id      text        not null,
    stage           text        not null default 'tech',
    transcript      text        not null default '',
    signal          text        not null default 'unknown',
    impression      int         not null default 5,
    summary         text        not null default '',
    analysis        jsonb       not null default '{}'::jsonb,
    created_at      timestamptz not null default now()
);
-- vacancy_id + свежесть — история разборов по вакансии (новые первыми, как load_prep_history).
create index interview_debriefs_vacancy_idx on interview_debriefs (vacancy_id, created_at desc);
