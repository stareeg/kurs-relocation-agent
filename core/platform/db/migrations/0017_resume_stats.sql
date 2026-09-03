-- 0017_resume_stats — time-series статистики резюме с hh (AF-1): снимки агрегата + строки истории.
-- Источник динамики отклика рынка (показы/просмотры/приглашения во времени). Пишет расширение
-- (AF-2) на заходе на /applicant/resumes и /applicant/resumeview/history, читает «Рынок» (AF-3).
-- По образцу 0016 (jsonb raw + денорм-скаляры + индекс по времени). БЕЗ FK — резюме вне jobs-домена.

-- Снимок агрегатных счётчиков резюме на момент времени (накопление → динамика).
create table resume_stats (
    id                bigint      generated always as identity primary key,
    captured_at       timestamptz not null default now(),
    resume_id         text        not null default '',
    period            text        not null default 'week',
    impressions       int         not null default 0,
    views             int         not null default 0,
    invitations       int         not null default 0,
    views_delta       int         not null default 0,
    invitations_delta int         not null default 0,
    raw               jsonb       not null default '{}'::jsonb,
    created_at        timestamptz not null default now()
);
-- resume_id + свежесть — серия снимков по резюме (новые первыми, asc разворачивает фронт).
create index resume_stats_captured_idx on resume_stats (resume_id, captured_at desc);

-- Строка истории просмотра резюме (кто смотрел, по какой вакансии, когда).
create table resume_views (
    id            bigint      generated always as identity primary key,
    viewed_at     timestamptz not null default now(),
    employer      text        not null default '',
    vacancy_title text        not null default '',
    vacancy_url   text        not null default '',
    resume_id     text        not null default '',
    raw           jsonb       not null default '{}'::jsonb,
    created_at    timestamptz not null default now()
);
-- дедуп повторных заходов: натуральный ключ строки истории (кто / какая вакансия / когда).
create unique index resume_views_natural_idx on resume_views (employer, vacancy_url, viewed_at);
-- лента истории просмотров (свежие первыми).
create index resume_views_viewed_idx on resume_views (viewed_at desc);
