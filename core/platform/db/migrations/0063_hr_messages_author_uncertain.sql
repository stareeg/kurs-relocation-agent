-- 0063_hr_messages_author_uncertain — FR3-74: честность атрибуции при LLM-разборе дампа.
-- Когда сплиттер не уверен в авторе реплики, пишем флаг; funnel_suggest такие hr_in не берёт,
-- UI помечает «автор?» в ленте. Старые строки — false (считаем уверенными).

alter table hr_messages
    add column if not exists author_uncertain boolean not null default false;
