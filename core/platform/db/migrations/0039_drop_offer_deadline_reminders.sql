-- 0039_drop_offer_deadline_reminders — функционал напоминаний о дедлайне оффера выпилен целиком
-- (продюсер/консьюмер/APScheduler-задача удалены из bot_app; см. миграцию 0012).
drop table if exists offer_deadline_reminders;
