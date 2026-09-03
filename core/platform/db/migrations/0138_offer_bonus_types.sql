-- 0138_offer_bonus_types — премия оффера: несколько типов сразу + % годовой/квартальной.
-- `bonus_type` остаётся денормализованным primary (первый канонический или none),
-- источник истины — `bonus_types`. Welcome и акции — тоже типы, а не «видимы при любой премии».

alter table offers
    add column if not exists bonus_types text[] not null default '{}',
    add column if not exists annual_bonus_pct integer
        check (annual_bonus_pct is null or annual_bonus_pct in (5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150)),
    add column if not exists quarterly_bonus_pct integer
        check (quarterly_bonus_pct is null or quarterly_bonus_pct in (5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150));

alter table offers drop constraint if exists offers_bonus_types_allowed_check;
alter table offers add constraint offers_bonus_types_allowed_check
    check (bonus_types <@ array['annual', 'quarterly', 'kpi', 'welcome', 'equity']::text[]);

alter table offers drop constraint if exists offers_bonus_type_check;
alter table offers add constraint offers_bonus_type_check
    check (bonus_type in ('none', 'annual', 'quarterly', 'kpi', 'welcome', 'equity'));

-- Существующие одиночные типы + уже заполненные welcome/акции, которые раньше жили
-- «в тени» любой премии и не были отдельным выбором.
update offers
set bonus_types = array[bonus_type]::text[]
where bonus_type is not null
  and bonus_type <> 'none'
  and bonus_types = '{}';

update offers
set bonus_types = bonus_types || '{welcome}'::text[]
where signon is not null
  and signon > 0
  and not ('welcome' = any(bonus_types));

update offers
set bonus_types = bonus_types || '{equity}'::text[]
where coalesce(btrim(equity), '') <> ''
  and not ('equity' = any(bonus_types));
