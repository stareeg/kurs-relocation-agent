-- 0007_offers — офферы per vacancy (S6 migration_plan): порт легаси SQLite `offers`
-- (bot/storage/offers_db.py) на Postgres. Postgres — единственный источник истины (Sheets — зеркало).
-- vacancy_id = HH id (как jobs.vacancy_id / vacancy_enrichment.vacancy_id), но БЕЗ FK: оффер может
-- прийти от HR раньше скоринга и для вакансий вне jobs (как enrichment S4 и interview_stages S5).
-- enum'ы = text + CHECK (конвенция 0001); времена timestamptz; деньги bigint (ge 0 — CHECK).
-- Напоминания о дедлайне (легаси offer_deadline_reminders) НЕ переносим: это шедулер бота на SQLite,
-- переедет вместе с apps/bot (как prep/debrief-хранилище, defer S5).
create table offers (
    vacancy_id              text        primary key,
    company                 text        not null default '',
    position                text        not null default '',
    base_salary             bigint      check (base_salary is null or base_salary >= 0),
    base_salary_currency    text        not null default 'RUB',
    base_salary_period      text        not null default 'month'
        check (base_salary_period in ('month', 'year')),
    bonus                   text        not null default '',
    bonus_amount            bigint      check (bonus_amount is null or bonus_amount >= 0),
    equity                  text        not null default '',
    signon                  bigint      check (signon is null or signon >= 0),
    vacation_days           integer     check (vacation_days is null or vacation_days >= 0),
    notice_period           text        not null default '',
    start_date              timestamptz,
    deadline                timestamptz,
    relocation_package      text        not null default '',
    work_format             text        not null default 'unknown'
        check (work_format in ('remote', 'hybrid', 'office', 'unknown')),
    location                text        not null default '',
    notes                   text        not null default '',
    raw_text                text        not null default '',
    status                  text        not null default 'active'
        check (status in ('draft', 'active', 'accepted', 'declined', 'expired')),
    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now()
);
-- status + updated_at — выборка активных офферов по возрасту для /offers/decide (легаси load_active_offers).
create index offers_status_updated_idx on offers (status, updated_at);
-- deadline — порядок «ближайший дедлайн оффера» (напоминания/дайджест).
create index offers_deadline_idx on offers (deadline);
