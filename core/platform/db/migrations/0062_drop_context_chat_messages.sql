-- 0062_drop_context_chat_messages — контекст снова шпаргалка (notes.body), не LLM-чат.
-- UI пишет/читает только notes; vacancy-чаты (conversation_messages и т.п.) не затрагиваются.
drop table if exists context_chat_messages;
