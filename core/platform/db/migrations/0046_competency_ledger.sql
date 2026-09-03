-- 0046_competency_ledger — RD-23: карта компетенций растёт от собеса к собесу, не умирает внутри
-- одного дебрифа. Каждый прогон `competency_map` дебрифа (JS-14) добавляет строки сюда — леджер
-- append-only (та же дисциплина, что `interview_debriefs`/`retro_snapshots`): история важна не
-- меньше текущего уровня, иначе не построить траекторию weak -> confident.
--
-- topic_canon — приведённая тема (канонизация синонимов - haiku-матчер в
-- core/interview/question_match.py, тот же модуль, что RD-22-матчинг). vacancy_id/stage
-- денормализованы из исходного дебрифа для быстрых срезов без join.

create table if not exists competency_ledger (
    id bigserial primary key,
    topic_canon text not null,
    level text not null check (level in ('confident', 'medium', 'weak')),
    evidence text not null default '',
    vacancy_id text not null,
    stage text not null,
    debrief_id bigint references interview_debriefs (id) on delete cascade,
    created_at timestamptz not null default now()
);

create index if not exists competency_ledger_topic_idx
    on competency_ledger (topic_canon, created_at desc);

create index if not exists competency_ledger_debrief_idx
    on competency_ledger (debrief_id);
