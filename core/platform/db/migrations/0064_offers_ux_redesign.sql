-- 0064_offers_ux_redesign — редизайн раздела «Офферы»: три статуса вместо пяти, оклад
-- до/после налогов, структурированный тип премии + помесячный эквивалент, вид договора вместо
-- нотиса, страна (только для «Валютки»). Данные штучные (один пользователь) — переносим строкой.

alter table offers
    add column base_salary_tax_basis text not null default 'gross'
        check (base_salary_tax_basis in ('gross', 'net')),
    add column bonus_type text not null default 'none'
        check (bonus_type in ('none', 'annual', 'quarterly', 'kpi')),
    add column bonus_monthly_equiv bigint
        check (bonus_monthly_equiv is null or bonus_monthly_equiv >= 0),
    -- Хэш входов (bonus_type/bonus/bonus_amount/base_salary), по которому посчитан
    -- bonus_monthly_equiv — не дёргаем LLM повторно, пока хэш не изменился.
    add column bonus_monthly_equiv_source_hash text not null default '',
    add column contract_type text not null default 'employment'
        check (contract_type in ('employment', 'gph', 'ip', 'self_employed')),
    add column location_country text not null default '';

-- Статусы: draft/active/expired как состояния исчезают, данные сворачиваются в 'thinking'
-- (владелец сам расставит accepted/declined там, где уже решил — см. ручную сверку ниже).
update offers set status = 'thinking' where status in ('active', 'draft', 'expired');
alter table offers drop constraint offers_status_check;
alter table offers add constraint offers_status_check
    check (status in ('thinking', 'accepted', 'declined'));
alter table offers alter column status set default 'thinking';

-- work_format: добавляем 'currency' (Валютка). 'unknown' остаётся валидным значением в БД
-- (легаси-строки/непроставлено), но фронт больше не предлагает его как выбор.
alter table offers drop constraint offers_work_format_check;
alter table offers add constraint offers_work_format_check
    check (work_format in ('remote', 'hybrid', 'office', 'currency', 'unknown'));
