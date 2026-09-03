-- 0099_openrouter_key_requests — Этап 5 (plans/vm_multitenant_hosting_2026_08_03.md §4, §9):
-- BYOK-заявки на ключ OpenRouter. Self-serve аккаунт жмёт «Ключ OpenRouter» в боте, оператор
-- (role='owner') видит заявку и выдаёт ключ вручную (Фаза 1, §4) — Management API (Фаза 2,
-- Этап 9) заменит только сам шаг выдачи, таблица и статусная машина не меняются.
--
-- Статусы: pending → approved (оператор нажал «Выдать», ждём вставленный ключ) → fulfilled
-- (ключ сохранён в account_settings заявителя); либо pending → rejected.
--
-- RLS: account_id — заявитель, не оператор. Заявитель создаёт/читает свои заявки через
-- account_scope() (core/platform/db/account_scope.py). Оператору нужен кросс-аккаунтный список
-- pending-заявок + resolve чужой заявки — это идёт МИМО account_scope(), тем же приёмом, что
-- core/repo/accounts.py (соединение по умолчанию — владелец таблиц, обходит RLS; см.
-- bot_app/services/openrouter_keys.py).

create table openrouter_key_requests (
    id           bigint      generated always as identity primary key,
    account_id   bigint      not null references accounts(id) on delete cascade,
    status       text        not null default 'pending'
        check (status in ('pending', 'approved', 'rejected', 'fulfilled')),
    requested_at timestamptz not null default now(),
    resolved_at  timestamptz,
    resolved_by  bigint references accounts(id),
    note         text
);

create index openrouter_key_requests_account_id_idx on openrouter_key_requests (account_id);
-- Оператору нужен быстрый список pending-заявок вне account_scope — частичный индекс по статусу.
create index openrouter_key_requests_pending_idx on openrouter_key_requests (requested_at)
    where status = 'pending';

alter table openrouter_key_requests enable row level security;

create policy openrouter_key_requests_isolation on openrouter_key_requests
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on openrouter_key_requests to app_rls, app_admin;
