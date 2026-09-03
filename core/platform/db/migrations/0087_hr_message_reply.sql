-- 0087_hr_message_reply — ответ на сообщение (reply-to) в ленте разговора вакансии.
-- Хранит id реплики-источника; используется композером (цитата над полем ввода) и промптом LLM
-- (цитата подставляется в контекст, чтобы ассистент видел, на что отвечает). SET NULL — цитата
-- пропадает, если источник удалён (сам ответ остаётся).

alter table hr_messages
    add column if not exists reply_to_message_id bigint references hr_messages (id) on delete set null;
