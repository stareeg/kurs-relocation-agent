-- 0003_salary_calibration — стор калибровочных сэмплов зарплат (задача 1.3).
-- Источник истории: data/vacancies.db → salary_calibration_samples (парсенные точки из
-- пересылок HR). 1.1 эту таблицу не создавал; план 1.3 требует «salary-калибровки → таблица
-- калибровок» — заводим здесь. Питает salary_estimator после переноса скоринга (1.5).
-- legacy_id — исходный SQLite id, уникален → миграция идемпотентна (upsert по нему).
create table salary_calibration_samples (
    id             bigint generated always as identity primary key,
    legacy_id      integer unique,
    is_relevant    boolean     not null default true,
    skip_reason    text,
    company        text,
    position       text,
    grade          text,
    company_type   text,
    salary_min_net integer,
    salary_max_net integer,
    salary_scale   text,
    bonus_text     text,
    bonus_type     text,
    city           text,
    work_format    text,
    source_channel text,
    confidence     text,
    note           text,
    raw_excerpt    text,
    created_at     timestamptz not null default now()
);
create index salary_calibration_samples_company_idx on salary_calibration_samples (company);
