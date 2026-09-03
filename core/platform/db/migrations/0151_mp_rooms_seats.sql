-- 0151_mp_rooms_seats — лобби столов «Хрюши и Волки» (Э4).
-- Общие комнаты: список открытых столов видят все аккаунты; изоляция — в service
-- (PIN, join, секреты ролей). RLS по host_account_id ломал бы SI-style лобби.
-- role_secret никогда не отдаём в REST/WS public (Э5+).

create table mp_rooms (
    id               bigint generated always as identity primary key,
    code             text not null unique
                     check (code ~ '^[A-Z0-9]{6}$'),
    name             text not null check (char_length(trim(name)) between 1 and 64),
    host_account_id  bigint not null references accounts (id) on delete cascade,
    pin_hash         text,
    status           text not null default 'open'
                     check (status in ('open', 'playing', 'closed')),
    mode             text not null
                     check (mode in ('solo', 'friends')),
    settings         jsonb not null default '{}'::jsonb,
    phase_label      text not null default 'лобби',
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);

create index mp_rooms_status_created_idx on mp_rooms (status, created_at desc);
create index mp_rooms_host_idx on mp_rooms (host_account_id);

create table mp_seats (
    id            bigint generated always as identity primary key,
    room_id       bigint not null references mp_rooms (id) on delete cascade,
    account_id    bigint references accounts (id) on delete set null,
    seat_kind     text not null check (seat_kind in ('hr', 'candidate', 'spectator')),
    seat_index    int not null check (seat_index >= 0),
    role_public   text not null default 'waiting',
    role_secret   text,
    is_bot        boolean not null default false,
    joined_at     timestamptz not null default now(),
    unique (room_id, seat_kind, seat_index)
);

-- Один человек — одно сиденье за столом (боты с account_id IS NULL не конфликтуют).
create unique index mp_seats_room_account_uidx
    on mp_seats (room_id, account_id)
    where account_id is not null;

create index mp_seats_room_idx on mp_seats (room_id);
create index mp_seats_account_idx on mp_seats (account_id)
    where account_id is not null;

grant select, insert, update, delete on mp_rooms to app_rls, app_admin;
grant select, insert, update, delete on mp_seats to app_rls, app_admin;
