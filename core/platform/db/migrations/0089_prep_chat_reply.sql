-- 0089_prep_chat_reply — ответ на сообщение (reply-to) в чате подготовки (вкладка «Технички»).
-- Тот же паттерн, что 0087_hr_message_reply для hr_messages: хранит id реплики-источника,
-- используется композером (цитата над полем ввода). SET NULL — цитата пропадает, если источник
-- удалён (сам ответ остаётся).

alter table prep_chat_messages
    add column if not exists reply_to_message_id bigint references prep_chat_messages (id) on delete set null;
