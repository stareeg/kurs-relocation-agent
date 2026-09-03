-- 0140_admin_friendships_origin — системная дружба оператора с member-аккаунтами.
-- origin=user — человек добавил по коду; system_admin — авторебро с владельцем установки.
-- Бэкфилл только owner↔member: member↔member по желанию, сюда не попадают.

alter table friendships
    add column if not exists origin text not null default 'user';

alter table friendships drop constraint if exists friendships_origin_check;
alter table friendships
    add constraint friendships_origin_check check (origin in ('user', 'system_admin'));

insert into friendships (account_id, friend_account_id, origin)
select o.id, m.id, 'system_admin'
from accounts o
cross join accounts m
where o.role = 'owner' and o.status = 'active'
  and m.role = 'member'
  and o.id <> m.id
on conflict (account_id, friend_account_id) do nothing;

insert into friendships (account_id, friend_account_id, origin)
select m.id, o.id, 'system_admin'
from accounts o
cross join accounts m
where o.role = 'owner' and o.status = 'active'
  and m.role = 'member'
  and o.id <> m.id
on conflict (account_id, friend_account_id) do nothing;
