-- 0141_openrouter_account_keys — происхождение действующего ключа OpenRouter аккаунта.
--
-- Зачем отдельная таблица, а не поле в account_settings: сам ключ лежит в
-- `account_settings.openrouter_api_key` (секрет, отдаётся только внутрь LLM-вызова), а
-- операторской консоли нужен разрез «кому какой ключ выдан» — маска, метка, кто и когда
-- выдал. Это метаданные, их видит оператор; секрет остаётся там же, где был.
--
-- origin:
--   'self'  — человек вставил свой ключ на «Аккаунте» (может сбросить/заменить сам);
--   'admin' — ключ выдан оператором из админ-панели. Такой ключ пользователю не показываем
--             и сбросить он его не может (см. core/platform/openrouter_keys.py) — иначе
--             отключит себе продукт кнопкой, к которой не имеет отношения.
--
-- Строка живёт ровно пока живёт ключ: очистка ключа удаляет и её (репозиторий
-- core/platform/repo/openrouter_account_keys.py). Отсюда PK по account_id, без истории —
-- журнал выдач и так остаётся в openrouter_key_requests (0099).

create table openrouter_account_keys (
    account_id bigint      not null primary key references accounts(id) on delete cascade,
    origin     text        not null check (origin in ('self', 'admin')),
    key_hint   text        not null default '',
    label      text,
    issued_by  bigint      references accounts(id),
    issued_at  timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table openrouter_account_keys enable row level security;

create policy openrouter_account_keys_isolation on openrouter_account_keys
    using (account_id = current_setting('app.account_id', true)::bigint);

grant select, insert, update, delete on openrouter_account_keys to app_rls, app_admin;

-- Бэкфилл: у кого ключ уже есть — считаем его своим. Ключи, выданные раньше через бота, тоже
-- попадают в 'self' осознанно: бот пересылал заявителю сырое значение, человек его видел и
-- волен им распоряжаться — задним числом отбирать у него кнопку «Сбросить» нечестно.
-- Маска: первые 9 символов (`sk-or-v1-`) + хвост из 4, как mask_key() в Python.
insert into openrouter_account_keys (account_id, origin, key_hint, issued_at, updated_at)
select
    s.account_id,
    'self',
    case
        when length(trim(s.value #>> '{}')) > 13
            then left(trim(s.value #>> '{}'), 9) || '…' || right(trim(s.value #>> '{}'), 4)
        else '…'
    end,
    s.updated_at,
    s.updated_at
from account_settings s
where s.key = 'openrouter_api_key'
  and jsonb_typeof(s.value) = 'string'
  and length(trim(s.value #>> '{}')) > 0
on conflict (account_id) do nothing;
