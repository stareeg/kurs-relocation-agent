-- 0131_auto_apply_queue_override — редизайн «Расширения» (Фаза E, пункт 4): ручной квик-экшен
-- «переместить между Сам откликнется / На ручной разбор». Бакет auto/manual_review в
-- pipeline.auto_apply.queue.preview_queue — живой пересчёт по score vs порогам (без персиста),
-- поэтому ручной выбор владельца нужен персистить отдельно — по образцу skipped_vacancies
-- (0008/0097): отдельная таблица, не колонка в jobs, FK на jobs (в отличие от skipped_vacancies —
-- здесь оверрайд всегда привязан к уже существующей отсканированной вакансии, вакансий "вне jobs"
-- для этой фичи не бывает). account-scoped + RLS с рождения, по образцу gm_trust_snapshots (0126).

create table auto_apply_queue_overrides (
    job_id     bigint      primary key references jobs (id) on delete cascade,
    account_id bigint      not null references accounts (id) on delete cascade,
    override   text        not null check (override in ('auto', 'manual_review')),
    created_at timestamptz not null default now()
);

create index auto_apply_queue_overrides_account_idx on auto_apply_queue_overrides (account_id);

alter table auto_apply_queue_overrides enable row level security;
create policy auto_apply_queue_overrides_account_isolation on auto_apply_queue_overrides
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on auto_apply_queue_overrides to app_rls, app_admin;
