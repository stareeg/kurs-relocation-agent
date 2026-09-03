-- 0122_hr_threads_channel_habr — расширяем channel до 'habr'.
--
-- На career.habr.com нет встроенного чата с HR: отклик даёт контакты, дальше переписка
-- уходит во внешний канал (обычно Telegram). 'habr' — тег происхождения отклика
-- (вакансия пришла через Хабр Карьера, контакт получен там, но сам диалог идёт в TG),
-- отдельно от чистого 'telegram'. По аналогии с 'getmatch' (0036).

alter table hr_threads drop constraint if exists hr_threads_channel_check;
alter table hr_threads add constraint hr_threads_channel_check
    check (channel in ('telegram', 'hh', 'getmatch', 'habr', 'email', 'phone', 'other'));
