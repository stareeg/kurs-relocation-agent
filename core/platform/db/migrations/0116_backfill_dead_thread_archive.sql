-- 0116: бейдж «Чаты» в сайдбаре считал hr_threads.status <> 'archived' по всем аккаунтам, а
-- фронт отдельно прятал из списка диалоги вакансий уже в Отказе/Архиве/Пропуске (jobs.status,
-- skipped_vacancies) — треды таких вакансий копились с status='active' в трёх местах, которые
-- писали стадию воронки в обход archive_threads_for_vacancy (core/domains/pipeline/negotiations.py
-- auto-sync откликов hh.ru, hr_actions.py разбор отказа HR в Telegram; код тоже правится в этой
-- сессии). Разовый backfill — привести Postgres в соответствие тому, что уже видно в UI.
update hr_threads t
set status = 'archived', updated_at = now()
where t.status <> 'archived'
  and (
    exists (
        select 1 from jobs j
        where j.vacancy_id = t.vacancy_id
          and j.account_id = t.account_id
          and j.status in ('Отказ', 'Архив')
    )
    or exists (
        select 1 from skipped_vacancies s
        where s.vacancy_id = t.vacancy_id
          and s.account_id = t.account_id
    )
  );
