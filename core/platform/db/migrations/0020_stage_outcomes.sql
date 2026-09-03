-- 0020_stage_outcomes — структурный исход этапа собеса (JS-5.2): факты от рекрутера, без транскрипта.
-- Детали следующего этапа рекрутер обычно называет ПОСЛЕ прохождения текущего, а фидбек по
-- пройденному скупой (чаще «прошли/не прошли», изредка с конкретикой). Сейчас это нигде структурно
-- не фиксируется: статус воронки + свободная заметка + разбор interview_debriefs (но он требует
-- ТРАНСКРИПТА). Эта таблица держит лёгкий факт-исход на (вакансию, этап): прошёл/отказ/ждём +
-- фидбек рекрутера + бриф следующего этапа (формат/фокус), который едет в подготовку (focus_topics).
-- По образцу interview_debriefs (0016)/prep_sessions (0009): vacancy_id = HH id, БЕЗ FK на jobs
-- (исход может быть для вакансии вне jobs). Накопительно: каждый исход — отдельная строка. Без LLM.
create table stage_outcomes (
    id                 bigint      generated always as identity primary key,
    vacancy_id         text        not null,
    stage              text        not null default 'screening',
    outcome            text        not null default 'passed'
                       check (outcome in ('passed', 'rejected', 'waiting')),
    recruiter_feedback text        not null default '',
    next_stage         text        not null default '',
    next_stage_notes   text        not null default '',
    focus_topics       jsonb       not null default '[]'::jsonb,
    created_at         timestamptz not null default now()
);
-- vacancy_id + свежесть — история исходов по вакансии (новые первыми, как load_debrief_history).
create index stage_outcomes_vacancy_idx on stage_outcomes (vacancy_id, created_at desc);
