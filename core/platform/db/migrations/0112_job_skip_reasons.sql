-- 0100_job_skip_reasons.sql
-- Таблица для LLM-сгенерированных причин пропуска под конкретную вакансию (2026-08-10).
--
-- После скоринга фоном генерируется 6 кратких чипов «почему можно пропустить» — не статичные
-- категории, а конкретные нюансы вакансии. Под капотом каждый чип замаплен в каноническую
-- причину из SELF_SKIP_REASONS (без «Избегать компанию» — она отдельная статичная кнопка).
--
-- Расширение и веб тянут причины через GET /vacancies/{id}/skip-reasons; если записей нет
-- (LLM недоступен / вакансия скорена до фичи) — UI падает на статичные канонические чипы.
--
-- Отдельная от skipped_vacancies: та хранит факт пропуска + выбранную причину, эта —
-- предзаготовленные чипы для выбора. Одна запись на (account_id, vacancy_id), upsert.

create table if not exists job_skip_reasons (
    id              bigint      generated always as identity primary key,
    vacancy_id      text        not null,
    account_id      bigint      not null,
    reasons         jsonb       not null,  -- SkipReasonsPack: [{text, canonical}, ...]
    generated_at    timestamptz not null default now(),
    created_at      timestamptz not null default now(),
    constraint job_skip_reasons_account_vacancy_key unique (account_id, vacancy_id)
);

create index if not exists job_skip_reasons_vacancy_id_idx on job_skip_reasons (vacancy_id);

alter table job_skip_reasons enable row level security;
create policy job_skip_reasons_account_isolation on job_skip_reasons
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on job_skip_reasons to app_rls;
grant usage, select on job_skip_reasons_id_seq to app_rls;

-- canonical_reason в skipped_vacancies: нормализованная каноническая причина
-- (после canonical_skip_reason), чтобы аналитика не гоняла regex на каждом чтении.
-- skip_reason остаётся как есть (сырая строка / LLM-текст чипа) — для отображения.
alter table skipped_vacancies add column if not exists canonical_reason text;
