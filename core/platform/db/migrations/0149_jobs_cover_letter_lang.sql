-- 0149_jobs_cover_letter_lang — язык последнего сгенерированного сопроводительного (Э4.4).
-- Денормализация рядом с cover_letter_text: переключалка RU/EN в дровере/расширении должна
-- при открытии показывать язык уже сгенерированного письма, а не гадать заново.

alter table jobs add column if not exists cover_letter_lang text;
