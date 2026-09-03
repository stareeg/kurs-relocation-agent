-- 0042_offer_negotiation — RD-17: аргументы для торга по офферу.
-- Персист прямо на строке оффера (не отдельная таблица — один бриф на оффер, перегенерация
-- затирает старый, как prep_packs/0041). jsonb хранит весь NegotiationBrief (аргументы + черновик
-- ответа HR); generated_at отдельно — фронт показывает «собрано <дата>» без парсинга jsonb.
alter table offers add column if not exists negotiation jsonb;
alter table offers add column if not exists negotiation_generated_at timestamptz;
