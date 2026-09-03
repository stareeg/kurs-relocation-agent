-- 0021_score_revisions — провенанс пересчёта скоринга по HR-фактам (JS-8.1).
-- Казус: вакансия скорнулась 10/100 по сухому JD, лид назвал 600k+/удалёнку — но система не узнала
-- (стор так и 10/skip). JS-8.1 замыкает петлю: HR назвал факты → LLM их извлёк → score_vacancy
-- пересчитан с override-блоком → jobs.overall_score перезаписан (полный авто). Чтобы ничего не
-- терялось молча — исходный JD-скор и КАЖДЫЙ пересчёт пишутся сюда отдельной строкой (накопительно).
-- vacancy_id = HH id, БЕЗ FK на jobs (как debrief/stage_outcomes). basis различает первичную
-- JD-оценку и подтверждённую HR; facts_hash — для дедупа (не гонять LLM, если факты не изменились).
create table score_revisions (
    id             bigint      generated always as identity primary key,
    vacancy_id     text        not null,
    basis          text        not null default 'jd_only'
                   check (basis in ('jd_only', 'hr_confirmed')),
    trigger        text        not null default '',
    facts          jsonb       not null default '{}'::jsonb,
    facts_hash     text        not null default '',
    overall_score  int         not null default 0,
    recommendation text        not null default '',
    delta          int         not null default 0,
    rationale      text        not null default '',
    created_at     timestamptz not null default now()
);
-- история пересчётов по вакансии (новые первыми, как load_debrief_history).
create index score_revisions_vacancy_idx on score_revisions (vacancy_id, created_at desc);

-- Денорм-флаг на jobs: на чём стоит текущий скор (для бейджа «подтверждён HR» в карточке).
alter table jobs add column if not exists score_basis text not null default 'jd_only';
