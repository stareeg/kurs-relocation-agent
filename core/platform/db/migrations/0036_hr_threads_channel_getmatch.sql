-- 0036_hr_threads_channel_getmatch — расширяем channel до 'getmatch'.
--
-- На getmatch.ru нет встроенного чата с HR: отклик даёт контакты, дальше переписка
-- уходит во внешний канал (обычно Telegram). 'getmatch' — тег происхождения отклика
-- (вакансия пришла через getmatch, контакт получен там, но сам диалог идёт в TG),
-- отдельно от чистого 'telegram'. См. plans/getmatch_gap.md S2/7.1 — отдельного
-- getmatch-hr-thread адаптера нет и не нужно (импортировать нечего).

alter table hr_threads drop constraint if exists hr_threads_channel_check;
alter table hr_threads add constraint hr_threads_channel_check
    check (channel in ('telegram', 'hh', 'getmatch', 'email', 'phone', 'other'));
