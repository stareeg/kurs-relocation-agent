-- 0153_auto_apply_override_reason — причина, почему автоотклик не отправился
-- (перенос в «Ручной разбор» с пояснением для владельца).

alter table auto_apply_queue_overrides
    add column if not exists reason text;
