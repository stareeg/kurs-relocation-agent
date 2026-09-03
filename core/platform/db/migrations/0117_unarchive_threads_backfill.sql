-- 0117: симметрия архивации диалогов (план local_context_blind_spots_2026_08_12.md §1) —
-- негативный синк (negotiations.py/service.py) архивировал тред на «Отказ», но обратного
-- механизма не было вовсе: воронка, вручную/синком возвращённая в активную стадию, оставляла
-- тред в hr_threads.status='archived' навсегда (job 317, «ТехВилл» — 2026-08-12, дважды за
-- день). Код правится в этой же сессии (unarchive_threads_for_vacancy в hr_threads.py,
-- подключено к set_job_stage/set_funnel_status/negotiations._sync_one). Разовый backfill
-- приводит Postgres в соответствие текущей воронке — зеркало 0116 в обратную сторону.
update hr_threads t
set status = 'active', updated_at = now()
where t.status = 'archived'
  and exists (
      select 1 from jobs j
      where j.vacancy_id = t.vacancy_id
        and j.account_id = t.account_id
        and j.status in ('Отклик', 'Скрининг', 'Техничка', 'Финал', 'Оффер')
  );
