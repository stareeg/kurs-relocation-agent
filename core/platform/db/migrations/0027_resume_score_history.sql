-- 0027_resume_score_history — измеримость прогресса резюме между итерациями (JS-10 п.2). Один
-- снимок = один сохранённый структурный скор (PUT /api/resume/data), чтобы видеть тренд по времени.
-- Без FK — резюме не строка в jobs, это singleton-документ владельца.
create table resume_score_history (
    id               bigint      generated always as identity primary key,
    total            integer     not null,
    ats              integer     not null,
    role_match       integer     not null,
    content_quality  integer     not null,
    completeness     integer     not null,
    created_at       timestamptz not null default now()
);
create index resume_score_history_created_idx on resume_score_history (created_at desc);
