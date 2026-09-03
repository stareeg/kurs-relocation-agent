-- 0137_jobs_track — трек вакансии и денормализованные условия на карточке (Э2.1/Э2.2).
-- Денормализация, чтобы доска не джойнила vacancy_work_terms на каждый рендер (приём 0129).
-- track_override — ручная поправка владельца: рескор её не перетирает (контракт is_salary_locked).

alter table jobs add column if not exists work_terms jsonb;
alter table jobs add column if not exists track text;
alter table jobs add column if not exists track_override boolean not null default false;
create index if not exists jobs_track_idx on jobs (account_id, track);
