-- 0015_remote_feasibility — под-скор «реальность полной удалёнки» (feature_ideas 2.2).
-- Параллелен основному score (jsonb): RemoteFeasibility {score, verdict, signals[], note}.
-- Считается на тире extract вместе со скорингом, пишется в upsert save_job (повторный скоринг
-- обновляет, как прочие денормализованные поля). NULL - под-скор не считался/упал (best-effort).
alter table jobs add column if not exists remote_feasibility jsonb;
