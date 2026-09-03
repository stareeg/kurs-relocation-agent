-- 0052_offer_priority_and_office_days — OF-1 (plans/offer_awareness_and_final_prep.md):
-- приоритет офферов для ручного drag-n-drop (OF-11) + дни в офисе для гибридного формата (OF-4/OF-10).
alter table offers add column if not exists priority integer;
alter table offers add column if not exists office_days_per_week integer
    check (office_days_per_week is null or (office_days_per_week between 0 and 7));
-- priority — ручной порядок для drag-n-drop в матрице (OF-11). NULL = ещё не проставлен
-- (новые офферы уходят в хвост списка, сортировка по updated_at как раньше).
-- office_days_per_week — только для work_format='hybrid' (не enforced CHECK'ом на work_format,
-- офферы редактируются инлайн полями независимо, как остальные колонки этой таблицы).
