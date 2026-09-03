-- 0121_friendships — friendship codes + friendships.
-- 0120_friendships.sql было случайно создано и применено с дублирующимся номером (0120 уже
-- занят) — ниже чистка tracking-записи. Сами таблицы account_friendship_codes и friendships
-- уже созданы при первом прогоне (0120), повторный прогон CREATE IF NOT EXISTS не навредит.

-- Friendship codes (one per account, unique 6-char code for sharing)
create table if not exists account_friendship_codes (
    account_id  integer primary key references accounts(id) on delete cascade,
    code        text not null unique check (code ~ '^[A-Z0-9]{6}$'),
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

-- Friendship links: account_id adds friend_account_id via code
create table if not exists friendships (
    id                  serial primary key,
    account_id          integer not null references accounts(id) on delete cascade,
    friend_account_id   integer not null references accounts(id) on delete cascade,
    status              text not null default 'active' check (status in ('active', 'blocked')),
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    unique(account_id, friend_account_id)
);

create index if not exists idx_friendships_account
    on friendships(account_id);
create index if not exists idx_friendships_friend
    on friendships(friend_account_id);

-- Clean up old tracking entry
delete from schema_migrations where filename = '0120_friendships.sql';